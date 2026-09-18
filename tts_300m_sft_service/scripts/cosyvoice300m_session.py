"""Complete-segment FIFO protocol for the fixed-voice 300M backend."""

import asyncio
from collections import deque
from dataclasses import dataclass
import logging
import threading

from protocol import (ProtocolError, close_iterator, close_websocket, error_event,
                      receive_message, stop_task)


LOG = logging.getLogger("tts-service")


@dataclass(frozen=True)
class Segment:
    segment_id: str
    text: str


def parse_segment_message(message, cfg, accepted_ids):
    ident = message.get("segment_id")
    error_id = ident if isinstance(ident, str) and ident else None
    if (set(message) != {"type", "segment_id", "text"}
            or message.get("type") != "input.segment"
            or not isinstance(ident, str) or not ident.strip()):
        raise ProtocolError("invalid_segment", "input.segment requires an ID and text",
                            segment_id=error_id)
    text = message["text"]
    if (not isinstance(text, str) or not text.strip() or "\x00" in text
            or "<|" in text or "<endofprompt>" in text):
        raise ProtocolError("invalid_segment", "text is empty or contains a control sequence",
                            segment_id=ident)
    if len(text) > cfg["max_segment_characters"]:
        raise ProtocolError("segment_too_long", "segment exceeds the character limit",
                            segment_id=ident)
    if ident in accepted_ids:
        raise ProtocolError("duplicate_segment_id", "segment ID has already been accepted",
                            segment_id=ident)
    return Segment(ident, text)


def next_output(iterator):
    try:
        return False, next(iterator)
    except StopIteration:
        return True, None


