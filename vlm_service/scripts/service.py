#!/usr/bin/env python3
"""Manage only this project's vLLM process group; never alter host GPU packages."""

import argparse
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
STATE = RUNTIME / "service.json"
KEY = RUNTIME / "api_key"
PYTHON = ROOT / ".venv/bin/python"
COREX = Path("/usr/local/corex")
EXPECTED = {
    "vllm": "0.17.0+corex.4.5.0.rc.11.20260701",
    "ixformer": "0.7.0+corex.4.5.0.rc.11.20260701",
    "torch": "2.7.1+corex.4.4.0",
    "transformers": "4.57.6",
}


def config():
    value = json.loads((ROOT / "config/server.json").read_text())
    for name in ("device", "port", "max_model_len", "max_num_seqs", "max_num_batched_tokens", "max_images", "max_image_pixels"):
        if type(value[name]) is not int or value[name] < (0 if name == "device" else 1):
            raise ValueError(f"invalid {name}")
    if value["port"] > 65535:
        raise ValueError("invalid port")
    fraction = value["gpu_memory_utilization"]
    if not isinstance(fraction, (int, float)) or not math.isfinite(fraction) or not 0 < fraction <= 1:
        raise ValueError("gpu_memory_utilization must be in (0, 1]")
    if value["dtype"] != "bfloat16":
        raise ValueError("this deployment is validated for bfloat16 only")
    model = Path(value["model"])
    if not model.is_absolute() or not model.is_dir():
        raise ValueError("model must be an existing absolute directory")
    model_config = json.loads((model / "config.json").read_text())
    if model_config.get("architectures") != ["Qwen3_5ForConditionalGeneration"]:
        raise ValueError("expected the approved dense Qwen3.5 architecture")
    index = json.loads((model / "model.safetensors.index.json").read_text())
    for name in set(index["weight_map"].values()):
        if Path(name).name != name or not (model / name).is_file():
            raise ValueError("missing or invalid model shard")
    return value


def environment(cfg):
    env = os.environ.copy()
    # Avoid inheriting another project's Python paths or its device selection.
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.update({
        "PYTHONPATH": str(COREX / "lib64/python3/dist-packages"),
        "PATH": f"{ROOT}/.venv/bin:{COREX}/bin:/usr/local/bin:/usr/bin:/bin",
        "LD_LIBRARY_PATH": f"{COREX}/lib64:/usr/local/lib:/usr/local/openmpi/lib",
        "VIRTUAL_ENV": str(ROOT / ".venv"),
        "VLM_SERVICE_ROOT": str(ROOT),
        "CUDA_VISIBLE_DEVICES": str(cfg["device"]),
        "VLLM_KV_DISABLE_CROSS_GROUP_SHARE": "1",
        "VLLM_ENFORCE_CUDA_GRAPH": "0",
        "VLLM_WORKER_MULTIPROC_METHOD": "spawn",
        "VLLM_NO_USAGE_STATS": "1",
        "VLLM_DO_NOT_TRACK": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": "4",
        "VLLM_MEDIA_URL_ALLOW_REDIRECTS": "0",
    })
    return env


def init_key():
    if not KEY.exists():
        fd = os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(secrets.token_urlsafe(32) + "\n")
    if KEY.stat().st_mode & 0o077:
        raise ValueError("runtime/api_key permissions must be 0600")
    if len(KEY.read_text().strip()) < 24:
        raise ValueError("runtime/api_key must contain a strong secret")
    print(f"API key ready: {KEY} (value not displayed)")


