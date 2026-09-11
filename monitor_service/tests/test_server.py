"""Snapshot freshness and forced-refresh behavior."""

from pathlib import Path
import sys
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from server import SnapshotStore


class FakeCollector:
    def __init__(self):
        self.calls = 0
        self.release = threading.Event()
        self.block = False

    def collect(self):
        self.calls += 1
        if self.block:
            self.release.wait(2)
        return {"sampled_at": str(self.calls), "services": []}


class SnapshotStoreTest(unittest.TestCase):
    def test_latest_expires_and_refresh_replaces_snapshot(self):
        collector = FakeCollector()
        store = SnapshotStore(collector, 5, 15)
        self.assertTrue(store._scheduled_collect())
        self.assertEqual(store.latest()["sampled_at"], "1")
        self.assertEqual(store.refresh()["sampled_at"], "2")
        store.published_at = time.monotonic() - 16
        self.assertIsNone(store.latest())

    def test_concurrent_forced_refreshes_coalesce(self):
        collector = FakeCollector()
        store = SnapshotStore(collector, 5, 15)
        store._scheduled_collect()
        collector.block = True
        values = []
        first = threading.Thread(target=lambda: values.append(store.refresh()))
        second = threading.Thread(target=lambda: values.append(store.refresh()))
        first.start()
        deadline = time.monotonic() + 1
        while not store.refreshing and time.monotonic() < deadline:
            time.sleep(0.001)
        second.start()
        collector.release.set()
        first.join(2)
        second.join(2)
        self.assertEqual(collector.calls, 2)
        self.assertEqual([value["sampled_at"] for value in values], ["2", "2"])


if __name__ == "__main__":
    unittest.main()
