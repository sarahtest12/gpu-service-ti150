"""Bounded text input and native PyTorch CosyVoice3 synthesis."""

from collections import deque
import functools
import logging
import math
import threading
import time

import numpy as np
from prometheus_client import Histogram


LOG = logging.getLogger("tts-service")
TTS_TTFT = Histogram(
    "tts_time_to_first_token_seconds",
    "Time from the first GPU text-token batch until the first speech token.",
    buckets=(0.001, 0.005, 0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64,
             1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92, 163.84),
)


class StreamBackpressure(RuntimeError):
    """Raised when text cannot enter the bounded bridge before its timeout."""


class StreamClosed(RuntimeError):
    """Raised when text is appended after finish or cancellation."""


class TextStream:
    """Thread-safe, bounded iterator consumed by CosyVoice's synchronous API."""

    def __init__(self, max_chunks):
        if type(max_chunks) is not int or max_chunks < 1:
            raise ValueError("max_chunks must be a positive integer")
        self._max_chunks = max_chunks
        self._items = deque()
        self._finished = False
        self._cancelled = False
        self._condition = threading.Condition()

    def append(self, text, timeout=None):
        if not isinstance(text, str) or not text:
            raise ValueError("text must be non-empty")
        if timeout is not None and (not isinstance(timeout, (int, float))
                                    or not math.isfinite(timeout) or timeout < 0):
            raise ValueError("timeout must be non-negative and finite")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while len(self._items) >= self._max_chunks and not self._finished:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise StreamBackpressure("text input queue is full")
                self._condition.wait(remaining)
            if self._finished:
                raise StreamClosed("text stream is closed")
            self._items.append(text)
            self._condition.notify_all()

    def finish(self):
        with self._condition:
            self._finished = True
            self._condition.notify_all()

    def cancel(self):
        with self._condition:
            self._cancelled = True
            self._finished = True
            self._items.clear()
            self._condition.notify_all()

    @property
    def cancelled(self):
        with self._condition:
            return self._cancelled

    def __iter__(self):
        while True:
            with self._condition:
                while not self._items and not self._finished:
                    self._condition.wait()
                if self._cancelled:
                    return
                if self._items:
                    item = self._items.popleft()
                    self._condition.notify_all()
                else:
                    return
            yield item


class CosyVoice3Engine:
    """Own one model and expose fixed-voice PCM generation."""

    def __init__(self, model, cfg):
        self.model = model
        self.cfg = cfg
        self._slots = threading.BoundedSemaphore(cfg["max_concurrency"])
        self._metric_lock = threading.Lock()
        self._measure_first_token = False
        self._instrument_token_decoder()

    def _instrument_token_decoder(self):
        vendor_model = getattr(self.model, "model", None)
        llm = getattr(vendor_model, "llm", None)
        original = getattr(llm, "inference_bistream", None)
        if original is None or getattr(original, "_tts_ttft_instrumented", False):
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
        llm.inference_bistream = measured_inference

    def _observe_first_token(self, latency_seconds):
        with self._metric_lock:
            if not self._measure_first_token:
                return
            self._measure_first_token = False
        TTS_TTFT.observe(latency_seconds)

    def acquire(self):
        return self._slots.acquire(blocking=False)

    def release(self):
        self._slots.release()

    @staticmethod
    def pcm16(tensor):
        samples = tensor.detach().float().cpu().numpy().reshape(-1)
        if samples.size == 0:
            return b""
        return np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype(
            "<i2", copy=False,
        ).tobytes()

    def synthesize(self, text_stream, request_id, utterance_id):
        """Yield PCM and finish the vendor generator so request caches are released."""
        output = None
        with self._metric_lock:
            self._measure_first_token = True
        try:
            output = self.model.inference_zero_shot(
                text_stream,
                self.cfg["prompt_text"],
                self.cfg["prompt_wav"],
                zero_shot_spk_id=self.cfg["voice_id"],
                stream=True,
                speed=1.0,
            )
            for item in output:
                chunk = self.pcm16(item["tts_speech"])
                if chunk:
                    yield chunk
        finally:
            if output is not None:
                try:
                    for _ in output:
                        pass
                except Exception:
                    LOG.exception(
                        "TTS generator cleanup failed request_id=%s utterance_id=%s",
                        request_id or "-", utterance_id or "-",
                    )
            with self._metric_lock:
                self._measure_first_token = False
