from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HF_CACHE = PROJECT_ROOT / ".cache" / "huggingface"
DEFAULT_HF_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(DEFAULT_HF_CACHE))
os.environ.setdefault("HF_HUB_CACHE", str(DEFAULT_HF_CACHE / "hub"))

from faster_whisper import WhisperModel


@dataclass
class TranscriptionResult:
    text: str
    start_seconds: float
    end_seconds: float


class WhisperASR:
    """Low-latency faster-whisper wrapper with CUDA/int8 preference and CPU fallback."""

    def __init__(
        self,
        model_size: str = "base.en",
        device: Literal["auto", "cuda", "cpu"] = "cuda",
        compute_type: str = "int8",
    ) -> None:
        self.model_size = model_size
        self.requested_device = device
        self.compute_type = compute_type
        self.device = self._resolve_device(device)
        self.model = self._load_model(self.device)

    def _resolve_device(self, device: Literal["auto", "cuda", "cpu"]) -> str:
        if device == "cpu":
            return "cpu"
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"

    def _load_model(self, device: str) -> WhisperModel:
        try:
            return WhisperModel(self.model_size, device=device, compute_type=self.compute_type)
        except Exception:
            if device == "cuda":
                self.device = "cpu"
                return WhisperModel(self.model_size, device="cpu", compute_type="int8")
            raise

    async def transcribe(
        self,
        samples: np.ndarray,
        chunk_start_seconds: float,
        language: str = "en",
    ) -> list[TranscriptionResult]:
        return await asyncio.to_thread(self._transcribe_sync, samples, chunk_start_seconds, language)

    def _transcribe_sync(
        self,
        samples: np.ndarray,
        chunk_start_seconds: float,
        language: str,
    ) -> list[TranscriptionResult]:
        segments, _ = self.model.transcribe(
            samples,
            language=language,
            vad_filter=True,
            beam_size=1,
            best_of=1,
            temperature=0,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            vad_parameters={"min_silence_duration_ms": 350},
        )

        results: list[TranscriptionResult] = []
        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue
            results.append(
                TranscriptionResult(
                    text=text,
                    start_seconds=chunk_start_seconds + float(segment.start),
                    end_seconds=chunk_start_seconds + float(segment.end),
                )
            )
        return results
