#!/usr/bin/env python3
"""Manage the local gateway and independent algorithm processes without importing GPU packages."""

import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import ssl
import subprocess
import sys
import time
import urllib.request

from configuration import load, render, secret


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
RUNTIME = ROOT / "runtime"
NGINX = ROOT / "runtime/nginx/sbin/nginx"


def write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(text)


def init(cfg, names):
    for path in (cfg["api_key_file"], cfg["vlm"]["api_key_file"], cfg["yolo"]["api_key_file"]):
        secret(path, create=True)
    cert, key = cfg["certificate"], cfg["certificate_key"]
    if cert.exists() or key.exists():
        if not cert.is_file() or not key.is_file():
            raise ValueError("both TLS certificate and key must exist; partial pair retained for inspection")
        print("Existing TLS certificate retained")
        return
    alternatives = []
    for name in dict.fromkeys(["localhost", "127.0.0.1", *names]):
        try:
            alternatives.append("IP:" + str(ipaddress.ip_address(name)))
        except ValueError:
            if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?", name):
                raise ValueError("certificate names must be IP addresses or DNS names")
            alternatives.append("DNS:" + name)
    cert.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "30",
        "-subj", "/CN=gpu-gateway-development", "-addext", "subjectAltName=" + ",".join(alternatives),
        "-keyout", str(key), "-out", str(cert),
    ], check=True, capture_output=True)
    print(f"Development certificate created: {cert}; distribute only the certificate to CPU clients")


