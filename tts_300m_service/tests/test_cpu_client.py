import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cpu_client"))

import tts_client


SESSION = json.dumps({
    "type": "session.created",
    "session_id": "tts_test",
    "model": "cosyvoice-300m-instruct",
    "voice": "中文女",
    "audio": {"format": "pcm_s16le", "sample_rate_hz": 22050, "channels": 1},
}, ensure_ascii=False)


class FakeConnection:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []
        self.closed = False

    def recv(self, timeout=None):
        if not self.incoming:
            raise TimeoutError
        return self.incoming.pop(0)

    def send(self, message):
        self.sent.append(json.loads(message))

    def close(self):
        self.closed = True


def event(kind, segment_id, **values):
    return json.dumps({"type": kind, "segment_id": segment_id, **values})


class TtsRealtimeClientTest(unittest.TestCase):
    def connect(self, incoming):
        connection = FakeConnection([SESSION, *incoming])
        patcher = patch.object(tts_client, "websocket_connect", return_value=connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        client = tts_client.TtsRealtimeClient(
            "https://gpu.example/tts", api_key="public-test-key"
        ).connect()
        self.addCleanup(client.close)
        return client, connection

    def test_requires_the_fixed_300m_session(self):
        wrong = json.loads(SESSION)
        wrong["model"] = "another-model"
        connection = FakeConnection([json.dumps(wrong)])
        with patch.object(tts_client, "websocket_connect", return_value=connection):
            client = tts_client.TtsRealtimeClient(
                "https://gpu.example/tts", api_key="public-test-key"
            )
            with self.assertRaisesRegex(RuntimeError, "unsupported model"):
                client.connect()
        self.assertTrue(connection.closed)

    def test_correlates_fifo_audio_frames(self):
        client, connection = self.connect([
            event("input.accepted", "s1"),
            event("audio.start", "s1"),
            b"\x01\x00\x02\x00",
            event("audio.done", "s1"),
        ])
        client.send_segment("s1", "第一段。")
        frames = [client.receive_segment_frame() for _ in range(4)]
        self.assertEqual([frame.kind for frame in frames],
                         ["accepted", "audio_start", "audio", "audio_done"])
        self.assertEqual(frames[2].pcm, b"\x01\x00\x02\x00")
        self.assertEqual(connection.sent[0], {
            "type": "input.segment", "segment_id": "s1", "text": "第一段。"
        })

    def test_rejected_unaccepted_id_can_be_retried(self):
        client, _ = self.connect([
            event("error", "s1", code="queue_full", message="busy", fatal=False),
            event("input.accepted", "s1"),
        ])
        client.send_segment("s1", "第一段。")
        with self.assertRaises(tts_client.SegmentRejected) as caught:
            client.receive_segment_frame()
        self.assertEqual(caught.exception.code, "queue_full")
        client.send_segment("s1", "第一段。")
        self.assertEqual(client.receive_segment_frame().kind, "accepted")

    def test_cancel_confirmation_clears_active_and_queued_segments(self):
        client, connection = self.connect([
            event("input.accepted", "s1"),
            event("input.accepted", "s2"),
            event("audio.start", "s1"),
            event("response.cancelled", "s1"),
        ])
        client.send_segment("s1", "第一段。")
        client.send_segment("s2", "第二段。")
        for _ in range(3):
            client.receive_segment_frame()
        client.cancel_segment("s1")
        frame = client.receive_segment_frame()
        self.assertEqual((frame.kind, frame.segment_id), ("cancelled", "s1"))
        self.assertEqual(connection.sent[-1], {
            "type": "response.cancel", "segment_id": "s1"
        })
        self.assertEqual(client.close(), ())


if __name__ == "__main__":
    unittest.main()