class SegmentPipeline:
    """Own admission and one active iterator; all state transitions are serialized."""

    def __init__(self, websocket, sender, engine, cfg, request_id):
        self.websocket = websocket
        self.sender = sender
        self.engine = engine
        self.cfg = cfg
        self.request_id = request_id
        self.accepted_ids = set()
        self.pending = deque()
        self.pending_characters = 0
        self.active = None
        self.started = False
        self.cancelled = threading.Event()
        self.stopping = False
        self.lock = asyncio.Lock()
        self.ready = asyncio.Event()
        self.idle = asyncio.Event()
        self.idle.set()

    def clear_pending(self):
        self.pending.clear()
        self.pending_characters = 0

    def stop(self):
        # No await: a receiver failure prevents the worker promoting queued work
        # before the supervising coroutine observes the receiver's completion.
        self.stopping = True
        self.cancelled.set()
        self.clear_pending()
        self.ready.set()

    async def accept(self, message):
        segment = parse_segment_message(message, self.cfg, self.accepted_ids)
        if self.cancelled.is_set():
            raise ProtocolError("invalid_state", "wait for cancellation to complete",
                                segment_id=segment.segment_id)
        if self.active is not None and (
                len(self.pending) >= self.cfg["max_queued_segments"]
                or self.pending_characters + len(segment.text) > self.cfg["max_queued_characters"]):
            raise ProtocolError("queue_full", "segment queue is full", segment_id=segment.segment_id)
        # Commit admission only after the acknowledgement is written. The lock
        # also prevents an inference start from overtaking its acknowledgement.
        await self.sender.json({"type": "input.accepted", "segment_id": segment.segment_id})
        self.accepted_ids.add(segment.segment_id)
        if self.active is None:
            self.active = segment
            self.idle.clear()
        else:
            self.pending.append(segment)
            self.pending_characters += len(segment.text)
        self.ready.set()

    async def handle(self, message):
        kind = message["type"]
        if kind == "input.segment":
            await self.accept(message)
        elif kind == "response.cancel":
            ident = message.get("segment_id")
            if (set(message) != {"type", "segment_id"}
                    or not isinstance(ident, str) or not ident):
                raise ProtocolError("invalid_message", "response.cancel requires a segment_id")
            if (self.active is None or not self.started or self.cancelled.is_set()
                    or ident != self.active.segment_id):
                raise ProtocolError("invalid_state", "no matching active segment", segment_id=ident)
            self.cancelled.set()
            self.clear_pending()
        elif kind == "session.close":
            if set(message) != {"type"}:
                raise ProtocolError("invalid_message", "session.close takes no additional fields")
            if self.active is not None or self.pending:
                raise ProtocolError("invalid_state", "session.close requires an idle pipeline")
            return True
        else:
            raise ProtocolError("unsupported_event", "event is not supported by this backend")
        return False

    async def receive_next(self):
        # The idle deadline starts after the last accepted segment completes,
        # rather than timing out a long-running synthesis or cancellation drain.
        operation = asyncio.create_task(receive_message(
            self.websocket, self.cfg["max_message_bytes"],
        ))
        became_idle = asyncio.create_task(self.idle.wait())
        try:
            completed, _ = await asyncio.wait(
                (operation, became_idle), return_when=asyncio.FIRST_COMPLETED,
            )
            if operation in completed:
                return operation.result()
            try:
                return await asyncio.wait_for(
                    operation, self.cfg.get("session_idle_timeout_seconds", 3600),
                )
            except asyncio.TimeoutError as failure:
                raise ProtocolError("input_timeout", "timed out waiting for a segment",
                                    fatal=True) from failure
        finally:
            await stop_task(became_idle)
            await stop_task(operation)

    async def receive(self):
        try:
            while not self.stopping:
                try:
                    message = await self.receive_next()
                    async with self.lock:
                        if self.stopping:
                            return False
                        if await self.handle(message):
                            return True
                except ProtocolError as error:
                    if error.fatal:
                        raise
                    await self.sender.json(error_event(error))
            return False
        except (EOFError, ProtocolError):
            raise
        except Exception as failure:
            LOG.error("TTS receive failed request_id=%s error_type=%s",
                      self.request_id or "-", type(failure).__name__)
            raise ProtocolError("session_failed", "TTS session failed", fatal=True) from failure
        finally:
            self.stop()

    async def synthesize(self, segment):
        iterator = None
        output_task = None
        try:
            iterator = self.engine.synthesize_segment(
                segment.text, self.request_id, segment.segment_id,
            )
            while not self.stopping and not self.cancelled.is_set():
                output_task = asyncio.create_task(asyncio.to_thread(next_output, iterator))
                done, chunk = await asyncio.shield(output_task)
                async with self.lock:
                    if self.stopping or self.cancelled.is_set():
                        break
                    if done:
                        break
                    await self.sender.bytes(chunk)
        finally:
            # A synchronous next() cannot be preempted. Join it before close()
            # to avoid closing a generator while its GPU step is still running.
            try:
                if output_task is not None and not output_task.done():
                    await asyncio.shield(output_task)
            finally:
                if iterator is not None:
                    # The engine closes/drains only the current vendor part,
                    # without starting additional internal text parts.
                    await close_iterator(iterator)

    async def work(self):
        try:
            while not self.stopping:
                await self.ready.wait()
                async with self.lock:
                    if self.stopping:
                        return
                    segment = self.active
                    if segment is None:
                        self.ready.clear()
                        continue
                    await self.sender.json({"type": "audio.start", "segment_id": segment.segment_id})
                    self.started = True
                await self.synthesize(segment)
                async with self.lock:
                    if self.stopping:
                        return
                    kind = "response.cancelled" if self.cancelled.is_set() else "audio.done"
                    await self.sender.json({"type": kind, "segment_id": segment.segment_id})
                    self.active = None
                    self.started = False
                    self.cancelled.clear()
                    if self.pending:
                        self.active = self.pending.popleft()
                        self.pending_characters -= len(self.active.text)
                    else:
                        self.ready.clear()
                        self.idle.set()
        except ProtocolError:
            raise
        except Exception as error:
            ident = self.active.segment_id if self.active else None
            LOG.error("TTS inference failed request_id=%s segment_id=%s error_type=%s",
                      self.request_id or "-", ident or "-", type(error).__name__)
            raise ProtocolError("inference_failed", "TTS inference or cleanup failed",
                                fatal=True, segment_id=ident) from error
        finally:
            self.stop()


async def serve_session(websocket, sender, engine, cfg, request_id):
    pipeline = SegmentPipeline(websocket, sender, engine, cfg, request_id)
    receiver = asyncio.create_task(pipeline.receive())
    worker = asyncio.create_task(pipeline.work())
    error = None
    close_requested = False
    disconnected = False
    try:
        completed, _ = await asyncio.wait((receiver, worker), return_when=asyncio.FIRST_COMPLETED)
        for task in (receiver, worker):
            if task not in completed:
                continue
            try:
                result = task.result()
                if task is receiver:
                    close_requested = bool(result)
            except EOFError:
                disconnected = True
            except ProtocolError as failure:
                error = failure
    finally:
        pipeline.stop()
        await stop_task(receiver)
        if receiver.done() and not receiver.cancelled():
            failure = receiver.exception()
            if isinstance(failure, EOFError):
                disconnected = True
            elif isinstance(failure, ProtocolError):
                error = failure
        # Keep the session's engine slot until the active generator has cleaned
        # up, including after disconnect. Worker is never cancelled mid-next().
        try:
            await asyncio.shield(worker)
        except ProtocolError as failure:
            error = failure
    if disconnected:
        return
    timeout = min(cfg["output_timeout_seconds"], 5)
    if error is not None:
        if error.code != "output_timeout":
            try:
                await sender.json(error_event(error), timeout=timeout)
            except (ProtocolError, RuntimeError):
                pass
        await close_websocket(websocket, 1011, timeout, error.code)
    elif close_requested:
        await close_websocket(websocket, 1000, timeout)
