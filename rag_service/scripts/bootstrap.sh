#!/usr/bin/env bash
set -euo pipefail
RAG_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAG_PROJECT_DIR"
umask 077
if [[ -e .venv ]]; then
  if ! .venv/bin/python -c 'import pathlib,sys; assert pathlib.Path(sys.prefix).resolve() == pathlib.Path.cwd()/".venv"' 2>/dev/null ||
     ! .venv/bin/python -c 'import pathlib,sys; assert "VIRTUAL_ENV="+sys.argv[1]+"/.venv" in pathlib.Path(".venv/bin/activate").read_text()' "$RAG_PROJECT_DIR" 2>/dev/null; then
    RAG_STALE_DIR="$RAG_PROJECT_DIR/.venv.stale-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    mv .venv "$RAG_STALE_DIR"
    printf 'Preserved previous environment: %s\n' "$RAG_STALE_DIR"
  fi
fi
if [[ ! -x .venv/bin/python ]]; then
  /usr/local/bin/python3.10 -m venv --system-site-packages .venv
fi
# Reuse the image's vendor packages read-only; do not install generic GPU wheels.
.venv/bin/python scripts/service.py check
.venv/bin/python scripts/service.py init-key
