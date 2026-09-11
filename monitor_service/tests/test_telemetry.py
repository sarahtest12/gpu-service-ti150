"""CPU-only tests for Prometheus parsing and rolling-window aggregation."""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from telemetry import HistogramWindow, parse_histogram


def metrics(count, total, buckets):
    lines = [
        "# TYPE example_seconds histogram",
        f'example_seconds_sum{{model="a"}} {total}',
        f'example_seconds_count{{model="a"}} {count}',
    ]
    lines.extend(f'example_seconds_bucket{{model="a",le="{bound}"}} {value}'
                 for bound, value in buckets)
    return "\n".join(lines)


class TelemetryTest(unittest.TestCase):
    def test_aggregates_label_sets_and_scales_units(self):
        text = metrics(2, 0.3, [("0.1", 1), ("0.2", 2), ("+Inf", 2)]) + "\n" + "\n".join([
            'example_seconds_sum{model="b"} 0.4',
            'example_seconds_count{model="b"} 1',
            'example_seconds_bucket{model="b",le="0.1"} 0',
            'example_seconds_bucket{model="b",le="0.2"} 0',
            'example_seconds_bucket{model="b",le="+Inf"} 1',
        ])
        snapshot = parse_histogram(text, "example_seconds")
        self.assertEqual((snapshot.count, snapshot.total), (3, 0.7))
        self.assertEqual(snapshot.buckets, {0.1: 1, 0.2: 2, float("inf"): 3})
        scaled = snapshot.scaled(0.001)
        self.assertAlmostEqual(scaled.total, 0.0007)
        self.assertAlmostEqual(scaled.buckets[0.0001], 1)

    def test_window_uses_only_counter_deltas_and_interpolates_p95(self):
        window = HistogramWindow(60, 12.5)
        first = parse_histogram(metrics(10, 1.0, [("0.1", 8), ("0.2", 10), ("+Inf", 10)]),
                                "example_seconds")
        second = parse_histogram(metrics(12, 1.3, [("0.1", 9), ("0.2", 12), ("+Inf", 12)]),
                                 "example_seconds")
        window.update(100, first)
        self.assertEqual(window.statistics_ms(100), (None, None))
        window.update(105, second)
        avg, p95 = window.statistics_ms(105)
        self.assertEqual(avg, 150.0)
        self.assertEqual(p95, 190.0)
        self.assertEqual(window.statistics_ms(166), (None, None))

    def test_counter_restart_discards_old_window(self):
        window = HistogramWindow(60, 12.5)
        high = parse_histogram(metrics(10, 1.0, [("0.1", 10), ("+Inf", 10)]),
                               "example_seconds")
        low = parse_histogram(metrics(1, 0.05, [("0.1", 1), ("+Inf", 1)]),
                              "example_seconds")
        window.update(100, high)
        window.update(105, low)
        self.assertEqual(window.statistics_ms(105), (None, None))

    def test_process_restart_discards_window_even_if_new_count_is_higher(self):
        window = HistogramWindow(60, 12.5)
        first = parse_histogram(metrics(1, 0.05, [("0.1", 1), ("+Inf", 1)]),
                                "example_seconds")
        second = parse_histogram(metrics(3, 0.15, [("0.1", 3), ("+Inf", 3)]),
                                 "example_seconds")
        window.update(100, first, generation=1)
        window.update(105, second, generation=2)
        self.assertEqual(window.statistics_ms(105), (None, None))


if __name__ == "__main__":
    unittest.main()
