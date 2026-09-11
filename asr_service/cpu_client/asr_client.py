"""CPU-backend client for the authenticated realtime ASR WebSocket."""

import json
from pathlib import Path
import ssl

from websockets.asyncio.client import connect


class RealtimeAsrSession:
    def __init__(self, connection):
        self._connection = connection
        self._started = False
        self._stopping = False

    async def start(self, *, language=None, hotwords=None):
        if self._started:
            raise RuntimeError("ASR session is already started")
        await self._connection.send("START")
        event = await self.receive()
        if event != {"event": "started"}:
            raise RuntimeError(f"unexpected ASR start response: {event!r}")
        self._started = True
        if language:
            await self._connection.send("LANGUAGE:" + language)
            await self.receive()
        if hotwords:
            if any("," in word or "\n" in word for word in hotwords):
                raise ValueError("hotwords cannot contain commas or newlines")
            await self._connection.send("HOTWORDS:" + ",".join(hotwords))
            await self.receive()
        return event

    async def send_pcm(self, pcm16le):
        if not self._started or self._stopping:
            raise RuntimeError("start the session before sending audio")
        if not isinstance(pcm16le, bytes) or not pcm16le or len(pcm16le) % 2:
            raise ValueError("audio must be non-empty little-endian signed 16-bit PCM")
        await self._connection.send(pcm16le)

    async def stop(self):
        if not self._started or self._stopping:
            raise RuntimeError("ASR session is not active")
        self._stopping = True
        await self._connection.send("STOP")

    async def receive(self):
        message = await self._connection.recv()
        if not isinstance(message, str):
            raise RuntimeError("ASR server returned an unexpected binary message")
        event = json.loads(message)
        if not isinstance(event, dict):
            raise RuntimeError("ASR server returned a non-object JSON message")
        return event


class RealtimeAsrClient:
    def __init__(self, url, api_key, ca_file, *, open_timeout_seconds=10):
        if not url.startswith("wss://"):
            raise ValueError("ASR URL must use wss://")
        if not api_key:
            raise ValueError("api_key is required")
        self.url = url
        self.api_key = api_key
        self.context = ssl.create_default_context(cafile=str(Path(ca_file)))
        self.open_timeout_seconds = open_timeout_seconds

    def connect(self):
        return _SessionContext(self)


class _SessionContext:
    def __init__(self, client):
        self.client = client
        self.manager = None

    async def __aenter__(self):
        self.manager = connect(
            self.client.url, ssl=self.client.context,
            additional_headers={"Authorization": "Bearer " + self.client.api_key},
            open_timeout=self.client.open_timeout_seconds, compression=None, proxy=None,
        )
        connection = await self.manager.__aenter__()
        return RealtimeAsrSession(connection)

    async def __aexit__(self, exc_type, exc_value, traceback):
        return await self.manager.__aexit__(exc_type, exc_value, traceback)
