from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import validate_segments as validation


class FakeEngine:
    def __init__(self, chunks):
        self.chunks = chunks
        self.ids = []

    def synthesize_segment(self, text, request_id, segment_id):
        self.ids.append(segment_id)
        yield from self.chunks


class ValidationTests(unittest.TestCase):
    def test_timing_uses_22050_hz_and_first_nonempty_chunk(self):
        engine = FakeEngine([b'', b'\0\0' * 22050])
        with patch.object(validation.time, 'perf_counter', side_effect=[10, 10.25, 10.75]):
            pcm, report = validation.consume(engine, 'test', 'seg-1', 22050)
        self.assertEqual(len(pcm), 44100)
        self.assertEqual(report['first_pcm_seconds'], .25)
        self.assertEqual(report['total_seconds'], .75)
        self.assertEqual(report['audio_seconds'], 1)
        self.assertEqual(report['rtf'], .75)
        self.assertEqual(report['segment_id'], 'seg-1')

    def test_rejects_invalid_audio_and_timing(self):
        for chunks, times in [([], [1, 2]), ([b'a'], [1, 2, 3]),
                              ([b'aa'], [1, float('nan'), 3]),
                              ([b'aa'], [3, 2, 1])]:
            with self.subTest(chunks=chunks, times=times):
                with patch.object(validation.time, 'perf_counter', side_effect=times):
                    with self.assertRaises(ValueError):
                        validation.consume(FakeEngine(chunks), 'test', 'seg-1', 22050)

    def test_report_requires_fifo_and_records_subdivision(self):
        segments = [{'segment_id': key} for key in ['a', 'b', 'c']]
        cfg = {'model_name': 'cosyvoice-300m-instruct', 'voice_id': '中文女', 'sample_rate_hz': 22050}
        result = validation.build_report(cfg, .5, {'process_mib': 2048}, segments,
                                         ['a', 'b', 'c'], 3, '/tmp/test.pcm')
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['fifo_order'], ['a', 'b', 'c'])
        self.assertEqual(result['fallback_subdivision_count'], 3)
        self.assertEqual(result['memory_after_load']['process_mib'], 2048)
        with self.assertRaises(ValueError):
            validation.build_report(cfg, .5, {}, segments, ['b', 'a', 'c'], 3, '/tmp/test.pcm')
        with self.assertRaises(ValueError):
            validation.build_report(cfg, .5, {}, segments, ['a', 'b', 'c'], 1, '/tmp/test.pcm')

    def test_pcm_written_private(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'out.pcm'
            target.write_bytes(b'old')
            target.chmod(0o644)
            validation.write_pcm(target, b'\0\0')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.read_bytes(), b'\0\0')


if __name__ == '__main__':
    unittest.main()
