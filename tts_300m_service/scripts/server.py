#!/usr/bin/env python3
"""Authenticated WebSocket service for CosyVoice-300M-Instruct."""

import argparse
import hmac
import logging
from pathlib import Path
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
import uvicorn

from cosyvoice300m_engine import CosyVoice300MEngine
from cosyvoice300m_session import serve_session
from protocol import ProtocolError, WebSocketSender, close_websocket, session_created_event


LOG = logging.getLogger("tts-300m-service")


class VendorPayloadFilter(logging.Filter):
    """Remove vendor records that include submitted synthesis text."""

    def filter(self, record):
        message = record.getMessage()
        return not (message.startswith("synthesis text ")
                    or " too short than prompt text " in message)


def configure_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(VendorPayloadFilter())


def authorized(value, token):
    return hmac.compare_digest(value or "", "Bearer " + token)


def load_runtime_config(path):
    import service

    original = service.CONFIG
    try:
        service.CONFIG = path.resolve()
        return service.config()
    finally:
        service.CONFIG = original


def load_engine(cfg):
    from cosyvoice.cli.cosyvoice import CosyVoice
    from cosyvoice.utils.common import set_all_random_seed

    model = CosyVoice(
        cfg["model"], load_jit=cfg["load_jit"],
        load_onnx=cfg["load_onnx"], fp16=cfg["fp16"],
    )
    if set(model.list_avaliable_spks()) != set(cfg["checkpoint_speakers"]):
        raise RuntimeError("300M checkpoint speaker metadata mismatch")
    if cfg["number_reading"] == "chinese" and not hasattr(
            model.frontend, "zh_tn_model"):
        raise RuntimeError("Chinese number normalizer is unavailable")
    return CosyVoice300MEngine(model, cfg, set_all_random_seed)


def create_app(engine, cfg, token):
    app = FastAPI(title="CosyVoice-300M TTS internal service", version="1.0",
                  docs_url=None, redoc_url=None, openapi_url=None)

    def authorize(authorization: str | None = Header(default=None)):
        if not authorized(authorization, token):
            raise HTTPException(status_code=401, detail="unauthorized",
                                headers={"WWW-Authenticate": "Bearer"})

    auth = Depends(authorize)

    @app.get("/health", dependencies=[auth])
    def health():
        return {"status": "ok"}

    @app.get("/metrics", dependencies=[auth])
    def metrics():
        return StreamingResponse(iter((generate_latest(),)), media_type=CONTENT_TYPE_LATEST,
                                 headers={"Cache-Control": "no-store"})

    @app.websocket("/realtime")
    async def realtime(websocket: WebSocket):
        if not authorized(websocket.headers.get("authorization"), token):
            await websocket.close(code=1008, reason="unauthorized")
            return
        if not engine.acquire():
            await websocket.close(code=1013, reason="TTS concurrency limit reached")
            return
        request_id = websocket.headers.get("x-request-id", "")
        session_id = "tts_" + secrets.token_hex(12)
        try:
            await websocket.accept()
            sender = WebSocketSender(websocket, cfg["output_timeout_seconds"])
            LOG.info("TTS session opened request_id=%s session_id=%s",
                     request_id or "-", session_id)
            try:
                await sender.json(session_created_event(cfg, session_id))
            except ProtocolError:
                await close_websocket(websocket, 1011,
                                      min(cfg["output_timeout_seconds"], 5),
                                      "output_timeout")
                return
            await serve_session(websocket, sender, engine, cfg, request_id)
        finally:
            engine.release()
            LOG.info("TTS session closed request_id=%s session_id=%s",
                     request_id or "-", session_id)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    configure_logging()
    cfg = load_runtime_config(args.config)
    token = args.key_file.read_text().strip()
    engine = load_engine(cfg)
    LOG.info("TTS 300M ready on ws://%s:%d/realtime", cfg["host"], cfg["port"])
    uvicorn.run(create_app(engine, cfg, token), host=cfg["host"], port=cfg["port"],
                workers=1, access_log=True)


if __name__ == "__main__":
    main()