def prepare_gateway(cfg):
    if not NGINX.is_file():
        raise ValueError("run bash gateway/bootstrap.sh first")
    content = render(cfg, RUNTIME)
    target = RUNTIME / "nginx.conf"
    write_private(target, content)
    command = [str(NGINX), "-p", str(RUNTIME) + "/", "-c", str(target)]
    result = subprocess.run([*command, "-t"], capture_output=True, text=True)
    write_private(RUNTIME / "check.log", result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("NGINX configuration check failed; inspect gateway/runtime/check.log locally")
    return command


def command_for(name, cfg):
    env = os.environ.copy()
    if name == "gateway":
        return prepare_gateway(cfg), env, ROOT
    if name == "vlm":
        project = REPO / "vlm_service"
        local = json.loads((project / "config/server.json").read_text())
        host = f"[{local['host']}]" if ":" in local["host"] else local["host"]
        if f"{host}:{local['port']}" != cfg["vlm"]["address"]:
            raise ValueError("VLM listen address must match the gateway loopback upstream")
        if cfg["vlm"]["api_key_file"] != project / "runtime/api_key":
            raise ValueError("VLM upstream key must point to vlm_service/runtime/api_key")
        return [str(project / ".venv/bin/python"), "scripts/service.py", "run"], env, project
    project = REPO / "yolov5v70-service"
    host, port = cfg["yolo"]["address"].rsplit(":", 1)
    health_host, health_port = cfg["yolo"]["health_address"].rsplit(":", 1)
    env.update({
        "DETECTOR_GRPC_HOST": host.strip("[]"), "DETECTOR_GRPC_PORT": port,
        "DETECTOR_HEALTH_HOST": health_host.strip("[]"), "DETECTOR_HEALTH_PORT": health_port,
        "DETECTOR_DEVICE": "0", "CUDA_VISIBLE_DEVICES": "0",
        "DETECTOR_AUTH_TOKEN": secret(cfg["yolo"]["api_key_file"]),
        "DETECTOR_WEIGHTS": str(cfg["yolo"]["weights"]),
        "DETECTOR_WEIGHTS_SHA256": cfg["yolo"]["weights_sha256"],
    })
    return ["bash", "scripts/run_gpu_detector.sh"], env, project


def live_state(name):
    state = RUNTIME / f"{name}.json"
    if not state.is_file():
        return None
    record = json.loads(state.read_text())
    proc = Path("/proc") / str(record["pid"])
    try:
        # Field 2 is parenthesized and may contain spaces.
        fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z" or fields[19] != record["start_ticks"]:
            return None
        if name == "gateway":
            # NGINX rewrites argv/environ for its process title; identify its binary and config instead.
            owned = ((proc / "exe").resolve() == NGINX.resolve()
                     and str(RUNTIME / "nginx.conf").encode() in (proc / "cmdline").read_bytes())
        else:
            expected = f"GPU_GATEWAY_PROCESS={ROOT}:{name}".encode()
            owned = expected in (proc / "environ").read_bytes().split(b"\0")
        if not owned:
            raise RuntimeError(f"{name} PID ownership mismatch; refusing to manage it")
    except FileNotFoundError:
        return None
    return record


def start(name, cfg):
    if live_state(name):
        print(f"{name}: already running")
        return
    command, env, cwd = command_for(name, cfg)
    env["GPU_GATEWAY_PROCESS"] = f"{ROOT}:{name}"
    log = RUNTIME / f"{name}-{time.time_ns()}.log"
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=fd, stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        os.close(fd)
    fields = Path(f"/proc/{process.pid}/stat").read_text().rsplit(")", 1)[1].split()
    write_private(RUNTIME / f"{name}.json", json.dumps({
        "pid": process.pid, "start_ticks": fields[19], "log": str(log),
    }) + "\n")
    if process.poll() is not None:
        raise RuntimeError(f"{name} exited during startup; inspect {log}")
    print(f"{name}: starting; pid={process.pid}; log={log}")


def stop(name):
    record = live_state(name)
    if not record:
        print(f"{name}: stopped")
        return
    if os.getpgid(record["pid"]) != record["pid"]:
        raise RuntimeError(f"{name}: unexpected process group")
    os.killpg(record["pid"], signal.SIGTERM)
    deadline = time.monotonic() + 30
    while live_state(name):
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{name}: shutdown timed out; inspect its processes before restarting")
        time.sleep(0.2)
    print(f"{name}: stopped")


def ready(url, context=None, key=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                       urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"} if key else {})
    try:
        with opener.open(request, timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def status(name, cfg):
    record = live_state(name)
    if name == "gateway":
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=str(cfg["certificate"]))
        healthy = ready(f"https://{cfg['probe_host']}:{cfg['listen_port']}/health/live",
                        context, secret(cfg["api_key_file"]))
    elif name == "vlm":
        healthy = ready(f"http://{cfg['vlm']['address']}/health")
    else:
        healthy = ready(f"http://{cfg['yolo']['health_address']}/health/ready")
    return {"managed": bool(record), "ready": healthy, **(record or {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "check", "start", "stop", "status", "run"))
    parser.add_argument("--service", choices=("all", "gateway", "yolo", "vlm"), default="all")
    parser.add_argument("--name", action="append", default=[], help="GPU destination DNS/IP for a development certificate")
    args = parser.parse_args()
    os.umask(0o077)
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    cfg = load(ROOT / "config/server.json")
    with (RUNTIME / "control.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == "init":
            init(cfg, args.name)
            print(f"Shared client credential: {cfg['api_key_file']} (value not displayed)")
        elif args.action == "check":
            prepare_gateway(cfg)
            print("NGINX configuration: PASS")
        elif args.action == "run":
            if args.service == "all":
                raise ValueError("run needs --service gateway, yolo or vlm")
            if live_state(args.service):
                raise RuntimeError("managed process already running")
            command, env, cwd = command_for(args.service, cfg)
            fcntl.flock(lock, fcntl.LOCK_UN)
            os.chdir(cwd)
            os.execvpe(command[0], command, env)
        else:
            names = ["yolo", "vlm", "gateway"] if args.service == "all" else [args.service]
            if args.action == "status":
                print(json.dumps({name: status(name, cfg) for name in names}, indent=2))
            else:
                failures = []
                for name in reversed(names) if args.action == "stop" else names:
                    try:
                        stop(name) if args.action == "stop" else start(name, cfg)
                    except (OSError, ValueError, RuntimeError) as error:
                        failures.append(f"{name}: {error}")
                if failures:
                    raise RuntimeError("; ".join(failures))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
