"""Filesystem-only tests for pinned CosyVoice3 service configuration."""

import base64
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave


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
        self.source_patch = root / "source.patch"
        self.prompt = root / "voice.wav"
        self.manifest = root / "voice.json"
        self.base_packages = root / "base-packages.json"
        self.path = root / "server.json"
        self.model.mkdir()
        (self.model / "CosyVoice-BlankEN").mkdir()
        for name in (
            "cosyvoice3.yaml", "config.json", "llm.pt", "flow.pt", "hift.pt", "campplus.onnx",
            "speech_tokenizer_v3.onnx", "CosyVoice-BlankEN/config.json",
            "CosyVoice-BlankEN/generation_config.json",
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
        self.source_patch.write_text("pinned patch\n")
        sample_rate = 24000
        samples = []
        for index in range(sample_rate * 6):
            phase = index % (sample_rate // 2)
            if (index < sample_rate // 5
                    or index >= sample_rate * 6 - sample_rate // 5
                    or phase < sample_rate // 10):
                value = 0
            else:
                value = round(2000 * math.sin(2 * math.pi * 220 * index / sample_rate))
            samples.append(value)
        with wave.open(str(self.prompt), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        self.manifest.write_text(json.dumps({
            "voice_id": "aishell3-female",
            "prompt_text": "You are a helpful assistant.<|endofprompt|>大家都在琢磨如何在产品差异和服务上下更多功夫",
            "dataset": {
                "repository": "AISHELL/AISHELL-3",
                "revision": "f20d5db4a31fe779ef07bb1af4ea92da5c786622",
                "license": "Apache-2.0",
                "speaker": {"id": "SSB0005", "gender": "female"},
                "transcript_index": {"path": "train/content.txt", "sha256": "e" * 64},
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
                "samples": len(samples),
                "duration_seconds": 6.0,
                "sha256": digest(self.prompt),
            },
        }))
        self.base_packages.write_text(json.dumps({
            "schema_version": 1,
            "packages": {
                "torch": {
                    "name": "torch",
                    "version": "2.7.1+corex.4.4.0",
                    "root": "corex",
                    "record_sha256": "a" * 64,
                },
            },
        }))
        self.cfg = {
            "model": str(self.model),
            "model_name": "fun-cosyvoice3-0.5b-2512",
            "model_revision": "29e01c4e8d000f4bcd70751be16fa94bf3d85a18",
            "model_checksums": {
                name: digest(self.model / name)
                for name in (
                    "cosyvoice3.yaml", "config.json", "llm.pt", "flow.pt", "hift.pt",
                    "campplus.onnx", "speech_tokenizer_v3.onnx",
                    "CosyVoice-BlankEN/config.json", "CosyVoice-BlankEN/generation_config.json",
                    "CosyVoice-BlankEN/model.safetensors",
                    "CosyVoice-BlankEN/merges.txt", "CosyVoice-BlankEN/tokenizer_config.json",
                    "CosyVoice-BlankEN/vocab.json",
                )
            },
            "source": str(self.source),
            "source_revision": "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc",
            "source_patch": str(self.source_patch),
            "source_patch_sha256": digest(self.source_patch),
            "source_tree_diff_sha256": "a" * 64,
            "source_submodules": {},
            "base_packages": str(self.base_packages),
            "source_checksums": {
                name: digest(self.source / name)
                for name in ("cosyvoice/cli/cosyvoice.py", "cosyvoice/cli/frontend.py",
                             "cosyvoice/cli/model.py", "cosyvoice/hifigan/generator.py")
            },
            "voice_manifest": str(self.manifest),
            "voice_manifest_sha256": digest(self.manifest),
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
            "output_timeout_seconds": 30,
            "max_concurrency": 1,
            "minimum_free_memory_mb": 6000,
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
            "minimum_free_memory_mb": 0,
            "output_timeout_seconds": 0,
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
        for path in (self.model / "llm.pt", self.model / "CosyVoice-BlankEN/vocab.json",
                     self.source / "cosyvoice/cli/frontend.py",
                     self.prompt):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    self.load()
                path.write_bytes(original)

    def test_rejects_incomplete_model_checksum_set(self):
        self.cfg["model_checksums"].pop("CosyVoice-BlankEN/vocab.json")
        self.write_config()
        with self.assertRaisesRegex(ValueError, "every required model artifact"):
            self.load()

    def test_resolves_service_paths_relative_to_the_config_file(self):
        root = self.path.parent
        self.cfg["source"] = str(self.source.relative_to(root))
        self.cfg["source_patch"] = str(self.source_patch.relative_to(root))
        self.cfg["voice_manifest"] = str(self.manifest.relative_to(root))
        self.cfg["prompt_wav"] = str(self.prompt.relative_to(root))
        self.cfg["base_packages"] = str(self.base_packages.relative_to(root))
        self.write_config()
        cfg = self.load()
        self.assertEqual(cfg["source"], str(self.source.resolve()))
        self.assertEqual(cfg["source_patch"], str(self.source_patch.resolve()))
        self.assertEqual(cfg["voice_manifest"], str(self.manifest.resolve()))
        self.assertEqual(cfg["prompt_wav"], str(self.prompt.resolve()))
        self.assertEqual(cfg["base_packages"], str(self.base_packages.resolve()))

    def test_rejects_invalid_base_package_manifest(self):
        manifest = json.loads(self.base_packages.read_text())
        manifest["packages"]["torch"]["record_sha256"] = "not-a-digest"
        self.base_packages.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "base package manifest entry"):
            self.load()

    def test_validates_base_package_version_and_record_fingerprint(self):
        package_root = self.path.parent / "packages"
        dist_info = package_root / "example_pkg-1.2.3.dist-info"
        dist_info.mkdir(parents=True)
        (dist_info / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: example-pkg\nVersion: 1.2.3\n"
        )
        metadata_digest = base64.urlsafe_b64encode(
            hashlib.sha256((dist_info / "METADATA").read_bytes()).digest(),
        ).rstrip(b"=").decode()
        (dist_info / "RECORD").write_text(
            f"example_pkg-1.2.3.dist-info/METADATA,sha256={metadata_digest},"
            f"{(dist_info / 'METADATA').stat().st_size}\n"
            "example_pkg-1.2.3.dist-info/RECORD,,\n"
        )
        self.base_packages.write_text(json.dumps({
            "schema_version": 1,
            "packages": {
                "example-pkg": {
                    "name": "example-pkg",
                    "version": "1.2.3",
                    "root": "corex",
                    "record_sha256": digest(dist_info / "RECORD"),
                },
            },
        }))
        cfg = self.load()
        with patch.dict(service.BASE_PACKAGE_ROOTS, {"corex": package_root.resolve()}, clear=True):
            service.validate_base_packages(cfg)
            original_metadata = (dist_info / "METADATA").read_text()
            (dist_info / "METADATA").write_text(
                original_metadata.replace("Metadata-Version: 2.1", "Metadata-Version: 2.2"),
            )
            with self.assertRaisesRegex(ValueError, "base package file mismatch"):
                service.validate_base_packages(cfg)
            (dist_info / "METADATA").write_text(original_metadata)
            (dist_info / "RECORD").write_text("changed\n")
            with self.assertRaisesRegex(ValueError, "RECORD mismatch"):
                service.validate_base_packages(cfg)

    def test_local_package_set_must_exactly_match_the_hash_locks(self):
        package_root = self.path.parent / "local-packages"
        dist_info = package_root / "example_pkg-1.2.3.dist-info"
        dist_info.mkdir(parents=True)
        (dist_info / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: example-pkg\nVersion: 1.2.3\n"
        )
        (dist_info / "RECORD").write_text("")
        lock = self.path.parent / "requirements.lock"
        lock.write_text("example-pkg==1.2.3 \\\n    --hash=sha256:" + "a" * 64 + "\n")
        rogue = package_root / "rogue-9.9.dist-info"
        rogue.mkdir()
        (rogue / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: rogue\nVersion: 9.9\n"
        )
        (rogue / "RECORD").write_text("")
        with (patch.object(service, "VENV_SITE", package_root),
              patch.object(service, "LOCK_FILES", (lock,))):
            with self.assertRaisesRegex(ValueError, "extra=.*rogue"):
                service.validate_local_packages()

    def test_validates_full_source_checkout_revision_patch_and_diff(self):
        other = self.source / "cosyvoice/other.py"
        other.write_text("tracked source\n")
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        subprocess.run(["git", "-C", str(self.source), "config", "user.name", "test"], check=True)
        subprocess.run(["git", "-C", str(self.source), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.source), "commit", "-qm", "base"], check=True)
        for relative in self.cfg["source_checksums"]:
            path = self.source / relative
            path.write_bytes(path.read_bytes() + b"patched")
            self.cfg["source_checksums"][relative] = digest(path)
        self.cfg["source_revision"] = subprocess.run(
            ["git", "-C", str(self.source), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        source_diff = subprocess.run(
            ["git", "-C", str(self.source), "diff", "--no-ext-diff", "--binary",
             "HEAD", "--", "."], check=True, capture_output=True,
        ).stdout
        self.cfg["source_tree_diff_sha256"] = hashlib.sha256(source_diff).hexdigest()
        self.write_config()
        cfg = self.load()
        service.validate_source_checkout(cfg)
        other.write_text("changed after provisioning\n")
        with self.assertRaisesRegex(ValueError, "working tree mismatch"):
            service.validate_source_checkout(cfg)

    def test_rejects_clipped_fixed_voice(self):
        with wave.open(str(self.prompt), "rb") as source:
            params = source.getparams()
            audio = bytearray(source.readframes(source.getnframes()))
        audio[100:102] = struct.pack("<h", 32767)
        with wave.open(str(self.prompt), "wb") as output:
            output.setparams(params)
            output.writeframes(audio)
        manifest = json.loads(self.manifest.read_text())
        manifest["derived"]["sha256"] = digest(self.prompt)
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "clipped"):
            self.load()

    def test_rejects_fixed_voice_without_quiet_edge_padding(self):
        with wave.open(str(self.prompt), "rb") as source:
            params = source.getparams()
            audio = bytearray(source.readframes(source.getnframes()))
        for offset in range(0, 2400 * 2, 2):
            audio[offset:offset + 2] = struct.pack("<h", 2000)
        with wave.open(str(self.prompt), "wb") as output:
            output.setparams(params)
            output.writeframes(audio)
        manifest = json.loads(self.manifest.read_text())
        manifest["derived"]["sha256"] = digest(self.prompt)
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "edge silence"):
            self.load()

    def test_rejects_fixed_voice_with_low_estimated_snr(self):
        with wave.open(str(self.prompt), "rb") as source:
            params = source.getparams()
            samples = list(struct.unpack(
                f"<{source.getnframes()}h", source.readframes(source.getnframes()),
            ))
        for index in range(4800, len(samples) - 4800):
            samples[index] = max(-32766, min(32766, samples[index] + (1000 if index % 2 else -1000)))
        with wave.open(str(self.prompt), "wb") as output:
            output.setparams(params)
            output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        manifest = json.loads(self.manifest.read_text())
        manifest["derived"]["sha256"] = digest(self.prompt)
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "SNR"):
            self.load()

    def test_transcript_must_match_the_pinned_aishell_index(self):
        manifest = json.loads(self.manifest.read_text())
        line = "SSB00050095.wav 大 da4 家 jia1 都 dou1 在 zai4 琢 zuo2 磨 mo5 如 ru2 何 he2 在 zai4 产 chan2 品 pin3 差 cha1 异 yi4 和 he2 服 fu2 务 wu4 上 shang4 下 xia4 更 geng4 多 duo1 功 gong1 夫 fu5"
        service.validate_transcript_index(manifest, line)
        manifest["dataset"]["utterances"][0]["transcript"] = "错误转写"
        with self.assertRaisesRegex(ValueError, "transcript mismatch"):
            service.validate_transcript_index(manifest, line)

    def test_rejects_cosyvoice3_prompt_without_endofprompt(self):
        manifest = json.loads(self.manifest.read_text())
        manifest["prompt_text"] = manifest["dataset"]["utterances"][0]["transcript"]
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "prompt text"):
            self.load()

    def test_rejects_an_otherwise_valid_changed_voice_manifest(self):
        manifest = json.loads(self.manifest.read_text())
        manifest["dataset"]["url"] = "https://example.invalid/replaced"
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "voice manifest mismatch"):
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
