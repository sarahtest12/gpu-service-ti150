#!/usr/bin/env python3
"""Authenticated streaming HTTP service for CosyVoice-300M-Instruct."""

import argparse
import functools
import hmac
import json
import logging
from pathlib import Path
import threading
import time
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
import numpy as np
from prometheus_client import CONTENT_TYPE_LATEST, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field, field_validator
import uvicorn


LOG = logging.getLogger("tts-service")
TTS_TTFT = Histogram(
    "tts_time_to_first_token_seconds",
    "Time from speech-token decoder submission until its first speech token.",
    buckets=(0.001, 0.005, 0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64,
             1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92, 163.84),
)


class VendorPayloadFilter(logging.Filter):
    """Remove CosyVoice v1 records that include request text or instructions."""

    def filter(self, record):
        message = record.getMessage()
        return not (message.startswith("synthesis text ") or " too short than prompt text " in message)


def configure_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(VendorPayloadFilter())


class SpeechRequest(BaseModel):
    """Reviewed public request; audio is always streamed as mono PCM S16LE."""

    model_config = ConfigDict(extra="forbid")

    model: str
    input: str = Field(min_length=1)
    voice: str
    instructions: str | None = None
    response_format: Literal["pcm"] = "pcm"
    stream: Literal[True] = True
    speed: Literal[1.0] = 1.0

    @field_validator("model", "input", "voice")
    @classmethod
    def required_text(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("must be non-empty text without NUL characters")
        value = value.strip()
        if "<|" in value or "<endofprompt>" in value:
            raise ValueError("must not contain tokenizer control sequences")
        return value

    @field_validator("instructions")
    @classmethod
    def optional_text(cls, value):
        if value is None:
            return None
        if "\x00" in value or "<|" in value or "<endofprompt>" in value:
            raise ValueError("must not contain NUL or tokenizer control sequences")
        value = value.strip()
        return value or None


class CosyVoiceEngine:
    def __init__(self, model, cfg):
        self.model = model
        self.cfg = cfg
        self.voices = tuple(cfg["voices"])
        self._slots = threading.BoundedSemaphore(cfg["max_concurrency"])
        self._metric_lock = threading.Lock()
        self._measure_first_token = False
        self._instrument_token_decoder()

    def _instrument_token_decoder(self):
        """Observe the first speech token for the one active HTTP request."""
        vendor_model = getattr(self.model, "model", None)
        llm = getattr(vendor_model, "llm", None)
        if llm is None:
            return
        original = llm.inference
        if getattr(original, "_tts_ttft_instrumented", False):
            return

        @functools.wraps(original)
        def measured_inference(*args, **kwargs):
            started = time.perf_counter()
            first = True
            for token in original(*args, **kwargs):
                if first:
                    first = False
                    self._observe_first_token(time.perf_counter() - started)
                yield token

        measured_inference._tts_ttft_instrumented = True
        llm.inference = measured_inference

    def _observe_first_token(self, latency_seconds):
        with self._metric_lock:
            if not self._measure_first_token:
                return
            self._measure_first_token = False
        TTS_TTFT.observe(latency_seconds)

    def acquire(self):
        return self._slots.acquire(blocking=False)

    @staticmethod
    def pcm16(tensor):
        samples = tensor.detach().float().cpu().numpy().reshape(-1)
        return np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2", copy=False).tobytes()

    def stream_locked(self, text, voice, instructions, request_id=""):
        """Drain the vendor generator after disconnect so its per-request caches are released."""
        output = None
        started = time.monotonic()
        first = True
        with self._metric_lock:
            self._measure_first_token = True
        try:
            output = self.model.inference_instruct(
                text, voice, instructions, stream=True, speed=1.0,
            )
            for item in output:
                chunk = self.pcm16(item["tts_speech"])
                if not chunk:
                    continue
                if first:
                    LOG.info("TTS first audio request_id=%s latency_ms=%.1f",
                             request_id or "-", (time.monotonic() - started) * 1000)
                    first = False
                yield chunk
        finally:
            # CosyVoice v1 only removes its UUID caches when the generator reaches the end.
            # It has no cancellation primitive, so finish generation after a client disconnect.
            if output is not None:
                try:
                    for _ in output:
                        pass
                except Exception:
                    LOG.exception("TTS generator cleanup failed request_id=%s", request_id or "-")
            with self._metric_lock:
                self._measure_first_token = False
            self._slots.release()


def load_engine(cfg):
    import torch
    from cosyvoice.cli.cosyvoice import CosyVoice

    torch.backends.cuda.enable_mem_efficient_sdp(False)
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_math_sdp(True)
    model = CosyVoice(
        cfg["model"], load_jit=cfg["load_jit"],
        load_onnx=cfg["load_onnx"], fp16=cfg["fp16"],
    )
    actual = set(model.list_avaliable_spks())
    configured = set(cfg["voices"])
    if actual != configured:
        raise RuntimeError(f"configured voices do not match the checkpoint: {sorted(actual)}")
    return CosyVoiceEngine(model, cfg)


def create_app(engine, cfg, token):
    app = FastAPI(title="CosyVoice TTS internal service", version="1.0",
                  docs_url=None, redoc_url=None, openapi_url=None)

    def authorize(authorization: Annotated[str | None, Header()] = None):
        if not hmac.compare_digest(authorization or "", "Bearer " + token):
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

    @app.get("/v1/audio/voices", dependencies=[auth])
    def voices():
        return {
            "object": "list",
            "data": [
                {"id": name, "object": "voice", "language": language}
                for name, language in cfg["voices"].items()
            ],
        }

    @app.post("/v1/audio/speech", dependencies=[auth])
    def speech(payload: SpeechRequest, request: Request):
        if payload.model != cfg["model_name"]:
            raise HTTPException(status_code=404, detail="unknown model")
        if payload.voice not in cfg["voices"]:
            raise HTTPException(status_code=400, detail="unsupported voice")
        if len(payload.input) > cfg["max_input_characters"]:
            raise HTTPException(status_code=400, detail="input is too long")
        instructions = payload.instructions or cfg["default_instruction"]
        if len(instructions) > cfg["max_instruction_characters"]:
            raise HTTPException(status_code=400, detail="instructions are too long")
        if not engine.acquire():
            raise HTTPException(status_code=429, detail="TTS concurrency limit reached")
        request_id = request.headers.get("X-Request-ID", "")
        return StreamingResponse(
            engine.stream_locked(payload.input, payload.voice, instructions, request_id),
            media_type="audio/pcm",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
                "X-Audio-Format": "pcm_s16le",
                "X-Audio-Sample-Rate": str(cfg["sample_rate_hz"]),
                "X-Audio-Channels": "1",
            },
        )

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
    LOG.info("TTS ready on http://%s:%d/v1/audio/speech", cfg["host"], cfg["port"])
    uvicorn.run(create_app(engine, cfg, token), host=cfg["host"], port=cfg["port"],
                workers=1, access_log=True)


if __name__ == "__main__":
    main()
