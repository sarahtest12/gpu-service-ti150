"""CPU-only client for monitoring snapshots through the shared GPU gateway."""

import math
import ssl
import urllib.parse

import httpx


METRICS = {
    "yolo": "model_inference",
    "vlm": "time_to_first_token",
    "rag": "http_request",
    "asr": "time_to_first_token",
    "tts": "time_to_first_token",
}


class MonitorClient:
    def __init__(self, base_url, *, api_key, timeout_seconds=12, ca_file=None):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("base_url must be an HTTP(S) origin without credentials, query or fragment")
        if not api_key or "\n" in api_key or "\r" in api_key:
            raise ValueError("set GPU_API_KEY to the shared gateway credential")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        verify = ssl.create_default_context(cafile=str(ca_file)) if ca_file is not None else True
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout_seconds, verify=verify,
            trust_env=False, follow_redirects=False,
            headers={"Authorization": "Bearer " + api_key},
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def overview(self, *, refresh=False):
        if type(refresh) is not bool:
            raise ValueError("refresh must be a boolean")
        try:
            response = self._client.get("/monitor/v1/overview",
                                        params={"refresh": "true"} if refresh else None)
            response.raise_for_status()
            value = response.json()
        except httpx.HTTPStatusError as error:
            raise RuntimeError(f"monitor HTTP {error.response.status_code}") from None
        except (httpx.TimeoutException, httpx.TransportError):
            raise RuntimeError("monitor connection failed or timed out") from None
        except ValueError:
            raise RuntimeError("monitor returned invalid JSON") from None
        self._validate(value)
        return value

    @staticmethod
    def _validate(value):
        if not isinstance(value, dict) or set(value) != {"sampled_at", "services"}:
            raise RuntimeError("monitor response shape is invalid")
        if not isinstance(value["sampled_at"], str) or not isinstance(value["services"], list):
            raise RuntimeError("monitor response shape is invalid")
        seen = set()
        for service in value["services"]:
            if not isinstance(service, dict):
                raise RuntimeError("monitor service item is invalid")
            name, status = service.get("name"), service.get("status")
            if name not in METRICS or name in seen or status not in {"running", "error"}:
                raise RuntimeError("monitor service item is invalid")
            seen.add(name)
            if status == "error":
                if set(service) != {"name", "status"}:
                    raise RuntimeError("error service must not include measurements")
                continue
            if set(service) != {"name", "status", "memory_mb", "latency"}:
                raise RuntimeError("running service shape is invalid")
            MonitorClient._nullable_number(service["memory_mb"])
            latency = service["latency"]
            if (not isinstance(latency, dict)
                    or set(latency) != {"metric", "avg_ms", "p95_ms"}
                    or latency["metric"] != METRICS[name]):
                raise RuntimeError("latency shape is invalid")
            MonitorClient._nullable_number(latency["avg_ms"])
            MonitorClient._nullable_number(latency["p95_ms"])

    @staticmethod
    def _nullable_number(value):
        if value is None:
            return
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise RuntimeError("monitor measurement is invalid")
