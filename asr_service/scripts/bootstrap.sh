#!/usr/bin/env bash
set -euo pipefail
ASR_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ASR_PROJECT_DIR"
umask 077

FUNASR_REVISION="e42443f55971d0c804dcf2973fdd2e6e09bd5611"
FUNASR_SOURCE="$ASR_PROJECT_DIR/runtime/FunASR"
MODEL_DIR="/share/fshare/common/models/FunAudioLLM/Fun-ASR-Nano-2512"
CACHE_DIR="$ASR_PROJECT_DIR/runtime/modelscope_cache"

if [[ -e .venv ]]; then
  if ! .venv/bin/python -c 'import pathlib,sys; assert pathlib.Path(sys.prefix).resolve() == pathlib.Path.cwd()/".venv"' 2>/dev/null ||
     ! .venv/bin/python -c 'import pathlib,sys; assert "VIRTUAL_ENV="+sys.argv[1]+"/.venv" in pathlib.Path(".venv/bin/activate").read_text()' "$ASR_PROJECT_DIR" 2>/dev/null; then
    ASR_STALE_DIR="$ASR_PROJECT_DIR/.venv.stale-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    mv .venv "$ASR_STALE_DIR"
    printf 'Preserved previous environment: %s\n' "$ASR_STALE_DIR"
  fi
fi
if [[ ! -x .venv/bin/python ]]; then
  /usr/local/bin/python3.10 -m venv --system-site-packages .venv
fi

mkdir -p runtime "$CACHE_DIR"
if [[ ! -d "$FUNASR_SOURCE/.git" ]]; then
  git clone https://github.com/modelscope/FunASR.git "$FUNASR_SOURCE"
fi
git -C "$FUNASR_SOURCE" fetch --depth 1 origin "$FUNASR_REVISION"
git -C "$FUNASR_SOURCE" checkout --detach "$FUNASR_REVISION"

# Keep the vendor torch/vLLM stack read-only and install only the realtime server's Python layer.
.venv/bin/python -m pip install --no-deps -e "$FUNASR_SOURCE"
.venv/bin/python -m pip install \
  omegaconf==2.3.0 hydra-core==1.3.2 kaldiio==2.18.1 rapidfuzz==3.14.3 torch-complex==0.4.4
.venv/bin/python -m pip install --no-deps \
  jaconv==0.4.0 jamo==0.4.1 tensorboardX==2.6.4 \
  umap-learn==0.5.7 pynndescent==0.5.13

if [[ ! -f "$MODEL_DIR/model.pt" ]]; then
  mkdir -p "$MODEL_DIR"
  MODELSCOPE_CACHE="$CACHE_DIR" .venv/bin/python -m modelscope.cli.cli download \
    --model FunAudioLLM/Fun-ASR-Nano-2512 --local_dir "$MODEL_DIR"
fi

MODELSCOPE_CACHE="$CACHE_DIR" .venv/bin/python - <<'PY'
from funasr import AutoModel
AutoModel(model="fsmn-vad", device="cpu", ncpu=1, disable_update=True)
print("Streaming VAD model: PASS")
PY

.venv/bin/python scripts/service.py check
.venv/bin/python scripts/service.py init-key
