"""CPU-backend client for the authenticated CosyVoice3 realtime WebSocket."""

from collections import deque
from collections.abc import Sequence
import json
import math
from pathlib import Path
import ssl
import struct
import threading
import time
import urllib.parse

from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect as websocket_connect


class TtsTextInput:
    """Bounded, cancel-aware text source for an utterance fed incrementally."""

    def __init__(self, max_chunks=16):
        if type(max_chunks) is not int or max_chunks < 1:
            raise ValueError("max_chunks must be a positive integer")
        self._max_chunks = max_chunks
        self._items = deque()
        self._finished = False
        self._cancelled = False
        self._condition = threading.Condition()

    def append(self, text, timeout=None):
        if timeout is not None and (isinstance(timeout, bool)
                                    or not isinstance(timeout, (int, float))
                                    or not math.isfinite(timeout) or timeout < 0):
            raise ValueError("timeout must be non-negative and finite")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while len(self._items) >= self._max_chunks and not self._finished:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("TTS text input queue is full")
                self._condition.wait(remaining)
            if self._finished:
                raise RuntimeError("TTS text input is closed")
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
        return self

    def __next__(self):
        with self._condition:
            while not self._items and not self._finished:
                self._condition.wait()
            if self._cancelled or not self._items:
                raise StopIteration
            value = self._items.popleft()
            self._condition.notify_all()
            return value


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
        self._state_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._connection = None
        self._active_token = None
        self._active_utterance_id = None
        self._active_source = None
        self._active_cancel_event = None
        self._cancel_requested = False
        self.session = None

    def connect(self):
        with self._state_lock:
            if self._connection is not None:
                raise RuntimeError("TTS client is already connected")
        connection = None
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
            with self._state_lock:
                if self._connection is not None:
                    connection.close()
                    raise RuntimeError("TTS client is already connected")
                self._connection = connection
            event = self._receive_event(connection)
            expected_audio = {"format": "pcm_s16le", "sample_rate_hz": 24000, "channels": 1}
            if (event.get("type") != "session.created"
                    or event.get("model") != "fun-cosyvoice3-0.5b-2512"
                    or event.get("voice") != "aishell3-female"
                    or event.get("audio") != expected_audio
                    or not isinstance(event.get("session_id"), str)
                    or not event["session_id"]):
                raise RuntimeError("TTS returned unsupported model, voice or audio metadata")
            self.session = event
            return self
        except InvalidStatus as error:
            if connection is not None:
                self._disconnect(connection)
            raise RuntimeError(
                f"TTS WebSocket HTTP {error.response.status_code}; check endpoint and token"
            ) from None
        except TimeoutError:
            if connection is not None:
                self._disconnect(connection)
            raise RuntimeError("TTS connection timed out; check endpoint and server load") from None
        except (ConnectionClosed, OSError, ssl.SSLError):
            if connection is not None:
                self._disconnect(connection)
            raise RuntimeError("TTS connection failed; check endpoint and network access") from None
        except Exception:
            if connection is not None:
                self._disconnect(connection)
            raise

    def synthesize(self, text_chunks):
        """Yield 24 kHz mono PCM S16LE while text chunks are still arriving."""
        def generate():
            token = object()
            source = text_chunks if isinstance(text_chunks, TtsTextInput) else None
            cancel_event = threading.Event()
            with self._state_lock:
                connection = self._connection
                if connection is None:
                    raise RuntimeError("TTS client is not connected")
                if self._active_token is not None:
                    raise RuntimeError("a TTS utterance is already active on this connection")
                self._active_token = token
                self._active_utterance_id = None
                self._active_source = source
                self._active_cancel_event = cancel_event
                self._cancel_requested = False
            sender_errors = []
            sender = None
            completed = False
            try:
                if source is None and (isinstance(text_chunks, (str, bytes))
                                       or not isinstance(text_chunks, Sequence)):
                    raise ValueError(
                        "streaming text_chunks must use TtsTextInput; finite input must be a sequence"
                    )
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
                        self._send_text(connection, first)
                        for value in iterator:
                            if cancel_event.is_set():
                                return
                            self._send_text(connection, self._validate_text(value))
                        if cancel_event.is_set() or (source is not None and source.cancelled):
                            return
                        self._send_event(connection, {"type": "input.done"})
                    except Exception as error:
                        sender_errors.append(error)
                        try:
                            connection.close()
                        except (ConnectionClosed, OSError):
                            pass

                sender = threading.Thread(target=send_text, name="tts-text-sender", daemon=True)
                sender.start()
                started = False
                utterance_id = None
                while True:
                    try:
                        message = connection.recv(timeout=self.timeout_seconds)
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
                        with self._state_lock:
                            if self._active_token is token:
                                self._active_utterance_id = utterance_id
                        started = True
                        continue
                    if (event.get("type") == "audio.done" and started
                            and event.get("utterance_id") == utterance_id):
                        sender.join(timeout=self.timeout_seconds)
                        if sender.is_alive():
                            raise RuntimeError("TTS text sender did not finish")
                        if sender_errors:
                            raise sender_errors[0]
                        completed = True
                        return
                    if (event.get("type") == "response.cancelled" and started
                            and event.get("utterance_id") == utterance_id):
                        with self._state_lock:
                            requested = (self._active_token is token and self._cancel_requested)
                        if not requested:
                            raise RuntimeError("TTS returned an unexpected cancellation")
                        sender.join(timeout=self.timeout_seconds)
                        if sender.is_alive():
                            raise RuntimeError("TTS text sender did not finish")
                        if sender_errors:
                            raise sender_errors[0]
                        completed = True
                        return
                    raise RuntimeError("TTS returned an unexpected event sequence")
            except (ValueError, RuntimeError):
                self._disconnect(connection)
                raise
            except (OSError, ssl.SSLError):
                self._disconnect(connection)
                raise RuntimeError("TTS connection failed during synthesis") from None
            finally:
                if not completed:
                    if source is not None:
                        source.cancel()
                    self._disconnect(connection)
                    if sender is not None and sender.is_alive():
                        sender.join(timeout=min(self.timeout_seconds, 10))
                with self._state_lock:
                    if self._active_token is token:
                        self._active_token = None
                        self._active_utterance_id = None
                        self._active_source = None
                        self._active_cancel_event = None
                        self._cancel_requested = False

        return generate()

    def cancel_active(self):
        """Cancel the active utterance while keeping the WebSocket reusable."""
        with self._state_lock:
            connection = self._connection
            if connection is None:
                raise RuntimeError("TTS client is not connected")
            if self._active_token is None:
                raise RuntimeError("no TTS utterance is active")
            utterance_id = self._active_utterance_id
            if utterance_id is None:
                raise RuntimeError("the active TTS utterance has not started")
            if self._cancel_requested:
                raise RuntimeError("TTS cancellation is already pending")
            source = self._active_source
            cancel_event = self._active_cancel_event
            self._cancel_requested = True
            cancel_event.set()
        if source is not None:
            source.cancel()
        try:
            self._send_event(connection, {
                "type": "response.cancel",
                "utterance_id": utterance_id,
            })
        except (ConnectionClosed, OSError):
            self._disconnect(connection)
            raise RuntimeError("TTS connection failed during cancellation") from None

    def close(self):
        with self._state_lock:
            connection = self._connection
            active = self._active_token is not None
        if connection is None:
            return
        try:
            if not active:
                self._send_event(connection, {"type": "session.close"})
        except (ConnectionClosed, OSError):
            pass
        finally:
            self._disconnect(connection)

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _send_text(self, connection, text):
        self._send_event(connection, {"type": "input.text", "text": text})

    def _send_event(self, connection, event):
        with self._send_lock:
            connection.send(json.dumps(event, ensure_ascii=False))

    def _receive_event(self, connection):
        try:
            message = connection.recv(timeout=self.timeout_seconds)
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

    def _disconnect(self, expected=None):
        with self._state_lock:
            if expected is None:
                connection, self._connection = self._connection, None
                self.session = None
            elif self._connection is expected:
                connection, self._connection = self._connection, None
                self.session = None
            else:
                connection = expected
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
