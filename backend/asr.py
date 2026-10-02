from __future__ import annotations

import asyncio
import os
import re
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from .terminology import build_hotword_text, build_meeting_prompt

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HF_CACHE = PROJECT_ROOT / ".cache" / "huggingface"
DEFAULT_MODEL_CACHE = PROJECT_ROOT / ".model-cache"
DEFAULT_HF_CACHE.mkdir(parents=True, exist_ok=True)
DEFAULT_MODEL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(DEFAULT_HF_CACHE))
os.environ.setdefault("HF_HUB_CACHE", str(DEFAULT_HF_CACHE / "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE", str(DEFAULT_HF_CACHE / "transformers"))
os.environ.setdefault("MODELSCOPE_CACHE", str(DEFAULT_MODEL_CACHE))

try:
    from opencc import OpenCC
except Exception:
    OpenCC = None

_ZH_TO_SIMPLIFIED = OpenCC("t2s") if OpenCC is not None else None


CHINESE_INITIAL_PROMPT = (
    "\u4ee5\u4e0b\u662f\u666e\u901a\u8bdd\u4e2d\u6587\u8bed\u97f3\u8f6c\u5199\u3002"
    "\u8bf7\u4f7f\u7528\u7b80\u4f53\u4e2d\u6587\uff0c\u4fdd\u7559\u6570\u5b57\u3001"
    "\u82f1\u6587\u7f29\u5199\u548c\u4e13\u4e1a\u672f\u8bed\u3002"
)

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
            initial_prompt=self._initial_prompt(language),
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

    def _initial_prompt(self, language: str) -> str | None:
        if language == "zh":
            return CHINESE_INITIAL_PROMPT
        if language == "en" and self.meeting_prompt:
            return self.meeting_prompt
        return None


class FunASRRealtimeASR:
    """Chinese-focused local ASR for realtime chunks."""

    model_size = "iic/SenseVoiceSmall"
    device = "cpu"

    def __init__(
        self,
        model_name: str = "iic/SenseVoiceSmall",
        device: Literal["auto", "cuda", "cpu"] = "auto",
    ) -> None:
        from funasr import AutoModel
        import torch

        self.model_size = model_name
        if device == "cuda" and torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"
        self.model = AutoModel(
            model=model_name,
            device=self.device,
            disable_update=True,
        )

    async def transcribe(
        self,
        samples: np.ndarray,
        chunk_start_seconds: float,
        language: str = "zh",
    ) -> list[TranscriptionResult]:
        return await asyncio.to_thread(self._transcribe_sync, samples, chunk_start_seconds, language)

    def _transcribe_sync(
        self,
        samples: np.ndarray,
        chunk_start_seconds: float,
        language: str,
    ) -> list[TranscriptionResult]:
        if samples.size == 0:
            return []
        with tempfile.NamedTemporaryFile(prefix="funasr-realtime-", suffix=".wav", delete=False) as file:
            temp_path = Path(file.name)
        try:
            write_mono_wav(temp_path, samples, 16000)
            output = self.model.generate(
                input=str(temp_path),
                language="zh",
                use_itn=True,
                batch_size_s=8,
            )
            return normalize_funasr_output(output, chunk_start_seconds, max(0.0, len(samples) / 16000.0))
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


class FunASRParaformerASR:
    """Chinese quality ASR for final reading text."""

    model_size = "paraformer-zh"
    device = "cpu"

    def __init__(
        self,
        model_name: str = "paraformer-zh",
        device: Literal["auto", "cuda", "cpu"] = "auto",
        hotwords_enabled: bool = True,
    ) -> None:
        from funasr import AutoModel
        import torch

        self.model_size = model_name
        if device == "cuda" and torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"
        self.hotword_text = build_hotword_text(limit=80, include_defaults=True) if hotwords_enabled else ""
        self.model = AutoModel(
            model=model_name,
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            device=self.device,
            disable_update=True,
        )

    async def transcribe(
        self,
        samples: np.ndarray,
        chunk_start_seconds: float,
        language: str = "zh",
    ) -> list[TranscriptionResult]:
        return await asyncio.to_thread(self._transcribe_sync, samples, chunk_start_seconds, language)

    def _transcribe_sync(
        self,
        samples: np.ndarray,
        chunk_start_seconds: float,
        language: str,
    ) -> list[TranscriptionResult]:
        if samples.size == 0:
            return []
        with tempfile.NamedTemporaryFile(prefix="funasr-final-", suffix=".wav", delete=False) as file:
            temp_path = Path(file.name)
        try:
            write_mono_wav(temp_path, samples, 16000)
            output = self.model.generate(
                input=str(temp_path),
                language="zh",
                use_itn=True,
                batch_size_s=60,
                hotword=self.hotword_text,
            )
            return normalize_funasr_output(output, chunk_start_seconds, max(0.0, len(samples) / 16000.0))
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


def write_mono_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    pcm16 = (np.clip(samples.astype(np.float32, copy=False), -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(pcm16.tobytes())


def normalize_funasr_output(output: object, chunk_start_seconds: float, duration_seconds: float) -> list[TranscriptionResult]:
    records = [output] if isinstance(output, dict) else output if isinstance(output, list) else []
    results: list[TranscriptionResult] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        sentence_info = record.get("sentence_info")
        if isinstance(sentence_info, list):
            for sentence in sentence_info:
                if not isinstance(sentence, dict):
                    continue
                text = clean_transcription_text(sentence.get("text") or "")
                if not text:
                    continue
                start = chunk_start_seconds + float(sentence.get("start") or 0) / 1000.0
                end = chunk_start_seconds + float(sentence.get("end") or sentence.get("timestamp") or 0) / 1000.0
                results.append(TranscriptionResult(text=text, start_seconds=start, end_seconds=max(start, end)))
            continue
        text = clean_transcription_text(record.get("text") or "")
        if text:
            results.append(
                TranscriptionResult(
                    text=text,
                    start_seconds=chunk_start_seconds,
                    end_seconds=chunk_start_seconds + duration_seconds,
                )
            )
    return results


def clean_transcription_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"<\|[^|]+?\|>", " ", cleaned)
    if _ZH_TO_SIMPLIFIED is not None and re.search(r"[\u4e00-\u9fff]", cleaned):
        cleaned = _ZH_TO_SIMPLIFIED.convert(cleaned)
    cleaned = VIDEO_OUTRO_HALLUCINATION_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s*,\s*(?=(?:and|also|then)\b)", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"([.!?])\s+(?:and|also|then)\s+(?=[A-Z])", r"\1 ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    cleaned = re.sub(r"([,.!?;:]){2,}", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" \t\r\n,.;:-")
    if cleaned.lower() in {"and", "also", "then", "but", "so", "please"}:
        return ""
    return cleaned.strip()
