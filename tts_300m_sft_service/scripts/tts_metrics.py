"""Prometheus metrics shared by TTS backend engines."""

from prometheus_client import Histogram


TTS_TTFT = Histogram(
    "tts_time_to_first_token_seconds",
    "Time from GPU text inference start until the first speech token.",
    buckets=(0.001, 0.005, 0.01, 0.02, 0.04, 0.08, 0.16, 0.32,
             0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92, 163.84),
)
