#!/usr/bin/env python3
"""Authenticated loopback WebSocket wrapper for FunASR's realtime vLLM engine."""

import argparse
import asyncio
import hmac
from http import HTTPStatus
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import websockets
from funasr.bin import realtime_ws


LOG = logging.getLogger("asr-realtime")


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


async def run(config_path, key_path):
    cfg = json.loads(config_path.read_text())
    token = key_path.read_text().strip()
    args = upstream_args(cfg)

    # Listen only after the audio encoder, VAD, and vLLM decoder are usable.
    await asyncio.to_thread(realtime_ws.load_models, args)

    def process_request(connection, request):
        if not authorized(request.headers, token):
            response = connection.respond(HTTPStatus.UNAUTHORIZED, "unauthorized\n")
            response.headers["WWW-Authenticate"] = "Bearer"
            return response
        if request.path == "/health":
            response = connection.respond(HTTPStatus.OK, '{"status":"ok"}\n')
            response.headers["Content-Type"] = "application/json"
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

