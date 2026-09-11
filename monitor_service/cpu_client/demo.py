#!/usr/bin/env python3
"""Read one monitoring snapshot without printing the shared credential."""

import argparse
import json
import os
from pathlib import Path

from monitor_client import MonitorClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    config_path = args.config.resolve()
    cfg = json.loads(config_path.read_text())
    ca_file = cfg.get("ca_file")
    if ca_file is not None:
        ca_file = (config_path.parent / ca_file).resolve()
    with MonitorClient(
        cfg["base_url"], api_key=os.environ.get("GPU_API_KEY", ""),
        timeout_seconds=cfg.get("timeout_seconds", 12), ca_file=ca_file,
    ) as client:
        print(json.dumps(client.overview(refresh=args.refresh), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
