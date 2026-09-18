#!/usr/bin/env python3
"""Validate and run the fixed CosyVoice-300M-SFT CoreX service."""

import argparse
import hashlib
from importlib.metadata import distributions, version
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
VENV_SITE = ROOT / ".venv/lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
COREX = Path("/usr/local/corex")
LOCK_FILES = (ROOT / "requirements-build.lock", ROOT / "requirements.lock")
if str(VENV_SITE) in sys.path:
    sys.path.remove(str(VENV_SITE))
sys.path.insert(0, str(VENV_SITE))

EXPECTED = {
    "torch": "2.7.1+corex.4.4.0",
    "torchaudio": "2.7.1+corex.4.4.0",
    "onnxruntime": "1.17.3",
    "HyperPyYAML": "1.2.3",
    "transformers": "4.51.3",
    "x-transformers": "2.11.24",
    "diffusers": "0.29.0",
    "openai-whisper": "20231117",
    "inflect": "7.3.1",
    "omegaconf": "2.3.0",
    "ruamel.yaml": "0.17.40",
    "hydra-core": "1.3.2",
    "lightning": "2.2.4",
    "gdown": "5.1.0",
    "wget": "3.2",
    "pyworld": "0.3.4",
    "huggingface-hub": "0.36.2",
    "tokenizers": "0.21.4",
    "einops": "0.8.2",
    "fsspec": "2024.12.0",
    "packaging": "24.2",
    "websockets": "15.0.1",
}
REQUIRED_MODEL_FILES = (
    "llm.pt", "flow.pt", "hift.pt", "llm.text_encoder.fp16.zip",
    "llm.llm.fp16.zip", "flow.encoder.fp32.zip", "cosyvoice.yaml", "spk2info.pt",
)
SOURCE_FILES = {
    "cosyvoice/cli/cosyvoice.py", "cosyvoice/cli/frontend.py", "cosyvoice/cli/model.py",
}
CHECKPOINT_SPEAKERS = {
    "中文女": "Chinese", "中文男": "Chinese", "粤语女": "Cantonese",
    "日语男": "Japanese", "英文女": "English", "英文男": "English",
    "韩语女": "Korean",
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def positive(cfg, key, maximum, *, allow_zero=False):
    value = cfg[key]
    if (type(value) is not int or (value < 0 if allow_zero else value <= 0)
            or value > maximum):
        raise ValueError(f"invalid {key}")


def validate_checksum_map(cfg, key, expected_names):
    values = cfg.get(key)
    if not isinstance(values, dict) or set(values) != set(expected_names):
        raise ValueError(f"invalid {key}")
    for name, digest in values.items():
        if (Path(name).is_absolute() or ".." in Path(name).parts
                or not re.fullmatch(r"[0-9a-f]{64}", digest or "")):
            raise ValueError(f"invalid {key}")


def resolve_paths(cfg, path):
    base = Path(path).resolve().parent
    for key in ("model", "source"):
        value = cfg.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"invalid {key}")
        candidate = Path(value)
        cfg[key] = str(candidate if candidate.is_absolute() else (base / candidate).resolve())


def config(*, require_artifacts=True):
    cfg = json.loads(CONFIG.read_text())
    resolve_paths(cfg, CONFIG)
    if cfg.get("backend") != "cosyvoice300msft":
        raise ValueError("this service supports only cosyvoice300msft")
    if not ipaddress.ip_address(cfg["host"]).is_loopback:
        raise ValueError("TTS must listen on loopback; expose it only through the gateway")
    for key, maximum, allow_zero in (
        ("port", 65535, False), ("device", 64, True),
        ("sample_rate_hz", 192000, False), ("max_segment_characters", 10000, False),
        ("max_queued_segments", 1024, False), ("max_queued_characters", 100000, False),
        ("model_segment_units", 10000, False), ("max_message_bytes", 1024 * 1024, False),
        ("session_idle_timeout_seconds", 86400, False),
        ("output_timeout_seconds", 300, False), ("max_concurrency", 4, False),
        ("minimum_free_memory_mb", 32768, False), ("random_seed", 2**32 - 1, True),
    ):
        positive(cfg, key, maximum, allow_zero=allow_zero)
    if (cfg["model_name"] != "cosyvoice-300m-sft"
            or cfg["device"] != 0 or cfg["sample_rate_hz"] != 22050
            or cfg["voice_id"] != "中文女"
            or cfg.get("checkpoint_speakers") != CHECKPOINT_SPEAKERS
            or "voices" in cfg
            or cfg.get("inference_mode") != "sft"
            or "instruction" in cfg
            or cfg["random_seed"] != 42
            or cfg.get("number_reading") != "chinese"
            or cfg["max_segment_characters"] != 2000
            or cfg["max_queued_segments"] != 8
            or cfg["max_queued_characters"] != 4096
            or cfg["model_segment_units"] != 80 or cfg["max_concurrency"] != 1
            or (cfg["load_jit"], cfg["load_onnx"], cfg["fp16"]) != (True, False, True)):
        raise ValueError("unexpected CosyVoice-300M-SFT deployment boundary")
    validate_checksum_map(cfg, "source_checksums", SOURCE_FILES)
    validate_checksum_map(cfg, "model_checksums", {"cosyvoice.yaml", "spk2info.pt"})
    model, source = Path(cfg["model"]), Path(cfg["source"])
    if not require_artifacts:
        return cfg
    missing = [name for name in REQUIRED_MODEL_FILES if not (model / name).is_file()]
    if missing:
        raise ValueError("CosyVoice-300M checkpoint is incomplete: " + ", ".join(missing))
    for name, expected in cfg["source_checksums"].items():
        if not (source / name).is_file() or sha256(source / name) != expected:
            raise ValueError(f"pinned CosyVoice-300M source mismatch: {name}")
    for name, expected in cfg["model_checksums"].items():
        if not (model / name).is_file() or sha256(model / name) != expected:
            raise ValueError(f"CosyVoice-300M checkpoint mismatch: {name}")
    return cfg


