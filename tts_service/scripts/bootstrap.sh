#!/usr/bin/env bash
set -euo pipefail

TTS_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TTS_SOURCE_DIR="$TTS_PROJECT_DIR/runtime/CosyVoice"
TTS_SOURCE_REVISION=074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc
TTS_MODEL_DIR=/share/fshare/common/models/CosyVoice/Fun-CosyVoice3-0.5B-2512
TTS_MODEL_REVISION=29e01c4e8d000f4bcd70751be16fa94bf3d85a18
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

# Install only the hash-locked Python/frontend layer. The environment continues
# to use torch, torchaudio, FastAPI and CUDA from the vendor CoreX base image.
.venv/bin/python -m pip install --ignore-installed --no-deps --require-hashes \
  -r requirements-build.lock
.venv/bin/python -m pip install --ignore-installed --no-deps --no-build-isolation \
  --require-hashes -r requirements.lock

mkdir -p runtime
if [[ ! -d "$TTS_SOURCE_DIR/.git" ]]; then
  if [[ -e "$TTS_SOURCE_DIR" ]]; then
    printf 'Refusing to replace non-git CosyVoice path: %s\n' "$TTS_SOURCE_DIR" >&2
    exit 1
  fi
  git clone --no-checkout https://github.com/QwenAudio/CosyVoice.git "$TTS_SOURCE_DIR"
fi
git -C "$TTS_SOURCE_DIR" fetch --depth 1 origin "$TTS_SOURCE_REVISION"
git -C "$TTS_SOURCE_DIR" checkout --detach "$TTS_SOURCE_REVISION"
git -C "$TTS_SOURCE_DIR" reset --hard "$TTS_SOURCE_REVISION"
git -C "$TTS_SOURCE_DIR" submodule update --init --recursive --depth 1
git -C "$TTS_SOURCE_DIR" apply --check --unidiff-zero "$TTS_PROJECT_DIR/patches/corex-runtime.patch"
git -C "$TTS_SOURCE_DIR" apply --unidiff-zero "$TTS_PROJECT_DIR/patches/corex-runtime.patch"

mkdir -p "$TTS_MODEL_DIR"
TTS_MODEL_DIR="$TTS_MODEL_DIR" TTS_MODEL_REVISION="$TTS_MODEL_REVISION" \
  .venv/bin/python - <<'PY'
import os
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
    revision=os.environ["TTS_MODEL_REVISION"],
    local_dir=os.environ["TTS_MODEL_DIR"],
    allow_patterns=[
        "cosyvoice3.yaml", "config.json", "configuration.json",
        "campplus.onnx", "flow.pt", "hift.pt", "llm.pt",
        "speech_tokenizer_v3.onnx", "CosyVoice-BlankEN/*",
    ],
)
PY

.venv/bin/python scripts/service.py prepare-voice
.venv/bin/python scripts/service.py check
.venv/bin/python scripts/service.py init-key
