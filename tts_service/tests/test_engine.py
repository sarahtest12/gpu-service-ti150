"""CPU-only tests for the bounded text bridge and CosyVoice3 engine."""

import json
from pathlib import Path
import sys
import threading
import time
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from engine import CosyVoice3Engine, StreamBackpressure, TextStream, TTS_TTFT


class Tensor:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=np.float32)

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.values


class FakeLlm:
    def inference_bistream(self, text):
        list(text)
        yield 101
        yield 102


class FakeVendor:
    def __init__(self):
        self.llm = FakeLlm()


class FakeModel:
    def __init__(self):
        self.model = FakeVendor()
        self.calls = []
        self.drained = threading.Event()
        self.pause = False
        self.release = threading.Event()

    def inference_zero_shot(self, text, prompt_text, prompt_wav, zero_shot_spk_id="",
                            stream=False, speed=1.0):
        self.calls.append((text, prompt_text, prompt_wav, zero_shot_spk_id, stream, speed))
        list(self.model.llm.inference_bistream(text))
        yield {"tts_speech": Tensor([])}
        yield {"tts_speech": Tensor([-1.5, 0.0, 1.5])}
        if self.pause:
            self.release.wait(2)
        yield {"tts_speech": Tensor([0.25])}
        self.drained.set()


def configuration():
    cfg = json.loads((ROOT / "config/server.json").read_text())
    cfg.update({
        "voice_id": "aishell3-female",
        "prompt_text": "固定参考音频的准确文本。",
        "prompt_wav": "/tmp/aishell3-female.wav",
        "text_queue_chunks": 2,
        "max_concurrency": 1,
    })
    return cfg


class TextStreamTest(unittest.TestCase):
    def test_delivers_appends_in_order_until_finish(self):
        stream = TextStream(max_chunks=2)
        stream.append("第一段")
        stream.append("第二段")
        stream.finish()
        self.assertEqual(list(stream), ["第一段", "第二段"])

    def test_backpressure_is_bounded_and_finish_is_idempotent(self):
        stream = TextStream(max_chunks=1)
        stream.append("已占满")
        with self.assertRaises(StreamBackpressure):
            stream.append("不应无限缓存", timeout=0)
        stream.finish()
        stream.finish()
        self.assertEqual(list(stream), ["已占满"])

    def test_cancel_unblocks_a_waiting_iterator_and_rejects_new_text(self):
        stream = TextStream(max_chunks=1)
        completed = threading.Event()

        def consume():
            self.assertEqual(list(stream), [])
            completed.set()

        thread = threading.Thread(target=consume)
        thread.start()
        time.sleep(0.01)
        stream.cancel()
        self.assertTrue(completed.wait(1))
        thread.join(1)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            stream.append("late")


class CosyVoice3EngineTest(unittest.TestCase):
    def setUp(self):
        self.model = FakeModel()
        self.engine = CosyVoice3Engine(self.model, configuration())

    @staticmethod
    def metric_count():
        return next(
            sample.value
            for family in TTS_TTFT.collect()
            for sample in family.samples
            if sample.name == "tts_time_to_first_token_seconds_count"
        )

    def test_uses_fixed_cached_voice_and_streams_clipped_pcm(self):
        before = self.metric_count()
        text = TextStream(max_chunks=2)
        text.append("测试")
        text.finish()

        chunks = list(self.engine.synthesize(text, "req", "utt"))

        self.assertEqual(np.frombuffer(b"".join(chunks), dtype="<i2").tolist(),
                         [-32767, 0, 32767, 8192])
        _, prompt_text, prompt_wav, voice, stream, speed = self.model.calls[0]
        self.assertEqual(prompt_text, "固定参考音频的准确文本。")
        self.assertEqual(prompt_wav, "/tmp/aishell3-female.wav")
        self.assertEqual((voice, stream, speed), ("aishell3-female", True, 1.0))
        self.assertEqual(self.metric_count(), before + 1)

    def test_concurrency_slot_has_one_owner(self):
        self.assertTrue(self.engine.acquire())
        self.assertFalse(self.engine.acquire())
        self.engine.release()
        self.assertTrue(self.engine.acquire())
        self.engine.release()

    def test_closing_output_drains_vendor_generator(self):
        text = TextStream(max_chunks=2)
        text.append("测试")
        text.finish()
        self.model.pause = True
        output = self.engine.synthesize(text, "req", "utt")
        self.assertTrue(next(output))
        self.model.release.set()
        output.close()
        self.assertTrue(self.model.drained.is_set())


if __name__ == "__main__":
    unittest.main()
