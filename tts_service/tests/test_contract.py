"""Cross-file checks for the published CosyVoice3 WebSocket contract."""

from pathlib import Path
import unittest

import yaml


REPO = Path(__file__).resolve().parents[2]


class TtsContractTest(unittest.TestCase):
    def test_openapi_exposes_only_the_tts_websocket_handshake(self):
        contract = yaml.safe_load((REPO / "contracts/openapi.yaml").read_text())
        tts_paths = {path for path in contract["paths"] if path.startswith("/tts/")}
        self.assertEqual(tts_paths, {"/tts/v1/realtime"})
        operation = contract["paths"]["/tts/v1/realtime"]["get"]
        self.assertEqual(operation["x-websocket-contract"], "./tts-websocket.md")
        self.assertIn("101", operation["responses"])
        self.assertEqual(operation["x-max-active-connections"], 1)
        self.assertEqual(operation["x-max-message-bytes"], 16384)
        self.assertFalse(any(name.startswith("Tts") for name in
                             contract["components"]["schemas"]))

    def test_websocket_contract_records_the_fixed_protocol_and_limits(self):
        text = (REPO / "contracts/tts-websocket.md").read_text()
        for value in ("fun-cosyvoice3-0.5b-2512", "aishell3-female", "24000",
                      "input.text", "input.done", "session.close", "session.created",
                      "audio.start", "audio.done", "pcm_s16le", "16384", "4096",
                      "300", "3600", "tts_time_to_first_token_seconds"):
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_current_readmes_do_not_advertise_the_removed_tts_http_api(self):
        files = (REPO / "README.md", REPO / "contracts/README.md",
                 REPO / "gateway/README.md", REPO / "tts_service/README.md",
                 REPO / "monitor_service/README.md")
        forbidden = ("/tts/v1/audio/speech", "/tts/v1/audio/voices", "/tts/health/ready",
                     "cosyvoice-300m-instruct", "22050 Hz", "TTS 使用每个 HTTP 请求")
        for path in files:
            text = path.read_text()
            for value in forbidden:
                with self.subTest(path=path.name, value=value):
                    self.assertNotIn(value, text)


if __name__ == "__main__":
    unittest.main()
