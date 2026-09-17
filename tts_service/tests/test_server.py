"""CPU-only tests for the reusable TTS WebSocket protocol."""

import json
import logging
from pathlib import Path
import sys
import threading
import unittest

import numpy as np
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from engine import CosyVoice3Engine
from server import VendorPayloadFilter, create_app


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
        yield 101


class FakeVendor:
    def __init__(self):
        self.llm = FakeLlm()


class InteractiveModel:
    """Yield once after the first text chunk, then wait for input.done."""

    def __init__(self):
        self.model = FakeVendor()
        self.calls = []
        self.first_text = threading.Event()
        self.finished_text = threading.Event()
        self.pause_after_done = False
        self.release = threading.Event()
        self.fail = False

    def inference_zero_shot(self, text, prompt_text, prompt_wav, zero_shot_spk_id="",
                            stream=False, speed=1.0):
        self.calls.append((prompt_text, prompt_wav, zero_shot_spk_id, stream, speed))
        iterator = iter(text)
        next(iterator)
        self.first_text.set()
        if self.fail:
            raise RuntimeError("sensitive-internal-model-failure")
        yield {"tts_speech": Tensor([-1.0, 0.0, 1.0])}
        list(iterator)
        self.finished_text.set()
        if self.pause_after_done:
            self.release.wait(2)
        yield {"tts_speech": Tensor([0.25, -0.25])}


def configuration():
    cfg = json.loads((ROOT / "config/server.json").read_text())
    cfg.update({
        "model_name": "fun-cosyvoice3-0.5b-2512",
        "voice_id": "aishell3-female",
        "sample_rate_hz": 24000,
        "prompt_text": "固定参考音频的准确文本。",
        "prompt_wav": "/tmp/aishell3-female.wav",
        "max_input_chunk_characters": 1024,
        "max_utterance_characters": 4096,
        "max_message_bytes": 16384,
        "input_timeout_seconds": 2,
        "text_queue_chunks": 4,
        "text_queue_timeout_seconds": 1,
        "max_concurrency": 1,
    })
    return cfg


