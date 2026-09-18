"""CPU-backend client for the authenticated CosyVoice-300M WebSocket."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import ssl
import struct
import threading
import urllib.parse

from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect as websocket_connect


MODELS = frozenset(("cosyvoice-300m-sft", "cosyvoice-300m-instruct"))
VOICE = "中文女"
AUDIO = {"format": "pcm_s16le", "sample_rate_hz": 22050, "channels": 1}


@dataclass(frozen=True)
class SegmentFrame:
    kind: str
    segment_id: str
    pcm: bytes | None = None


class SegmentRejected(RuntimeError):
    """A correlated nonfatal rejection; the connection remains usable."""

    def __init__(self, code, segment_id, message):
        super().__init__(f"TTS {code}: {message}")
        self.code = code
        self.segment_id = segment_id
        self.message = message


class SegmentStreamError(RuntimeError):
    """The pipeline failed; unfinished IDs must not be automatically replayed."""

    def __init__(self, message, unfinished_segment_ids):
        self.unfinished_segment_ids = tuple(unfinished_segment_ids)
        super().__init__(f"{message}; unfinished segment IDs: {self.unfinished_segment_ids!r}")


class TtsRealtimeClient:
    """One reusable connection for complete, CPU-segmented text."""

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
        self._receive_lock = threading.Lock()
        self._segments = {}  # Ordered outstanding ID -> acknowledgement received.
        self._accepted_ids = set()  # Lifetime history, including completed/cancelled IDs.
        self._audio_segment = None
        self._segment_cancel = None
        self.unfinished_segment_ids = ()
        self._connection = None
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
            audio = event.get("audio")
            if (event.get("type") != "session.created" or event.get("model") not in MODELS
                    or event.get("voice") != VOICE
                    or not isinstance(audio, dict)
                    or audio != AUDIO
                    or type(audio.get("sample_rate_hz")) is not int
                    or type(audio.get("channels")) is not int
                    or not isinstance(event.get("session_id"), str)
                    or not event["session_id"]):
                raise RuntimeError("TTS returned unsupported model, voice or audio metadata")
            with self._state_lock:
                self._segments.clear()
                self._accepted_ids.clear()
                self._audio_segment = None
                self._segment_cancel = None
                self.unfinished_segment_ids = ()
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

    def _require_connection(self):
        # Caller holds the state lock. Never hold it while receiving from the network.
        if self._connection is None or self.session is None:
            raise RuntimeError("TTS client is not connected")
        return self._connection

    def send_segment(self, segment_id: str, text: str) -> None:
        """Submit a complete segment; acceptance is reported by the receive loop."""
        with self._send_lock:
            with self._state_lock:
                connection = self._require_connection()
                if self._segment_cancel is not None:
                    raise RuntimeError("TTS cancellation is pending")
                if not isinstance(segment_id, str) or not segment_id:
                    raise ValueError("segment_id must be a non-empty string")
                if segment_id in self._segments or segment_id in self._accepted_ids:
                    raise ValueError("segment ID has already been submitted or accepted")
                self._validate_text(text)
                # Register before sending so a fast acknowledgement can be correlated.
                self._segments[segment_id] = False
            try:
                connection.send(json.dumps({"type": "input.segment", "segment_id": segment_id,
                                            "text": text}, ensure_ascii=False))
            except (ConnectionClosed, OSError, TimeoutError):
                raise self._segment_failure(connection, "TTS segment send failed") from None

    def cancel_segment(self, segment_id: str) -> None:
        """Cancel the started segment and all queued work; keep receiving until confirmed."""
        with self._send_lock:
            with self._state_lock:
                connection = self._require_connection()
                if self._segment_cancel is not None:
                    raise RuntimeError("TTS cancellation is already pending")
                if self._audio_segment is None or segment_id != self._audio_segment:
                    raise RuntimeError("segment_id must match the active audio segment")
                self._segment_cancel = segment_id
            try:
                connection.send(json.dumps({"type": "response.cancel", "segment_id": segment_id}))
            except (ConnectionClosed, OSError, TimeoutError):
                raise self._segment_failure(connection, "TTS cancellation send failed") from None

    def receive_segment_frame(self) -> SegmentFrame:
        """Receive one correlated frame. Exactly one receiver may consume this pipeline."""
        with self._state_lock:
            connection = self._require_connection()
        if not self._receive_lock.acquire(blocking=False):
            raise RuntimeError("a TTS segment receiver is already active")
        try:
            try:
                message = connection.recv(timeout=self.timeout_seconds)
                event = None if isinstance(message, bytes) else self._decode_event(message)
                with self._state_lock:
                    if connection is not self._connection:
                        raise RuntimeError("TTS connection closed during receive")
                    return self._segment_frame(message, event)
            except SegmentRejected:
                raise
            except (ConnectionClosed, OSError, TimeoutError):
                raise self._segment_failure(connection, "TTS segment connection closed or timed out") from None
            except RuntimeError as error:
                raise self._segment_failure(connection, str(error)) from None
        finally:
            self._receive_lock.release()

    def _segment_frame(self, message, event):
        # Called with state lock. All event ordering is relative to the wire, not sends.
        if isinstance(message, bytes):
            if self._audio_segment is None or not message or len(message) % 2:
                raise RuntimeError("TTS returned invalid PCM audio ordering or length")
            return SegmentFrame("audio", self._audio_segment, message)
        kind, ident = event["type"], event.get("segment_id")
        if kind == "error":
            code, detail = event.get("code"), event.get("message")
            if not isinstance(code, str) or not isinstance(detail, str) or event.get("fatal") is not False:
                raise RuntimeError(f"TTS fatal error: {code if isinstance(code, str) else 'unknown'}")
            if not isinstance(ident, str) or not ident:
                raise RuntimeError("TTS returned an uncorrelated rejection")
            if code == "invalid_state" and ident == self._segment_cancel:
                # The server may finish audio before it receives our cancellation.
                self._segment_cancel = None
            elif (code in {"queue_full", "invalid_segment", "segment_too_long",
                           "duplicate_segment_id", "invalid_state"}
                  and self._segments.get(ident) is False):
                first_unaccepted = next((key for key, accepted in self._segments.items() if not accepted), None)
                if ident != first_unaccepted:
                    raise RuntimeError("TTS returned an out-of-order rejection")
                del self._segments[ident]
            else:
                raise RuntimeError("TTS returned an unexpected rejection")
            raise SegmentRejected(code, ident, detail)
        if not isinstance(ident, str) or not ident:
            raise RuntimeError("TTS returned an invalid segment ID")
        if kind == "input.accepted":
            first_unaccepted = next((key for key, accepted in self._segments.items() if not accepted), None)
            if ident != first_unaccepted or ident in self._accepted_ids:
                raise RuntimeError("TTS returned an unexpected acceptance")
            self._segments[ident] = True
            self._accepted_ids.add(ident)
            return SegmentFrame("accepted", ident)
        if kind == "audio.start":
            if (self._audio_segment is not None or self._segments.get(ident) is not True
                    or ident != next(iter(self._segments), None)):
                raise RuntimeError("TTS returned an unexpected audio.start")
            self._audio_segment = ident
            return SegmentFrame("audio_start", ident)
        if kind == "audio.done" and ident == self._audio_segment:
            del self._segments[ident]
            self._audio_segment = None
            return SegmentFrame("audio_done", ident)
        if (kind == "response.cancelled" and ident == self._segment_cancel
                and ident == self._audio_segment):
            self._segments.clear()
            self._audio_segment = None
            self._segment_cancel = None
            return SegmentFrame("cancelled", ident)
        raise RuntimeError("TTS returned an unexpected segment event sequence")

    def _segment_failure(self, connection, message):
        self._disconnect(connection)
        return SegmentStreamError(message, self.unfinished_segment_ids)

    def close(self):
        """Close without replay; return IDs whose completion was not confirmed."""
        with self._send_lock:
            with self._state_lock:
                connection = self._connection
                active = bool(self._segments) or self._segment_cancel is not None
            if connection is None:
                return self.unfinished_segment_ids
            try:
                if not active:
                    connection.send(json.dumps({"type": "session.close"}))
            except (ConnectionClosed, OSError):
                pass
            finally:
                self._disconnect(connection)
        return self.unfinished_segment_ids

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

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
                self.unfinished_segment_ids = tuple(self._segments)
                self.session = None
            elif self._connection is expected:
                connection, self._connection = self._connection, None
                self.unfinished_segment_ids = tuple(self._segments)
                self.session = None
            else:
                connection = expected
        if connection is not None:
            try:
                connection.close()
            except (ConnectionClosed, OSError):
                pass


def write_wav_header(output, data_size, sample_rate, channels=1, bits_per_sample=16):
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
