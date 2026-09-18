"""CPU tests for FIFO admission, audio ordering and cancellation cleanup."""

import asyncio
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cosyvoice300m_session import Segment, parse_segment_message, serve_session
from protocol import ProtocolError, WebSocketSender, error_event


def configuration(**overrides):
    cfg = dict(max_segment_characters=2000, max_queued_segments=8,
               max_queued_characters=4096, max_message_bytes=16384,
               output_timeout_seconds=0.2, session_idle_timeout_seconds=5)
    cfg.update(overrides)
    return cfg


class ParserTest(unittest.TestCase):
    def test_accepts_exact_complete_segment_and_preserves_text(self):
        self.assertEqual(parse_segment_message(
            {"type": "input.segment", "segment_id": "s1", "text": " 一句话。 "},
            configuration(), set()), Segment("s1", " 一句话。 "))

    def test_rejects_bad_fields_control_tokens_and_overlong_text(self):
        base = {"type": "input.segment", "segment_id": "s1", "text": "有效。"}
        cases = [({**base, "voice": "other"}, "invalid_segment"),
                 ({"type": "input.segment", "text": "有效。"}, "invalid_segment"),
                 ({**base, "segment_id": ""}, "invalid_segment"),
                 ({**base, "segment_id": 1}, "invalid_segment")]
        for text in ("", "  ", None, "含\x00控制", "<|stop|>", "<endofprompt>"):
            cases.append(({**base, "text": text}, "invalid_segment"))
        cases.append(({**base, "text": "字" * 2001}, "segment_too_long"))
        for message, code in cases:
            with self.subTest(message=message), self.assertRaises(ProtocolError) as caught:
                parse_segment_message(message, configuration(), set())
            self.assertEqual(caught.exception.code, code)

    def test_unicode_limit_and_duplicate_ids(self):
        message = {"type": "input.segment", "segment_id": "s1", "text": "🙂" * 2000}
        self.assertEqual(len(parse_segment_message(message, configuration(), set()).text), 2000)
        with self.assertRaises(ProtocolError) as caught:
            parse_segment_message(message, configuration(), {"s1"})
        self.assertEqual(error_event(caught.exception)["segment_id"], "s1")
        self.assertEqual(caught.exception.code, "duplicate_segment_id")


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.frames = []
        self.sending = False
        self.block_kind = None
        self.closed = None

    def submit(self, message):
        self.incoming.put_nowait({"type": "websocket.receive", "text": json.dumps(message)})

    async def receive(self):
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def send(self, value):
        assert not self.sending, "concurrent socket writes"
        self.sending = True
        try:
            if (self.block_kind == "bytes" and isinstance(value, bytes)
                    or isinstance(value, dict) and value["type"] == self.block_kind):
                await asyncio.Event().wait()
            await asyncio.sleep(0)
            self.frames.append(value)
            self.outgoing.put_nowait(value)
        finally:
            self.sending = False

    send_json = send
    send_bytes = send

    async def close(self, code, reason=None):
        self.closed = code


class Engine:
    def __init__(self):
        self.calls = []
        self.hold = threading.Event()
        self.waiting = threading.Event()
        self.cleaned = threading.Event()
        self.fail = False
        self.fail_cleanup = False

    def synthesize_segment(self, text, request_id, segment_id):
        self.calls.append(segment_id)
        try:
            if self.fail:
                raise RuntimeError("private-text-secret")
            yield segment_id.encode() + b"-1"
            if segment_id == "s1":
                self.waiting.set()
                if not self.hold.wait(3):
                    raise RuntimeError("test did not release inference")
            yield segment_id.encode() + b"-2"
        finally:
            self.cleaned.set()
            if self.fail_cleanup:
                raise RuntimeError("private-cleanup-secret")


class SessionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket = Socket()
        self.engine = Engine()
        self.task = None

    async def asyncTearDown(self):
        self.engine.hold.set()
        self.socket.incoming.put_nowait({"type": "websocket.disconnect"})
        if self.task:
            await asyncio.wait_for(self.task, 3)

    def start(self, **overrides):
        cfg = configuration(**overrides)
        self.task = asyncio.create_task(serve_session(
            self.socket, WebSocketSender(self.socket, cfg["output_timeout_seconds"]),
            self.engine, cfg, "request-test"))

    def segment(self, ident, text="测试文本。"):
        self.socket.submit({"type": "input.segment", "segment_id": ident, "text": text})

    async def frame(self):
        return await asyncio.wait_for(self.socket.outgoing.get(), 2)

    async def event(self, kind, ident=None):
        while True:
            value = await self.frame()
            if isinstance(value, dict) and value["type"] == kind:
                if ident is not None:
                    self.assertEqual(value.get("segment_id"), ident)
                return value

    async def active(self):
        self.segment("s1")
        await self.event("input.accepted", "s1")
        await self.event("audio.start", "s1")
        self.assertEqual(await self.frame(), b"s1-1")
        self.assertTrue(await asyncio.to_thread(self.engine.waiting.wait, 1))

    async def test_fifo_admits_later_segments_during_inference(self):
        self.start()
        await self.active()
        for ident in ("s2", "s3"):
            self.segment(ident)
            await self.event("input.accepted", ident)
        self.assertEqual(self.engine.calls, ["s1"])
        self.engine.hold.set()
        for ident in ("s1", "s2", "s3"):
            await self.event("audio.done", ident)
        self.assertEqual(self.engine.calls, ["s1", "s2", "s3"])
        for kind in ("input.accepted", "audio.start", "audio.done"):
            self.assertEqual([v["segment_id"] for v in self.socket.frames
                              if isinstance(v, dict) and v["type"] == kind], ["s1", "s2", "s3"])
        self.assertEqual([v for v in self.socket.frames if isinstance(v, bytes)],
                         [b"s1-1", b"s1-2", b"s2-1", b"s2-2", b"s3-1", b"s3-2"])

    async def test_waiting_count_excludes_active_and_rejected_id_can_retry(self):
        self.start(max_queued_segments=1)
        await self.active()
        self.segment("s2")
        await self.event("input.accepted", "s2")
        self.segment("retry")
        error = await self.event("error", "retry")
        self.assertEqual((error["code"], error["fatal"]), ("queue_full", False))
        self.engine.hold.set()
        await self.event("audio.done", "s1")
        await self.event("audio.done", "s2")
        self.segment("retry")
        await self.event("input.accepted", "retry")
        await self.event("audio.done", "retry")
        self.segment("retry")
        self.assertEqual((await self.event("error", "retry"))["code"], "duplicate_segment_id")

    async def test_waiting_character_limit_excludes_active(self):
        self.start(max_queued_characters=6)
        await self.active()
        self.segment("s2", "字" * 6)
        await self.event("input.accepted", "s2")
        self.segment("retry", "字")
        self.assertEqual((await self.event("error", "retry"))["code"], "queue_full")
        self.engine.hold.set()
        await self.event("audio.done", "s1")
        await self.event("audio.done", "s2")
        self.segment("retry", "字")
        await self.event("audio.done", "retry")

    async def test_cancel_discards_queue_and_pcm_waits_for_cleanup_and_reuses(self):
        self.start()
        await self.active()
        for ident in ("s2", "s3"):
            self.segment(ident)
            await self.event("input.accepted", ident)
        self.socket.submit({"type": "response.cancel", "segment_id": "s1"})
        # This recoverable error acts as a barrier proving cancellation was processed.
        self.socket.submit({"type": "input.done"})
        self.assertEqual((await self.event("error"))["code"], "unsupported_event")
        self.assertFalse(self.engine.cleaned.is_set())
        self.assertFalse(any(isinstance(v, dict) and v["type"] == "response.cancelled"
                             for v in self.socket.frames))
        self.engine.hold.set()
        await self.event("response.cancelled", "s1")
        self.assertTrue(self.engine.cleaned.is_set())
        self.assertEqual(self.engine.calls, ["s1"])
        self.assertNotIn(b"s1-2", self.socket.frames)
        self.segment("s2")
        self.assertEqual((await self.event("error", "s2"))["code"], "duplicate_segment_id")
        self.segment("new")
        await self.event("audio.done", "new")

    async def test_cancel_wrong_id_and_idle_cancel_preserve_work(self):
        self.start()
        self.socket.submit({"type": "response.cancel", "segment_id": "none"})
        self.assertEqual((await self.event("error", "none"))["code"], "invalid_state")
        await self.active()
        self.socket.submit({"type": "response.cancel", "segment_id": "other"})
        self.assertEqual((await self.event("error", "other"))["code"], "invalid_state")
        self.engine.hold.set()
        await self.event("audio.done", "s1")

    async def test_close_only_when_idle_and_unsupported_input_is_recoverable(self):
        self.start()
        for kind in ("input.text", "input.done"):
            self.socket.submit({"type": kind})
            self.assertEqual((await self.event("error"))["code"], "unsupported_event")
        await self.active()
        self.socket.submit({"type": "session.close"})
        self.assertEqual((await self.event("error"))["code"], "invalid_state")
        self.engine.hold.set()
        await self.event("audio.done", "s1")
        self.socket.submit({"type": "session.close"})
        await asyncio.wait_for(self.task, 1)
        self.assertEqual(self.socket.closed, 1000)

    async def test_disconnect_cleans_active_and_never_starts_pending(self):
        self.start()
        await self.active()
        self.segment("s2")
        await self.event("input.accepted", "s2")
        self.socket.incoming.put_nowait({"type": "websocket.disconnect"})
        await asyncio.sleep(0.02)
        self.engine.hold.set()
        await asyncio.wait_for(self.task, 1)
        self.assertEqual(self.engine.calls, ["s1"])
        self.assertTrue(self.engine.cleaned.is_set())
        self.assertNotIn(b"s1-2", self.socket.frames)

    async def test_inference_failure_is_safe_fatal_and_closes(self):
        self.engine.fail = True
        self.start()
        self.segment("s1")
        error = await self.event("error", "s1")
        self.assertEqual((error["code"], error["fatal"]), ("inference_failed", True))
        self.assertNotIn("private", error["message"])
        await asyncio.wait_for(self.task, 1)
        self.assertEqual(self.socket.closed, 1011)

    async def test_pcm_timeout_cleans_generator_and_closes(self):
        self.socket.block_kind = "bytes"
        self.engine.hold.set()
        self.start(output_timeout_seconds=0.02)
        self.segment("s1")
        await asyncio.wait_for(self.task, 1)
        self.assertEqual(self.socket.closed, 1011)
        self.assertTrue(self.engine.cleaned.is_set())

    async def test_acceptance_timeout_does_not_start_inference(self):
        self.socket.block_kind = "input.accepted"
        self.start(output_timeout_seconds=0.02)
        self.segment("s1")
        await asyncio.wait_for(self.task, 1)
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(self.socket.closed, 1011)

    async def test_cleanup_failure_is_fatal_instead_of_cancelled(self):
        self.start()
        await self.active()
        self.engine.fail_cleanup = True
        self.socket.submit({"type": "response.cancel", "segment_id": "s1"})
        self.socket.submit({"type": "input.done"})
        await self.event("error")
        self.engine.hold.set()
        error = await self.event("error", "s1")
        self.assertTrue(error["fatal"])
        await asyncio.wait_for(self.task, 1)
        self.assertEqual(self.socket.closed, 1011)
        self.assertFalse(any(isinstance(v, dict) and v["type"] == "response.cancelled"
                             for v in self.socket.frames))

    async def test_new_segment_during_cleanup_is_rejected_and_can_retry(self):
        self.start()
        await self.active()
        self.socket.submit({"type": "response.cancel", "segment_id": "s1"})
        self.segment("new")
        self.assertEqual((await self.event("error", "new"))["code"], "invalid_state")
        self.engine.hold.set()
        await self.event("response.cancelled", "s1")
        self.segment("new")
        await self.event("audio.done", "new")

    async def test_bad_json_and_wrong_cancel_shape_preserve_active_work(self):
        self.start()
        await self.active()
        self.socket.incoming.put_nowait({"type": "websocket.receive", "text": "{"})
        self.assertEqual((await self.event("error"))["code"], "invalid_json")
        self.socket.submit({"type": "response.cancel", "segment_id": "s1", "extra": True})
        self.assertEqual((await self.event("error"))["code"], "invalid_message")
        self.engine.hold.set()
        await self.event("audio.done", "s1")

    async def test_outer_task_cancellation_joins_active_generator(self):
        self.start()
        await self.active()
        self.segment("s2")
        await self.event("input.accepted", "s2")
        self.task.cancel()
        await asyncio.sleep(0.02)
        self.assertFalse(self.task.done())
        self.engine.hold.set()
        task, self.task = self.task, None
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.engine.cleaned.is_set())
        self.assertEqual(self.engine.calls, ["s1"])

    async def test_unexpected_receive_failure_closes_and_cleans_pending_work(self):
        self.start()
        await self.active()
        self.segment("s2")
        await self.event("input.accepted", "s2")
        self.socket.incoming.put_nowait(RuntimeError("private-transport-error"))
        self.engine.hold.set()
        error = await self.event("error")
        self.assertTrue(error["fatal"])
        await asyncio.wait_for(self.task, 1)
        self.assertEqual(self.socket.closed, 1011)
        self.assertEqual(self.engine.calls, ["s1"])

    async def test_idle_timeout_does_not_abort_active_inference(self):
        self.start(session_idle_timeout_seconds=0.03)
        await self.active()
        await asyncio.sleep(0.06)
        self.assertFalse(self.task.done())
        self.engine.hold.set()
        await self.event("audio.done", "s1")
        error = await self.event("error")
        self.assertEqual((error["code"], error["fatal"]), ("input_timeout", True))
        await asyncio.wait_for(self.task, 1)
        self.assertEqual(self.socket.closed, 1011)
