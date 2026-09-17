"""TLS WebSocket protocol tests for the reusable CPU TTS client."""

import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from websockets.sync.server import serve as websocket_serve


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cpu_client"))

from tts_client import TtsRealtimeClient


class TtsRealtimeClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.certdir = tempfile.TemporaryDirectory()
        cls.cert = Path(cls.certdir.name) / "server.crt"
        cls.key = Path(cls.certdir.name) / "server.key"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-keyout", str(cls.key), "-out", str(cls.cert),
        ], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.certdir.cleanup()

    def setUp(self):
        self.mode = "normal"
        self.headers = []
        self.paths = []
        self.messages = []
        self.connection_messages = []
        self.connections = 0
        self.session_close = threading.Event()
        fixture = self

        def process_request(connection, request):
            fixture.headers.append(dict(request.headers))
            fixture.paths.append(request.path)
            return None

        def handler(connection):
            fixture.connections += 1
            messages = []
            fixture.connection_messages.append(messages)
            metadata = {"type": "session.created", "session_id": "tts_test",
                        "model": "fun-cosyvoice3-0.5b-2512", "voice": "aishell3-female",
                        "audio": {"format": "pcm_s16le", "sample_rate_hz": 24000,
                                  "channels": 1}}
            if fixture.mode == "bad_metadata":
                metadata["audio"]["sample_rate_hz"] = 22050
            if fixture.mode == "bad_identity":
                metadata["voice"] = "unexpected-voice"
            connection.send(json.dumps(metadata))
            utterance = 0
            current_id = None
            for raw in connection:
                event = json.loads(raw)
                fixture.messages.append(event)
                messages.append(event)
                if event["type"] == "session.close":
                    fixture.session_close.set()
                    return
                if event["type"] == "input.text" and current_id is None:
                    utterance += 1
                    current_id = f"utt-{utterance}"
                    if fixture.mode == "error":
                        connection.send(json.dumps({"type": "error", "code": "inference_failed",
                                                    "message": "TTS inference failed", "fatal": True}))
                        return
                    if fixture.mode == "timeout":
                        continue
                    connection.send(json.dumps({"type": "audio.start",
                                                "utterance_id": current_id}))
                    connection.send(bytes((utterance, 0, utterance + 1, 0)))
                elif event["type"] == "input.done" and fixture.mode == "normal":
                    connection.send(bytes((utterance + 2, 0, utterance + 3, 0)))
                    connection.send(json.dumps({"type": "audio.done",
                                                "utterance_id": current_id}))
                    current_id = None

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen()
        self.port = self.socket.getsockname()[1]
        self.server = websocket_serve(handler, sock=self.socket, ssl=context,
                                      process_request=process_request, compression=None,
                                      server_header=None)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.thread.join(timeout=2)

    def client(self, timeout=1):
        return TtsRealtimeClient(f"https://localhost:{self.port}/tts", api_key="public-test-key",
                                 timeout_seconds=timeout, ca_file=self.cert)

    def test_streams_text_and_audio_in_both_directions_and_reuses_connection(self):
        allow_second_text = threading.Event()

        def text_chunks():
            yield "第一段，"
            self.assertTrue(allow_second_text.wait(2))
            yield "第二段。"

        with self.client() as client:
            first_audio = client.synthesize(text_chunks())
            self.assertEqual(next(first_audio), b"\x01\x00\x02\x00")
            self.assertFalse(any(event["type"] == "input.done" for event in self.messages))
            allow_second_text.set()
            self.assertEqual(b"".join(first_audio), b"\x03\x00\x04\x00")
            self.assertEqual(b"".join(client.synthesize(["第三段。"])),
                             b"\x02\x00\x03\x00\x04\x00\x05\x00")
        self.assertTrue(self.session_close.wait(1))
        self.assertEqual(self.connections, 1)
        self.assertEqual(self.paths, ["/tts/v1/realtime"])
        authorization = next(value for name, value in self.headers[0].items()
                             if name.lower() == "authorization")
        self.assertEqual(authorization, "Bearer public-test-key")
        self.assertEqual([event["type"] for event in self.messages],
                         ["input.text", "input.text", "input.done",
                          "input.text", "input.done", "session.close"])

    def test_rejects_unsupported_session_audio_metadata(self):
        self.mode = "bad_metadata"
        with self.assertRaisesRegex(RuntimeError, "unsupported model, voice or audio"):
            self.client().connect()

    def test_rejects_unexpected_fixed_model_or_voice(self):
        self.mode = "bad_identity"
        with self.assertRaisesRegex(RuntimeError, "unsupported model, voice or audio"):
            self.client().connect()

    def test_lazy_iterators_cannot_overlap_on_one_connection(self):
        with self.client() as client:
            first = client.synthesize(["第一条。"])
            second = client.synthesize(["不应并行。"])
            self.assertTrue(next(first))
            with self.assertRaisesRegex(RuntimeError, "already active"):
                next(second)
            self.assertTrue(b"".join(first))

    def test_abandoned_sender_cannot_write_into_reconnected_session(self):
        release_old_text = threading.Event()

        def blocked_text():
            yield "旧请求。"
            self.assertTrue(release_old_text.wait(2))
            yield "不得进入新连接。"

        client = self.client()
        client.connect()
        abandoned = client.synthesize(blocked_text())
        self.assertTrue(next(abandoned))
        abandoned.close()
        client.connect()
        release_old_text.set()
        self.assertTrue(b"".join(client.synthesize(["新请求。"])))
        client.close()
        self.assertEqual(self.connections, 2)
        self.assertEqual(
            [event.get("text") for event in self.connection_messages[1]
             if event["type"] == "input.text"],
            ["新请求。"],
        )

    def test_propagates_server_error_without_reusing_failed_connection(self):
        self.mode = "error"
        client = self.client()
        client.connect()
        with self.assertRaisesRegex(RuntimeError, "inference_failed"):
            list(client.synthesize(["测试错误。"]))
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            list(client.synthesize(["不能复用。"]))

    def test_times_out_when_server_stops_responding(self):
        self.mode = "timeout"
        client = self.client(timeout=0.1)
        client.connect()
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            list(client.synthesize(["测试超时。"]))
        self.assertLess(time.monotonic() - started, 1)

    def test_validates_url_key_and_text_before_network_use(self):
        default_trust = TtsRealtimeClient("https://localhost/tts", api_key="key")
        self.assertEqual(default_trust.url, "wss://localhost/tts/v1/realtime")
        for url in ("ftp://localhost/tts", "https://user@localhost/tts",
                    "https://localhost/tts?token=bad"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                TtsRealtimeClient(url, api_key="key", ca_file=self.cert)
        with self.assertRaises(ValueError):
            TtsRealtimeClient("https://localhost/tts", api_key="bad\nkey", ca_file=self.cert)
        client = self.client()
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            list(client.synthesize(["测试。"]))


if __name__ == "__main__":
    unittest.main()
