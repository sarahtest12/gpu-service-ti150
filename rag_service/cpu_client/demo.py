#!/usr/bin/env python3
"""Encode one or more texts; runnable from any directory on a CPU host."""

import argparse
import json
import os
from pathlib import Path
import sys

from rag_client import RagClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.gateway.example.json"))
    parser.add_argument("--text", action="append", required=True)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    ca = os.getenv("GPU_CA_FILE", cfg.get("ca_file"))
    if ca:
        ca = args.config.resolve().parent / ca
    with RagClient(os.getenv("RAG_BASE_URL", cfg["base_url"]), api_key=os.getenv("GPU_API_KEY", ""),
                   model=cfg["model"], timeout_seconds=cfg["timeout_seconds"], ca_file=ca) as client:
        result = client.embed(args.text)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("Request cancelled", file=sys.stderr)
        raise SystemExit(130)
