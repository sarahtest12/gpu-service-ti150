#!/usr/bin/env bash
set -euo pipefail
VLM_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$VLM_PROJECT_DIR"

if [[ -e .venv ]]; then
  if ! .venv/bin/python -c 'import pathlib,sys; assert pathlib.Path(sys.prefix).resolve() == pathlib.Path.cwd()/".venv"' 2>/dev/null ||
     ! grep -Fq "VIRTUAL_ENV=$VLM_PROJECT_DIR/.venv" .venv/bin/activate; then
    VLM_STALE_DIR="$VLM_PROJECT_DIR/.venv.stale-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    mv "$VLM_PROJECT_DIR/.venv" "$VLM_STALE_DIR"
    printf 'Preserved previous environment: %s\n' "$VLM_STALE_DIR"
  fi
fi
if [[ ! -x .venv/bin/python ]]; then
  /usr/local/bin/python3.10 -m venv --system-site-packages .venv
fi
# Accelerator packages are supplied by this host image; never upgrade them here.
.venv/bin/python scripts/service.py check
.venv/bin/python scripts/service.py init-key
