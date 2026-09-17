"""Opt-in real-model acceptance through the shared TLS port and public key."""

import os
from pathlib import Path
import json
import ssl
import subprocess
import sys
import time
import unittest

import grpc
import httpx
from PIL import Image
from websockets.sync.client import connect as websocket_connect

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "gateway"), str(REPO / "vlm_service/cpu_client"),
               str(REPO / "yolov5v70-service/cpu_client"), str(REPO / "yolov5v70-service/shared")]
from configuration import load, secret
from client import VlmClient
from detector_client import DetectorClient, frame_from_jpeg, pb


@unittest.skipUnless(os.getenv("RUN_GATEWAY_INTEGRATION") == "1", "requires running gateway and both models")
class LiveGatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = load(REPO / "gateway/config/server.json")
        cls.key = secret(cfg["api_key_file"])
        cls.ca_file = cfg["certificate"]
        cls.target = f"{cfg['probe_host']}:{cfg['listen_port']}"
        cls.base = "https://" + cls.target

    def test_models_health_and_authentication(self):
        with httpx.Client(verify=ssl.create_default_context(cafile=str(self.ca_file)), trust_env=False) as client:
            for path in ("/vlm/v1/models", "/rag/v1/models", "/health/live",
                         "/vlm/health/ready", "/yolo/health/ready",
                         "/rag/health/ready", "/asr/health/ready",
                         "/monitor/v1/overview"):
                self.assertEqual(client.get(self.base + path).status_code, 401)
                response = client.get(self.base + path, headers={"Authorization": "Bearer " + self.key})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.headers.get("X-Request-ID"))

    def test_real_yolo_stream_preserves_expired_frame_and_detects_next_frame(self):
        image = REPO / "yolov5v70-service/tests/fixtures/bus.jpg"
        with Image.open(image) as decoded:
            width, height = decoded.size
        jpeg = image.read_bytes()

        def frames():
            yield frame_from_jpeg(jpeg, width=width, height=height, stream_id="gateway-live", frame_id=1,
                                  observed_at_unix_ms=time.time_ns() // 1_000_000 - 5000)
            yield frame_from_jpeg(jpeg, width=width, height=height, stream_id="gateway-live", frame_id=2)

        with DetectorClient(self.target, token=self.key, tls=True, root_certificates=self.ca_file.read_bytes()) as client:
            results = list(client.detect(frames(), rpc_timeout_seconds=15))
        self.assertEqual([r.code for r in results], [pb.RESULT_CODE_EXPIRED, pb.RESULT_CODE_OK])
        self.assertGreater(len(results[1].detections), 0)
        with DetectorClient(self.target, token="wrong", tls=True, root_certificates=self.ca_file.read_bytes()) as client:
            with self.assertRaises(grpc.RpcError) as caught:
                list(client.detect(frames(), rpc_timeout_seconds=5))
        self.assertEqual(caught.exception.code(), grpc.StatusCode.UNAUTHENTICATED)

    def test_real_vlm_stream_on_same_port(self):
        with VlmClient(self.base + "/vlm/v1", api_key=self.key, ca_file=self.ca_file) as client:
            with client.stream_chat([{"role": "user", "content": "Reply in one short sentence: what is a GPU?"}],
                                    max_tokens=128) as chunks:
                parts, finish, usage = [], None, None
                for chunk in chunks:
                    usage = chunk.get("usage") or usage
                    for choice in chunk.get("choices", []):
                        finish = choice.get("finish_reason") or finish
                        text = choice.get("delta", {}).get("content")
                        if text:
                            parts.append(text)
                self.assertGreater(len(parts), 1)
                self.assertEqual(finish, "stop")
                self.assertIsNotNone(usage)

    def test_real_asr_stream_on_same_port(self):
        sample = Path("/share/fshare/common/models/FunAudioLLM/Fun-ASR-Nano-2512/example/zh.mp3")
        pcm = subprocess.run([
            "ffmpeg", "-v", "error", "-i", str(sample), "-f", "s16le",
            "-ac", "1", "-ar", "16000", "pipe:1",
        ], check=True, capture_output=True).stdout
        context = ssl.create_default_context(cafile=str(self.ca_file))
        events = []
        with websocket_connect(
            "wss://" + self.target + "/asr/v1/realtime", ssl=context, proxy=None,
            additional_headers={"Authorization": "Bearer " + self.key}, compression=None,
        ) as connection:
            connection.send("START")
            self.assertEqual(json.loads(connection.recv()), {"event": "started"})
            for offset in range(0, len(pcm), 3200):
                connection.send(pcm[offset:offset + 3200])
                time.sleep(0.1)
            connection.send("STOP")
            while True:
                event = json.loads(connection.recv())
                events.append(event)
                if event.get("event") == "stopped":
                    break
        self.assertTrue(any(event.get("partial") for event in events))
        final = next(event for event in events if event.get("is_final"))
        self.assertIn("九点", "".join(sentence["text"] for sentence in final["sentences"]))


if __name__ == "__main__":
    unittest.main()
