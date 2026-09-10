"""Exercise the real OpenAI SDK against a local HTTP fixture, without a GPU."""

import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cpu_client.client import VlmClient, image_part


class CpuClientTest(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.status = 200
        self.headers = {}
        self.delay = 0
        self.disconnect = False
        self.response = {
            "id": "chatcmpl-test", "object": "chat.completion", "created": 1,
            "model": "qwen3.5-9b",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": "测试回答", "reasoning": None,
            }}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                fixture.requests.append((self.path, self.headers,
                                         json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                if fixture.disconnect:
                    self.close_connection = True
                    return
                time.sleep(fixture.delay)
                body = json.dumps(fixture.response).encode()
                self.send_response(fixture.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for key, value in fixture.headers.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Expected when the timeout test has already disconnected.

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def client(self, **kwargs):
        return VlmClient(self.base_url, api_key="fixture-key-not-a-secret", **kwargs)

    def test_sdk_request_and_dict_response_preserve_wire_contract(self):
        messages = [{"role": "user", "content": "你好"}]
        with self.client() as client:
            response = client.chat(messages, max_tokens=37)
        self.assertEqual(response, self.response)
        path, headers, body = self.requests[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertTrue(headers["User-Agent"].startswith("OpenAI/Python"))
        self.assertEqual(headers["Authorization"], "Bearer fixture-key-not-a-secret")
        self.assertEqual(body, {
            "model": "qwen3.5-9b", "messages": messages, "temperature": 0,
            "max_completion_tokens": 37, "chat_template_kwargs": {"enable_thinking": False},
        })
        with self.assertRaisesRegex(RuntimeError, "connection failed"):
            client.chat(messages)
        self.assertEqual(len(self.requests), 1)  # Context manager closed the transport.

    def test_images_tools_and_thinking_are_forwarded(self):
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
        call = {"id": "call-test", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}
        self.response["choices"][0].update(finish_reason="tool_calls", message={
            "role": "assistant", "content": None, "tool_calls": [call],
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "测试.png"
            path.write_bytes(b"fixture-image")
            part = image_part(path)
        self.assertEqual(base64.b64decode(part["image_url"]["url"].split(",")[1]), b"fixture-image")
        messages = [{"role": "user", "content": [part, {"type": "text", "text": "查询"}]}]
        with self.client() as client:
            for choice in ("auto", "none"):
                response = client.chat(messages, tools=tools, tool_choice=choice, thinking=True)
                body = self.requests[-1][2]
                self.assertEqual(body["messages"], messages)
                self.assertEqual(body["tools"], tools)
                self.assertEqual(body["tool_choice"], choice)
                self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": True})
                self.assertEqual(response, self.response)

    def test_http_errors_are_sanitized_and_not_retried(self):
        self.response = {"error": {"message": "PRIVATE-DOCUMENT fixture-key-not-a-secret", "type": "test"}}
        with self.client() as client:
            for status in (401, 429, 500):
                with self.subTest(status=status):
                    self.status = status
                    count = len(self.requests)
                    with self.assertRaises(RuntimeError) as caught:
                        client.chat([{"role": "user", "content": "PRIVATE-DOCUMENT"}])
                    self.assertEqual(str(caught.exception), f"VLM HTTP {status}; check endpoint, model, token and server log")
                    self.assertEqual(len(self.requests), count + 1)

    def test_redirects_are_not_followed(self):
        self.status = 307
        self.headers["Location"] = self.base_url + "/redirect-target"
        with self.client() as client:
            with self.assertRaisesRegex(RuntimeError, "VLM HTTP 307"):
                client.chat([{"role": "user", "content": "private"}])
        self.assertEqual(len(self.requests), 1)

    def test_environment_proxy_and_openai_endpoint_do_not_override_vlm(self):
        with patch.dict(os.environ, {
            "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1", "NO_PROXY": "", "no_proxy": "",
            "http_proxy": "http://127.0.0.1:1", "https_proxy": "http://127.0.0.1:1",
            "OPENAI_BASE_URL": "http://127.0.0.1:1/v1", "OPENAI_API_KEY": "unrelated-key",
        }):
            with self.client() as client:
                self.assertEqual(client.chat([{"role": "user", "content": "hello"}]), self.response)
        self.assertEqual(self.requests[0][1]["Authorization"], "Bearer fixture-key-not-a-secret")

    def test_timeout_is_sanitized_and_not_retried(self):
        self.delay = 0.3
        with self.client(timeout_seconds=0.05) as client:
            with self.assertRaisesRegex(RuntimeError, "VLM request timed out"):
                client.chat([{"role": "user", "content": "private"}])
        self.assertEqual(len(self.requests), 1)

    def test_connection_error_is_sanitized_and_not_retried(self):
        self.disconnect = True
        with self.client() as client:
            with self.assertRaisesRegex(RuntimeError, "VLM connection failed"):
                client.chat([{"role": "user", "content": "private"}])
        self.assertEqual(len(self.requests), 1)

    def test_invalid_configuration_and_request_options_fail_locally(self):
        for kwargs in ({"base_url": "file:///tmp/test"}, {"base_url": "http://user:pass@localhost/v1"},
                       {"api_key": ""}, {"api_key": "bad\nkey"}, {"timeout_seconds": 0},
                       {"timeout_seconds": float("inf")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                VlmClient(**{"base_url": self.base_url, "api_key": "fixture-key", **kwargs})
        with self.client() as client:
            for kwargs in ({"max_tokens": 0}, {"max_tokens": True}, {"thinking": "false"}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    client.chat([], **kwargs)
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
