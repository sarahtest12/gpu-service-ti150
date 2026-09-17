#!/usr/bin/env python3
"""Validate complete and delayed bi-streaming CosyVoice3 inference on CoreX."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import service


def process_memory_mib():
    result = subprocess.run(
        ["ixsmi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader"],
        capture_output=True, text=True,
    )
    if result.returncode:
        return None
    for line in result.stdout.splitlines():
        match = re.fullmatch(r"\s*(\d+)\s*,\s*([0-9.]+)\s+MiB\s*", line)
        if match and int(match.group(1)) == os.getpid():
            return float(match.group(2))
    return None


def torch_memory(torch):
    return {
        "allocated_mb": round(torch.cuda.memory_allocated() / 1_000_000, 3),
        "reserved_mb": round(torch.cuda.memory_reserved() / 1_000_000, 3),
        "peak_allocated_mb": round(torch.cuda.max_memory_allocated() / 1_000_000, 3),
        "process_mib": process_memory_mib(),
    }


def consume(engine, text_stream, request_id, utterance_id):
    started = time.perf_counter()
    first_pcm = None
    chunks = []
    for chunk in engine.synthesize(text_stream, request_id, utterance_id):
        if first_pcm is None:
            first_pcm = time.perf_counter()
        chunks.append(chunk)
    ended = time.perf_counter()
    if first_pcm is None or not chunks:
        raise RuntimeError(f"{utterance_id} produced no PCM")
    pcm = b"".join(chunks)
    if len(pcm) % 2:
        raise RuntimeError(f"{utterance_id} produced odd-length PCM")
    audio_seconds = len(pcm) / (24000 * 2)
    return pcm, {
        "first_pcm_seconds": round(first_pcm - started, 6),
        "total_seconds": round(ended - started, 6),
        "pcm_bytes": len(pcm),
        "audio_seconds": round(audio_seconds, 6),
        "rtf": round((ended - started) / audio_seconds, 6),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/server.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chunk-delay-seconds", type=float, default=0.1)
    parser.add_argument("--finish-delay-seconds", type=float, default=15.0)
    args = parser.parse_args()
    if not 0.05 <= args.chunk_delay_seconds <= 30:
        raise ValueError("chunk delay must be in 0.05..30 seconds")
    if not 1 <= args.finish_delay_seconds <= 120:
        raise ValueError("finish delay must be in 1..120 seconds")
    service.CONFIG = args.config.resolve()
    cfg = service.config()
    if os.environ.get("TTS_VALIDATION_ENV") != "1":
        env = service.environment(cfg)
        env["TTS_VALIDATION_ENV"] = "1"
        os.execvpe(str(service.PYTHON), [str(service.PYTHON), str(Path(__file__).resolve()),
                   "--config", str(args.config.resolve()), "--output", str(args.output.resolve()),
                   "--chunk-delay-seconds", str(args.chunk_delay_seconds),
                   "--finish-delay-seconds", str(args.finish_delay_seconds)], env)

    import torch
    from engine import TextStream
    from server import configure_logging, load_engine

    configure_logging()
    if not torch.cuda.is_available():
        raise RuntimeError("CoreX GPU is not available")
    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    engine = load_engine(cfg)
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_started
    after_load = torch_memory(torch)

    complete = TextStream(cfg["text_queue_chunks"])
    complete.append("这是完整文本合成验证，用于确认模型在当前CoreX环境能够生成清晰连续的语音。")
    complete.finish()
    _, complete_result = consume(engine, complete, "validation", "complete")

    delayed = TextStream(cfg["text_queue_chunks"])
    pieces = (
        "收到好友从远方寄来的生日礼物，那份意外的惊喜，",
        "与深深的祝福让我心中充满了甜蜜的快乐，",
        "笑容如花儿般绽放，也期待下一次温暖的相聚。",
    )
    producer_started = time.perf_counter()
    producer_finished = threading.Event()
    producer_error = []
    finished_at = []

    def produce():
        try:
            for index, piece in enumerate(pieces):
                if index:
                    time.sleep(args.chunk_delay_seconds)
                delayed.append(piece, timeout=cfg["text_queue_timeout_seconds"])
            time.sleep(args.finish_delay_seconds)
            finished_at.append(time.perf_counter())
            delayed.finish()
        except Exception as error:
            producer_error.append(error)
            delayed.cancel()
        finally:
            producer_finished.set()

    producer = threading.Thread(target=produce, name="validation-text-producer", daemon=True)
    producer.start()
    pcm, bistream = consume(engine, delayed, "validation", "bistream")
    producer.join(timeout=args.chunk_delay_seconds * len(pieces) + args.finish_delay_seconds + 10)
    if producer.is_alive() or not producer_finished.is_set():
        raise RuntimeError("text producer did not finish")
    if producer_error:
        raise producer_error[0]
    if not finished_at:
        raise RuntimeError("text producer finish time is missing")
    first_pcm_at = producer_started + bistream["first_pcm_seconds"]
    bistream.update({
        "chunk_count": len(pieces),
        "chunk_delay_seconds": args.chunk_delay_seconds,
        "finish_delay_seconds": args.finish_delay_seconds,
        "text_finished_seconds": round(finished_at[0] - producer_started, 6),
        "first_pcm_before_text_finished": first_pcm_at < finished_at[0],
    })
    if not bistream["first_pcm_before_text_finished"]:
        raise RuntimeError("first PCM did not arrive before the text generator finished")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(pcm)
    os.chmod(args.output, 0o600)
    torch.cuda.synchronize()
    result = {
        "model": cfg["model_name"],
        "voice": cfg["voice_id"],
        "sample_rate_hz": cfg["sample_rate_hz"],
        "load_seconds": round(load_seconds, 6),
        "memory_after_load": after_load,
        "memory_after_validation": torch_memory(torch),
        "complete": complete_result,
        "bistream": bistream,
        "output": str(args.output.resolve()),
        "status": "pass",
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print(f"validation failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