class TtsServerTest(unittest.TestCase):
    def setUp(self):
        self.model = InteractiveModel()
        self.engine = CosyVoice3Engine(self.model, configuration())
        self.client = TestClient(create_app(self.engine, configuration(), "internal-secret"))
        self.headers = {"Authorization": "Bearer internal-secret", "X-Request-ID": "request-test"}

    def receive_utterance_tail(self, websocket):
        self.assertIsInstance(websocket.receive_bytes(), bytes)
        event = websocket.receive_json()
        self.assertEqual(event["type"], "audio.done")
        return event

    def test_auth_internal_health_metrics_and_removed_http_business_routes(self):
        self.assertEqual(self.client.get("/health").status_code, 401)
        self.assertEqual(self.client.get("/health", headers=self.headers).json(), {"status": "ok"})
        metrics = self.client.get("/metrics", headers=self.headers)
        self.assertEqual(metrics.status_code, 200)
        self.assertIn("tts_time_to_first_token_seconds", metrics.text)
        self.assertEqual(self.client.post("/v1/audio/speech", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get("/v1/audio/voices", headers=self.headers).status_code, 404)

    def test_rejects_bad_websocket_auth(self):
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect("/realtime") as websocket:
                websocket.receive_json()
        self.assertEqual(caught.exception.code, 1008)

    def test_streams_audio_before_done_and_reuses_the_connection(self):
        with self.client.websocket_connect("/realtime", headers=self.headers) as websocket:
            created = websocket.receive_json()
            self.assertEqual(created, {
                "type": "session.created",
                "session_id": created["session_id"],
                "model": "fun-cosyvoice3-0.5b-2512",
                "voice": "aishell3-female",
                "audio": {"format": "pcm_s16le", "sample_rate_hz": 24000, "channels": 1},
            })

            websocket.send_json({"type": "input.text", "text": "第一段足够长的文本。"})
            start = websocket.receive_json()
            self.assertEqual(start["type"], "audio.start")
            first_pcm = websocket.receive_bytes()
            self.assertEqual(np.frombuffer(first_pcm, dtype="<i2").tolist(), [-32767, 0, 32767])
            self.assertFalse(self.model.finished_text.is_set())
            websocket.send_json({"type": "input.text", "text": "继续追加。"})
            websocket.send_json({"type": "input.done"})
            done = self.receive_utterance_tail(websocket)
            self.assertEqual(done["utterance_id"], start["utterance_id"])

            websocket.send_json({"type": "input.text", "text": "第二个请求。"})
            second_start = websocket.receive_json()
            self.assertEqual(second_start["type"], "audio.start")
            websocket.receive_bytes()
            websocket.send_json({"type": "input.done"})
            self.receive_utterance_tail(websocket)
            websocket.send_json({"type": "session.close"})
            with self.assertRaises(WebSocketDisconnect) as caught:
                websocket.receive_json()
            self.assertEqual(caught.exception.code, 1000)
        self.assertEqual(len(self.model.calls), 2)

    def test_recoverable_input_errors_leave_the_session_usable(self):
        with self.client.websocket_connect("/realtime", headers=self.headers) as websocket:
            websocket.receive_json()
            websocket.send_text("{")
            self.assertEqual(websocket.receive_json()["code"], "invalid_json")
            websocket.send_bytes(b"not-json")
            self.assertEqual(websocket.receive_json()["code"], "invalid_message")
            invalid = [
                {"type": "unknown"},
                {"type": "input.text", "text": "  "},
                {"type": "input.text", "text": "坏<|endoftext|>文本"},
                {"type": "input.text", "text": "字" * 1025},
                {"type": "input.done"},
            ]
            for message in invalid:
                websocket.send_json(message)
                error = websocket.receive_json()
                self.assertEqual(error["type"], "error")
                self.assertFalse(error["fatal"])

            websocket.send_json({"type": "input.text", "text": "错误后仍可使用。"})
            self.assertEqual(websocket.receive_json()["type"], "audio.start")
            websocket.receive_bytes()
            websocket.send_text("{")
            self.assertEqual(websocket.receive_json()["code"], "invalid_json")
            websocket.send_json({"type": "input.done"})
            self.receive_utterance_tail(websocket)

    def test_rejects_text_after_done_until_audio_done(self):
        self.model.pause_after_done = True
        with self.client.websocket_connect("/realtime", headers=self.headers) as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "input.text", "text": "当前请求。"})
            websocket.receive_json()
            websocket.receive_bytes()
            websocket.send_json({"type": "input.done"})
            self.assertTrue(self.model.finished_text.wait(1))
            websocket.send_json({"type": "input.text", "text": "发送得太早。"})
            error = websocket.receive_json()
            self.assertEqual((error["type"], error["code"], error["fatal"]),
                             ("error", "invalid_state", False))
            self.model.release.set()
            self.receive_utterance_tail(websocket)

    def test_limits_total_utterance_characters(self):
        with self.client.websocket_connect("/realtime", headers=self.headers) as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "input.text", "text": "字" * 1024})
            websocket.receive_json()
            websocket.receive_bytes()
            for _ in range(3):
                websocket.send_json({"type": "input.text", "text": "字" * 1024})
            websocket.send_json({"type": "input.text", "text": "多"})
            error = websocket.receive_json()
            self.assertEqual(error["code"], "input_too_long")
            self.assertFalse(error["fatal"])
            self.receive_utterance_tail(websocket)

    def test_second_connection_is_rejected_until_first_closes(self):
        with self.client.websocket_connect("/realtime", headers=self.headers) as first:
            first.receive_json()
            with self.assertRaises(WebSocketDisconnect) as caught:
                with self.client.websocket_connect("/realtime", headers=self.headers) as second:
                    second.receive_json()
            self.assertEqual(caught.exception.code, 1013)
        with self.client.websocket_connect("/realtime", headers=self.headers) as next_session:
            self.assertEqual(next_session.receive_json()["type"], "session.created")

    def test_model_error_is_fatal_without_exposing_internal_message(self):
        self.model.fail = True
        with self.assertLogs("tts-service", level="ERROR") as captured:
            with self.client.websocket_connect("/realtime", headers=self.headers) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "input.text", "text": "私密文本"})
                self.assertEqual(websocket.receive_json()["type"], "audio.start")
                error = websocket.receive_json()
                self.assertEqual((error["type"], error["code"], error["fatal"]),
                                 ("error", "inference_failed", True))
                self.assertNotIn("sensitive", error["message"])
                self.assertNotIn("私密", error["message"])
                with self.assertRaises(WebSocketDisconnect):
                    websocket.receive_json()
        log = "\n".join(captured.output)
        self.assertIn("error_type=RuntimeError", log)
        self.assertNotIn("sensitive-internal-model-failure", log)
        self.assertNotIn("私密文本", log)

    def test_vendor_payload_filter_removes_text_bearing_records(self):
        payload_filter = VendorPayloadFilter()
        sensitive = logging.LogRecord("root", logging.INFO, "", 0,
                                      "synthesis text 客户隐私内容", (), None)
        ordinary = logging.LogRecord("root", logging.INFO, "", 0,
                                     "yield speech len 1.0, rtf 2.0", (), None)
        self.assertFalse(payload_filter.filter(sensitive))
        self.assertTrue(payload_filter.filter(ordinary))


if __name__ == "__main__":
    unittest.main()
