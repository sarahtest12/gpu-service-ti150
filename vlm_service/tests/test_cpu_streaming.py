"""Exercise incremental SSE, cancellation and failures through the real SDK."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest

from cpu_client.client import VlmClient


def chunk(delta, finish_reason=None):
    return {
        "id": "chatcmpl-stream", "object": "chat.completion.chunk", "created": 1,
        "model": "qwen3.5-9b",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


class StreamingClientTest(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.status = 200
        self.pause = False
        self.expect_close = False
        self.send_done = True
        self.release = threading.Event()
        self.peer_closed = threading.Event()
        self.events = [
            chunk({"role": "assistant", "content": "你"}),
            chunk({"content": "好"}),
            chunk({}, "stop"),
            {"id": "chatcmpl-stream", "object": "chat.completion.chunk", "created": 1,
             "model": "qwen3.5-9b", "choices": [],
             "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}},
        ]
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                fixture.requests.append((self.path, self.headers,
                                         json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(fixture.status)
                if fixture.status != 200:
                    body = b'{"error":{"message":"PRIVATE-DOCUMENT fixture-key","type":"test"}}'
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for index, event in enumerate(list(fixture.events)):
                        data = event if isinstance(event, str) else json.dumps(event, ensure_ascii=False)
                        wire = ("data: " + data + "\n\n").encode()
                        # Split an event, including inside a UTF-8 character, across writes.
                        for byte in wire:
                            self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        if index == 0:
                            if fixture.expect_close:
                                self.connection.settimeout(2)
                                if self.rfile.read(1) == b"":
                                    fixture.peer_closed.set()
                                return
                            if fixture.pause and not fixture.release.wait(3):
                                return
                    if fixture.send_done:
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/vlm/v1"
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def client(self, **kwargs):
        return VlmClient(self.base_url, api_key="fixture-key", **kwargs)

    def test_first_chunk_arrives_before_server_finishes_and_preserves_usage(self):
        self.pause = True
        messages = [{"role": "user", "content": "你好"}]
        with self.client(timeout_seconds=1) as client:
            with client.stream_chat(messages, max_tokens=37) as chunks:
                first = next(chunks)
                self.assertFalse(self.release.is_set())
                self.assertEqual(first, self.events[0])
                self.release.set()
                self.assertEqual([first, *chunks], self.events)
        path, headers, body = self.requests[0]
        self.assertEqual(path, "/vlm/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer fixture-key")
        self.assertEqual(body, {
            "model": "qwen3.5-9b", "messages": messages, "temperature": 0,
            "max_completion_tokens": 37, "chat_template_kwargs": {"enable_thinking": False},
            "stream": True, "stream_options": {"include_usage": True},
        })

    def test_images_reasoning_and_tool_argument_fragments_are_preserved(self):
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
        messages = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,dGVzdA=="}},
            {"type": "text", "text": "查询"},
        ]}]
        self.events = [
            chunk({"reasoning": "检查图片", "content": None}),
            chunk({"tool_calls": [{"index": 0, "id": "call-1", "type": "function",
                                    "function": {"name": "lookup", "arguments": '{"id":'}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"42"}'}}]}),
            chunk({}, "tool_calls"),
        ]
        with self.client() as client:
            with client.stream_chat(messages, tools=tools, tool_choice="auto", thinking=True) as chunks:
                self.assertEqual(list(chunks), self.events)
        body = self.requests[0][2]
        self.assertEqual(body["messages"], messages)
        self.assertEqual(body["tools"], tools)
        self.assertEqual(body["tool_choice"], "auto")
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": True})

    def test_early_exit_closes_transport_and_client_can_be_reused(self):
        self.expect_close = True
        with self.client() as client:
            with client.stream_chat([]) as chunks:
                next(chunks)
            self.assertTrue(self.peer_closed.wait(2), "server did not observe the cancelled connection")
            self.expect_close = False
            with client.stream_chat([]) as chunks:
                self.assertEqual(list(chunks), self.events)
        self.assertEqual(len(self.requests), 2)

    def test_http_errors_are_sanitized_without_retries(self):
        with self.client() as client:
            for status in (401, 429, 500):
                with self.subTest(status=status):
                    self.status = status
                    count = len(self.requests)
                    with self.assertRaisesRegex(RuntimeError, f"^VLM HTTP {status};") as caught:
                        with client.stream_chat([]):
                            self.fail("HTTP error should fail when opening the stream")
                    self.assertNotIn("PRIVATE", str(caught.exception))
                    self.assertEqual(len(self.requests), count + 1)

    def test_timeout_after_first_chunk_is_sanitized_without_retries(self):
        self.pause = True
        with self.client(timeout_seconds=0.15) as client:
            with client.stream_chat([]) as chunks:
                next(chunks)
                with self.assertRaisesRegex(RuntimeError, "VLM request timed out"):
                    next(chunks)
        self.assertEqual(len(self.requests), 1)

    def test_stream_errors_and_malformed_json_do_not_expose_response(self):
        with self.client() as client:
            for event in ({"error": {"message": "PRIVATE-DOCUMENT fixture-key"}},
                          '{"PRIVATE-DOCUMENT fixture-key":', chunk({}, "error")):
                with self.subTest(event=event):
                    self.events = [chunk({"content": "部分"}), event]
                    count = len(self.requests)
                    with client.stream_chat([]) as chunks:
                        next(chunks)
                        with self.assertRaisesRegex(RuntimeError, "^VLM response failed; check server log$"):
                            next(chunks)
                    self.assertEqual(len(self.requests), count + 1)

    def test_eof_or_done_without_finish_reason_is_incomplete(self):
        self.events = [chunk({"content": "部分"})]
        with self.client() as client:
            for send_done in (True, False):
                with self.subTest(send_done=send_done):
                    self.send_done = send_done
                    with client.stream_chat([]) as chunks:
                        next(chunks)
                        with self.assertRaisesRegex(RuntimeError, "stream ended before completion"):
                            next(chunks)

    def test_invalid_request_options_fail_before_sending(self):
        with self.client() as client:
            for kwargs in ({"max_tokens": 0}, {"thinking": "false"}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    with client.stream_chat([], **kwargs):
                        self.fail("invalid request must not open a stream")
        self.assertEqual(self.requests, [])

    def test_demo_flushes_text_before_completion(self):
        self.pause = True
        env = {**os.environ, "VLM_BASE_URL": self.base_url, "VLM_API_KEY": "fixture-key"}
        demo = Path(__file__).resolve().parents[1] / "cpu_client/demo.py"
        with subprocess.Popen([sys.executable, str(demo), "--stream", "--prompt", "你好"],
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            first_output = []
            received = threading.Event()

            def read_first():
                first_output.append(process.stdout.read(len("你".encode())))
                received.set()

            reader = threading.Thread(target=read_first, daemon=True)
            reader.start()
            try:
                self.assertTrue(received.wait(2), "CLI buffered the first text chunk")
                self.assertEqual(first_output, ["你".encode()])
            finally:
                self.release.set()
                reader.join(timeout=2)
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise
            self.assertEqual(process.returncode, 0, stderr.decode())
            self.assertEqual(stdout.decode(), "好\n")


if __name__ == "__main__":
    unittest.main()
