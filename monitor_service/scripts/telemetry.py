"""Collect the five reviewed service metrics and aggregate 60-second histograms."""

from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
import time
import urllib.request


SERVICES = ("yolo", "vlm", "rag", "asr", "tts")
LATENCY_NAMES = {
    "yolo": "model_inference",
    "vlm": "time_to_first_token",
    "rag": "http_request",
    "asr": "time_to_first_token",
    "tts": "time_to_first_token",
}
PROMETHEUS_METRICS = {
    "yolo": ("detector_inference_ms", 0.001),
    "vlm": ("vllm:time_to_first_token_seconds", 1.0),
    "rag": ("vllm:e2e_request_latency_seconds", 1.0),
    "asr": ("asr_time_to_first_token_seconds", 1.0),
    "tts": ("tts_time_to_first_token_seconds", 1.0),
}
SAMPLE_RE = re.compile(
    r"^(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)(?:\{(?P<labels>.*)\})?\s+"
    r"(?P<value>[-+]?(?:Inf|NaN|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?))"
    r"(?:\s+\d+)?$"
)
LE_RE = re.compile(r'(?:^|,)le="(?P<le>(?:\\.|[^"\\])*)"(?:,|$)')


@dataclass(frozen=True)
class HistogramSnapshot:
    count: float
    total: float
    buckets: dict[float, float]

    def scaled(self, factor):
        return HistogramSnapshot(
            self.count,
            self.total * factor,
            {bound * factor: count for bound, count in self.buckets.items()},
        )


def parse_histogram(text, metric_name):
    """Aggregate every label set of one Prometheus histogram."""
    count = 0.0
    total = 0.0
    buckets = {}
    found_count = found_sum = False
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = SAMPLE_RE.match(line)
        if not match:
            continue
        name = match.group("name")
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        if not math.isfinite(value) or value < 0:
            continue
        if name == metric_name + "_count":
            count += value
            found_count = True
        elif name == metric_name + "_sum":
            total += value
            found_sum = True
        elif name == metric_name + "_bucket":
            labels = match.group("labels") or ""
            le_match = LE_RE.search(labels)
            if not le_match:
                continue
            raw_bound = le_match.group("le")
            try:
                bound = math.inf if raw_bound == "+Inf" else float(raw_bound)
            except ValueError:
                continue
            buckets[bound] = buckets.get(bound, 0.0) + value
    if not found_count or not found_sum or not buckets:
        return None
    return HistogramSnapshot(count, total, buckets)


def parse_scalar(text, metric_name):
    for line in text.splitlines():
        match = SAMPLE_RE.match(line)
        if not match or match.group("name") != metric_name or match.group("labels"):
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            return None
        return value if math.isfinite(value) else None
    return None


class HistogramWindow:
    """Turn cumulative Prometheus samples into a bounded rolling window."""

    def __init__(self, window_seconds, max_sample_gap_seconds):
        self.window_seconds = float(window_seconds)
        self.max_sample_gap_seconds = float(max_sample_gap_seconds)
        self.previous = None
        self.intervals = []

    def update(self, now, current, generation=None):
        previous = self.previous
        self.previous = (now, current, generation)
        if previous is None:
            self._prune(now)
            return
        previous_at, old, old_generation = previous
        reset = (
            now - previous_at > self.max_sample_gap_seconds
            or (generation is not None and old_generation is not None
                and generation != old_generation)
            or set(old.buckets) != set(current.buckets)
            or current.count < old.count
            or current.total < old.total
            or any(current.buckets[bound] < old.buckets[bound] for bound in old.buckets)
        )
        if reset:
            self.intervals.clear()
            return
        count = current.count - old.count
        total = current.total - old.total
        buckets = {bound: current.buckets[bound] - old.buckets[bound]
                   for bound in current.buckets}
        if count > 0 and total >= 0:
            self.intervals.append((now, count, total, buckets))
        self._prune(now)

    def _prune(self, now):
        cutoff = now - self.window_seconds
        self.intervals = [item for item in self.intervals if item[0] > cutoff]

    def statistics_ms(self, now):
        self._prune(now)
        count = sum(item[1] for item in self.intervals)
        if count <= 0:
            return None, None
        total = sum(item[2] for item in self.intervals)
        bucket_totals = {}
        for _, _, _, buckets in self.intervals:
            for bound, value in buckets.items():
                bucket_totals[bound] = bucket_totals.get(bound, 0.0) + value
        p95 = histogram_quantile(0.95, count, bucket_totals)
        return round(total / count * 1000, 3), (round(p95 * 1000, 3) if p95 is not None else None)


def histogram_quantile(quantile, count, cumulative_buckets):
    """Estimate a histogram quantile with Prometheus-style interpolation."""
    if count <= 0 or not cumulative_buckets:
        return None
    rank = quantile * count
    previous_bound = 0.0
    previous_count = 0.0
    for bound in sorted(cumulative_buckets):
        bucket_count = cumulative_buckets[bound]
        if bucket_count < rank:
            previous_bound, previous_count = bound, bucket_count
            continue
        if math.isinf(bound):
            return None
        population = bucket_count - previous_count
        if population <= 0:
            return bound
        fraction = min(1.0, max(0.0, (rank - previous_count) / population))
        return previous_bound + (bound - previous_bound) * fraction
    return None


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    health_url: str
    metrics_url: str
    token: str | None
    prometheus_metric: str
    metric_scale: float


