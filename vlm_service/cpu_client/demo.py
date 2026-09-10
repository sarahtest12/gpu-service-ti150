#!/usr/bin/env python3
"""Run image/text requests from any directory, including CPU-only hosts."""

import argparse
import json
import os
from pathlib import Path
import sys

from client import VlmClient, image_part


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.example.json"))
    parser.add_argument("--image", action="append", type=Path, default=[])
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--stream", action="store_true", help="print answer text as each chunk arrives")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    if not args.prompt.strip():
        raise ValueError("prompt cannot be empty")
    if len(args.image) > 2:
        raise ValueError("current server configuration accepts at most two images")
    content = [image_part(path) for path in args.image]
    content.append({"type": "text", "text": args.prompt})
    ca_file = os.getenv("GPU_CA_FILE", cfg.get("ca_file"))
    if ca_file:
        ca_file = args.config.resolve().parent / ca_file
    with VlmClient(
        os.getenv("VLM_BASE_URL", cfg["base_url"]), api_key=os.getenv("GPU_API_KEY", os.getenv("VLM_API_KEY", "")),
        model=cfg["model"], timeout_seconds=cfg["timeout_seconds"],
        ca_file=ca_file,
    ) as client:
        messages = [{"role": "user", "content": content}]
        if args.stream:
            with client.stream_chat(messages, max_tokens=cfg["max_tokens"], thinking=cfg["thinking"]) as chunks:
                for chunk in chunks:
                    for choice in chunk.get("choices", []):
                        text = choice.get("delta", {}).get("content")
                        if text:
                            print(text, end="", flush=True)
            print()
            return 0
        response = client.chat(messages, max_tokens=cfg["max_tokens"], thinking=cfg["thinking"])
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\nRequest cancelled", file=sys.stderr)
        raise SystemExit(130)
