#!/usr/bin/env python3
"""Stream one TTS request to a WAV file; runnable from any directory on a CPU host."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from tts_client import TtsClient, write_wav_header


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.gateway.example.json"))
    parser.add_argument("--text", required=True)
    parser.add_argument("--voice")
    parser.add_argument("--instructions")
    parser.add_argument("--output", type=Path, default=Path("tts-output.wav"))
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    ca = os.getenv("GPU_CA_FILE", cfg.get("ca_file"))
    if ca:
        ca = args.config.resolve().parent / ca
    voice = args.voice or cfg["voice"]
    instructions = args.instructions if args.instructions is not None else cfg.get("instructions")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as pcm:
        size = 0
        with TtsClient(os.getenv("TTS_BASE_URL", cfg["base_url"]),
                       api_key=os.getenv("GPU_API_KEY", ""), model=cfg["model"],
                       timeout_seconds=cfg["timeout_seconds"], ca_file=ca) as client:
            with client.stream(args.text, voice=voice, instructions=instructions) as chunks:
                for chunk in chunks:
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
                      "sample_rate_hz": 22050, "channels": 1}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("Request cancelled", file=sys.stderr)
        raise SystemExit(130)

