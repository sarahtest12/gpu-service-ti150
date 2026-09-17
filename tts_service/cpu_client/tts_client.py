"""CPU-backend client for the authenticated CosyVoice3 realtime WebSocket."""

import json
import math
from pathlib import Path
import ssl
import struct
import threading
import urllib.parse

from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect as websocket_connect


class TtsRealtimeClient:
    """One reusable TTS WebSocket carrying sequential bi-streaming utterances."""

    def __init__(self, base_url, *, api_key, timeout_seconds=3600, ca_file=None):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError(
                "base_url must be an HTTPS TTS base without credentials, query or fragment"
            )
        if not isinstance(api_key, str) or not api_key or "\n" in api_key or "\r" in api_key:
            raise ValueError("set GPU_API_KEY to the shared gateway credential")
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("timeout_seconds must be positive and finite")
        path = parsed.path.rstrip("/") + "/v1/realtime"
        self.url = urllib.parse.urlunsplit(("wss", parsed.netloc, path, "", ""))
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.context = ssl.create_default_context(
            cafile=str(Path(ca_file)) if ca_file is not None else None,
        )
        self._connection = None
        self._active = False
        self.session = None

    def connect(self):
        if self._connection is not None:
            raise RuntimeError("TTS client is already connected")
        try:
            connection = websocket_connect(
                self.url,
                ssl=self.context,
                additional_headers={"Authorization": "Bearer " + self.api_key},
                open_timeout=self.timeout_seconds,
                close_timeout=min(self.timeout_seconds, 10),
                compression=None,
                proxy=None,
            )
            self._connection = connection
            event = self._receive_event()
            expected_audio = {"format": "pcm_s16le", "sample_rate_hz": 24000, "channels": 1}
            if (event.get("type") != "session.created"
                    or event.get("audio") != expected_audio
                    or not isinstance(event.get("session_id"), str)
                    or not event["session_id"]):
                raise RuntimeError("TTS returned unsupported audio metadata or session response")
            self.session = event
            return self
        except InvalidStatus as error:
            self._disconnect()
            raise RuntimeError(
                f"TTS WebSocket HTTP {error.response.status_code}; check endpoint and token"
            ) from None
        except TimeoutError:
            self._disconnect()
            raise RuntimeError("TTS connection timed out; check endpoint and server load") from None
        except (ConnectionClosed, OSError, ssl.SSLError):
            self._disconnect()
            raise RuntimeError("TTS connection failed; check endpoint and network access") from None
        except Exception:
            self._disconnect()
            raise

    def synthesize(self, text_chunks):
        """Yield 24 kHz mono PCM S16LE while text chunks are still arriving."""
        if self._connection is None:
            raise RuntimeError("TTS client is not connected")
        if self._active:
            raise RuntimeError("a TTS utterance is already active on this connection")

        def generate():
            self._active = True
            sender_errors = []
            sender = None
            try:
                try:
                    iterator = iter(text_chunks)
                    first = next(iterator)
                except StopIteration:
                    raise ValueError("text_chunks must contain at least one text chunk") from None
                except TypeError:
                    raise ValueError("text_chunks must be an iterable of strings") from None
                first = self._validate_text(first)

                def send_text():
                    try:
                        self._send_text(first)
                        for value in iterator:
                            self._send_text(self._validate_text(value))
                        self._connection.send(json.dumps({"type": "input.done"}))
                    except Exception as error:
                        sender_errors.append(error)
                        connection = self._connection
                        if connection is not None:
                            connection.close()

                sender = threading.Thread(target=send_text, name="tts-text-sender", daemon=True)
                sender.start()
                started = False
                utterance_id = None
                while True:
                    try:
                        message = self._connection.recv(timeout=self.timeout_seconds)
                    except TimeoutError:
                        raise RuntimeError("TTS response timed out; check server load or timeout_seconds") from None
                    except ConnectionClosed:
                        if sender_errors:
                            raise sender_errors[0]
                        raise RuntimeError("TTS connection closed before audio.done") from None
                    if isinstance(message, bytes):
                        if not started or not message or len(message) % 2:
                            raise RuntimeError("TTS returned invalid PCM audio ordering or length")
                        yield message
                        continue
                    event = self._decode_event(message)
                    if event.get("type") == "error":
                        code = event.get("code") if isinstance(event.get("code"), str) else "unknown"
                        message = event.get("message") if isinstance(event.get("message"), str) else "request failed"
                        raise RuntimeError(f"TTS {code}: {message}")
                    if event.get("type") == "audio.start" and not started:
                        utterance_id = event.get("utterance_id")
                        if not isinstance(utterance_id, str) or not utterance_id:
                            raise RuntimeError("TTS returned an invalid audio.start event")
                        started = True
                        continue
                    if (event.get("type") == "audio.done" and started
                            and event.get("utterance_id") == utterance_id):
                        sender.join(timeout=self.timeout_seconds)
                        if sender.is_alive():
                            raise RuntimeError("TTS text sender did not finish")
                        if sender_errors:
                            raise sender_errors[0]
                        return
                    raise RuntimeError("TTS returned an unexpected event sequence")
            except (ValueError, RuntimeError):
                self._disconnect()
                raise
            except (OSError, ssl.SSLError):
                self._disconnect()
                raise RuntimeError("TTS connection failed during synthesis") from None
            finally:
                self._active = False

        return generate()

    def close(self):
        connection = self._connection
        if connection is None:
            return
        try:
            if not self._active:
                connection.send(json.dumps({"type": "session.close"}))
        except (ConnectionClosed, OSError):
            pass
        finally:
            self._disconnect()

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _send_text(self, text):
        self._connection.send(json.dumps({"type": "input.text", "text": text}, ensure_ascii=False))

    def _receive_event(self):
        try:
            message = self._connection.recv(timeout=self.timeout_seconds)
        except TimeoutError:
            raise RuntimeError("TTS response timed out; check server load or timeout_seconds") from None
        if not isinstance(message, str):
            raise RuntimeError("TTS returned binary data before session.created")
        return self._decode_event(message)

    @staticmethod
    def _decode_event(message):
        try:
            event = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            raise RuntimeError("TTS returned invalid JSON") from None
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise RuntimeError("TTS returned an invalid event")
        return event

    @staticmethod
    def _validate_text(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("each text chunk must be a non-empty string")
        return value

    def _disconnect(self):
        connection, self._connection = self._connection, None
        self.session = None
        if connection is not None:
            try:
                connection.close()
            except (ConnectionClosed, OSError):
                pass


def write_wav_header(output, data_size, sample_rate=24000, channels=1, bits_per_sample=16):
    """Write a standard PCM WAV header once the streamed PCM byte length is known."""
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    output.write(b"RIFF")
    output.write(struct.pack("<I", 36 + data_size))
    output.write(b"WAVEfmt ")
    output.write(struct.pack("<IHHIIHH", 16, 1, channels, sample_rate,
                             byte_rate, block_align, bits_per_sample))
    output.write(b"data")
    output.write(struct.pack("<I", data_size))
