"""Real NGINX, TLS, HTTP/SSE and gRPC contracts with CPU-only upstream fixtures."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
from unittest.mock import patch

import grpc
import httpx

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "gateway"), str(REPO / "vlm_service/cpu_client"),
               str(REPO / "yolov5v70-service/cpu_client"), str(REPO / "yolov5v70-service/shared")]
from configuration import render, secret
import service as gateway_service
from client import VlmClient
from detector_client import DetectorClient, frame_from_jpeg, pb
from detector_contract import detector_pb2_grpc

NGINX = REPO / "gateway/runtime/nginx/sbin/nginx"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not NGINX.is_file():
            raise RuntimeError("run bash gateway/bootstrap.sh before gateway tests")
        cls.certdir = tempfile.TemporaryDirectory()
        cls.cert = Path(cls.certdir.name) / "server.crt"
        cls.certkey = Path(cls.certdir.name) / "server.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
                        "-keyout", str(cls.certkey), "-out", str(cls.cert)], check=True, capture_output=True)
        cls.certkey.chmod(0o600)

    @classmethod
    def tearDownClass(cls):
        cls.certdir.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        self.http_requests = []
        self.grpc_metadata = []
        self.stream_mode = "normal"
        self.http_status = 200
        self.rag_status = 200
        self.rag_pause = False
        self.rag_started = threading.Event()
        self.release = threading.Event()
        self.peer_closed = threading.Event()
        self.grpc_closed = threading.Event()
        self.addCleanup(self.release.set)
        fixture = self

        class HttpFixture(BaseHTTPRequestHandler):
            def do_GET(self):
                fixture.http_requests.append((self.path, dict(self.headers), None))
                body = json.dumps({"object": "list", "data": [{"id": "qwen3.5-9b"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fixture.http_requests.append((self.path, dict(self.headers), body))
                if self.path == "/v1/embeddings":
                    fixture.rag_started.set()
                    if fixture.rag_pause:
                        fixture.release.wait(4)
                    result = json.dumps({"object": "list", "model": "bge-m3", "data": [],
                                         "usage": {"prompt_tokens": 1, "total_tokens": 1}}).encode()
                    self.send_response(fixture.rag_status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(result)))
                    self.end_headers()
                    self.wfile.write(result)
                    return
                if fixture.http_status != 200:
                    self.send_response(fixture.http_status)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                # The gateway must enforce streaming even if an upstream asks for buffering.
                self.send_header("X-Accel-Buffering", "yes")
                self.end_headers()

                def event(content, finish=None):
                    data = {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1,
                            "model": "qwen3.5-9b", "choices": [{"index": 0,
                            "delta": {"content": content}, "finish_reason": finish}]}
                    self.wfile.write(("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode())
                    self.wfile.flush()

                try:
                    event("第一段")
                    if fixture.stream_mode == "cancel":
                        self.connection.settimeout(3)
                        if self.rfile.read(1) == b"":
                            fixture.peer_closed.set()
                        return
                    if fixture.stream_mode == "pause" and not fixture.release.wait(4):
                        return
                    if fixture.stream_mode == "truncate":
                        return
                    event("第二段")
                    event(None, "stop")
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass

            def log_message(self, *args):
                pass

        self.http_server = ThreadingHTTPServer(("127.0.0.1", 0), HttpFixture)
        self.http_thread = threading.Thread(target=self.http_server.serve_forever,
                                            kwargs={"poll_interval": 0.01}, daemon=True)
        self.http_thread.start()
        self.addCleanup(self.close_http)

        class DetectorFixture(detector_pb2_grpc.DetectorServicer):
            def Detect(self, requests, context):
                metadata = dict(context.invocation_metadata())
                fixture.grpc_metadata.append(metadata)
                if metadata.get("authorization") != "Bearer " + secret(fixture.cfg["yolo"]["api_key_file"]):
                    context.abort(grpc.StatusCode.UNAUTHENTICATED, "bad internal credential")
                context.add_callback(fixture.grpc_closed.set)
                for request in requests:
                    yield pb.DetectionResult(stream_id=request.stream_id, frame_id=request.frame_id,
                                             source_pts=request.source_pts, time_base_num=request.time_base_num,
                                             time_base_den=request.time_base_den,
                                             code=pb.RESULT_CODE_EXPIRED if request.frame_id == 1 else pb.RESULT_CODE_OK)

        self.pool = ThreadPoolExecutor(max_workers=4)
        self.grpc_server = grpc.server(self.pool)
        detector_pb2_grpc.add_DetectorServicer_to_server(DetectorFixture(), self.grpc_server)
        grpc_port = self.grpc_server.add_insecure_port("127.0.0.1:0")
        self.grpc_server.start()
        self.addCleanup(lambda: self.pool.shutdown(wait=True))
        self.addCleanup(lambda: self.grpc_server.stop(0).wait())
        self.port = free_port()
        self.cfg = {
            "listen_host": "127.0.0.1", "listen_port": self.port,
            "certificate": self.cert, "certificate_key": self.certkey,
            "api_key_file": self.root / "public_key",
            "vlm": {"address": f"127.0.0.1:{self.http_server.server_port}",
                    "api_key_file": self.root / "vlm_key", "max_body_bytes": 1024,
                    "max_connections": 1, "read_timeout_seconds": 2},
            "rag": {"address": f"127.0.0.1:{self.http_server.server_port}",
                    "api_key_file": self.root / "rag_key", "max_body_bytes": 512,
                    "max_connections": 1, "read_timeout_seconds": 2},
            "yolo": {"address": f"127.0.0.1:{grpc_port}",
                     "health_address": f"127.0.0.1:{self.http_server.server_port}",
                     "api_key_file": self.root / "yolo_key", "max_connections": 1, "read_timeout_seconds": 2},
        }
        for path in (self.cfg["api_key_file"], *(self.cfg[n]["api_key_file"] for n in ("vlm", "yolo", "rag"))):
            secret(path, create=True)
        self.key = secret(self.cfg["api_key_file"])
        config = self.root / "nginx.conf"
        config.write_text(render(self.cfg, self.root))
        config.chmod(0o600)
        self.log = (self.root / "process.log").open("wb")
        self.addCleanup(self.log.close)
        self.nginx = subprocess.Popen([str(NGINX), "-p", str(self.root) + "/", "-c", str(config)],
                                      stdout=self.log, stderr=self.log)
        self.addCleanup(self.close_nginx)
        self.url = f"https://localhost:{self.port}"
        self.http = httpx.Client(base_url=self.url, verify=ssl.create_default_context(cafile=str(self.cert)),
                                 trust_env=False, timeout=2, headers={"Authorization": "Bearer " + self.key})
        self.addCleanup(self.http.close)
        deadline = time.monotonic() + 3
        while True:
            if self.nginx.poll() is not None:
                self.fail("NGINX exited; inspect temporary gateway configuration")
            try:
                if self.http.get("/health/live").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                self.fail("gateway did not become ready")
            time.sleep(0.02)

    def close_nginx(self):
        self.release.set()
        self.nginx.terminate()
        self.nginx.wait(timeout=5)

    def close_http(self):
        self.release.set()
        self.http_server.shutdown()
        self.http_server.server_close()
        self.http_thread.join(timeout=2)

    def detector(self, token=None, trusted=True):
        return DetectorClient(f"localhost:{self.port}", token=self.key if token is None else token,
                              tls=True, root_certificates=self.cert.read_bytes() if trusted else None,
                              connect_timeout_seconds=0.5)

    def vlm(self):
        return VlmClient(self.url + "/vlm/v1", api_key=self.key, ca_file=self.cert, timeout_seconds=2)

    def frame(self, number):
        return frame_from_jpeg(b"jpeg", width=1, height=1, stream_id="gateway-test", frame_id=number,
                               source_pts=90000, time_base_num=1, time_base_den=90000)

    def test_same_port_key_routes_both_protocols_and_replaces_internal_credentials(self):
        response = self.http.get("/vlm/v1/models", headers={"X-Request-ID": "spoofed"})
        self.assertEqual(response.status_code, 200)
        path, headers, _ = self.http_requests[-1]
        self.assertEqual(path, "/v1/models")
        self.assertEqual(headers["Authorization"], "Bearer " + secret(self.cfg["vlm"]["api_key_file"]))
        self.assertEqual(headers["X-Request-ID"], response.headers["X-Request-ID"])
        self.assertNotEqual(headers["X-Request-ID"], "spoofed")
        with self.detector() as client:
            results = list(client.detect([self.frame(1), self.frame(2)], rpc_timeout_seconds=2))
        self.assertEqual([r.code for r in results], [pb.RESULT_CODE_EXPIRED, pb.RESULT_CODE_OK])
        self.assertEqual(results[1].source_pts, 90000)
        self.assertEqual(results[1].time_base_den, 90000)
        self.assertTrue(self.grpc_metadata[0]["x-request-id"])

    def test_bad_missing_case_changed_and_internal_keys_are_rejected_before_upstream(self):
        for token in ("", "wrong", self.key.swapcase(), secret(self.cfg["vlm"]["api_key_file"])):
            with self.subTest(token_kind="invalid"):
                request = self.http.build_request("GET", "/vlm/v1/models")
                request.headers.pop("Authorization")
                if token:
                    request.headers["Authorization"] = "Bearer " + token
                self.assertEqual(self.http.send(request).status_code, 401)
                with self.detector(token=token) as client:
                    with self.assertRaises(grpc.RpcError) as caught:
                        list(client.detect([self.frame(2)], rpc_timeout_seconds=2))
                self.assertEqual(caught.exception.code(), grpc.StatusCode.UNAUTHENTICATED)
        self.assertEqual(self.http_requests, [])
        self.assertEqual(self.grpc_metadata, [])

    def test_sse_delivers_first_chunk_before_completion_and_limits_only_vlm(self):
        self.stream_mode = "pause"
        with self.vlm() as client:
            with client.stream_chat([{"role": "user", "content": "hello"}]) as chunks:
                self.assertEqual(next(chunks)["choices"][0]["delta"]["content"], "第一段")
                self.assertFalse(self.release.is_set())
                self.assertEqual(self.http.post("/vlm/v1/chat/completions", json={"stream": True}).status_code, 429)
                with self.detector() as detector:
                    self.assertEqual(next(detector.detect([self.frame(2)], rpc_timeout_seconds=2)).code, pb.RESULT_CODE_OK)
                self.release.set()
                self.assertEqual(len(list(chunks)), 2)

    def test_grpc_is_bidirectional_and_cancellation_reaches_upstream(self):
        def frames():
            yield self.frame(2)
            if self.release.wait(3):
                yield self.frame(3)

        with self.detector() as client:
            results = client.detect(frames(), rpc_timeout_seconds=3)
            self.assertEqual(next(results).frame_id, 2)
            self.assertFalse(self.release.is_set())
            with self.detector() as other:
                with self.assertRaises(grpc.RpcError) as caught:
                    list(other.detect([self.frame(4)], rpc_timeout_seconds=2))
                self.assertEqual(caught.exception.code(), grpc.StatusCode.RESOURCE_EXHAUSTED)
            results.close()
            self.assertTrue(self.grpc_closed.wait(2))

    def test_sse_cancel_closes_upstream_connection(self):
        self.stream_mode = "cancel"
        with self.vlm() as client:
            with client.stream_chat([]) as chunks:
                next(chunks)
            self.assertTrue(self.peer_closed.wait(2))

    def test_truncated_sse_is_not_reported_as_complete(self):
        self.stream_mode = "truncate"
        with self.vlm() as client:
            with client.stream_chat([]) as chunks:
                next(chunks)
                with self.assertRaisesRegex(RuntimeError, "stream ended before completion"):
                    list(chunks)

    def test_route_allowlist_body_limit_and_upstream_errors(self):
        for path in ("/metrics", "/v1/models", "/vlm/metrics", "/rag/v1/rerank", "/rag/metrics", "/rag/pooling"):
            self.assertEqual(self.http.get(path).status_code, 404)
        self.assertEqual(self.http.get("/vlm/v1/chat/completions").status_code, 403)
        self.assertEqual(self.http.post("/vlm/v1/chat/completions", content=b"x" * 1025).status_code, 413)
        self.assertEqual(self.http_requests, [])
        self.http_status = 503
        self.assertEqual(self.http.post("/vlm/v1/chat/completions", json={}).status_code, 503)
        self.assertEqual(len(self.http_requests), 1)

    def test_rag_json_routes_use_own_key_and_enforce_public_auth_method_and_size(self):
        payload = {"model": "bge-m3", "input": ["中文资料", "English document"]}
        for token in ("", "wrong", secret(self.cfg["rag"]["api_key_file"])):
            request = self.http.build_request("POST", "/rag/v1/embeddings", json=payload)
            request.headers.pop("Authorization")
            if token:
                request.headers["Authorization"] = "Bearer " + token
            response = self.http.send(request)
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.http_requests, [])
        response = self.http.post("/rag/v1/embeddings", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model"], "bge-m3")
        path, headers, body = self.http_requests[-1]
        self.assertEqual((path, body), ("/v1/embeddings", payload))
        self.assertEqual(headers["Authorization"], "Bearer " + secret(self.cfg["rag"]["api_key_file"]))
        self.assertEqual(headers["X-Request-ID"], response.headers["X-Request-ID"])
        for path, upstream in (("/rag/v1/models", "/v1/models"), ("/rag/health/ready", "/health")):
            self.assertEqual(self.http.get(path).status_code, 200)
            self.assertEqual(self.http_requests[-1][0], upstream)
            self.assertEqual(self.http_requests[-1][1]["Authorization"], headers["Authorization"])
        self.assertEqual(self.http.get("/rag/v1/embeddings").status_code, 403)
        self.assertEqual(self.http.post("/rag/v1/embeddings", content=b"x" * 513).status_code, 413)

    def test_rag_limits_and_failures_do_not_block_other_algorithms(self):
        self.rag_pause = True
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.http.post, "/rag/v1/embeddings", json={"input": "hello"})
            try:
                self.assertTrue(self.rag_started.wait(1))
                self.assertEqual(self.http.post("/rag/v1/embeddings", json={"input": "hello"}).status_code, 429)
                self.assertEqual(self.http.get("/vlm/v1/models").status_code, 200)
                with self.detector() as client:
                    self.assertEqual(next(client.detect([self.frame(2)], rpc_timeout_seconds=2)).code, pb.RESULT_CODE_OK)
            finally:
                self.release.set()
            self.assertEqual(pending.result().status_code, 200)
        self.rag_status = 503
        self.assertEqual(self.http.post("/rag/v1/embeddings", json={"input": "hello"}).status_code, 503)
        self.assertEqual(self.http.get("/health/live").status_code, 200)
        self.assertEqual(self.http.get("/vlm/v1/models").status_code, 200)

    def test_failed_configuration_check_retains_last_valid_gateway_configuration(self):
        with patch.object(gateway_service, "RUNTIME", self.root):
            gateway_service.prepare_gateway(self.cfg)
            original = (self.root / "nginx.conf").read_bytes()
            broken = self.root / "invalid.crt"
            broken.write_text("not a certificate")
            with self.assertRaisesRegex(RuntimeError, "configuration check failed"):
                gateway_service.prepare_gateway({**self.cfg, "certificate": broken})
            self.assertEqual((self.root / "nginx.conf").read_bytes(), original)

    def test_one_upstream_failure_keeps_other_algorithm_and_gateway_available(self):
        self.grpc_server.stop(0).wait()
        with self.detector() as client:
            with self.assertRaises(grpc.RpcError) as caught:
                list(client.detect([self.frame(2)], rpc_timeout_seconds=2))
            self.assertEqual(caught.exception.code(), grpc.StatusCode.UNAVAILABLE)
        self.assertEqual(self.http.get("/vlm/v1/models").status_code, 200)
        self.assertEqual(self.http.get("/health/live").status_code, 200)

    def test_clients_require_a_trusted_certificate(self):
        with httpx.Client(trust_env=False) as client:
            with self.assertRaises(httpx.ConnectError):
                client.get(self.url + "/health/live")
        with self.assertRaises(grpc.FutureTimeoutError):
            with self.detector(trusted=False):
                self.fail("untrusted certificate was accepted")


if __name__ == "__main__":
    unittest.main()
