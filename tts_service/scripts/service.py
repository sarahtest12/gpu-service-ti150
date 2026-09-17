#!/usr/bin/env python3
"""Provision, validate, and run Fun-CosyVoice3 on the vendor CoreX stack."""

import argparse
from array import array
import base64
import csv
import hashlib
from importlib.metadata import distributions, packages_distributions, version
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import wave


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/server.json"
KEY = ROOT / "runtime/api_key"
PYTHON = ROOT / ".venv/bin/python"
VENV_SITE = ROOT / ".venv/lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
COREX = Path("/usr/local/corex")
BASE_PACKAGE_ROOTS = {
    "corex": (COREX / "lib64/python3/dist-packages").resolve(),
    "system": Path("/usr/local/lib/python3.10/site-packages").resolve(),
}
LOCK_FILES = (ROOT / "requirements-build.lock", ROOT / "requirements.lock")
# This host exports CoreX through PYTHONPATH globally.  Put the service's pinned
# frontend packages ahead of that vendor directory while continuing to import
# torch and torchaudio from CoreX.
if str(VENV_SITE) in sys.path:
    sys.path.remove(str(VENV_SITE))
sys.path.insert(0, str(VENV_SITE))
EXPECTED = {
    "torch": "2.7.1+corex.4.4.0",
    "torchaudio": "2.7.1+corex.4.4.0",
    "onnxruntime": "1.17.3",
    "HyperPyYAML": "1.2.3",
    "transformers": "4.51.3",
    "x-transformers": "2.11.24",
    "diffusers": "0.29.0",
    "openai-whisper": "20231117",
    "inflect": "7.3.1",
    "omegaconf": "2.3.0",
    "ruamel.yaml": "0.17.40",
    "hydra-core": "1.3.2",
    "lightning": "2.2.4",
    "gdown": "5.1.0",
    "wget": "3.2",
    "pyworld": "0.3.4",
    "huggingface-hub": "0.36.2",
    "tokenizers": "0.21.4",
    "einops": "0.8.2",
    "fsspec": "2024.12.0",
    "packaging": "24.2",
    "websockets": "15.0.1",
}
REQUIRED_MODEL_FILES = (
    "cosyvoice3.yaml", "config.json", "llm.pt", "flow.pt", "hift.pt", "campplus.onnx",
    "speech_tokenizer_v3.onnx", "CosyVoice-BlankEN/config.json",
    "CosyVoice-BlankEN/generation_config.json", "CosyVoice-BlankEN/model.safetensors",
    "CosyVoice-BlankEN/merges.txt",
    "CosyVoice-BlankEN/tokenizer_config.json", "CosyVoice-BlankEN/vocab.json",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def positive(cfg, key, *, integer=False, maximum=None, allow_zero=False):
    value = cfg[key]
    valid_type = type(value) is int if integer else type(value) in (int, float)
    lower_ok = value >= 0 if allow_zero else value > 0
    if not valid_type or not lower_ok or (not integer and not math.isfinite(value)):
        raise ValueError(f"invalid {key}")
    if maximum is not None and value > maximum:
        raise ValueError(f"invalid {key}")


def revision(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError(f"invalid {name}")


def canonical_package_name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def locked_packages(lock_files=None):
    if lock_files is None:
        lock_files = LOCK_FILES
    packages = {}
    for lock_path in lock_files:
        for line in Path(lock_path).read_text().splitlines():
            match = re.match(r"([A-Za-z0-9_.-]+)==([^ \\]+)", line)
            if match:
                packages[canonical_package_name(match.group(1))] = match.group(2)
    if not packages:
        raise ValueError("Python package locks are empty")
    return packages


def distribution_map(path):
    found = {}
    for package in distributions(path=[str(path)]):
        name = canonical_package_name(package.metadata["Name"])
        if name in found:
            raise ValueError(f"duplicate Python distribution in {path}: {name}")
        found[name] = package
    return found


def read_base_package_manifest(cfg):
    path = Path(cfg["base_packages"])
    if not path.is_absolute() or not path.is_file():
        raise ValueError("base_packages must be an existing absolute file")
    manifest = json.loads(path.read_text())
    packages = manifest.get("packages")
    if manifest.get("schema_version") != 1 or not isinstance(packages, dict) or not packages:
        raise ValueError("invalid base package manifest")
    for key, item in packages.items():
        if (canonical_package_name(key) != key
                or not isinstance(item, dict)
                or set(item) != {"name", "version", "root", "record_sha256"}
                or canonical_package_name(item.get("name", "")) != key
                or not isinstance(item.get("version"), str)
                or not item["version"]
                or item.get("root") not in BASE_PACKAGE_ROOTS
                or not re.fullmatch(r"[0-9a-f]{64}", item.get("record_sha256", ""))):
            raise ValueError(f"invalid base package manifest entry: {key}")
    return packages


def validate_local_packages():
    expected = locked_packages()
    installed = distribution_map(VENV_SITE)
    permitted_tools = {"pip", "setuptools"}
    actual = set(installed) - permitted_tools
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise ValueError(f"service-local package set mismatch: missing={missing}, extra={extra}")
    for name, expected_version in expected.items():
        actual_version = installed[name].version
        if actual_version != expected_version:
            raise ValueError(
                f"{name} version mismatch: expected {expected_version}, got {actual_version}"
            )


def validate_base_packages(cfg):
    packages = read_base_package_manifest(cfg)
    installed_by_root = {
        root_name: distribution_map(root_path)
        for root_name, root_path in BASE_PACKAGE_ROOTS.items()
    }
    for name, expected in packages.items():
        package = installed_by_root[expected["root"]].get(name)
        if package is None:
            raise ValueError(f"base package is missing: {name}")
        if package.version != expected["version"]:
            raise ValueError(
                f"{name} version mismatch: expected {expected['version']}, got {package.version}"
            )
        record = next((Path(package.locate_file(item)) for item in package.files or ()
                       if str(item).endswith(".dist-info/RECORD")), None)
        if (record is None or not record.is_file()
                or BASE_PACKAGE_ROOTS[expected["root"]] not in record.resolve().parents
                or sha256(record) != expected["record_sha256"]):
            raise ValueError(f"base package RECORD mismatch: {name}")
        install_prefix = BASE_PACKAGE_ROOTS[expected["root"]].parents[2]
        with record.open(newline="") as record_file:
            for relative, encoded_digest, size in csv.reader(record_file):
                if (not encoded_digest or "__pycache__" in Path(relative).parts
                        or relative.endswith((".pyc", ".pyo"))):
                    continue
                algorithm, separator, value = encoded_digest.partition("=")
                if algorithm != "sha256" or not separator:
                    raise ValueError(f"unsupported RECORD digest for base package: {name}")
                installed_file = Path(package.locate_file(relative)).resolve()
                if not installed_file.is_file() and relative.startswith("../"):
                    # The BI150 image keeps wheel entry points and shared data
                    # under site-packages instead of their ../../bin or
                    # ../../share wheel destinations.
                    relative_parts = list(Path(relative).parts)
                    while relative_parts and relative_parts[0] in ("..", "."):
                        relative_parts.pop(0)
                    relocated = BASE_PACKAGE_ROOTS[expected["root"]].joinpath(
                        *relative_parts,
                    ).resolve()
                    if relocated.is_file():
                        installed_file = relocated
                if (not installed_file.is_file()
                        or install_prefix not in installed_file.parents
                        or (size and installed_file.stat().st_size != int(size))):
                    raise ValueError(f"base package file mismatch: {name}: {relative}")
                expected_digest = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
                actual_digest = bytes.fromhex(sha256(installed_file))
                if actual_digest != expected_digest:
                    raise ValueError(f"base package file mismatch: {name}: {relative}")


def validate_imported_packages(cfg):
    allowed = set(locked_packages()) | set(read_base_package_manifest(cfg)) | {
        "pip", "setuptools",
    }
    package_mapping = packages_distributions()
    imported = set()
    for module_name, module in sys.modules.items():
        if module is None:
            continue
        imported.update(
            canonical_package_name(name)
            for name in package_mapping.get(module_name.split(".")[0], ())
        )
    unexpected = sorted(imported - allowed)
    if unexpected:
        raise ValueError(f"unlocked imported Python packages: {unexpected}")


def git_output(source, *args):
    try:
        return subprocess.run(
            ["git", "-C", str(source), *args], check=True, capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise ValueError("pinned CosyVoice source is not a valid checkout") from error


def validate_source_checkout(cfg):
    source = Path(cfg["source"])
    if git_output(source, "rev-parse", "HEAD").decode().strip() != cfg["source_revision"]:
        raise ValueError("pinned CosyVoice source revision mismatch")
    patch = Path(cfg["source_patch"])
    if not patch.is_file() or sha256(patch) != cfg["source_patch_sha256"]:
        raise ValueError("pinned CosyVoice patch mismatch")
    expected_status = {f" M {name}" for name in cfg["source_checksums"]}
    actual_status = set(git_output(
        source, "status", "--porcelain=v1", "--untracked-files=all",
    ).decode().splitlines())
    if actual_status != expected_status:
        raise ValueError("pinned CosyVoice working tree mismatch")
    tree_diff = git_output(source, "diff", "--no-ext-diff", "--binary", "HEAD", "--", ".")
    if hashlib.sha256(tree_diff).hexdigest() != cfg["source_tree_diff_sha256"]:
        raise ValueError("pinned CosyVoice source diff mismatch")

    configured = cfg["source_submodules"]
    observed = {}
    for line in git_output(source, "submodule", "status", "--recursive").decode().splitlines():
        if not line or line[0] != " ":
            raise ValueError("pinned CosyVoice submodule is not clean")
        fields = line[1:].split()
        if len(fields) < 2:
            raise ValueError("invalid CosyVoice submodule status")
        observed[fields[1]] = fields[0]
    if observed != configured:
        raise ValueError("pinned CosyVoice submodule revision mismatch")
    for relative, expected_revision in configured.items():
        submodule = source / relative
        if (git_output(submodule, "rev-parse", "HEAD").decode().strip() != expected_revision
                or git_output(
                    submodule, "status", "--porcelain=v1", "--untracked-files=all",
                ).strip()):
            raise ValueError(f"pinned CosyVoice submodule mismatch: {relative}")


def resolve_config_paths(cfg, config_path):
    """Resolve checkout-owned paths relative to the config file."""
    base = Path(config_path).resolve().parent
    for key in ("source", "source_patch", "voice_manifest", "prompt_wav", "base_packages"):
        value = cfg.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"invalid {key}")
        path = Path(value)
        cfg[key] = str(path if path.is_absolute() else (base / path).resolve())
    return cfg


def validate_voice_audio(path, derived):
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            payload = source.readframes(frame_count)
    except (EOFError, wave.Error) as error:
        raise ValueError("fixed voice must be PCM WAV") from error
    if (channels != 1 or sample_width != 2
            or sample_rate != derived["sample_rate_hz"]
            or frame_count != derived["samples"]):
        raise ValueError("fixed voice audio metadata mismatch")
    duration = frame_count / sample_rate
    if (not 5 <= duration <= 10
            or not math.isclose(duration, derived["duration_seconds"], abs_tol=1e-6)):
        raise ValueError("fixed voice effective duration must be 5 to 10 seconds")
    samples = array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples or any(abs(value) >= 32767 for value in samples):
        raise ValueError("fixed voice is empty or clipped")
    active_threshold = round(32767 * 0.01)
    first_active = next((index for index, value in enumerate(samples)
                         if abs(value) >= active_threshold), len(samples))
    last_active = next((index for index, value in enumerate(reversed(samples))
                        if abs(value) >= active_threshold), len(samples))
    leading_silence = first_active / sample_rate
    trailing_silence = last_active / sample_rate
    if (first_active == len(samples)
            or not 0.05 <= leading_silence <= 0.5
            or not 0.05 <= trailing_silence <= 0.5):
        raise ValueError("fixed voice edge silence must be 0.05 to 0.5 seconds")
    edge = list(samples[:first_active]) + list(samples[len(samples) - last_active:])
    if edge:
        rms = math.sqrt(sum(value * value for value in edge) / len(edge))
        noise_dbfs = 20 * math.log10(max(rms, 1.0) / 32767)
        if noise_dbfs > -45:
            raise ValueError("fixed voice edge noise exceeds -45 dBFS")
    frame_size = sample_rate // 50
    frame_rms = []
    active_end = len(samples) - last_active
    for offset in range(first_active, active_end - frame_size + 1, frame_size):
        frame = samples[offset:offset + frame_size]
        frame_rms.append(math.sqrt(sum(value * value for value in frame) / len(frame)))
    if len(frame_rms) < 20:
        raise ValueError("fixed voice has too little speech for a noise estimate")
    frame_rms.sort()
    quiet_count = max(1, len(frame_rms) // 20)
    speech_count = max(1, len(frame_rms) // 2)
    noise_rms = math.sqrt(sum(value * value for value in frame_rms[:quiet_count])
                          / quiet_count)
    speech_rms = math.sqrt(sum(value * value for value in frame_rms[-speech_count:])
                           / speech_count)
    snr_db = 20 * math.log10(max(speech_rms, 1.0) / max(noise_rms, 1.0))
    if snr_db < 25:
        raise ValueError("fixed voice estimated SNR is below 25 dB")


def validate_transcript_index(manifest, content):
    transcripts = {}
    for line in content.splitlines():
        fields = line.split()
        if len(fields) >= 3 and len(fields) % 2 == 1:
            transcripts[fields[0]] = "".join(fields[1::2])
    for item in manifest["dataset"]["utterances"]:
        filename = Path(item["path"]).name
        if transcripts.get(filename) != item["transcript"]:
            raise ValueError(f"AISHELL-3 transcript mismatch: {filename}")


def read_voice_manifest(cfg, *, require_audio):
    manifest_path = Path(cfg["voice_manifest"])
    prompt_wav = Path(cfg["prompt_wav"])
    if not manifest_path.is_absolute() or not manifest_path.is_file():
        raise ValueError("voice_manifest must be an existing absolute file")
    if not prompt_wav.is_absolute():
        raise ValueError("prompt_wav must be an absolute path")
    if not re.fullmatch(r"[0-9a-f]{64}", cfg.get("voice_manifest_sha256", "")):
        raise ValueError("invalid fixed voice manifest checksum")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("voice_id") != cfg["voice_id"] or cfg["voice_id"] != "aishell3-female":
        raise ValueError("fixed voice ID mismatch")
    prompt_text = manifest.get("prompt_text")
    if not isinstance(prompt_text, str) or not prompt_text.strip() or "\x00" in prompt_text:
        raise ValueError("invalid fixed voice prompt text")
    dataset = manifest.get("dataset", {})
    speaker = dataset.get("speaker", {})
    if (dataset.get("repository") != "AISHELL/AISHELL-3"
            or dataset.get("license") != "Apache-2.0"
            or speaker.get("gender") != "female"):
        raise ValueError("unexpected AISHELL-3 voice provenance")
    revision(dataset.get("revision"), "AISHELL-3 revision")
    utterances = dataset.get("utterances")
    transcript_index = dataset.get("transcript_index", {})
    if (not isinstance(transcript_index.get("path"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", transcript_index.get("sha256", ""))):
        raise ValueError("invalid AISHELL-3 transcript index")
    if not isinstance(utterances, list) or not utterances:
        raise ValueError("voice manifest has no utterances")
    for item in utterances:
        if (not isinstance(item.get("path"), str)
                or not isinstance(item.get("transcript"), str)
                or not item["transcript"].strip()
                or not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", ""))
                or type(item.get("trim_start_sample")) is not int
                or type(item.get("trim_end_sample")) is not int
                or item["trim_start_sample"] < 0
                or item["trim_end_sample"] <= item["trim_start_sample"]):
            raise ValueError("invalid voice utterance manifest")
    expected_prompt = "You are a helpful assistant.<|endofprompt|>" + "".join(
        item.get("transcript", "") for item in utterances
    )
    if prompt_text != expected_prompt:
        raise ValueError("fixed voice prompt text must include the CosyVoice3 endofprompt prefix")
    derived = manifest.get("derived", {})
    if (derived.get("sample_rate_hz") != cfg["sample_rate_hz"]
            or derived.get("channels") != 1
            or type(derived.get("samples")) is not int
            or derived["samples"] < 1
            or type(derived.get("duration_seconds")) not in (int, float)
            or not math.isfinite(derived["duration_seconds"])
            or derived["duration_seconds"] <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", derived.get("sha256", ""))):
        raise ValueError("invalid derived voice manifest")
    if require_audio:
        if not prompt_wav.is_file() or sha256(prompt_wav) != derived["sha256"]:
            raise ValueError("fixed voice audio mismatch")
        validate_voice_audio(prompt_wav, derived)
    if sha256(manifest_path) != cfg["voice_manifest_sha256"]:
        raise ValueError("fixed voice manifest mismatch")
    return manifest


def config(*, require_artifacts=True):
    cfg = json.loads(CONFIG.read_text())
    resolve_config_paths(cfg, CONFIG)
    if not ipaddress.ip_address(cfg["host"]).is_loopback:
        raise ValueError("TTS must listen on loopback; expose it only through the gateway")
    positive(cfg, "port", integer=True, maximum=65535)
    positive(cfg, "device", integer=True, maximum=64, allow_zero=True)
    positive(cfg, "sample_rate_hz", integer=True, maximum=192000)
    positive(cfg, "max_input_chunk_characters", integer=True, maximum=4096)
    positive(cfg, "max_utterance_characters", integer=True, maximum=10000)
    positive(cfg, "max_message_bytes", integer=True, maximum=1024 * 1024)
    positive(cfg, "input_timeout_seconds", integer=True, maximum=3600)
    positive(cfg, "session_idle_timeout_seconds", integer=True, maximum=86400)
    positive(cfg, "text_queue_chunks", integer=True, maximum=1024)
    positive(cfg, "text_queue_timeout_seconds", integer=True, maximum=300)
    positive(cfg, "output_timeout_seconds", integer=True, maximum=300)
    positive(cfg, "max_concurrency", integer=True, maximum=4)
    positive(cfg, "minimum_free_memory_mb", integer=True, maximum=32768)
    revision(cfg["model_revision"], "model_revision")
    revision(cfg["source_revision"], "source_revision")
    if (not re.fullmatch(r"[0-9a-f]{64}", cfg.get("source_patch_sha256", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", cfg.get("source_tree_diff_sha256", ""))
            or not isinstance(cfg.get("source_submodules"), dict)):
        raise ValueError("invalid pinned CosyVoice source metadata")
    for relative, submodule_revision in cfg["source_submodules"].items():
        if (not isinstance(relative, str) or not relative
                or Path(relative).is_absolute() or ".." in Path(relative).parts):
            raise ValueError("invalid CosyVoice submodule path")
        revision(submodule_revision, "CosyVoice submodule revision")
    if (cfg["model_name"] != "fun-cosyvoice3-0.5b-2512"
            or cfg["device"] != 0
            or cfg["sample_rate_hz"] != 24000
            or cfg["max_concurrency"] != 1):
        raise ValueError("unexpected CosyVoice3 deployment boundary")
    if cfg["max_input_chunk_characters"] > cfg["max_utterance_characters"]:
        raise ValueError("input chunk limit exceeds utterance limit")
    if (cfg["load_vllm"], cfg["load_trt"], cfg["fp16"]) != (False, False, True):
        raise ValueError("this deployment uses native PyTorch FP16 bi-streaming")
    if (not isinstance(cfg.get("model_checksums"), dict)
            or set(cfg["model_checksums"]) != set(REQUIRED_MODEL_FILES)
            or not all(re.fullmatch(r"[0-9a-f]{64}", value or "")
                       for value in cfg["model_checksums"].values())):
        raise ValueError("model_checksums must pin every required model artifact")
    read_base_package_manifest(cfg)

    model, source = Path(cfg["model"]), Path(cfg["source"])
    if not model.is_absolute():
        raise ValueError("model path must be absolute")
    cfg["prompt_text"] = read_voice_manifest(cfg, require_audio=require_artifacts)["prompt_text"]
    if not require_artifacts:
        return cfg
    if not model.is_dir():
        raise ValueError("model must be an existing absolute directory")
    if not (source / "cosyvoice").is_dir():
        raise ValueError("pinned CosyVoice source is missing")
    missing = [name for name in REQUIRED_MODEL_FILES if not (model / name).is_file()]
    if missing:
        raise ValueError("CosyVoice3 checkpoint is incomplete: " + ", ".join(missing))
    if not (source / "third_party/Matcha-TTS/matcha").is_dir():
        raise ValueError("CosyVoice Matcha-TTS submodule is missing")
    for name, expected in cfg["source_checksums"].items():
        path = source / name
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"pinned CosyVoice source mismatch: {name}")
    for name, expected in cfg["model_checksums"].items():
        path = model / name
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"CosyVoice3 checkpoint mismatch: {name}")
    return cfg


def environment(cfg):
    source = Path(cfg["source"])
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.update({
        "PYTHONPATH": ":".join((str(source), str(source / "third_party/Matcha-TTS"),
                                str(VENV_SITE), str(COREX / "lib64/python3/dist-packages"))),
        "PATH": f"{ROOT}/.venv/bin:{COREX}/bin:/usr/local/bin:/usr/bin:/bin",
        "LD_LIBRARY_PATH": f"{COREX}/lib64:/usr/local/lib:/usr/local/openmpi/lib",
        "VIRTUAL_ENV": str(ROOT / ".venv"),
        "CUDA_VISIBLE_DEVICES": str(cfg["device"]),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": "4",
    })
    return env


def init_key():
    KEY.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not KEY.exists():
        fd = os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(secrets.token_urlsafe(32) + "\n")
    if KEY.stat().st_mode & 0o077:
        raise ValueError(f"TTS internal credential must have mode 0600: {KEY}")
    token = KEY.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_~.\-]{24,256}", token):
        raise ValueError("invalid TTS internal credential")


def prepare_voice(cfg):
    from huggingface_hub import hf_hub_download
    import torch
    import torchaudio

    manifest = read_voice_manifest(cfg, require_audio=False)
    dataset = manifest["dataset"]
    transcript_index = dataset["transcript_index"]
    index_path = Path(hf_hub_download(
        repo_id=dataset["repository"],
        repo_type="dataset",
        revision=dataset["revision"],
        filename=transcript_index["path"],
    ))
    if sha256(index_path) != transcript_index["sha256"]:
        raise ValueError("AISHELL-3 transcript index mismatch")
    validate_transcript_index(manifest, index_path.read_text())
    segments = []
    for item in dataset["utterances"]:
        source = Path(hf_hub_download(
            repo_id=dataset["repository"],
            repo_type="dataset",
            revision=dataset["revision"],
            filename=item["path"],
        ))
        if sha256(source) != item["sha256"]:
            raise ValueError(f"AISHELL-3 source mismatch: {item['path']}")
        audio, sample_rate = torchaudio.load(source)
        if (audio.shape[0] != 1 or sample_rate != item["sample_rate_hz"]
                or audio.shape[1] != item["samples"]):
            raise ValueError(f"AISHELL-3 audio metadata mismatch: {item['path']}")
        segments.append(audio[:, item["trim_start_sample"]:item["trim_end_sample"]])
    audio = torch.cat(segments, dim=1)
    audio = torchaudio.functional.resample(
        audio, dataset["utterances"][0]["sample_rate_hz"],
        manifest["derived"]["sample_rate_hz"],
    )
    if audio.shape != (1, manifest["derived"]["samples"]):
        raise ValueError("derived fixed voice sample count mismatch")
    target = Path(cfg["prompt_wav"])
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_name(target.name + ".tmp.wav")
    torchaudio.save(str(temporary), audio, manifest["derived"]["sample_rate_hz"],
                    encoding="PCM_S", bits_per_sample=16)
    if sha256(temporary) != manifest["derived"]["sha256"]:
        temporary.unlink(missing_ok=True)
        raise ValueError("derived fixed voice checksum mismatch")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    read_voice_manifest(cfg, require_audio=True)


def check(cfg):
    if Path(sys.executable).resolve() != PYTHON.resolve():
        raise ValueError(f"run this command with {PYTHON}")
    validate_local_packages()
    validate_base_packages(cfg)
    validate_source_checkout(cfg)
    for package, expected in EXPECTED.items():
        actual = version(package)
        if actual != expected:
            raise ValueError(f"{package} version mismatch: expected {expected}, got {actual}")
    probe = f"""
import onnxruntime
import torch
from cosyvoice.cli.cosyvoice import AutoModel
assert '/usr/local/corex' in torch.__file__
assert torch.cuda.is_available(), 'CoreX CUDA is unavailable'
assert torch.cuda.device_count() == 1, 'CUDA_VISIBLE_DEVICES must expose exactly one GPU'
free_bytes, total_bytes = torch.cuda.mem_get_info()
assert free_bytes >= {cfg["minimum_free_memory_mb"]} * 1024 * 1024, 'insufficient free GPU memory'
probe = torch.ones(1, device='cuda', dtype=torch.float16)
assert probe.is_cuda and probe.dtype == torch.float16
providers = onnxruntime.get_available_providers()
assert 'CPUExecutionProvider' in providers
assert 'CUDAExecutionProvider' not in providers
print('CosyVoice3 imports and CoreX runtime: PASS')
"""
    subprocess.run([str(PYTHON), "-c", probe], cwd=ROOT, env=environment(cfg), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "init-key", "prepare-voice", "run"))
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == "prepare-voice":
        cfg = config(require_artifacts=False)
        prepare_voice(cfg)
        print(f"Pinned AISHELL-3 voice ready: {cfg['prompt_wav']}")
        return
    cfg = config()
    if args.action == "check":
        check(cfg)
        print("TTS environment, pinned model, source and voice: PASS")
        return
    if args.action == "init-key":
        init_key()
        print(f"TTS internal credential ready: {KEY} (value not displayed)")
        return
    check(cfg)
    with socket.socket(socket.AF_INET6 if ":" in cfg["host"] else socket.AF_INET) as probe:
        probe.settimeout(1)
        if probe.connect_ex((cfg["host"], cfg["port"])) == 0:
            raise RuntimeError("TTS port is already in use")
    init_key()
    command = [str(PYTHON), "scripts/server.py", "--config", str(CONFIG), "--key-file", str(KEY)]
    os.execvpe(command[0], command, environment(cfg))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
