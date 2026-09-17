#!/usr/bin/env python3
"""Authenticated bi-streaming WebSocket service for Fun-CosyVoice3."""

import argparse
import asyncio
import hmac
import json
import logging
from pathlib import Path
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
import uvicorn

from engine import CosyVoice3Engine, StreamBackpressure, StreamClosed, TextStream


LOG = logging.getLogger("tts-service")


class VendorPayloadFilter(logging.Filter):
    """Remove vendor records that include synthesis or prompt text."""

    def filter(self, record):
        message = record.getMessage()
        return not (message.startswith("synthesis text ")
                    or " too short than prompt text " in message)


class ProtocolError(Exception):
    def __init__(self, code, message, *, fatal=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fatal = fatal


def configure_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(VendorPayloadFilter())


def authorized(value, token):
    return hmac.compare_digest(value or "", "Bearer " + token)


def error_event(error):
    return {
        "type": "error",
        "code": error.code,
        "message": error.message,
        "fatal": error.fatal,
    }


def validate_text(value, cfg):
    if not isinstance(value, str):
        raise ProtocolError("invalid_text", "input.text requires a string")
    value = value.strip()
    if not value or "\x00" in value or "<|" in value or "<endofprompt>" in value:
        raise ProtocolError("invalid_text", "text is empty or contains a control sequence")
    if len(value) > cfg["max_input_chunk_characters"]:
        raise ProtocolError("input_chunk_too_long", "text chunk exceeds the character limit")
    return value


async def receive_message(websocket, cfg, timeout=None):
    try:
        operation = websocket.receive()
        value = await asyncio.wait_for(operation, timeout) if timeout is not None else await operation
    except asyncio.TimeoutError as error:
        raise ProtocolError("input_timeout", "timed out waiting for more text", fatal=True) from error
    message_type = value.get("type")
    if message_type == "websocket.disconnect":
        raise EOFError
    if message_type != "websocket.receive" or value.get("text") is None:
        raise ProtocolError("invalid_message", "client messages must be JSON text")
    raw = value["text"]
    if len(raw.encode("utf-8")) > cfg["max_message_bytes"]:
        raise ProtocolError("message_too_large", "message exceeds the byte limit")
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProtocolError("invalid_json", "message is not valid JSON") from error
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError("invalid_message", "message must be an object with a type")
    return message


def parse_idle_message(message, cfg):
    kind = message["type"]
    if kind == "input.text" and set(message) == {"type", "text"}:
        return kind, validate_text(message["text"], cfg)
    if kind == "session.close" and set(message) == {"type"}:
        return kind, None
    if kind == "input.done" and set(message) == {"type"}:
        raise ProtocolError("invalid_state", "input.done requires an active utterance")
    raise ProtocolError("invalid_message", "unsupported message for an idle session")


def parse_active_message(message, cfg, input_done):
    kind = message["type"]
    if input_done:
        raise ProtocolError("invalid_state", "messages are not allowed after input.done")
    if kind == "input.text" and set(message) == {"type", "text"}:
        return kind, validate_text(message["text"], cfg)
    if kind == "input.done" and set(message) == {"type"}:
        return kind, None
    if kind == "session.close" and set(message) == {"type"}:
        raise ProtocolError("invalid_state", "session.close is allowed only between utterances")
    raise ProtocolError("invalid_message", "unsupported message for an active utterance")


def next_output(iterator):
    try:
        return "chunk", next(iterator)
    except StopIteration:
        return "done", None


async def stop_task(task):
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, EOFError):
        pass


async def close_iterator(iterator):
    close = getattr(iterator, "close", None)
    if close is not None:
        await asyncio.to_thread(close)


