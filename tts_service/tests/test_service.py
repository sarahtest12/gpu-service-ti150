"""Filesystem-only tests for pinned CosyVoice3 service configuration."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import service


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ServiceConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.model = root / "model"
        self.source = root / "source"
        self.prompt = root / "voice.wav"
        self.manifest = root / "voice.json"
        self.path = root / "server.json"
        self.model.mkdir()
        (self.model / "CosyVoice-BlankEN").mkdir()
        for name in (
            "cosyvoice3.yaml", "llm.pt", "flow.pt", "hift.pt", "campplus.onnx",
            "speech_tokenizer_v3.onnx", "CosyVoice-BlankEN/config.json",
            "CosyVoice-BlankEN/model.safetensors", "CosyVoice-BlankEN/merges.txt",
            "CosyVoice-BlankEN/tokenizer_config.json", "CosyVoice-BlankEN/vocab.json",
        ):
            path = self.model / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("model:" + name).encode())
        for name in (
            "cosyvoice/cli/cosyvoice.py", "cosyvoice/cli/frontend.py",
            "cosyvoice/cli/model.py", "cosyvoice/hifigan/generator.py",
        ):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("source:" + name).encode())
        (self.source / "third_party/Matcha-TTS/matcha").mkdir(parents=True)
        self.prompt.write_bytes(b"RIFF-fixed-voice")
        self.manifest.write_text(json.dumps({
            "voice_id": "aishell3-female",
            "prompt_text": "You are a helpful assistant.<|endofprompt|>大家都在琢磨如何在产品差异和服务上下更多功夫",
            "dataset": {
                "repository": "AISHELL/AISHELL-3",
                "revision": "f20d5db4a31fe779ef07bb1af4ea92da5c786622",
                "license": "Apache-2.0",
                "speaker": {"id": "SSB0005", "gender": "female"},
                "utterances": [{
                    "path": "train/wav/SSB0005/SSB00050095.wav",
                    "transcript": "大家都在琢磨如何在产品差异和服务上下更多功夫",
                    "sha256": "f" * 64,
                    "sample_rate_hz": 44100,
                    "samples": 371986,
                    "trim_start_sample": 13894,
                    "trim_end_sample": 357548,
                }],
            },
            "derived": {
                "sample_rate_hz": 24000,
                "channels": 1,
                "samples": 187023,
                "sha256": digest(self.prompt),
            },
        }))
        self.cfg = {
            "model": str(self.model),
            "model_name": "fun-cosyvoice3-0.5b-2512",
            "model_revision": "29e01c4e8d000f4bcd70751be16fa94bf3d85a18",
            "model_checksums": {
                name: digest(self.model / name)
                for name in ("llm.pt", "flow.pt", "hift.pt", "campplus.onnx",
                             "speech_tokenizer_v3.onnx", "CosyVoice-BlankEN/model.safetensors")
            },
            "source": str(self.source),
            "source_revision": "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc",
            "source_checksums": {
                name: digest(self.source / name)
                for name in ("cosyvoice/cli/cosyvoice.py", "cosyvoice/cli/frontend.py",
                             "cosyvoice/cli/model.py", "cosyvoice/hifigan/generator.py")
            },
            "voice_manifest": str(self.manifest),
            "prompt_wav": str(self.prompt),
            "voice_id": "aishell3-female",
            "device": 0,
            "host": "127.0.0.1",
            "port": 8004,
            "sample_rate_hz": 24000,
            "max_input_chunk_characters": 1024,
            "max_utterance_characters": 4096,
            "max_message_bytes": 16384,
            "input_timeout_seconds": 300,
            "session_idle_timeout_seconds": 3600,
            "text_queue_chunks": 16,
            "text_queue_timeout_seconds": 30,
            "max_concurrency": 1,
            "load_vllm": False,
            "load_trt": False,
            "fp16": True,
        }
        self.write_config()

    def write_config(self):
        self.path.write_text(json.dumps(self.cfg))

    def load(self):
        with patch.object(service, "CONFIG", self.path):
            return service.config()

    def test_accepts_native_cosyvoice3_and_loads_fixed_voice_metadata(self):
        cfg = self.load()
        self.assertEqual(cfg["model_name"], "fun-cosyvoice3-0.5b-2512")
        self.assertEqual(cfg["sample_rate_hz"], 24000)
        self.assertEqual(cfg["voice_id"], "aishell3-female")
        self.assertEqual(cfg["prompt_text"],
                         "You are a helpful assistant.<|endofprompt|>大家都在琢磨如何在产品差异和服务上下更多功夫")
        self.assertFalse(cfg["load_vllm"])
        self.assertFalse(cfg["load_trt"])

    def test_rejects_modes_that_break_the_validated_deployment(self):
        cases = {
            "model_name": "cosyvoice-300m-instruct",
            "sample_rate_hz": 22050,
            "load_vllm": True,
            "load_trt": True,
            "max_concurrency": 2,
            "device": 1,
            "host": "0.0.0.0",
        }
        for field, invalid in cases.items():
            with self.subTest(field=field):
                original = self.cfg[field]
                self.cfg[field] = invalid
                self.write_config()
                with self.assertRaises((ValueError, KeyError)):
                    self.load()
                self.cfg[field] = original

    def test_rejects_changed_model_source_and_voice_files(self):
        for path in (self.model / "llm.pt", self.source / "cosyvoice/cli/frontend.py",
                     self.prompt):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    self.load()
                path.write_bytes(original)

    def test_rejects_cosyvoice3_prompt_without_endofprompt(self):
        manifest = json.loads(self.manifest.read_text())
        manifest["prompt_text"] = manifest["dataset"]["utterances"][0]["transcript"]
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "prompt text"):
            self.load()

    def test_runtime_prefers_pinned_venv_packages_before_corex_packages(self):
        with patch.object(service, "ROOT", ROOT):
            paths = service.environment(self.cfg)["PYTHONPATH"].split(":")
        self.assertEqual(paths[0], str(self.source))
        self.assertEqual(paths[1], str(self.source / "third_party/Matcha-TTS"))
        self.assertEqual(paths[2], str(ROOT / ".venv/lib/python3.10/site-packages"))
        self.assertEqual(paths[3], "/usr/local/corex/lib64/python3/dist-packages")


if __name__ == "__main__":
    unittest.main()
