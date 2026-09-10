#!/usr/bin/env python3
"""Validate and run the BGE-M3 engine; gateway/service.py owns its lifecycle."""

import argparse
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
KEY = ROOT / "runtime/api_key"
PYTHON = ROOT / ".venv/bin/python"
COREX = Path("/usr/local/corex")
EXPECTED = {
    "vllm": "0.17.0+corex.4.5.0.rc.11.20260701",
    "ixformer": "0.7.0+corex.4.5.0.rc.11.20260701",
    "torch": "2.7.1+corex.4.4.0",
    "transformers": "4.57.6",
}


def config():
    cfg = json.loads((ROOT / "config/server.json").read_text())
    for name in ("device", "port", "max_model_len", "max_num_seqs", "max_num_batched_tokens"):
        if type(cfg[name]) is not int or cfg[name] < (0 if name == "device" else 1):
            raise ValueError(f"invalid {name}")
    if cfg["port"] > 65535 or not ipaddress.ip_address(cfg["host"]).is_loopback:
        raise ValueError("RAG must listen on a valid loopback port")
    if cfg["max_model_len"] > 8192 or cfg["max_num_batched_tokens"] < cfg["max_model_len"]:
        raise ValueError("BGE-M3 context must be <= 8192 and fit the encoder token budget")
    fraction = cfg["gpu_memory_utilization"]
    if type(fraction) not in (float, int) or not math.isfinite(fraction) or not 0 < fraction <= 1:
        raise ValueError("gpu_memory_utilization must be in (0, 1]")
    if cfg["dtype"] != "half" or cfg["served_model_name"] != "bge-m3":
        raise ValueError("this deployment uses FP16 and the bge-m3 alias")
    model = Path(cfg["model"])
    if not model.is_absolute() or not model.is_dir():
        raise ValueError("model must be an existing absolute directory")
    model_config = json.loads((model / "config.json").read_text())
    if (model_config.get("architectures") != ["XLMRobertaModel"]
            or model_config.get("hidden_size") != 1024):
        raise ValueError("expected the BGE-M3 1024-dimensional XLM-RoBERTa architecture")
    if not any((model / name).is_file() for name in ("model.safetensors", "pytorch_model.bin")):
        raise ValueError("missing BGE-M3 weights")
    return cfg


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
        raise ValueError("RAG internal key must have mode 0600")
    if not re.fullmatch(r"[A-Za-z0-9_~.\-]{24,256}", KEY.read_text().strip()):
        raise ValueError("invalid RAG internal credential")


def check(cfg):
    if not PYTHON.is_file():
        raise ValueError("run bash rag_service/scripts/bootstrap.sh first")
    probe = """
from importlib import metadata
from pathlib import Path
import sys
assert sys.version_info[:2] == (3, 10)
assert Path(sys.prefix).resolve() == Path(%r)
for name, expected in %r.items():
    actual = metadata.version(name)
    print(name + '=' + actual)
    assert actual == expected, name + ': unexpected vendor package version'
import torch, vllm, ixformer
assert '/usr/local/corex' in torch.__file__
from transformers import AutoConfig, AutoTokenizer
cfg = AutoConfig.from_pretrained(%r, local_files_only=True, trust_remote_code=False)
assert cfg.architectures == ['XLMRobertaModel'] and cfg.hidden_size == 1024
AutoTokenizer.from_pretrained(%r, local_files_only=True, trust_remote_code=False)
print('Vendor imports and BGE-M3 configuration: PASS')
""" % (str(ROOT / ".venv"), EXPECTED, cfg["model"], cfg["model"])
    subprocess.run([str(PYTHON), "-c", probe], cwd=ROOT, env=environment(cfg), check=True)


def command(cfg):
    args = [str(PYTHON), "-m", "vllm.entrypoints.openai.api_server"]
    for name in ("model", "served_model_name", "host", "port", "dtype", "max_model_len",
                 "max_num_seqs", "max_num_batched_tokens", "gpu_memory_utilization"):
        args.extend(["--" + name.replace("_", "-"), str(cfg[name])])
    args.extend(["--runner", "pooling", "--tensor-parallel-size", "1", "--enforce-eager",
                 "--pooler-config", json.dumps({"pooling_type": "CLS", "use_activation": True})])
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "init-key", "run"))
    args = parser.parse_args()
    os.umask(0o077)
    cfg = config()
    if args.action == "check":
        check(cfg)
    elif args.action == "init-key":
        init_key()
        print(f"RAG internal credential ready: {KEY} (value not displayed)")
    else:
        check(cfg)
        with socket.socket(socket.AF_INET6 if ":" in cfg["host"] else socket.AF_INET) as probe:
            probe.settimeout(1)
            if probe.connect_ex((cfg["host"], cfg["port"])) == 0:
                raise RuntimeError("RAG port is already in use")
        init_key()
        env = environment(cfg)
        env["VLLM_API_KEY"] = KEY.read_text().strip()
        argv = command(cfg)
        os.execvpe(argv[0], argv, env)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
