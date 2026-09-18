"""CPU-only tests for the CosyVoice-300M inference adapter."""

import json
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cosyvoice300m_engine import CosyVoice300MEngine
from tts_metrics import TTS_TTFT


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


class FakeTokenizer:
    def encode(self, text):
        return list(text)


class FakeFrontend:
    def __init__(self):
        self.tokenizer = FakeTokenizer()
        self.native_parts = None
        self.calls = []

    def text_normalize(self, text, split=True):
        self.calls.append((text, split))
        if self.native_parts is not None:
            return list(self.native_parts)
        return [text]


class FakeLlm:
    def __init__(self):
        self.calls = 0

    def inference(self, *args, **kwargs):
        self.calls += 1
        yield 101
        yield 102


class FakeModel:
    def __init__(self):
        self.frontend = FakeFrontend()
        self.model = SimpleNamespace(llm=FakeLlm())
        self.calls = []
        self.started_parts = []
        self.drained_parts = []
        self.pause = False
        self.release = threading.Event()

    def inference_instruct(self, text, voice, instruction, stream=False, speed=1.0):
        self.calls.append((text, voice, instruction, stream, speed))
        self.started_parts.append(text)
        list(self.model.llm.inference(text=text))
        yield {"tts_speech": Tensor([-1.5, 0.0, 1.5])}
        if self.pause:
            self.release.wait(2)
        yield {"tts_speech": Tensor([0.25])}
        self.drained_parts.append(text)


def configuration():
    cfg = json.loads((ROOT / "config/server.json").read_text())
    cfg.update({
        "backend": "cosyvoice300m",
        "voice_id": "中文女",
        "voices": {
            "中文女": "Chinese",
            "中文男": "Chinese",
        },
        "instruction": "用自然、清晰、中性的语气播报。",
        "model_segment_units": 80,
        "max_concurrency": 1,
        "model": "/models/CosyVoice-300M-Instruct",
        "load_jit": True,
        "load_onnx": False,
        "fp16": True,
    })
    return cfg


