"""Opt-in acceptance tests against the real, already-running VLM HTTP API."""

import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from PIL import Image, ImageDraw, ImageFont
from cpu_client.client import VlmClient


ROOT = Path(__file__).resolve().parents[1]


def configured_client():
    key = os.environ.get("GPU_API_KEY", os.environ.get("VLM_API_KEY"))
    if not key:
        key_file = ROOT / "runtime/api_key"
        key = key_file.read_text().strip() if key_file.exists() else "not-configured"
    return VlmClient(os.environ.get("VLM_BASE_URL", "http://127.0.0.1:8000/v1"), api_key=key,
                     ca_file=os.environ.get("GPU_CA_FILE"))


def chat(messages):
    with configured_client() as client:
        return client.chat(messages)


def image_content(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
    }}


def json_answer(response):
    message = response["choices"][0]["message"]
    text = message.get("content") or ""
    if text.strip().startswith("```"):
        text = "\n".join(text.strip().splitlines()[1:-1])
    return json.loads(text)


@unittest.skipUnless(os.getenv("RUN_VLM_INTEGRATION") == "1", "requires running VLM and RUN_VLM_INTEGRATION=1")
class LiveApiTest(unittest.TestCase):
    def test_streaming_image_understanding(self):
        image = Image.new("RGB", (320, 240), "white")
        ImageDraw.Draw(image).rectangle((60, 40, 260, 200), fill="red")
        messages = [{"role": "user", "content": [
            image_content(image),
            {"type": "text", "text": "Describe the color and shape in this image in two short English sentences."},
        ]}]
        started = time.monotonic()
        first_text_seconds = None
        text_parts = []
        finish_reason = None
        usage = None
        with configured_client() as client:
            with client.stream_chat(messages, max_tokens=128) as chunks:
                for chunk in chunks:
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices", []):
                        text = choice.get("delta", {}).get("content")
                        if text:
                            if first_text_seconds is None:
                                first_text_seconds = time.monotonic() - started
                            text_parts.append(text)
                        finish_reason = choice.get("finish_reason") or finish_reason
        self.assertIn("red", "".join(text_parts).lower())
        self.assertGreater(len(text_parts), 1)
        self.assertEqual(finish_reason, "stop")
        self.assertIsNotNone(usage)
        self.assertGreater(usage["completion_tokens"], 0)
        print(json.dumps({"stream_text_chunks": len(text_parts), "first_text_seconds": first_text_seconds,
                          "total_seconds": time.monotonic() - started}))

    def test_streaming_cancel_then_followup(self):
        with configured_client() as client:
            with client.stream_chat([{"role": "user", "content": "Count from 1 to 100, one number per line."}],
                                    max_tokens=512) as chunks:
                for chunk in chunks:
                    if any(choice.get("delta", {}).get("content") for choice in chunk.get("choices", [])):
                        break
                else:
                    self.fail("no text received before cancellation")
            with client.stream_chat([{"role": "user", "content": "Reply with exactly OK."}],
                                    max_tokens=16) as chunks:
                text = "".join(choice.get("delta", {}).get("content") or ""
                               for chunk in chunks for choice in chunk.get("choices", []))
            self.assertIn("OK", text)

    def test_streaming_tool_arguments(self):
        tools = [{"type": "function", "function": {
            "name": "get_order_status", "description": "Look up an order by its ID.",
            "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}},
                           "required": ["order_id"]},
        }}]
        calls = {}
        finish_reason = None
        with configured_client() as client:
            with client.stream_chat(
                [{"role": "user", "content": "Look up the status of order DEMO-1001."}],
                tools=tools, tool_choice="auto", max_tokens=256,
            ) as chunks:
                for chunk in chunks:
                    for choice in chunk.get("choices", []):
                        finish_reason = choice.get("finish_reason") or finish_reason
                        for delta in choice.get("delta", {}).get("tool_calls") or []:
                            call = calls.setdefault(delta["index"], {"id": "", "name": "", "arguments": ""})
                            call["id"] += delta.get("id") or ""
                            function = delta.get("function") or {}
                            call["name"] += function.get("name") or ""
                            call["arguments"] += function.get("arguments") or ""
        self.assertEqual(finish_reason, "tool_calls")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["id"])
        self.assertEqual(calls[0]["name"], "get_order_status")
        self.assertEqual(json.loads(calls[0]["arguments"]), {"order_id": "DEMO-1001"})

    def test_image_understanding(self):
        image = Image.new("RGB", (640, 360), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((40, 70, 260, 290), fill="red")
        draw.rectangle((350, 100, 600, 260), fill="blue")
        response = chat([{"role": "user", "content": [
            image_content(image),
            {"type": "text", "text": '识别图中的圆形和矩形颜色。仅输出 JSON，键为 circle_color、rectangle_color，值用英文小写颜色名称。'},
        ]}])
        self.assertEqual(json_answer(response), {"circle_color": "red", "rectangle_color": "blue"})

    def test_document_fields_through_sdk_cpu_client(self):
        image = Image.new("RGB", (768, 960), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype("DejaVuSans.ttf", 30)
        lines = ["DEMO INVOICE", "Invoice No: INV-2026-0042", "Customer: ACME TEST", "Currency: CNY", "Total Amount: 1234.50"]
        for number, text in enumerate(lines):
            draw.text((40, 60 + number * 90), text, font=font, fill="black")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "测试票据.png"
            image.save(path)
            env = os.environ.copy()
            env["VLM_API_KEY"] = os.getenv("VLM_API_KEY") or (ROOT / "runtime/api_key").read_text().strip()
            completed = subprocess.run([
                sys.executable, str(ROOT / "cpu_client/demo.py"), "--image", str(path),
                "--prompt", '提取票据字段。只输出 JSON，键为 invoice_no、currency、total_amount，所有值用字符串，金额保留两位小数。',
            ], env=env, cwd=directory, capture_output=True, text=True, timeout=180)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json_answer(json.loads(completed.stdout)), {
            "invoice_no": "INV-2026-0042", "currency": "CNY", "total_amount": "1234.50",
        })

    def test_readonly_business_tool_round_trip(self):
        env = os.environ.copy()
        env["VLM_API_KEY"] = os.getenv("VLM_API_KEY") or (ROOT / "runtime/api_key").read_text().strip()
        completed = subprocess.run([
            sys.executable, str(ROOT / "cpu_client/tool_demo.py"), "--order-id", "DEMO-1001",
        ], env=env, cwd=ROOT, capture_output=True, text=True, timeout=360)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertEqual(len(output["tool_calls"]), 1)
        self.assertEqual(output["tool_calls"][0]["function"]["name"], "get_order_status")
        self.assertEqual(json.loads(output["tool_calls"][0]["function"]["arguments"]), {"order_id": "DEMO-1001"})
        self.assertEqual(output["tool_results"][0]["status"], "ready_to_ship")
        self.assertEqual(json_answer(output["final_response"]), {
            "order_id": "DEMO-1001", "status": "ready_to_ship", "source": "demo",
        })


if __name__ == "__main__":
    unittest.main()
