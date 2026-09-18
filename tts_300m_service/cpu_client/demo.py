#!/usr/bin/env python3
"""Stream CPU-segmented lines over WSS and save PCM as WAV."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

from tts_client import SegmentRejected, TtsRealtimeClient, write_wav_header


def stream_segments(client, lines, write_pcm):
    """Feed lines on a producer thread while this thread consumes ordered audio.

    Wait only for each admission acknowledgement, never for its audio completion.
    Limit local outstanding work and retry queue_full only after audio.done.
    """
    condition = threading.Condition()
    pending = {}
    failures = []
    finished = False
    stopped = False
    completions = 0

    def produce():
        nonlocal finished
        try:
            for index, line in enumerate(lines, 1):
                text = line.strip()
                if not text:
                    continue
                ident = f"seg-{index:06d}"
                while True:
                    with condition:
                        condition.wait_for(lambda: stopped or len(pending) < 4)
                        if stopped:
                            return
                        pending[ident] = "sent"
                        condition.notify_all()
                    client.send_segment(ident, text)
                    with condition:
                        condition.wait_for(lambda: stopped or pending.get(ident) != "sent")
                        if stopped:
                            return
                        result = pending.get(ident)
                        if not isinstance(result, int):
                            break  # accepted, or already completed
                        condition.wait_for(lambda: stopped or completions > result)
                        if stopped:
                            return
                        del pending[ident]
        except Exception as error:
            with condition:
                failures.append(error)
                condition.notify_all()
            client.close()
        finally:
            with condition:
                finished = True
                condition.notify_all()

    producer = threading.Thread(target=produce, name="tts-segment-producer", daemon=True)
    producer.start()
    size = 0
    try:
        while True:
            with condition:
                condition.wait_for(lambda: failures or finished or any(
                    isinstance(status, str) for status in pending.values()))
                if failures:
                    raise failures[0]
                if finished and not pending:
                    break
            try:
                frame = client.receive_segment_frame()
            except SegmentRejected as error:
                if error.code != "queue_full":
                    raise
                with condition:
                    pending[error.segment_id] = completions
                    if not any(status == "accepted" for status in pending.values()):
                        raise RuntimeError("queue_full without local work to complete") from error
                    condition.notify_all()
                continue
            with condition:
                if frame.kind == "accepted":
                    pending[frame.segment_id] = "accepted"
                elif frame.kind == "audio_done":
                    del pending[frame.segment_id]
                    completions += 1
                condition.notify_all()
            if frame.kind == "audio":
                write_pcm(frame.pcm)
                size += len(frame.pcm)
        return size
    finally:
        with condition:
            stopped = True
            condition.notify_all()
        if not finished:
            client.close()
        producer.join(timeout=min(client.timeout_seconds, 10))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=Path(__file__).with_name("config.gateway.example.json"))
    parser.add_argument("--output", type=Path, default=Path("tts-output.wav"))
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    ca = os.getenv("GPU_CA_FILE", cfg.get("ca_file"))
    if ca:
        ca = args.config.resolve().parent / ca

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as pcm:
        size = 0
        with TtsRealtimeClient(
            os.getenv("TTS_BASE_URL", cfg["base_url"]),
            api_key=os.getenv("GPU_API_KEY", ""),
            timeout_seconds=cfg["timeout_seconds"],
            ca_file=ca,
        ) as client:
            audio = dict(client.session["audio"])
            size = stream_segments(client, sys.stdin, pcm.write)
        if size == 0 or size % 2:
            raise RuntimeError("TTS returned empty or invalid PCM audio")
        pcm.seek(0)
        with args.output.open("wb") as output:
            write_wav_header(output, size, sample_rate=audio["sample_rate_hz"],
                             channels=audio["channels"])
            while chunk := pcm.read(1024 * 1024):
                output.write(chunk)
    print(json.dumps({"output": str(args.output), "pcm_bytes": size,
                      "sample_rate_hz": audio["sample_rate_hz"], "channels": audio["channels"]}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("Request cancelled", file=sys.stderr)
        raise SystemExit(130)
