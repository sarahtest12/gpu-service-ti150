#!/usr/bin/env python3
"""Validate, initialize and run the monitoring snapshot service."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/server.json"
KEY = ROOT / "runtime/api_key"


def config():
    cfg = json.loads(CONFIG.read_text())
    if not ipaddress.ip_address(cfg["host"]).is_loopback:
        raise ValueError("monitor must listen on loopback")
    if type(cfg["port"]) is not int or not 1 <= cfg["port"] <= 65535:
        raise ValueError("invalid monitor port")
    for name in ("sample_interval_seconds", "window_seconds", "stale_after_seconds",
                 "upstream_timeout_seconds"):
        if type(cfg[name]) not in (int, float) or cfg[name] <= 0:
            raise ValueError(f"invalid {name}")
    if cfg["sample_interval_seconds"] != 5 or cfg["window_seconds"] != 60:
        raise ValueError("the reviewed contract requires 5-second samples and a 60-second window")
    if cfg["stale_after_seconds"] < cfg["sample_interval_seconds"] * 2:
        raise ValueError("stale_after_seconds is too short for scheduled sampling")
    gateway = (CONFIG.parent / cfg["gateway_config"]).resolve()
    if not gateway.is_file():
        raise ValueError("gateway config is missing")
    if not Path(cfg["ixsmi"]).is_file() or not os.access(cfg["ixsmi"], os.X_OK):
        raise ValueError("ixsmi is missing")
    return cfg


def init_key():
    KEY.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not KEY.exists():
        fd = os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(secrets.token_urlsafe(32) + "\n")
    if KEY.stat().st_mode & 0o077:
        raise ValueError("monitor internal credential must have mode 0600")
    if not re.fullmatch(r"[A-Za-z0-9_~.\-]{24,256}", KEY.read_text().strip()):
        raise ValueError("invalid monitor internal credential")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "init-key", "run"))
    args = parser.parse_args()
    os.umask(0o077)
    cfg = config()
    if args.action == "check":
        init_key()
        print("monitor configuration: PASS")
        return
    if args.action == "init-key":
        init_key()
        print(f"monitor internal credential ready: {KEY} (value not displayed)")
        return
    init_key()
    with socket.socket(socket.AF_INET6 if ":" in cfg["host"] else socket.AF_INET) as probe:
        probe.settimeout(1)
        if probe.connect_ex((cfg["host"], cfg["port"])) == 0:
            raise RuntimeError("monitor port is already in use")
    command = [sys.executable, "scripts/server.py", "--config", str(CONFIG), "--key-file", str(KEY)]
    os.execv(command[0], command)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
