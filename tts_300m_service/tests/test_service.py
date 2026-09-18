import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import service


class ServiceConfigurationTest(unittest.TestCase):
    def test_fixed_300m_configuration(self):
        cfg = service.config(require_artifacts=False)
        self.assertEqual(cfg["backend"], "cosyvoice300m")
        self.assertEqual(cfg["model_name"], "cosyvoice-300m-instruct")
        self.assertEqual((cfg["voice_id"], cfg["sample_rate_hz"]), ("中文女", 22050))
        self.assertEqual(cfg["inference_mode"], "instruct")
        self.assertEqual(cfg["instruction"], "Speak in a natural, clear, and neutral tone.")
        self.assertEqual(cfg["random_seed"], 42)
        self.assertEqual(cfg["number_reading"], "chinese")
        self.assertNotIn("voices", cfg)
        self.assertEqual((cfg["max_queued_segments"], cfg["max_queued_characters"]),
                         (8, 4096))

    def test_rejects_non_loopback_and_changed_protocol_limits(self):
        original = json.loads(service.CONFIG.read_text())
        for change in ({"host": "0.0.0.0"}, {"max_queued_segments": 9},
                       {"voice_id": "中文男"}, {"inference_mode": "sft"},
                       {"random_seed": -1}, {"random_seed": 43},
                       {"number_reading": "english"},
                       {"instruction": "Speak naturally."}, {"load_jit": False}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "server.json"
                path.write_text(json.dumps({**original, **change}, ensure_ascii=False))
                with patch.object(service, "CONFIG", path), self.assertRaises(ValueError):
                    service.config(require_artifacts=False)

    def test_environment_prioritizes_pinned_source_and_local_packages(self):
        cfg = service.config(require_artifacts=False)
        env = service.environment(cfg)
        paths = env["PYTHONPATH"].split(":")
        self.assertEqual(paths[0], cfg["source"])
        self.assertEqual(paths[2], str(service.VENV_SITE))
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "0")
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")

    def test_port_probe_reports_a_bound_socket(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            self.assertTrue(service.port_in_use("127.0.0.1", listener.getsockname()[1]))

    def test_internal_key_is_private_and_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "runtime/api_key"
            with patch.object(service, "KEY", key):
                service.init_key()
                first = key.read_text()
                service.init_key()
                self.assertEqual(key.read_text(), first)
                self.assertEqual(key.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
