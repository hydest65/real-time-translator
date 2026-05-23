from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from .terminology import build_hotword_text, build_meeting_prompt

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HF_CACHE = PROJECT_ROOT / ".cache" / "huggingface"
DEFAULT_HF_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(DEFAULT_HF_CACHE))
os.environ.setdefault("HF_HUB_CACHE", str(DEFAULT_HF_CACHE / "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE", str(DEFAULT_HF_CACHE / "transformers"))

VIDEO_OUTRO_HALLUCINATION_RE = re.compile(
    r"(?:^|(?<=[\s.!?;:,]))"
    r"("
    r"(?:thank\s+you|thanks)(?:\s+so\s+much)?\s+for\s+(?:watching|your\s+attention)"
    r"(?:\s+(?:this|the)\s+video)?"
    r"|(?:please\s+)?(?:like\s+and\s+)?subscribe"
    r"|see\s+you\s+(?:next\s+time|in\s+the\s+next\s+video)"
    r")"
    r"[.!?]*",
    re.IGNORECASE,
)


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
        beam_size: int = 3,
        best_of: int = 3,
        patience: float = 1.2,
        condition_on_previous_text: bool = True,
        no_speech_threshold: float = 0.58,
        log_prob_threshold: float = -1.1,
        compression_ratio_threshold: float = 2.4,
        hallucination_silence_threshold: float = 1.2,
        repetition_penalty: float = 1.08,
        no_repeat_ngram_size: int = 3,
        hotwords_enabled: bool = False,
        use_default_hotwords: bool = False,
    ) -> None:
        self.model_size = model_size
        self.requested_device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.best_of = best_of
        self.patience = patience
        self.condition_on_previous_text = condition_on_previous_text
        self.no_speech_threshold = no_speech_threshold
        self.log_prob_threshold = log_prob_threshold
        self.compression_ratio_threshold = compression_ratio_threshold
        self.hallucination_silence_threshold = hallucination_silence_threshold
        self.repetition_penalty = repetition_penalty
        self.no_repeat_ngram_size = no_repeat_ngram_size
        self.meeting_prompt = build_meeting_prompt(limit=80, include_defaults=use_default_hotwords) if hotwords_enabled else ""
        self.hotword_text = build_hotword_text(limit=80, include_defaults=use_default_hotwords) if hotwords_enabled else ""
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

    def _load_model(self, device: str) -> Any:
        from faster_whisper import WhisperModel

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
            beam_size=self.beam_size,
            best_of=self.best_of,
            patience=self.patience,
            repetition_penalty=self.repetition_penalty,
            no_repeat_ngram_size=self.no_repeat_ngram_size,
            temperature=0,
            condition_on_previous_text=self.condition_on_previous_text,
            initial_prompt=self.meeting_prompt if language == "en" and self.meeting_prompt else None,
            hotwords=self.hotword_text if language == "en" and self.hotword_text else None,
            no_speech_threshold=self.no_speech_threshold,
            log_prob_threshold=self.log_prob_threshold,
            compression_ratio_threshold=self.compression_ratio_threshold,
            hallucination_silence_threshold=self.hallucination_silence_threshold,
            vad_parameters={
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 250,
            },
        )

        results: list[TranscriptionResult] = []
        for segment in segments:
            text = clean_transcription_text(segment.text)
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


def clean_transcription_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = VIDEO_OUTRO_HALLUCINATION_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s*,\s*(?=(?:and|also|then)\b)", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"([.!?])\s+(?:and|also|then)\s+(?=[A-Z])", r"\1 ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    cleaned = re.sub(r"([,.!?;:]){2,}", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" \t\r\n,.;:-")
    if cleaned.lower() in {"and", "also", "then", "but", "so", "please"}:
        return ""
    return cleaned.strip()
