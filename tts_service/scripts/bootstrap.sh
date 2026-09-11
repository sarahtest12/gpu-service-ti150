#!/usr/bin/env bash
set -euo pipefail
TTS_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TTS_PROJECT_DIR"
umask 077

if [[ -e .venv ]]; then
  if ! .venv/bin/python -c 'import pathlib,sys; assert pathlib.Path(sys.prefix).resolve() == pathlib.Path.cwd()/".venv"' 2>/dev/null ||
     ! .venv/bin/python -c 'import pathlib,sys; assert "VIRTUAL_ENV="+sys.argv[1]+"/.venv" in pathlib.Path(".venv/bin/activate").read_text()' "$TTS_PROJECT_DIR" 2>/dev/null; then
    TTS_STALE_DIR="$TTS_PROJECT_DIR/.venv.stale-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    mv .venv "$TTS_STALE_DIR"
    printf 'Preserved previous environment: %s\n' "$TTS_STALE_DIR"
  fi
fi
if [[ ! -x .venv/bin/python ]]; then
  /usr/local/bin/python3.10 -m venv --system-site-packages .venv
fi

# Install only the Python/frontend layer. Never install upstream torch, torchaudio,
# onnxruntime-gpu, CUDA, TensorRT or vLLM wheels into the CoreX image.
.venv/bin/python -m pip install \
  onnxruntime==1.17.3 HyperPyYAML==1.2.2 inflect==7.3.1 \
  WeTextProcessing==1.0.3 omegaconf==2.3.0 conformer==0.3.2 ruamel.yaml==0.17.40 \
  hydra-core==1.3.2 lightning==2.2.4 gdown==5.1.0 wget==3.2
.venv/bin/python -m pip install --no-build-isolation --no-deps openai-whisper==20231117

.venv/bin/python scripts/service.py check
.venv/bin/python scripts/service.py init-key
