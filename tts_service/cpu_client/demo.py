#!/usr/bin/env python3
"""Stream one TTS utterance over a reusable WebSocket and save it as WAV."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from tts_client import TtsRealtimeClient, write_wav_header


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=Path(__file__).with_name("config.gateway.example.json"))
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", type=Path, default=Path("tts-output.wav"))
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    ca = os.getenv("GPU_CA_FILE", cfg.get("ca_file"))
    if ca:
        ca = args.config.resolve().parent / ca

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as pcm:
        size = 0
        with TtsRealtimeClient(
            os.getenv("TTS_BASE_URL", cfg["base_url"]),
            api_key=os.getenv("GPU_API_KEY", ""),
            timeout_seconds=cfg["timeout_seconds"],
            ca_file=ca,
        ) as client:
            for chunk in client.synthesize([args.text]):
                pcm.write(chunk)
                size += len(chunk)
        if size == 0 or size % 2:
            raise RuntimeError("TTS returned empty or invalid PCM audio")
        pcm.seek(0)
        with args.output.open("wb") as output:
            write_wav_header(output, size)
            while chunk := pcm.read(1024 * 1024):
                output.write(chunk)
    print(json.dumps({"output": str(args.output), "pcm_bytes": size,
                      "sample_rate_hz": 24000, "channels": 1}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("Request cancelled", file=sys.stderr)
        raise SystemExit(130)
