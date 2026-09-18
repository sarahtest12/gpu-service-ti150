"""Shared WebSocket protocol primitives for TTS backends."""

import asyncio
import json


class ProtocolError(Exception):
    def __init__(self, code, message, *, fatal=False, preserve_utterance=False, segment_id=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fatal = fatal
        self.preserve_utterance = preserve_utterance
        self.segment_id = segment_id


class WebSocketSender:
    """Serialize all writes to one WebSocket and bound each write."""

    def __init__(self, websocket, timeout):
        self.websocket = websocket
        self.timeout = timeout
        self.lock = asyncio.Lock()

    async def json(self, event, timeout=None):
        try:
            async with self.lock:
                await asyncio.wait_for(
                    self.websocket.send_json(event),
                    self.timeout if timeout is None else timeout,
                )
        except asyncio.TimeoutError as error:
            raise ProtocolError(
                "output_timeout", "timed out sending a control event", fatal=True,
            ) from error

    async def bytes(self, chunk, timeout=None):
        try:
            async with self.lock:
                await asyncio.wait_for(
                    self.websocket.send_bytes(chunk),
                    self.timeout if timeout is None else timeout,
                )
        except asyncio.TimeoutError as error:
            raise ProtocolError(
                "output_timeout", "timed out sending audio to the client", fatal=True,
            ) from error


def error_event(error):
    event = {
        "type": "error",
        "code": error.code,
        "message": error.message,
        "fatal": error.fatal,
    }
    if error.segment_id is not None:
        event["segment_id"] = error.segment_id
    return event


def session_created_event(cfg, session_id):
    return {
        "type": "session.created",
        "session_id": session_id,
        "model": cfg["model_name"],
        "voice": cfg["voice_id"],
        "audio": {
            "format": "pcm_s16le",
            "sample_rate_hz": cfg["sample_rate_hz"],
            "channels": 1,
        },
    }


async def receive_message(websocket, max_message_bytes, timeout=None):
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
    if len(raw.encode("utf-8")) > max_message_bytes:
        raise ProtocolError("message_too_large", "message exceeds the byte limit")
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProtocolError("invalid_json", "message is not valid JSON") from error
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError("invalid_message", "message must be an object with a type")
    return message


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


async def close_websocket(websocket, code, timeout, reason=None):
    try:
        await asyncio.wait_for(websocket.close(code=code, reason=reason), timeout)
    except (asyncio.TimeoutError, RuntimeError):
        pass
