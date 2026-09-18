"""Fixed-voice streaming adapter for CosyVoice-300M-SFT."""

import functools
import logging
import re
import threading
import time

import numpy as np

from tts_metrics import TTS_TTFT


LOG = logging.getLogger("tts-service")
CHINESE = re.compile(r"[\u4e00-\u9fff]")
ARABIC_DIGIT = re.compile(r"[0-9]")
FALLBACK_BOUNDARY = re.compile(r"[，,\s]")


class CosyVoice300MEngine:
    """Own one 300M model and expose bounded fixed-voice PCM generation."""

    def __init__(self, model, cfg, set_random_seed):
        self.model = model
        self.cfg = cfg
        self._set_random_seed = set_random_seed
        self._slots = threading.BoundedSemaphore(cfg["max_concurrency"])
        self._metric_lock = threading.Lock()
        self._measure_first_token = False
        self._instrument_token_decoder()

    def _instrument_token_decoder(self):
        vendor_model = getattr(self.model, "model", None)
        llm = getattr(vendor_model, "llm", None)
        original = getattr(llm, "inference", None)
        if original is None or getattr(original, "_tts_ttft_instrumented", False):
            return

        @functools.wraps(original)
        def measured_inference(*args, **kwargs):
            started = time.perf_counter()
            with self._metric_lock:
                measure = self._measure_first_token
                if measure:
                    self._measure_first_token = False
            first = True
            for token in original(*args, **kwargs):
                if first:
                    first = False
                    if measure:
                        TTS_TTFT.observe(max(0.0, time.perf_counter() - started))
                yield token

        measured_inference._tts_ttft_instrumented = True
        llm.inference = measured_inference

    def acquire(self):
        return self._slots.acquire(blocking=False)

    def release(self):
        self._slots.release()

    def _unit_count(self, text):
        if CHINESE.search(text):
            return len(text)
        return len(self.model.frontend.tokenizer.encode(text))

    def _longest_prefix(self, text, limit):
        low = 1
        high = len(text)
        longest = 0
        while low <= high:
            middle = (low + high) // 2
            if self._unit_count(text[:middle]) <= limit:
                longest = middle
                low = middle + 1
            else:
                high = middle - 1
        if longest == 0:
            raise ValueError("text tokenizer produced an oversized character")
        return longest

    def _split_to_units(self, text, limit):
        parts = []
        remaining = text
        while self._unit_count(remaining) > limit:
            hard_boundary = self._longest_prefix(remaining, limit)
            prefix = remaining[:hard_boundary]
            preferred = [match.end() for match in FALLBACK_BOUNDARY.finditer(prefix)]
            boundary = preferred[-1] if preferred else hard_boundary
            parts.append(remaining[:boundary])
            remaining = remaining[boundary:]
        if remaining:
            parts.append(remaining)
        return parts

    def subdivide(self, text):
        if ARABIC_DIGIT.search(text) and not CHINESE.search(text):
            text = self.model.frontend.zh_tn_model.normalize(text)
        native = list(self.model.frontend.text_normalize(text, split=True))
        if not native or any(not part for part in native):
            raise ValueError("text normalization produced an empty segment")
        result = []
        for part in native:
            result.extend(self._split_to_units(
                part, self.cfg["model_segment_units"],
            ))
        if not result or any(not part for part in result):
            raise ValueError("text normalization produced an empty segment")
        return result

    @staticmethod
    def pcm16(tensor):
        samples = tensor.detach().float().cpu().numpy().reshape(-1)
        if samples.size == 0:
            return b""
        if not np.isfinite(samples).all():
            raise ValueError("model produced non-finite audio")
        return np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype(
            "<i2", copy=False,
        ).tobytes()

    def synthesize_segment(self, text, request_id, segment_id):
        """Yield PCM and drain the active vendor generator before returning."""
        self._set_random_seed(self.cfg["random_seed"])
        with self._metric_lock:
            self._measure_first_token = True
        try:
            for part in self.subdivide(text):
                output = self.model.inference_sft(
                    part,
                    self.cfg["voice_id"],
                    stream=True,
                    speed=1.0,
                )
                try:
                    for item in output:
                        chunk = self.pcm16(item["tts_speech"])
                        if chunk:
                            yield chunk
                finally:
                    try:
                        for _ in output:
                            pass
                    except Exception as error:
                        LOG.error(
                            "TTS generator cleanup failed request_id=%s segment_id=%s error_type=%s",
                            request_id or "-", segment_id or "-", type(error).__name__,
                        )
                        raise
        finally:
            with self._metric_lock:
                self._measure_first_token = False