def canonical_package_name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def locked_packages():
    packages = {}
    for lock_path in LOCK_FILES:
        for line in lock_path.read_text().splitlines():
            match = re.match(r"([A-Za-z0-9_.-]+)==([^ \\]+)", line)
            if match:
                packages[canonical_package_name(match.group(1))] = match.group(2)
    if not packages:
        raise ValueError("Python package locks are empty")
    return packages


def validate_local_packages():
    expected = locked_packages()
    installed = {}
    for package in distributions(path=[str(VENV_SITE)]):
        name = canonical_package_name(package.metadata["Name"])
        if name in installed:
            raise ValueError(f"duplicate Python distribution: {name}")
        installed[name] = package.version
    actual = set(installed) - {"pip", "setuptools"}
    if actual != set(expected):
        raise ValueError(
            "service-local package set mismatch: "
            f"missing={sorted(set(expected) - actual)}, extra={sorted(actual - set(expected))}"
        )
    for name, expected_version in expected.items():
        if installed[name] != expected_version:
            raise ValueError(
                f"{name} version mismatch: expected {expected_version}, got {installed[name]}"
            )


def environment(cfg):
    source = Path(cfg["source"])
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.update({
        "PYTHONPATH": ":".join((str(source), str(source / "third_party/Matcha-TTS"),
                                str(VENV_SITE), str(COREX / "lib64/python3/dist-packages"))),
        "PATH": f"{ROOT}/.venv/bin:{COREX}/bin:/usr/local/bin:/usr/bin:/bin",
        "LD_LIBRARY_PATH": f"{COREX}/lib64:/usr/local/lib:/usr/local/openmpi/lib",
        "VIRTUAL_ENV": str(ROOT / ".venv"),
        "CUDA_VISIBLE_DEVICES": str(cfg["device"]),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false", "OMP_NUM_THREADS": "4",
    })
    return env


def port_in_use(host, port):
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as probe:
        probe.settimeout(1)
        return probe.connect_ex((host, port)) == 0


def init_key():
    KEY.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not KEY.exists():
        fd = os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(secrets.token_urlsafe(32) + "\n")
    if KEY.stat().st_mode & 0o077:
        raise ValueError(f"TTS internal credential must have mode 0600: {KEY}")
    if not re.fullmatch(r"[A-Za-z0-9_~.\-]{24,256}", KEY.read_text().strip()):
        raise ValueError("invalid TTS internal credential")


def check(cfg):
    if Path(sys.executable).resolve() != PYTHON.resolve():
        raise ValueError(f"run this command with {PYTHON}")
    validate_local_packages()
    for package, expected in EXPECTED.items():
        actual = version(package)
        if actual != expected:
            raise ValueError(f"{package} version mismatch: expected {expected}, got {actual}")
    probe = f"""
import onnxruntime
import torch
from cosyvoice.cli.cosyvoice import CosyVoice
assert '/usr/local/corex' in torch.__file__
assert torch.cuda.is_available(), 'CoreX CUDA is unavailable'
assert torch.cuda.device_count() == 1, 'CUDA_VISIBLE_DEVICES must expose exactly one GPU'
free_bytes, total_bytes = torch.cuda.mem_get_info()
assert free_bytes >= {cfg['minimum_free_memory_mb']} * 1024 * 1024, 'insufficient free GPU memory'
value = torch.ones(1, device='cuda', dtype=torch.float16)
assert value.is_cuda and value.dtype == torch.float16
providers = onnxruntime.get_available_providers()
assert 'CPUExecutionProvider' in providers and 'CUDAExecutionProvider' not in providers
print('CosyVoice-300M-SFT imports and CoreX runtime: PASS')
"""
    subprocess.run([str(PYTHON), "-c", probe], cwd=ROOT, env=environment(cfg), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "init-key", "run"))
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == "init-key":
        init_key()
        print(f"TTS 300M SFT internal credential ready: {KEY} (value not displayed)")
        return
    cfg = config()
    if args.action == "check":
        check(cfg)
        print("CosyVoice-300M-SFT environment, source and checkpoint: PASS")
        return
    check(cfg)
    if port_in_use(cfg["host"], cfg["port"]):
        raise RuntimeError("TTS port is already in use")
    init_key()
    command = [str(PYTHON), "scripts/server.py", "--config", str(CONFIG),
               "--key-file", str(KEY)]
    os.execvpe(command[0], command, environment(cfg))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
