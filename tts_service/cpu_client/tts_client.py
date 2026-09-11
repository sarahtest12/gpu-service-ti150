"""CPU-only streaming client for CosyVoice through the shared HTTPS gateway."""

from contextlib import contextmanager
import math
import ssl
import urllib.parse

import httpx


class TtsClient:
    def __init__(self, base_url, *, api_key, model="cosyvoice-300m-instruct",
                 timeout_seconds=600, ca_file=None):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("base_url must be an HTTP(S) API base without credentials, query or fragment")
        if not api_key or "\n" in api_key or "\r" in api_key:
            raise ValueError("set GPU_API_KEY to the shared gateway credential")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        if not model.strip():
            raise ValueError("model must be non-empty")
        verify = ssl.create_default_context(cafile=str(ca_file)) if ca_file is not None else True
        self.model = model
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), verify=verify, trust_env=False,
            follow_redirects=False, timeout=timeout_seconds,
            headers={"Authorization": "Bearer " + api_key},
        )

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def voices(self):
        response = self._http.get("/audio/voices")
        self._raise(response)
        value = response.json()
        if value.get("object") != "list" or not isinstance(value.get("data"), list):
            raise RuntimeError("TTS returned an invalid voice list")
        return value

    @contextmanager
    def stream(self, text, *, voice, instructions=None):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be non-empty")
        if not isinstance(voice, str) or not voice.strip():
            raise ValueError("voice must be non-empty")
        payload = {
            "model": self.model, "input": text, "voice": voice,
            "response_format": "pcm", "stream": True, "speed": 1.0,
        }
        if instructions is not None:
            payload["instructions"] = instructions
        try:
            with self._http.stream("POST", "/audio/speech", json=payload) as response:
                self._raise(response)
                expected = {
                    "x-audio-format": "pcm_s16le",
                    "x-audio-sample-rate": "22050",
                    "x-audio-channels": "1",
                }
                if any(response.headers.get(name) != value for name, value in expected.items()):
                    raise RuntimeError("TTS returned unsupported audio metadata")
                yield response.iter_bytes()
        except httpx.TimeoutException:
            raise RuntimeError("TTS request timed out; check server load or timeout_seconds") from None
        except httpx.TransportError:
            raise RuntimeError("TTS connection failed; check endpoint and network access") from None

    @staticmethod
    def _raise(response):
        if response.status_code >= 400:
            raise RuntimeError(f"TTS HTTP {response.status_code}; check request, token and server log")


def write_wav_header(output, data_size, sample_rate=22050, channels=1, bits_per_sample=16):
    """Write a standard PCM WAV header once the streamed PCM byte length is known."""
    import struct

    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    output.write(b"RIFF")
    output.write(struct.pack("<I", 36 + data_size))
    output.write(b"WAVEfmt ")
    output.write(struct.pack("<IHHIIHH", 16, 1, channels, sample_rate,
                             byte_rate, block_align, bits_per_sample))
    output.write(b"data")
    output.write(struct.pack("<I", data_size))
