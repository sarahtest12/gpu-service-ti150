#!/usr/bin/env python3
"""Replay a 16 kHz mono PCM WAV through the realtime endpoint for integration testing."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import wave

from asr_client import RealtimeAsrClient


async def run(args):
    config = json.loads(args.config.read_text())
    key = os.environ.get("GPU_API_KEY")
    if not key:
        raise RuntimeError("set GPU_API_KEY")
    ca_file = Path(os.environ.get("GPU_CA_FILE", config["ca_file"]))
    if not ca_file.is_absolute():
        ca_file = (args.config.parent / ca_file).resolve()

    with wave.open(str(args.wav), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
            raise ValueError("WAV must be mono, signed 16-bit PCM, 16 kHz")
        pcm = source.readframes(source.getnframes())

    client = RealtimeAsrClient(config["url"], key, ca_file)
    async with client.connect() as session:
        started = await session.start(language=args.language)
        print(json.dumps(started, ensure_ascii=False), flush=True)

        async def receive():
            while True:
                event = await session.receive()
                print(json.dumps(event, ensure_ascii=False), flush=True)
                if event.get("event") == "stopped":
                    return

        receiver = asyncio.create_task(receive())
        bytes_per_frame = 16000 * 2 * args.frame_ms // 1000
        for offset in range(0, len(pcm), bytes_per_frame):
            await session.send_pcm(pcm[offset:offset + bytes_per_frame])
            await asyncio.sleep(args.frame_ms / 1000)
        await session.stop()
        await receiver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config.gateway.json"))
    parser.add_argument("--language", default="中文")
    parser.add_argument("--frame-ms", type=int, default=100, choices=(20, 40, 100, 200))
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

