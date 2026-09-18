#!/usr/bin/env python3
"""Benchmark the selected 300M engine while the TTS service is stopped."""

import argparse
from contextlib import redirect_stdout
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

import service

ROOT = Path(__file__).resolve().parents[1]


def torch_memory(torch):
    free_bytes, total_bytes = torch.cuda.mem_get_info()
    return {
        'process_mib': round(torch.cuda.memory_allocated() / 1024 / 1024, 3),
        'reserved_mib': round(torch.cuda.memory_reserved() / 1024 / 1024, 3),
        'free_mib': round(free_bytes / 1024 / 1024, 3),
        'total_mib': round(total_bytes / 1024 / 1024, 3),
    }


def consume(engine, text, segment_id, sample_rate_hz):
    started = time.perf_counter()
    first = None
    chunks = []
    for chunk in engine.synthesize_segment(text, 'validation', segment_id):
        if not chunk:
            continue
        if first is None:
            first = time.perf_counter()
        chunks.append(chunk)
    ended = time.perf_counter()
    pcm = b''.join(chunks)
    if not pcm or len(pcm) % 2 or sample_rate_hz <= 0:
        raise ValueError('invalid or empty PCM output')
    if first is None or not all(math.isfinite(value) for value in (started, first, ended)):
        raise ValueError('non-finite timing')
    if not started <= first <= ended:
        raise ValueError('invalid timing order')
    duration = len(pcm) / (sample_rate_hz * 2)
    return pcm, {
        'segment_id': segment_id,
        'first_pcm_seconds': round(first - started, 6),
        'total_seconds': round(ended - started, 6),
        'pcm_bytes': len(pcm),
        'audio_seconds': round(duration, 6),
        'rtf': round((ended - started) / duration, 6),
    }


def build_report(cfg, load_seconds, memory, segments, expected_order, subdivision_count, output):
    order = [item['segment_id'] for item in segments]
    if order != expected_order or len(set(order)) != len(order):
        raise ValueError('segment order mismatch')
    if not math.isfinite(load_seconds) or load_seconds < 0:
        raise ValueError('invalid load time')
    if subdivision_count < 2:
        raise ValueError('fallback subdivision did not run')
    return {
        'model': cfg['model_name'], 'voice': cfg['voice_id'],
        'sample_rate_hz': cfg['sample_rate_hz'],
        'load_seconds': round(load_seconds, 6), 'memory_after_load': memory,
        'segments': segments, 'fifo_order': order,
        'fallback_subdivision_count': subdivision_count,
        'output': str(Path(output).resolve()), 'status': 'pass',
    }


def write_pcm(path, pcm):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.truncate(0)
        stream.write(pcm)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/server.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    service.CONFIG = args.config.resolve()
    cfg = service.config()
    if cfg['backend'] != 'cosyvoice300m':
        raise ValueError('segment validation supports only the cosyvoice300m backend')
    if service.port_in_use(cfg['host'], cfg['port']):
        raise ValueError('stop TTS before loading a standalone validation model')
    if os.environ.get('TTS_SEGMENT_VALIDATION_ENV') != '1':
        env = service.environment(cfg)
        env['TTS_SEGMENT_VALIDATION_ENV'] = '1'
        os.execvpe(str(service.PYTHON), [str(service.PYTHON), str(Path(__file__).resolve()),
                   '--config', str(args.config.resolve()), '--output', str(args.output.resolve())], env)
    with redirect_stdout(sys.stderr):
        import torch
        from server import configure_logging, load_engine

    configure_logging()
    if not torch.cuda.is_available():
        raise RuntimeError('CoreX GPU is not available')
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    with redirect_stdout(sys.stderr):
        engine = load_engine(cfg)
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - started
    memory = torch_memory(torch)
    inputs = [
        ('segment-1', '欢迎使用语音合成服务。'),
        ('segment-2', '现在开始验证连续分段的合成和播放顺序。'),
        ('segment-3', '本次验证已经完成，感谢您的耐心等待。'),
    ]
    pcm, results = [], []
    for segment_id, text in inputs:
        audio, result = consume(engine, text, segment_id, cfg['sample_rate_hz'])
        pcm.append(audio)
        results.append(result)
    fallback_text = '我们正在验证没有标点的长句能否自动分段并保持语音连续' * 8
    fallback_text = fallback_text[:170]
    native = list(engine.model.frontend.text_normalize(fallback_text, split=True))
    if not any(engine._unit_count(part) > cfg['model_segment_units'] for part in native):
        raise ValueError('validation text did not exercise oversized native output')
    subdivisions = len(engine.subdivide(fallback_text))
    audio, fallback = consume(engine, fallback_text, 'fallback', cfg['sample_rate_hz'])
    pcm.append(audio)
    write_pcm(args.output, b''.join(pcm))
    report = build_report(cfg, load_seconds, memory, results,
                          [item[0] for item in inputs], subdivisions, args.output)
    report['fallback'] = fallback
    report['fallback_input_characters'] = len(fallback_text)
    report['memory_after_validation'] = torch_memory(torch)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print(f'validation failed: {type(error).__name__}: {error}', file=sys.stderr)
        raise SystemExit(1)
