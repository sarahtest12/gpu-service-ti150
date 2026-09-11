#!/usr/bin/env python3
"""Authenticated loopback WebSocket wrapper for FunASR's realtime vLLM engine."""

import argparse
import asyncio
import functools
import hmac
from http import HTTPStatus
import json
import logging
import math
from pathlib import Path
from types import SimpleNamespace

from prometheus_client import CONTENT_TYPE_LATEST, Histogram, generate_latest
import websockets
from funasr.bin import realtime_ws


LOG = logging.getLogger("asr-realtime")
ASR_TTFT = Histogram(
    "asr_time_to_first_token_seconds",
    "Time from submitting prepared audio context to vLLM until its first text token.",
    buckets=(0.001, 0.005, 0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64,
             1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92, 163.84),
)


def upstream_args(cfg):
    """Translate the reviewed deployment config into the pinned FunASR server API."""
    return SimpleNamespace(
        model=cfg["model"], hub="ms", device=f"cuda:{cfg['device']}",
        vad_device=cfg["vad_device"], vad_ncpu=cfg["vad_ncpu"],
        use_context=True, decode_interval=cfg["decode_interval_seconds"],
        decode_batch_wait_ms=cfg["decode_batch_wait_ms"],
        decode_max_batch_size=cfg["decode_max_batch_size"],
        log_decode_profile=True, endpoint_mode=cfg["endpoint_mode"],
        partial_window_sec=cfg["partial_window_seconds"], enable_spk=False,
        spk_model="", hotword_file="", postprocess_hotword_file="",
        language=cfg["language"], dtype=cfg["dtype"],
        tensor_parallel_size=cfg["tensor_parallel_size"],
        gpu_memory_utilization=cfg["gpu_memory_utilization"],
        max_model_len=cfg["max_model_len"], enforce_eager=cfg["enforce_eager"],
        ws_ping_interval=cfg["ping_interval_seconds"],
        ws_ping_timeout=cfg["ping_timeout_seconds"],
        ws_close_timeout=cfg["close_timeout_seconds"],
        ws_max_size=cfg["max_message_bytes"], log_session_stats_interval=0.0,
    )


def authorized(headers, token):
    supplied = headers.get("Authorization", "")
    return hmac.compare_digest(supplied, "Bearer " + token)


def instrument_vllm_ttft(batch_engine):
    """Record vLLM's own per-decode first-token latency without changing output."""
    engine = getattr(batch_engine, "_engine", None)
    vllm_engine = getattr(engine, "vllm_engine", None)
    if vllm_engine is None:
        raise RuntimeError("ASR vLLM engine does not expose its request metrics")
    original = vllm_engine.generate
    if getattr(original, "_asr_ttft_instrumented", False):
        return

    @functools.wraps(original)
    def measured_generate(*args, **kwargs):
        outputs = original(*args, **kwargs)
        for output in outputs:
            stats = getattr(output, "metrics", None)
            latency = getattr(stats, "first_token_latency", None)
            completions = getattr(output, "outputs", ())
            token_ids = getattr(completions[0], "token_ids", ()) if completions else ()
            if (token_ids and isinstance(latency, (int, float))
                    and math.isfinite(latency) and latency >= 0):
                ASR_TTFT.observe(latency)
        return outputs

    measured_generate._asr_ttft_instrumented = True
    vllm_engine.generate = measured_generate


def enable_vllm_request_metrics():
    """Keep per-request timestamps in offline vLLM RequestOutput objects."""
    from funasr.auto.auto_model_vllm import AutoModelVLLM

    original = AutoModelVLLM.__init__
    if getattr(original, "_asr_request_metrics_enabled", False):
        return

    @functools.wraps(original)
    def measured_init(self, *args, **kwargs):
        vllm_kwargs = dict(kwargs.get("vllm_kwargs", {}))
        vllm_kwargs["disable_log_stats"] = False
        kwargs["vllm_kwargs"] = vllm_kwargs
        original(self, *args, **kwargs)

    measured_init._asr_request_metrics_enabled = True
    AutoModelVLLM.__init__ = measured_init


async def run(config_path, key_path):
    cfg = json.loads(config_path.read_text())
    token = key_path.read_text().strip()
    args = upstream_args(cfg)

    # Offline vLLM disables request stats by default; retain them so the output
    # carries the engine's own first-token timestamp used by our histogram.
    enable_vllm_request_metrics()
    # Listen only after the audio encoder, VAD, and vLLM decoder are usable.
    await asyncio.to_thread(realtime_ws.load_models, args)
    instrument_vllm_ttft(realtime_ws._vllm_engine)

    def process_request(connection, request):
        if not authorized(request.headers, token):
            response = connection.respond(HTTPStatus.UNAUTHORIZED, "unauthorized\n")
            response.headers["WWW-Authenticate"] = "Bearer"
            return response
        if request.path == "/health":
            response = connection.respond(HTTPStatus.OK, '{"status":"ok"}\n')
            response.headers["Content-Type"] = "application/json"
            return response
        if request.path == "/metrics":
            response = connection.respond(HTTPStatus.OK, generate_latest().decode("utf-8"))
            response.headers["Content-Type"] = CONTENT_TYPE_LATEST
            response.headers["Cache-Control"] = "no-store"
            return response
        if request.path != "/realtime":
            return connection.respond(HTTPStatus.NOT_FOUND, "not found\n")
        return None

    options = realtime_ws.build_websocket_serve_kwargs(args)
    LOG.info("ASR ready on ws://%s:%d/realtime", cfg["host"], cfg["port"])
    async with websockets.serve(
        lambda connection: realtime_ws.handle_client(connection, args),
        cfg["host"], cfg["port"], process_request=process_request,
        compression=None, server_header=None, **options,
    ):
        await asyncio.Future()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(run(args.config.resolve(), args.key_file.resolve()))


if __name__ == "__main__":
    main()
