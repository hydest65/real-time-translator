from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_HF_CACHE = PROJECT_ROOT / ".cache" / "huggingface"
DEFAULT_HF_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(DEFAULT_HF_CACHE))
os.environ.setdefault("HF_HUB_CACHE", str(DEFAULT_HF_CACHE / "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE", str(DEFAULT_HF_CACHE / "transformers"))

MARKER_PATH = PROJECT_ROOT / ".model-cache" / "first-run-ready-5070ti-v1.json"
WHISPER_MEDIUM_CACHE = DEFAULT_HF_CACHE / "hub" / "models--Systran--faster-whisper-medium.en" / "snapshots"
MARIAN_CT2_MODEL = (
    PROJECT_ROOT
    / ".model-cache"
    / "marianmt-ct2"
    / "Helsinki-NLP_opus-mt-en-zh-int8_float16"
    / "model.bin"
)
MARIAN_CT2_TOKENIZER = MARIAN_CT2_MODEL.parent / "tokenizer_config.json"
PROGRESS_PREFIX = "[subtitle-studio-progress] "


def emit(status: str, detail: str, percent: int) -> None:
    payload = {"status": status, "detail": detail, "percent": max(0, min(100, percent))}
    print(f"{PROGRESS_PREFIX}{json.dumps(payload, ensure_ascii=False)}", flush=True)


def ready() -> bool:
    return MARKER_PATH.exists() and whisper_ready() and MARIAN_CT2_MODEL.exists() and MARIAN_CT2_TOKENIZER.exists()


def whisper_ready() -> bool:
    if not WHISPER_MEDIUM_CACHE.exists():
        return False
    return any(
        (snapshot / "model.bin").exists()
        and (snapshot / "config.json").exists()
        and (snapshot / "tokenizer.json").exists()
        for snapshot in WHISPER_MEDIUM_CACHE.iterdir()
        if snapshot.is_dir()
    )


def prepare_whisper() -> None:
    emit("Downloading ASR", "Checking Whisper medium.en for CUDA int8.", 12)
    from faster_whisper import WhisperModel

    WhisperModel("medium.en", device="cuda", compute_type="int8")
    emit("ASR ready", "Whisper medium.en is cached and loadable.", 45)


def prepare_marianmt() -> None:
    emit("Downloading MT", "Checking MarianMT English-Chinese tokenizer and weights.", 52)
    from backend.translator import MarianMTTranslator

    translator = MarianMTTranslator(
        "Helsinki-NLP/opus-mt-en-zh",
        "Helsinki-NLP/opus-mt-es-zh",
        "cuda",
        "ctranslate2",
        "int8_float16",
    )
    emit("Converting MT", "Preparing CTranslate2 int8_float16 model for low-latency local translation.", 70)
    translator._translate_sync("Warm up the meeting translator.", "eng_Latn")
    emit("MT ready", "MarianMT CTranslate2 model is cached and warmed.", 92)


def write_marker() -> None:
    MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    MARKER_PATH.write_text(
        json.dumps(
            {
                "ready": True,
                "profile": "5070Ti",
                "whisper": "medium.en cuda int8",
                "translation": "MarianMT CTranslate2 int8_float16",
                "updatedAt": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return 0 if ready() else 1
    if ready():
        emit("Ready", "All local 5070Ti models are already cached.", 100)
        return 0
    try:
        emit("Starting", "Preparing local 5070Ti translation models.", 3)
        prepare_whisper()
        prepare_marianmt()
        write_marker()
        emit("Ready", "Local models are ready. You can start captions now.", 100)
        return 0
    except Exception as exc:
        emit("Failed", str(exc), 0)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
