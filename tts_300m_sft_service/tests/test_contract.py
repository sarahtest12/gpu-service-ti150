from pathlib import Path
import unittest

import yaml


REPO = Path(__file__).resolve().parents[2]


class DefaultTtsContractTest(unittest.TestCase):
    def test_openapi_points_to_the_dedicated_300m_service(self):
        contract = yaml.safe_load((REPO / "contracts/openapi.yaml").read_text())
        self.assertEqual(contract["info"]["version"], "1.1.0")
        self.assertEqual(
            contract["x-source"]["tts_configuration"],
            "../tts_300m_sft_service/config/server.json",
        )
        self.assertEqual(contract["x-source"]["tts_alternate_configuration"],
                         "../tts_300m_service/config/server.json")
        paths = {path for path in contract["paths"] if path.startswith("/tts/")}
        self.assertEqual(paths, {"/tts/v1/realtime"})

    def test_contract_records_segment_protocol_and_limits(self):
        text = (REPO / "contracts/tts-websocket.md").read_text()
        for value in (
            "cosyvoice-300m-sft", "中文女", "22050", "input.segment",
            "input.accepted", "audio.start", "audio.done", "response.cancel",
            "response.cancelled", "queue_full", "duplicate_segment_id", "2000",
            "4096", "tts_time_to_first_token_seconds",
        ):
            with self.subTest(value=value):
                self.assertIn(value, text)
        self.assertNotIn('"input_mode"', text)

    def test_gateway_defaults_to_new_runtime_key(self):
        gateway = yaml.safe_load((REPO / "gateway/config/server.json").read_text())
        self.assertEqual(gateway["tts"]["project"], "tts_300m_sft_service")
        self.assertEqual(gateway["tts"]["api_key_file"],
                         "../../tts_300m_sft_service/runtime/api_key")


if __name__ == "__main__":
    unittest.main()
