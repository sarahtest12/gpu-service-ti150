#!/usr/bin/env bash
set -euo pipefail

TTS_300M_SFT_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TTS_300M_SFT_PROJECT_DIR"
umask 077

TTS_300M_SFT_PREVIOUS_VENV=""
restore_previous_venv() {
  TTS_300M_SFT_BOOTSTRAP_STATUS=$?
  if [[ $TTS_300M_SFT_BOOTSTRAP_STATUS -ne 0 && -n "$TTS_300M_SFT_PREVIOUS_VENV" ]]; then
    if [[ -e .venv || -L .venv ]]; then
      TTS_300M_SFT_FAILED_VENV="$TTS_300M_SFT_PROJECT_DIR/.venv.failed-$(date -u +%Y%m%dT%H%M%SZ)-$$"
      mv .venv "$TTS_300M_SFT_FAILED_VENV"
      printf 'Preserved failed environment: %s\n' "$TTS_300M_SFT_FAILED_VENV" >&2
    fi
    mv "$TTS_300M_SFT_PREVIOUS_VENV" .venv
    printf 'Restored previous environment after bootstrap failure.\n' >&2
  fi
  exit "$TTS_300M_SFT_BOOTSTRAP_STATUS"
}
trap restore_previous_venv EXIT

if [[ -e .venv || -L .venv ]]; then
  TTS_300M_SFT_PREVIOUS_VENV="$TTS_300M_SFT_PROJECT_DIR/.venv.stale-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  mv .venv "$TTS_300M_SFT_PREVIOUS_VENV"
fi
/usr/local/bin/python3.10 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --ignore-installed --no-deps --require-hashes \
  -r requirements-build.lock
.venv/bin/python -m pip install --ignore-installed --no-deps --no-build-isolation \
  --require-hashes -r requirements.lock

.venv/bin/python scripts/service.py check
.venv/bin/python scripts/service.py init-key

trap - EXIT
if [[ -n "$TTS_300M_SFT_PREVIOUS_VENV" ]]; then
  printf 'Preserved previous environment: %s\n' "$TTS_300M_SFT_PREVIOUS_VENV"
fi
