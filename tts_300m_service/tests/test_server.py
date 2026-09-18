from pathlib import Path
import sys
import unittest

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from server import VendorPayloadFilter, create_app


class FakeEngine:
    def __init__(self):
        self.owned = False
        self.calls = []

    def acquire(self):
        if self.owned:
            return False
        self.owned = True
        return True

    def release(self):
        self.owned = False

    def synthesize_segment(self, text, request_id, segment_id):
        self.calls.append((text, segment_id))
        yield b"\x01\x00\x02\x00"


def configuration():
    return {
        "model_name": "cosyvoice-300m-instruct", "voice_id": "中文女",
        "sample_rate_hz": 22050, "max_segment_characters": 2000,
        "max_queued_segments": 8, "max_queued_characters": 4096,
        "max_message_bytes": 16384, "session_idle_timeout_seconds": 3600,
        "output_timeout_seconds": 1,
    }


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        self.client = TestClient(create_app(self.engine, configuration(), "internal-secret"))

    def test_health_requires_internal_key(self):
        self.assertEqual(self.client.get("/health").status_code, 401)
        response = self.client.get(
            "/health", headers={"Authorization": "Bearer internal-secret"},
        )
        self.assertEqual(response.json(), {"status": "ok"})

    def test_segment_session_metadata_and_pcm(self):
        with self.client.websocket_connect(
            "/realtime", headers={"Authorization": "Bearer internal-secret"},
        ) as websocket:
            session = websocket.receive_json()
            self.assertEqual(session["model"], "cosyvoice-300m-instruct")
            self.assertEqual(session["voice"], "中文女")
            self.assertEqual(session["audio"], {
                "format": "pcm_s16le", "sample_rate_hz": 22050, "channels": 1,
            })
            self.assertNotIn("input_mode", session)
            websocket.send_json({
                "type": "input.segment", "segment_id": "seg-1", "text": "测试。",
            })
            self.assertEqual(websocket.receive_json(), {
                "type": "input.accepted", "segment_id": "seg-1",
            })
            self.assertEqual(websocket.receive_json(), {
                "type": "audio.start", "segment_id": "seg-1",
            })
            self.assertEqual(websocket.receive_bytes(), b"\x01\x00\x02\x00")
            self.assertEqual(websocket.receive_json(), {
                "type": "audio.done", "segment_id": "seg-1",
            })
            websocket.send_json({"type": "session.close"})
        self.assertEqual(self.engine.calls, [("测试。", "seg-1")])

    def test_vendor_filter_removes_synthesis_payload(self):
        import logging
        record = logging.LogRecord("vendor", logging.INFO, "", 0,
                                   "synthesis text secret", (), None)
        self.assertFalse(VendorPayloadFilter().filter(record))


if __name__ == "__main__":
    unittest.main()