class CosyVoice300MEngineTest(unittest.TestCase):
    def setUp(self):
        self.model = FakeModel()
        self.engine = CosyVoice300MEngine(self.model, configuration())

    @staticmethod
    def metric_count():
        return next(
            sample.value
            for family in TTS_TTFT.collect()
            for sample in family.samples
            if sample.name == "tts_time_to_first_token_seconds_count"
        )

    def test_uses_fixed_voice_instruction_and_streaming_output(self):
        pcm = b"".join(self.engine.synthesize_segment(
            "第一句。", "request", "seg-001",
        ))

        self.assertEqual(self.model.calls, [
            ("第一句。", "中文女", "用自然、清晰、中性的语气播报。", True, 1.0),
        ])
        self.assertEqual(
            np.frombuffer(pcm, dtype="<i2").tolist(),
            [-32767, 0, 32767, 8192],
        )

    def test_rejects_non_finite_audio_samples(self):
        for value in (np.nan, np.inf, -np.inf):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "non-finite audio",
            ):
                self.engine.pcm16(Tensor([value]))

    def test_preserves_native_multi_part_normalization(self):
        self.model.frontend.native_parts = ["第一句。", "第二句！"]

        self.assertEqual(self.engine.subdivide("原始输入"), ["第一句。", "第二句！"])
        self.assertEqual(self.model.frontend.calls, [("原始输入", True)])

    def test_hard_splits_unpunctuated_chinese_after_native_split(self):
        text = "测" * 170

        parts = self.engine.subdivide(text)

        self.assertEqual("".join(parts), text)
        self.assertEqual([len(part) for part in parts], [80, 80, 10])

    def test_splits_long_english_at_whitespace_without_losing_content(self):
        text = "a" * 50 + " " + "b" * 50 + " " + "c" * 20

        parts = self.engine.subdivide(text)

        self.assertEqual(parts, ["a" * 50 + " ", "b" * 50 + " " + "c" * 20])
        self.assertEqual("".join(parts), text)

    def test_hard_splits_long_english_without_whitespace(self):
        text = "x" * 170

        parts = self.engine.subdivide(text)

        self.assertEqual("".join(parts), text)
        self.assertEqual([len(part) for part in parts], [80, 80, 10])

    def test_preserves_commas_when_using_fallback_boundaries(self):
        text = "甲" * 50 + "，" + "乙" * 50 + "," + "丙" * 20

        parts = self.engine.subdivide(text)

        self.assertEqual(parts, ["甲" * 50 + "，", "乙" * 50 + "," + "丙" * 20])
        self.assertEqual("".join(parts), text)

    def test_rejects_empty_native_normalization(self):
        for native_parts in ([], [""], ["有效", ""]):
            with self.subTest(native_parts=native_parts):
                self.model.frontend.native_parts = native_parts
                with self.assertRaisesRegex(ValueError, "empty segment"):
                    self.engine.subdivide("输入")

    def test_one_outer_segment_records_one_ttft_for_multiple_internal_parts(self):
        self.model.frontend.native_parts = ["第一句。", "第二句。"]
        before = self.metric_count()

        list(self.engine.synthesize_segment("原始输入", "request", "seg-001"))

        self.assertEqual(self.model.model.llm.calls, 2)
        self.assertEqual(self.metric_count(), before + 1)

    def test_closing_pcm_iterator_drains_only_the_active_vendor_generator(self):
        self.model.frontend.native_parts = ["第一句。", "第二句。"]
        iterator = self.engine.synthesize_segment("原始输入", "request", "seg-001")

        self.assertEqual(
            np.frombuffer(next(iterator), dtype="<i2").tolist(),
            [-32767, 0, 32767],
        )
        iterator.close()

        self.assertEqual(self.model.started_parts, ["第一句。"])
        self.assertEqual(self.model.drained_parts, ["第一句。"])

    def test_concurrency_slot_has_one_owner(self):
        self.assertTrue(self.engine.acquire())
        self.assertFalse(self.engine.acquire())
        self.engine.release()


class CosyVoice300MLoaderTest(unittest.TestCase):
    @staticmethod
    def fake_vendor_module(model_class):
        cosyvoice = ModuleType("cosyvoice")
        cli = ModuleType("cosyvoice.cli")
        vendor = ModuleType("cosyvoice.cli.cosyvoice")
        vendor.CosyVoice = model_class
        return {
            "cosyvoice": cosyvoice,
            "cosyvoice.cli": cli,
            "cosyvoice.cli.cosyvoice": vendor,
        }

    def test_selected_300m_loader_uses_pinned_flags_and_checks_speakers(self):
        calls = []

        class Model(FakeModel):
            def __init__(self, model, load_jit, load_onnx, fp16):
                super().__init__()
                calls.append((model, load_jit, load_onnx, fp16))

            def list_avaliable_spks(self):
                return ["中文男", "中文女"]

        from server import load_engine

        cfg = configuration()
        with patch.dict(sys.modules, self.fake_vendor_module(Model)):
            engine = load_engine(cfg)

        self.assertIsInstance(engine, CosyVoice300MEngine)
        self.assertEqual(calls, [
            ("/models/CosyVoice-300M-Instruct", True, False, True),
        ])

    def test_selected_300m_loader_rejects_checkpoint_speaker_mismatch(self):
        class Model(FakeModel):
            def __init__(self, *args, **kwargs):
                super().__init__()

            def list_avaliable_spks(self):
                return ["中文女"]

        from server import load_engine

        with (patch.dict(sys.modules, self.fake_vendor_module(Model)),
              self.assertRaisesRegex(RuntimeError, "speaker metadata mismatch")):
            load_engine(configuration())


if __name__ == "__main__":
    unittest.main()
