"""CPU-only tests for request validation, auth, streaming and concurrency."""

import json
import logging
from pathlib import Path
import sys
import threading
import unittest

import numpy as np
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from server import CosyVoiceEngine, VendorPayloadFilter, create_app


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


class FakeModel:
    def __init__(self):
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.pause = False
        self.drained = threading.Event()

    def inference_instruct(self, text, voice, instructions, *, stream, speed):
        self.calls.append((text, voice, instructions, stream, speed))
        self.started.set()
        yield {"tts_speech": Tensor([-1.0, 0.0, 1.0])}
        if self.pause:
            self.release.wait(2)
        yield {"tts_speech": Tensor([0.25, -0.25])}
        self.drained.set()


def configuration():
    cfg = json.loads((ROOT / "config/server.json").read_text())
    cfg["max_input_characters"] = 20
    cfg["max_instruction_characters"] = 20
    return cfg


class TtsServerTest(unittest.TestCase):
    def setUp(self):
        self.model = FakeModel()
        self.engine = CosyVoiceEngine(self.model, configuration())
        self.client = TestClient(create_app(self.engine, configuration(), "internal-secret"))
        self.headers = {"Authorization": "Bearer internal-secret", "X-Request-ID": "request-test"}
        self.payload = {"model": "cosyvoice-300m-instruct", "input": "测试语音", "voice": "中文女",
                        "instructions": "自然播报", "response_format": "pcm", "stream": True, "speed": 1.0}

    def test_auth_health_and_voice_list(self):
        self.assertEqual(self.client.get("/health").status_code, 401)
        health = self.client.get("/health", headers=self.headers)
        self.assertEqual(health.json(), {"status": "ok"})
        voices = self.client.get("/v1/audio/voices", headers=self.headers).json()["data"]
        self.assertEqual({item["id"] for item in voices}, set(configuration()["voices"]))

    def test_vendor_payload_text_is_not_logged(self):
        payload_filter = VendorPayloadFilter()
        sensitive = logging.LogRecord("root", logging.INFO, "", 0,
                                      "synthesis text 客户隐私内容", (), None)
        ordinary = logging.LogRecord("root", logging.INFO, "", 0,
                                     "yield speech len 1.0, rtf 2.0", (), None)
        self.assertFalse(payload_filter.filter(sensitive))
        self.assertTrue(payload_filter.filter(ordinary))

    def test_streams_little_endian_pcm_and_passes_instructions(self):
        response = self.client.post("/v1/audio/speech", headers=self.headers, json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-audio-format"], "pcm_s16le")
        self.assertEqual(response.headers["x-audio-sample-rate"], "22050")
        values = np.frombuffer(response.content, dtype="<i2").tolist()
        self.assertEqual(values, [-32767, 0, 32767, 8192, -8192])
        self.assertEqual(self.model.calls, [("测试语音", "中文女", "自然播报", True, 1.0)])

    def test_validates_allowlists_lengths_and_extra_fields(self):
        cases = [
            ({**self.payload, "model": "wrong"}, 404),
            ({**self.payload, "voice": "unknown"}, 400),
            ({**self.payload, "input": "字" * 21}, 400),
            ({**self.payload, "instructions": "字" * 21}, 400),
            ({**self.payload, "stream": False}, 422),
            ({**self.payload, "response_format": "wav"}, 422),
            ({**self.payload, "unexpected": True}, 422),
            ({**self.payload, "input": "文本<|endoftext|>"}, 422),
            ({**self.payload, "instructions": "自然<endofprompt>"}, 422),
        ]
        for payload, status in cases:
            with self.subTest(payload=set(payload), status=status):
                self.assertEqual(self.client.post("/v1/audio/speech", headers=self.headers,
                                                  json=payload).status_code, status)

    def test_default_instruction_and_concurrency_limit(self):
        self.assertTrue(self.engine.acquire())
        try:
            self.assertEqual(self.client.post("/v1/audio/speech", headers=self.headers,
                                              json={**self.payload, "instructions": None}).status_code, 429)
        finally:
            self.engine._slots.release()
        response = self.client.post("/v1/audio/speech", headers=self.headers,
                                    json={**self.payload, "instructions": None})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.model.calls[-1][2], configuration()["default_instruction"])

    def test_closing_a_stream_drains_vendor_state_and_releases_the_slot(self):
        self.assertTrue(self.engine.acquire())
        stream = self.engine.stream_locked("测试语音", "中文女", "自然播报")
        self.assertTrue(next(stream))
        stream.close()
        self.assertTrue(self.model.drained.is_set())
        self.assertTrue(self.engine.acquire())
        self.engine._slots.release()


if __name__ == "__main__":
    unittest.main()
