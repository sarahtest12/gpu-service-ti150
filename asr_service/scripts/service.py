#!/usr/bin/env python3
"""Validate and run Fun-ASR-Nano-2512 realtime ASR with the vendor CoreX vLLM."""

import argparse
import hashlib
from importlib.metadata import version
import ipaddress
import json
import math
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
SOURCE = ROOT / "runtime/FunASR"
CACHE = ROOT / "runtime/modelscope_cache"
PYTHON = ROOT / ".venv/bin/python"
COREX = Path("/usr/local/corex")
EXPECTED = {
    "funasr": "1.4.14",
    "vllm": "0.17.0+corex.4.5.0.rc.11.20260701",
    "torch": "2.7.1+corex.4.4.0",
    "transformers": "4.57.6",
    "websockets": "16.0",
}


def positive_number(cfg, key, *, integer=False, maximum=None, allow_zero=False):
    value = cfg[key]
    lower_ok = value >= 0 if allow_zero else value > 0
    if type(value) not in ((int,) if integer else (int, float)) or not lower_ok:
        raise ValueError(f"invalid {key}")
    if not integer and not math.isfinite(value):
        raise ValueError(f"invalid {key}")
    if maximum is not None and value > maximum:
        raise ValueError(f"invalid {key}")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def config():
    cfg = json.loads(CONFIG.read_text())
    if not ipaddress.ip_address(cfg["host"]).is_loopback:
        raise ValueError("ASR must listen on loopback; expose it only through the gateway")
    positive_number(cfg, "port", integer=True, maximum=65535)
    positive_number(cfg, "device", integer=True, allow_zero=True)
    positive_number(cfg, "tensor_parallel_size", integer=True)
    positive_number(cfg, "max_model_len", integer=True, maximum=2048)
    positive_number(cfg, "decode_max_batch_size", integer=True, maximum=64)
    positive_number(cfg, "vad_ncpu", integer=True, maximum=32)
    positive_number(cfg, "max_message_bytes", integer=True, maximum=10 * 1024 * 1024)
    for name in ("gpu_memory_utilization", "decode_interval_seconds",
                 "decode_batch_wait_ms", "partial_window_seconds",
                 "ping_interval_seconds", "close_timeout_seconds"):
        positive_number(cfg, name)
    positive_number(cfg, "ping_timeout_seconds", allow_zero=True)
    if not 0 < cfg["gpu_memory_utilization"] <= 1:
        raise ValueError("gpu_memory_utilization must be in (0, 1]")
    if cfg["dtype"] != "bf16" or cfg["endpoint_mode"] != "server":
        raise ValueError("this deployment uses BF16 and server-side streaming VAD")
    if cfg["vad_device"] != "cpu" or cfg["language"] not in ("中文", "English", "日本語", None):
        raise ValueError("unsupported VAD device or default language")
    if type(cfg["enforce_eager"]) is not bool:
        raise ValueError("invalid enforce_eager")
    if not re.fullmatch(r"[0-9a-f]{40}", cfg["funasr_revision"]):
        raise ValueError("invalid pinned FunASR revision")
    if not re.fullmatch(r"[0-9a-f]{64}", cfg["model_sha256"]):
        raise ValueError("invalid model SHA-256")

    model = Path(cfg["model"])
    if not model.is_absolute() or not model.is_dir():
        raise ValueError("model must be an existing absolute directory")
    required = ("model.pt", "config.yaml", "multilingual.tiktoken", "Qwen3-0.6B/config.json")
    missing = [name for name in required if not (model / name).is_file()]
    if missing:
        raise ValueError("Fun-ASR-Nano model is incomplete: " + ", ".join(missing))
    if sha256(model / "model.pt") != cfg["model_sha256"]:
        raise ValueError("Fun-ASR-Nano model.pt SHA-256 mismatch")

    if not (SOURCE / ".git").exists():
        raise ValueError("pinned FunASR source is missing; run asr_service/scripts/bootstrap.sh")
    revision = subprocess.run(["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.strip()
    if revision != cfg["funasr_revision"]:
        raise ValueError(f"FunASR source revision mismatch: {revision}")
    vad = CACHE / "models/iic--speech_fsmn_vad_zh-cn-16k-common-pytorch/snapshots/master"
    if not (vad / "model.pt").is_file() or not (vad / "config.yaml").is_file():
        raise ValueError("streaming VAD model is missing; run asr_service/scripts/bootstrap.sh")
    return cfg


def check(cfg):
    if Path(sys.executable).resolve() != PYTHON.resolve():
        raise ValueError(f"run this command with {PYTHON}")
    for package, expected in EXPECTED.items():
        actual = version(package)
        if actual != expected:
            raise ValueError(f"{package} version mismatch: expected {expected}, got {actual}")
    print("ASR environment and pinned model: PASS")
    print(f"FunASR source revision: {cfg['funasr_revision']}")


def environment(cfg):
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.update({
        "PYTHONPATH": str(COREX / "lib64/python3/dist-packages"),
        "PATH": f"{ROOT}/.venv/bin:{COREX}/bin:/usr/local/bin:/usr/bin:/bin",
        "LD_LIBRARY_PATH": f"{COREX}/lib64:/usr/local/lib:/usr/local/openmpi/lib",
        "VIRTUAL_ENV": str(ROOT / ".venv"),
        "CUDA_VISIBLE_DEVICES": str(cfg["device"]),
        "VLLM_ENFORCE_CUDA_GRAPH": "0",
        "VLLM_WORKER_MULTIPROC_METHOD": "spawn",
        "VLLM_NO_USAGE_STATS": "1", "VLLM_DO_NOT_TRACK": "1",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "MODELSCOPE_CACHE": str(CACHE),
        "TOKENIZERS_PARALLELISM": "false", "OMP_NUM_THREADS": "4",
    })
    return env


def init_key():
    KEY.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not KEY.exists():
        fd = os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(secrets.token_urlsafe(32) + "\n")
    if KEY.stat().st_mode & 0o077:
        raise ValueError(f"ASR internal credential must have mode 0600: {KEY}")
    token = KEY.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_~.\-]{24,256}", token):
        raise ValueError("invalid ASR internal credential")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "init-key", "run"))
    args = parser.parse_args()
    os.umask(0o077)
    cfg = config()
    if args.action == "check":
        check(cfg)
        return
    if args.action == "init-key":
        init_key()
        print(f"ASR internal credential ready: {KEY} (value not displayed)")
        return

    check(cfg)
    with socket.socket(socket.AF_INET6 if ":" in cfg["host"] else socket.AF_INET) as probe:
        probe.settimeout(1)
        if probe.connect_ex((cfg["host"], cfg["port"])) == 0:
            raise RuntimeError("ASR port is already in use")
    init_key()
    command = [str(PYTHON), "scripts/realtime_server.py", "--config", str(CONFIG),
               "--key-file", str(KEY)]
    os.execvpe(command[0], command, environment(cfg))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