async def run_utterance(websocket, engine, cfg, first_text, request_id, utterance_id):
    text_stream = TextStream(cfg["text_queue_chunks"])
    text_stream.append(first_text, timeout=0)
    total_characters = len(first_text)
    input_done = False
    iterator = engine.synthesize(text_stream, request_id, utterance_id)
    receive_task = None
    output_task = None
    await websocket.send_json({"type": "audio.start", "utterance_id": utterance_id})
    try:
        receive_task = asyncio.create_task(
            receive_message(websocket, cfg, cfg["input_timeout_seconds"]),
        )
        output_task = asyncio.create_task(asyncio.to_thread(next_output, iterator))
        while True:
            completed, _ = await asyncio.wait(
                (receive_task, output_task), return_when=asyncio.FIRST_COMPLETED,
            )

            if output_task in completed:
                kind, chunk = output_task.result()
                if kind == "done":
                    if not input_done:
                        raise ProtocolError(
                            "inference_failed", "TTS inference ended before input.done", fatal=True,
                        )
                    await stop_task(receive_task)
                    await websocket.send_json({"type": "audio.done", "utterance_id": utterance_id})
                    return
                await websocket.send_bytes(chunk)
                output_task = asyncio.create_task(asyncio.to_thread(next_output, iterator))

            if receive_task in completed:
                try:
                    message = receive_task.result()
                    kind, text = parse_active_message(message, cfg, input_done)
                    if kind == "input.done":
                        input_done = True
                        text_stream.finish()
                    else:
                        if total_characters + len(text) > cfg["max_utterance_characters"]:
                            input_done = True
                            text_stream.finish()
                            raise ProtocolError(
                                "input_too_long", "utterance exceeds the character limit",
                            )
                        await asyncio.to_thread(
                            text_stream.append, text, cfg["text_queue_timeout_seconds"],
                        )
                        total_characters += len(text)
                except (ProtocolError, StreamBackpressure, StreamClosed) as error:
                    if isinstance(error, ProtocolError):
                        protocol_error = error
                    else:
                        protocol_error = ProtocolError(
                            "input_backpressure", "text input queue is not accepting data",
                        )
                    await websocket.send_json(error_event(protocol_error))
                    if protocol_error.fatal:
                        raise protocol_error
                receive_task = asyncio.create_task(
                    receive_message(
                        websocket, cfg,
                        None if input_done else cfg["input_timeout_seconds"],
                    ),
                )
    except EOFError:
        text_stream.cancel()
        raise
    except ProtocolError:
        text_stream.cancel()
        raise
    except Exception as error:
        text_stream.cancel()
        LOG.error(
            "TTS inference failed request_id=%s utterance_id=%s error_type=%s",
            request_id or "-", utterance_id, type(error).__name__,
        )
        raise ProtocolError("inference_failed", "TTS inference failed", fatal=True) from error
    finally:
        await stop_task(receive_task)
        if output_task is not None and not output_task.done():
            text_stream.cancel()
            try:
                await output_task
            except Exception:
                pass
        await close_iterator(iterator)


async def serve_session(websocket, engine, cfg, request_id, session_id):
    await websocket.send_json({
        "type": "session.created",
        "session_id": session_id,
        "model": cfg["model_name"],
        "voice": cfg["voice_id"],
        "audio": {
            "format": "pcm_s16le",
            "sample_rate_hz": cfg["sample_rate_hz"],
            "channels": 1,
        },
    })
    while True:
        try:
            message = await receive_message(
                websocket, cfg, cfg.get("session_idle_timeout_seconds", 3600),
            )
            kind, text = parse_idle_message(message, cfg)
        except ProtocolError as error:
            await websocket.send_json(error_event(error))
            if error.fatal:
                await websocket.close(code=1011, reason=error.code)
                return
            continue
        except EOFError:
            return

        if kind == "session.close":
            await websocket.close(code=1000)
            return
        utterance_id = "utt_" + secrets.token_hex(12)
        try:
            await run_utterance(
                websocket, engine, cfg, text, request_id, utterance_id,
            )
        except EOFError:
            return
        except ProtocolError as error:
            if error.code != "inference_failed":
                await websocket.send_json(error_event(error))
            else:
                await websocket.send_json(error_event(error))
            await websocket.close(code=1011, reason=error.code)
            return


def load_engine(cfg):
    import torch
    from cosyvoice.cli.cosyvoice import AutoModel

    torch.backends.cuda.enable_mem_efficient_sdp(False)
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_math_sdp(True)
    model = AutoModel(
        model_dir=cfg["model"],
        load_vllm=cfg["load_vllm"],
        load_trt=cfg["load_trt"],
        fp16=cfg["fp16"],
    )
    if model.sample_rate != cfg["sample_rate_hz"]:
        raise RuntimeError("configured sample rate does not match CosyVoice3")
    if not model.add_zero_shot_spk(
        cfg["prompt_text"], cfg["prompt_wav"], cfg["voice_id"],
    ):
        raise RuntimeError("failed to register fixed voice")
    return CosyVoice3Engine(model, cfg)


def create_app(engine, cfg, token):
    app = FastAPI(title="CosyVoice3 TTS internal service", version="2.0",
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
        await websocket.accept()
        request_id = websocket.headers.get("x-request-id", "")
        session_id = "tts_" + secrets.token_hex(12)
        LOG.info("TTS session opened request_id=%s session_id=%s", request_id or "-", session_id)
        try:
            await serve_session(websocket, engine, cfg, request_id, session_id)
        finally:
            engine.release()
            LOG.info("TTS session closed request_id=%s session_id=%s", request_id or "-", session_id)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    configure_logging()
    cfg = json.loads(args.config.read_text())
    token = args.key_file.read_text().strip()
    engine = load_engine(cfg)
    LOG.info("TTS ready on ws://%s:%d/realtime", cfg["host"], cfg["port"])
    uvicorn.run(create_app(engine, cfg, token), host=cfg["host"], port=cfg["port"],
                workers=1, access_log=True)


if __name__ == "__main__":
    main()
