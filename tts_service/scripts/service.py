#!/usr/bin/env python3
"""Validate and run the CosyVoice-300M-Instruct service on the vendor CoreX stack."""

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
PYTHON = ROOT / ".venv/bin/python"
COREX = Path("/usr/local/corex")
EXPECTED = {
    "torch": "2.7.1+corex.4.4.0",
    "torchaudio": "2.7.1+corex.4.4.0",
    "onnxruntime": "1.17.3",
    "HyperPyYAML": "1.2.2",
    "openai-whisper": "20231117",
    "inflect": "7.3.1",
    "WeTextProcessing": "1.0.3",
    "omegaconf": "2.3.0",
    "ruamel.yaml": "0.17.40",
    "hydra-core": "1.3.2",
    "lightning": "2.2.4",
    "gdown": "5.1.0",
    "wget": "3.2",
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def positive(cfg, key, *, integer=False, maximum=None, allow_zero=False):
    value = cfg[key]
    valid_type = type(value) is int if integer else type(value) in (int, float)
    lower_ok = value >= 0 if allow_zero else value > 0
    if not valid_type or not lower_ok or (not integer and not math.isfinite(value)):
        raise ValueError(f"invalid {key}")
    if maximum is not None and value > maximum:
        raise ValueError(f"invalid {key}")


def config():
    cfg = json.loads(CONFIG.read_text())
    if not ipaddress.ip_address(cfg["host"]).is_loopback:
        raise ValueError("TTS must listen on loopback; expose it only through the gateway")
    positive(cfg, "port", integer=True, maximum=65535)
    positive(cfg, "device", integer=True, maximum=64, allow_zero=True)
    positive(cfg, "sample_rate_hz", integer=True, maximum=192000)
    positive(cfg, "max_input_characters", integer=True, maximum=10000)
    positive(cfg, "max_instruction_characters", integer=True, maximum=2000)
    positive(cfg, "max_concurrency", integer=True, maximum=4)
    if cfg["device"] != 0 or cfg["sample_rate_hz"] != 22050 or cfg["max_concurrency"] != 1:
        raise ValueError("this deployment is validated for GPU 0, 22050 Hz and one active request")
    if cfg["model_name"] != "cosyvoice-300m-instruct":
        raise ValueError("unexpected public model name")
    if (cfg["load_jit"], cfg["load_onnx"], cfg["fp16"]) != (True, False, True):
        raise ValueError("this deployment uses FP16 TorchScript and the PyTorch flow decoder")
    if not isinstance(cfg["default_instruction"], str) or not cfg["default_instruction"].strip():
        raise ValueError("default_instruction must be non-empty")
    expected_voices = {"中文女", "中文男", "粤语女", "日语男", "英文女", "英文男", "韩语女"}
    if set(cfg["voices"]) != expected_voices or not all(isinstance(v, str) for v in cfg["voices"].values()):
        raise ValueError("configured voice allowlist does not match CosyVoice-300M-Instruct")

    model, source = Path(cfg["model"]), Path(cfg["source"])
    if not model.is_absolute() or not model.is_dir():
        raise ValueError("model must be an existing absolute directory")
    if not source.is_absolute() or not (source / "cosyvoice").is_dir():
        raise ValueError("vendor CosyVoice source is missing")
    required_model = ("llm.pt", "flow.pt", "hift.pt", "llm.text_encoder.fp16.zip",
                      "llm.llm.fp16.zip", "flow.encoder.fp32.zip", "cosyvoice.yaml", "spk2info.pt")
    missing = [name for name in required_model if not (model / name).is_file()]
    if missing:
        raise ValueError("CosyVoice checkpoint is incomplete: " + ", ".join(missing))
    if not (source / "third_party/Matcha-TTS/matcha").is_dir():
        raise ValueError("CosyVoice Matcha-TTS submodule is missing")
    for name, expected in cfg["source_checksums"].items():
        path = source / name
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"vendor CosyVoice source mismatch: {name}")
    for name, expected in cfg["model_checksums"].items():
        path = model / name
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"CosyVoice checkpoint metadata mismatch: {name}")
    return cfg


def environment(cfg):
    source = Path(cfg["source"])
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.update({
        "PYTHONPATH": ":".join((str(source), str(source / "third_party/Matcha-TTS"),
                                str(COREX / "lib64/python3/dist-packages"))),
        "PATH": f"{ROOT}/.venv/bin:{COREX}/bin:/usr/local/bin:/usr/bin:/bin",
        "LD_LIBRARY_PATH": f"{COREX}/lib64:/usr/local/lib:/usr/local/openmpi/lib",
        "VIRTUAL_ENV": str(ROOT / ".venv"),
        "CUDA_VISIBLE_DEVICES": str(cfg["device"]),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
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
        raise ValueError(f"TTS internal credential must have mode 0600: {KEY}")
    token = KEY.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_~.\-]{24,256}", token):
        raise ValueError("invalid TTS internal credential")


def check(cfg):
    if Path(sys.executable).resolve() != PYTHON.resolve():
        raise ValueError(f"run this command with {PYTHON}")
    for package, expected in EXPECTED.items():
        actual = version(package)
        if actual != expected:
            raise ValueError(f"{package} version mismatch: expected {expected}, got {actual}")
    probe = """
import onnxruntime
import torch
from cosyvoice.cli.cosyvoice import CosyVoice
assert '/usr/local/corex' in torch.__file__
assert 'CPUExecutionProvider' in onnxruntime.get_available_providers()
print('CosyVoice imports and CoreX runtime: PASS')
"""
    subprocess.run([str(PYTHON), "-c", probe], cwd=ROOT, env=environment(cfg), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "init-key", "run"))
    args = parser.parse_args()
    os.umask(0o077)
    cfg = config()
    if args.action == "check":
        check(cfg)
        print("TTS environment and pinned model: PASS")
        return
    if args.action == "init-key":
        init_key()
        print(f"TTS internal credential ready: {KEY} (value not displayed)")
        return
    check(cfg)
    with socket.socket(socket.AF_INET6 if ":" in cfg["host"] else socket.AF_INET) as probe:
        probe.settimeout(1)
        if probe.connect_ex((cfg["host"], cfg["port"])) == 0:
            raise RuntimeError("TTS port is already in use")
    init_key()
    command = [str(PYTHON), "scripts/server.py", "--config", str(CONFIG), "--key-file", str(KEY)]
    os.execvpe(command[0], command, environment(cfg))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