class Collector:
    def __init__(self, config_path):
        config_path = Path(config_path).resolve()
        self.cfg = json.loads(config_path.read_text())
        gateway_path = (config_path.parent / self.cfg["gateway_config"]).resolve()
        self.gateway_cfg = json.loads(gateway_path.read_text())
        self.timeout = self.cfg["upstream_timeout_seconds"]
        interval = self.cfg["sample_interval_seconds"]
        self.windows = {
            name: HistogramWindow(self.cfg["window_seconds"], interval * 2.5)
            for name in SERVICES if name in self.gateway_cfg
        }
        self.specs = [self._service_spec(name, gateway_path.parent)
                      for name in SERVICES if name in self.gateway_cfg]
        self.proc_root = Path("/proc")

    def _service_spec(self, name, gateway_config_dir):
        route = self.gateway_cfg[name]
        if name == "yolo":
            health_address = route["health_address"]
            health_url = f"http://{health_address}/health/ready"
            metrics_url = f"http://{health_address}/metrics"
            token = None
        else:
            address = route["address"]
            health_url = f"http://{address}/health"
            metrics_url = f"http://{address}/metrics"
            token = None
            if name in ("asr", "tts"):
                key_path = (gateway_config_dir / route["api_key_file"]).resolve()
                token = key_path.read_text().strip()
        metric, scale = PROMETHEUS_METRICS[name]
        return ServiceSpec(name, health_url, metrics_url, token, metric, scale)

    @staticmethod
    def _opener():
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _get(self, url, token=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        request = urllib.request.Request(url, headers=headers)
        with self._opener().open(request, timeout=self.timeout) as response:
            body = response.read(16 * 1024 * 1024 + 1)
            if len(body) > 16 * 1024 * 1024:
                raise ValueError("metrics response is too large")
            return response.status, body.decode("utf-8")

    def _collect_health(self, spec):
        try:
            status, _ = self._get(spec.health_url, spec.token)
            return status == 200
        except (OSError, ValueError, UnicodeError):
            return False

    def _collect_metric(self, spec):
        try:
            status, body = self._get(spec.metrics_url, spec.token)
            if status == 200:
                parsed = parse_histogram(body, spec.prometheus_metric)
                histogram = parsed.scaled(spec.metric_scale) if parsed is not None else None
                generation = parse_scalar(body, "process_start_time_seconds")
                return histogram, generation
        except (OSError, ValueError, UnicodeError):
            pass
        return None, None

    def collect(self):
        with ThreadPoolExecutor(max_workers=len(self.specs) * 2 + 1) as pool:
            health_pending = {spec.name: pool.submit(self._collect_health, spec)
                              for spec in self.specs}
            metric_pending = {spec.name: pool.submit(self._collect_metric, spec)
                              for spec in self.specs}
            memory_pending = pool.submit(self._memory_by_service)
            service_data = {
                spec.name: (health_pending[spec.name].result(),
                            *metric_pending[spec.name].result())
                for spec in self.specs
            }
            memory_available, memory = memory_pending.result()

        now = time.monotonic()
        services = []
        for spec in self.specs:
            healthy, histogram, generation = service_data[spec.name]
            if histogram is not None:
                self.windows[spec.name].update(now, histogram, generation)
            if not healthy:
                services.append({"name": spec.name, "status": "error"})
                continue
            avg_ms, p95_ms = ((None, None) if histogram is None
                              else self.windows[spec.name].statistics_ms(now))
            services.append({
                "name": spec.name,
                "status": "running",
                "memory_mb": (round(memory[spec.name] * 1.048576, 3)
                              if memory_available and spec.name in memory else None),
                "latency": {
                    "metric": LATENCY_NAMES[spec.name],
                    "avg_ms": avg_ms,
                    "p95_ms": p95_ms,
                },
            })
        sampled_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return {"sampled_at": sampled_at, "services": services}

    def _memory_by_service(self):
        try:
            result = subprocess.run(
                [self.cfg["ixsmi"], "--query-compute-apps=pid,used_memory",
                 "--format=csv,noheader,nounits"],
                check=True, capture_output=True, text=True, timeout=self.timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return False, {}
        memory = {}
        cache = {}
        for row in csv.reader(result.stdout.splitlines(), skipinitialspace=True):
            if len(row) != 2:
                continue
            try:
                pid, used_mib = int(row[0]), float(row[1])
            except ValueError:
                continue
            service = self._process_service(pid, cache)
            if service is not None:
                memory[service] = memory.get(service, 0.0) + used_mib
        return True, memory

    def _process_service(self, pid, cache):
        visited = []
        current = pid
        for _ in range(64):
            if current in cache:
                service = cache[current]
                break
            visited.append(current)
            proc = self.proc_root / str(current)
            try:
                variables = (proc / "environ").read_bytes().split(b"\0")
                marker = next((value for value in variables
                               if value.startswith(b"GPU_GATEWAY_PROCESS=")), None)
                if marker is not None:
                    candidate = marker.rsplit(b":", 1)[-1].decode("ascii", "strict")
                    service = candidate if candidate in SERVICES else None
                    break
                fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
                parent = int(fields[1])
            except (OSError, ValueError, UnicodeError):
                service = None
                break
            if parent <= 1 or parent == current:
                service = None
                break
            current = parent
        else:
            service = None
        for item in visited:
            cache[item] = service
        return service
