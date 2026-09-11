#!/usr/bin/env python3
"""Authenticated snapshot API for GPU algorithm status, memory and latency."""

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlsplit

from telemetry import Collector


LOG = logging.getLogger("monitor-service")


class SnapshotStore:
    def __init__(self, collector, sample_interval_seconds, stale_after_seconds):
        self.collector = collector
        self.interval = sample_interval_seconds
        self.stale_after = stale_after_seconds
        self.condition = threading.Condition()
        self.collect_lock = threading.Lock()
        self.snapshot = None
        self.published_at = None
        self.refreshing = False
        self.refresh_generation = 0
        self.last_refresh_success = False
        self.stopped = threading.Event()
        self.thread = None

    def start(self):
        self._scheduled_collect()
        self.thread = threading.Thread(target=self._schedule, name="monitor-sampler", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=self.interval + 1)

    def _schedule(self):
        deadline = time.monotonic() + self.interval
        while not self.stopped.wait(max(0.0, deadline - time.monotonic())):
            self._scheduled_collect()
            deadline += self.interval
            now = time.monotonic()
            if deadline <= now:
                deadline = now + self.interval

    def _scheduled_collect(self):
        try:
            with self.collect_lock:
                snapshot = self.collector.collect()
        except Exception:
            LOG.exception("scheduled monitoring sample failed")
            return False
        with self.condition:
            self.snapshot = snapshot
            self.published_at = time.monotonic()
            self.condition.notify_all()
        return True

    def latest(self):
        with self.condition:
            if (self.snapshot is None or self.published_at is None
                    or time.monotonic() - self.published_at > self.stale_after):
                return None
            return self.snapshot

    def refresh(self):
        with self.condition:
            if self.refreshing:
                generation = self.refresh_generation
                deadline = time.monotonic() + self.stale_after
                while self.refreshing and self.refresh_generation == generation:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    self.condition.wait(remaining)
                if self.refresh_generation == generation or not self.last_refresh_success:
                    return None
                return self.latest()
            self.refreshing = True
        success = False
        try:
            success = self._scheduled_collect()
        finally:
            with self.condition:
                self.refreshing = False
                self.refresh_generation += 1
                self.last_refresh_success = success
                self.condition.notify_all()
        return self.latest() if success else None


def handler(store, token):
    class MonitorHandler(BaseHTTPRequestHandler):
        server_version = ""
        sys_version = ""

        def do_GET(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self._json(401, {"error": "unauthorized"}, {"WWW-Authenticate": "Bearer"})
                return
            parsed = urlsplit(self.path)
            if parsed.path == "/health" and not parsed.query:
                self._json(200, {"status": "ok"})
                return
            if parsed.path != "/v1/overview":
                self._json(404, {"error": "not_found"})
                return
            query = parse_qs(parsed.query, keep_blank_values=True)
            if set(query) - {"refresh"} or len(query.get("refresh", [])) > 1:
                self._json(400, {"error": "invalid_request"})
                return
            refresh_value = query.get("refresh", ["false"])[0].lower()
            if refresh_value not in ("true", "false"):
                self._json(400, {"error": "invalid_request"})
                return
            snapshot = store.refresh() if refresh_value == "true" else store.latest()
            if snapshot is None:
                self._json(503, {"error": "monitor_unavailable"})
                return
            self._json(200, snapshot, {"Cache-Control": "no-store"})

        def _json(self, status, value, headers=None):
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            LOG.info("%s %s", self.address_string(), format % args)

    return MonitorHandler


def run(config_path, key_path):
    cfg = json.loads(config_path.read_text())
    token = key_path.read_text().strip()
    store = SnapshotStore(Collector(config_path), cfg["sample_interval_seconds"],
                          cfg["stale_after_seconds"])
    store.start()
    server = ThreadingHTTPServer((cfg["host"], cfg["port"]), handler(store, token))
    server.daemon_threads = True
    LOG.info("monitor ready on http://%s:%d/v1/overview", cfg["host"], cfg["port"])
    try:
        server.serve_forever()
    finally:
        server.server_close()
        store.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run(args.config.resolve(), args.key_file.resolve())


if __name__ == "__main__":
    main()
