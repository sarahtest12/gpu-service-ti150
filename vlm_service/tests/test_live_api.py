"""Opt-in acceptance tests against the real, already-running VLM HTTP API."""

import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageFont
from cpu_client.client import VlmClient


ROOT = Path(__file__).resolve().parents[1]


def chat(messages):
    key = os.environ.get("VLM_API_KEY")
    if not key:
        key_file = ROOT / "runtime/api_key"
        key = key_file.read_text().strip() if key_file.exists() else "not-configured"
    with VlmClient(os.environ.get("VLM_BASE_URL", "http://127.0.0.1:8000/v1"), api_key=key) as client:
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
