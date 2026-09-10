"""Opt-in BGE-M3 acceptance through the shared HTTPS ingress; never starts a model."""

import base64
import json
import math
import os
from pathlib import Path
import ssl
import struct
import subprocess
import sys
import unittest

import httpx

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "gateway"), str(REPO / "rag_service/cpu_client")]
from configuration import load, secret
from rag_client import RagClient


@unittest.skipUnless(os.getenv("RUN_RAG_INTEGRATION") == "1", "requires running gateway and BGE-M3")
class LiveRagTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = load(REPO / "gateway/config/server.json")
        cls.key = secret(cfg["api_key_file"])
        cls.ca = cfg["certificate"]
        cls.base = f"https://{cfg['probe_host']}:{cfg['listen_port']}"
        cls.model_config = json.loads((REPO / "rag_service/config/server.json").read_text())

    def setUp(self):
        self.http = httpx.Client(base_url=self.base, trust_env=False, timeout=60,
                                 verify=ssl.create_default_context(cafile=str(self.ca)),
                                 headers={"Authorization": "Bearer " + self.key})
        self.addCleanup(self.http.close)

    def test_dense_vectors_are_normalized_and_rank_chinese_and_cross_language_matches(self):
        documents = ["员工忘记登录密码时，可在登录页面点击忘记密码，通过手机验证码重置。",
                     "公司差旅报销需要提交发票和出差审批单。", "苹果派需要苹果、面粉、黄油和糖。"]
        queries = ["忘记密码后应该怎么办？", "How can an employee reset a forgotten password?"]
        with RagClient(self.base + "/rag/v1", api_key=self.key, ca_file=self.ca) as client:
            result = client.embed(documents + queries)
            separate = client.embed(queries[0])
        vectors = [d["embedding"] for d in result["data"]]
        self.assertEqual(result["model"], "bge-m3")
        self.assertGreater(result["usage"]["prompt_tokens"], 0)
        for vector in vectors:
            self.assertEqual(len(vector), 1024)
            self.assertTrue(all(math.isfinite(x) for x in vector))
            self.assertAlmostEqual(math.sqrt(sum(x*x for x in vector)), 1, delta=0.002)
        for query in vectors[3:]:
            scores = [sum(a*b for a, b in zip(query, doc)) for doc in vectors[:3]]
            self.assertEqual(max(range(3), key=scores.__getitem__), 0)
        similarity = sum(a*b for a, b in zip(vectors[3], separate["data"][0]["embedding"]))
        self.assertGreater(similarity, 0.999)

    def test_base64_matches_float_and_preserves_batch_order(self):
        payload = {"model": "bge-m3", "input": ["图像识别服务", "语音识别服务"]}
        floats = self.http.post("/rag/v1/embeddings", json={**payload, "encoding_format": "float"})
        encoded = self.http.post("/rag/v1/embeddings", json={**payload, "encoding_format": "base64"})
        self.assertEqual((floats.status_code, encoded.status_code), (200, 200))
        self.assertEqual((len(floats.json()["data"]), len(encoded.json()["data"])), (2, 2))
        for index, (a, b) in enumerate(zip(floats.json()["data"], encoded.json()["data"])):
            self.assertEqual((a["index"], b["index"]), (index, index))
            decoded = struct.unpack("<1024f", base64.b64decode(b["embedding"]))
            self.assertLess(max(abs(x-y) for x, y in zip(a["embedding"], decoded)), 1e-5)

    def test_authentication_models_health_and_reserved_routes(self):
        for path in ("/rag/v1/models", "/rag/health/ready"):
            request = self.http.build_request("GET", path)
            request.headers.pop("Authorization")
            self.assertEqual(self.http.send(request).status_code, 401)
            response = self.http.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers.get("X-Request-ID"))
        self.assertEqual(self.http.get("/rag/v1/models").json()["data"][0]["id"], "bge-m3")
        for path in ("/rag/v1/rerank", "/rag/metrics", "/rag/pooling", "/rag/v1/chat/completions"):
            self.assertEqual(self.http.post(path, json={}).status_code, 404)
        self.assertEqual(self.http.post("/rag/v1/embeddings", json={"input": "hello"},
                                       headers={"Authorization": "Bearer wrong"}).status_code, 401)

    def test_invalid_requests_are_rejected_and_model_recovers(self):
        limit = self.model_config["max_model_len"]
        for payload, expected in (({"model": "missing-model", "input": "hello"}, 404),
                                  ({"model": "bge-m3", "input": {}}, 400),
                                  ({"model": "bge-m3", "input": "hello", "dimensions": 512}, 400),
                                  ({"model": "bge-m3", "input": [100] * (limit + 1)}, 400)):
            with self.subTest(case=list(payload)):
                response = self.http.post("/rag/v1/embeddings", json=payload)
                self.assertEqual(response.status_code, expected)
        self.assertEqual(self.http.post("/rag/v1/embeddings", content=b"x" * 262145).status_code, 413)
        self.assertEqual(self.http.post("/rag/v1/embeddings", json={"model": "bge-m3", "input": "恢复检查"}).status_code, 200)

    def test_configured_token_limit_is_usable(self):
        # Pre-tokenized input is supplied as-is; text input includes tokenizer-added special tokens.
        response = self.http.post("/rag/v1/embeddings", json={"model": "bge-m3",
                                  "input": [100] * self.model_config["max_model_len"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"][0]["embedding"]), 1024)
        self.assertEqual(response.json()["usage"]["prompt_tokens"], self.model_config["max_model_len"])

    def test_cpu_cli_works_outside_project(self):
        env = os.environ.copy()
        env.update({"GPU_API_KEY": self.key, "GPU_CA_FILE": str(self.ca), "RAG_BASE_URL": self.base + "/rag/v1"})
        process = subprocess.run([sys.executable, str(REPO / "rag_service/cpu_client/demo.py"),
                                  "--text", "这是一个中文知识库。"], cwd="/tmp", env=env,
                                 capture_output=True, text=True, timeout=65)
        self.assertEqual(process.returncode, 0, "CPU CLI failed (raw output withheld)")
        self.assertEqual(len(json.loads(process.stdout)["data"][0]["embedding"]), 1024)


if __name__ == "__main__":
    unittest.main()