def check(cfg):
    if not PYTHON.is_file():
        raise ValueError("run bash scripts/bootstrap.sh first")
    probe = """
from importlib import metadata
from pathlib import Path
import sys
expected = %r
assert sys.version_info[:2] == (3, 10)
assert Path(sys.prefix).resolve() == Path(%r)
for name, version in expected.items():
    actual = metadata.version(name)
    print(name + '=' + actual)
    assert actual == version, name + ': unexpected vendor package version'
import torch, vllm, ixformer
assert '/usr/local/corex' in torch.__file__
from vllm.transformers_utils.config import get_config
c = get_config(%r, trust_remote_code=False)
assert c.architectures == ['Qwen3_5ForConditionalGeneration']
print('Vendor imports and model configuration: PASS')
""" % (EXPECTED, str(ROOT / ".venv"), cfg["model"])
    subprocess.run([str(PYTHON), "-c", probe], cwd=ROOT, env=environment(cfg), check=True)


def live_state():
    if not STATE.exists():
        return None
    record = json.loads(STATE.read_text())
    proc = Path("/proc") / str(record["pid"])
    try:
        fields = (proc / "stat").read_text().split()
        if fields[2] == "Z" or fields[21] != record["start_ticks"]:
            return None
        env = (proc / "environ").read_bytes().split(b"\0")
        if f"VLM_SERVICE_ROOT={ROOT}".encode() not in env:
            raise RuntimeError("PID ownership mismatch; refusing to manage this process")
        if b"vllm.entrypoints.openai.api_server" not in (proc / "cmdline").read_bytes().split(b"\0"):
            raise RuntimeError("PID is not the expected vLLM API process")
        return record
    except FileNotFoundError:
        return None


def healthy(record):
    url = f"http://127.0.0.1:{record['port']}/health"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def start(cfg, *, foreground=False):
    if record := live_state():
        if foreground:
            raise RuntimeError("background VLM is already running; stop it before using foreground supervision")
        print(json.dumps({**record, "healthy": healthy(record)}, ensure_ascii=False))
        return
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1", cfg["port"])) == 0:
            raise RuntimeError("port already in use; refusing to start another service")
    init_key()
    env = environment(cfg)
    env["VLLM_API_KEY"] = KEY.read_text().strip()
    args = [str(PYTHON), "-m", "vllm.entrypoints.openai.api_server"]
    for name in ("model", "served_model_name", "host", "port", "dtype", "max_model_len", "max_num_seqs", "max_num_batched_tokens", "gpu_memory_utilization"):
        args.extend(["--" + name.replace("_", "-"), str(cfg[name])])
    args.extend([
        "--tensor-parallel-size", "1",
        "--enforce-eager",
        "--enable-auto-tool-choice", "--tool-call-parser", "qwen3_coder",
        "--reasoning-parser", "qwen3",
        "--limit-mm-per-prompt", json.dumps({"image": cfg["max_images"], "video": 0}),
        "--mm-processor-kwargs", json.dumps({"max_pixels": cfg["max_image_pixels"]}),
        "--allowed-media-domains", "media.invalid",
    ])
    if foreground:
        os.execvpe(args[0], args, env)
    logfile = RUNTIME / ("vllm-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".log")
    fd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        child = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=fd, stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        os.close(fd)
    ticks = Path(f"/proc/{child.pid}/stat").read_text().split()[21]
    record = {"pid": child.pid, "start_ticks": ticks, "port": cfg["port"], "device": cfg["device"], "log": str(logfile)}
    STATE.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({**record, "status": "starting; use status and inspect log"}, ensure_ascii=False))


def stop():
    record = live_state()
    if not record:
        print("Service not running")
        return
    pid = record["pid"]
    if os.getpgid(pid) != pid:
        raise RuntimeError("unexpected process group; refusing to stop")
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            print("Service process group stopped")
            return
        time.sleep(0.2)
    raise RuntimeError("process group has not exited after SIGTERM; inspect before restarting")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "init-key", "start", "run", "status", "stop"))
    action = parser.parse_args().action
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    with (RUNTIME / "control.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "stop":
            stop()
        elif action == "status":
            record = live_state()
            print(json.dumps({**record, "healthy": healthy(record)} if record else {"status": "stopped"}))
        elif action == "init-key":
            init_key()
        elif action == "check":
            check(config())
        else:
            start(config(), foreground=action == "run")


if __name__ == "__main__":
    main()
