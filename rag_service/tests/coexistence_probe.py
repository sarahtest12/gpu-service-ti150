#!/usr/bin/env python3
"""Opt-in short coexistence probe. Reports client latency, not GPU-only RAG timing."""

from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / path) for path in ("gateway", "rag_service/cpu_client",
                 "vlm_service/cpu_client", "yolov5v70-service/cpu_client", "yolov5v70-service/shared")]
from configuration import load, secret
from rag_client import RagClient
from client import VlmClient
from detector_client import DetectorClient, frame_from_jpeg, pb


def summarize(values):
    ordered = sorted(values)
    return {"samples": len(values), "avg_ms": statistics.mean(values),
            "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1], "max_ms": ordered[-1]}


def main():
    if os.getenv("RUN_RAG_INTEGRATION") != "1":
        raise SystemExit("set RUN_RAG_INTEGRATION=1 to send real requests")
    cfg = load(REPO / "gateway/config/server.json")
    key, ca = secret(cfg["api_key_file"]), cfg["certificate"]
    target = f"{cfg['probe_host']}:{cfg['listen_port']}"
    base = "https://" + target
    file = REPO / "yolov5v70-service/tests/fixtures/bus.jpg"
    jpeg = file.read_bytes()
    with Image.open(file) as decoded:
        width, height = decoded.size

    def yolo(count, label):
        submitted = {}
        def frames():
            started = time.monotonic()
            for i in range(1, count + 1):
                time.sleep(max(0, started + (i - 1) / 10 - time.monotonic()))
                submitted[i] = time.monotonic()
                yield frame_from_jpeg(jpeg, width=width, height=height, stream_id=label, frame_id=i)
        observed, inference, codes = [], [], {}
        with DetectorClient(target, token=key, tls=True, root_certificates=ca.read_bytes()) as client:
            for result in client.detect(frames(), rpc_timeout_seconds=30):
                code = pb.ResultCode.Name(result.code)
                codes[code] = codes.get(code, 0) + 1
                observed.append((time.monotonic() - submitted[result.frame_id]) * 1000)
                if result.code == pb.RESULT_CODE_OK:
                    if not result.detections:
                        raise RuntimeError("YOLO returned no boxes for the bus fixture")
                    inference.append(result.inference_ms)
        if len(observed) != count or len(inference) != count:
            raise RuntimeError(f"YOLO failed: {codes}")
        return {"codes": codes, "client_round_trip": summarize(observed), "model_inference": summarize(inference)}

    baseline = yolo(40, "rag-baseline")
    stop = threading.Event()
    ready = [threading.Event(), threading.Event()]
    peaks = {}

    def sample_memory():
        while not stop.is_set():
            tree = ET.fromstring(subprocess.check_output(["ixsmi", "-q", "-x"], text=True, timeout=5))
            for gpu in tree.findall("gpu"):
                for proc in gpu.findall("./processes/process_info"):
                    identifier = f"gpu{gpu.findtext('minor_number')}:pid{proc.findtext('pid')}"
                    mb = int(proc.findtext("used_memory").split()[0]) * 1024 * 1024 / 1_000_000
                    peaks[identifier] = max(peaks.get(identifier, 0), mb)
            stop.wait(1)

    def rag(index):
        timings = []
        text = "员工通过手机验证码重置密码，登录后可以查询出差审批和报销进度。" * 16
        with RagClient(base + "/rag/v1", api_key=key, ca_file=ca) as client:
            while not stop.is_set():
                started = time.monotonic()
                result = client.embed([text] * 4)
                if len(result["data"]) != 4:
                    raise RuntimeError("missing RAG batch results")
                timings.append((time.monotonic() - started) * 1000)
                ready[index].set()
        return timings

    def vlm():
        pieces, finish = 0, None
        with VlmClient(base + "/vlm/v1", api_key=key, ca_file=ca) as client:
            with client.stream_chat([{"role": "user", "content": "请用一句话说明知识库的用途。"}], max_tokens=128) as chunks:
                for chunk in chunks:
                    for choice in chunk.get("choices", []):
                        if choice.get("delta", {}).get("content"):
                            pieces += 1
                        finish = choice.get("finish_reason") or finish
        if not pieces or finish != "stop":
            raise RuntimeError("VLM stream did not finish successfully")
        return {"text_chunks": pieces, "finish_reason": finish}

    with ThreadPoolExecutor(max_workers=4) as pool:
        memory = pool.submit(sample_memory)
        requests = [pool.submit(rag, i) for i in range(2)]
        try:
            if not all(event.wait(20) for event in ready):
                raise RuntimeError("RAG workers did not become active")
            stream = pool.submit(vlm)
            concurrent = yolo(80, "rag-concurrent")
            vlm_result = stream.result(timeout=30)
        finally:
            stop.set()
        timings = [value for request in requests for value in request.result(timeout=65)]
        memory.result(timeout=10)
    print(json.dumps({"yolo_baseline": baseline, "yolo_with_rag": concurrent,
                      "rag_client_http": summarize(timings), "rag_http_concurrency": 2,
                      "rag_documents_per_request": 4, "vlm": vlm_result,
                      "sampled_peak_process_memory_mb": peaks}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
