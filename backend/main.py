from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import numpy as np
from asr.audio_capture import StreamingAudioCapture
from asr.funasr_streaming import (
    ASR_CHUNK_MS,
    ASR_CHUNK_SIZE,
    ASR_DEVICE,
    ASR_ENABLE_PUNCTUATION,
    ASR_ENABLE_VAD,
    ASR_ENGINE,
    ASR_QUEUE_MAXSIZE,
    ASR_SAMPLE_RATE,
    FunASRStreamingASR,
    FunASRStreamingConfig,
)
from asr.subtitle_state import SubtitleState
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .audio_capture import AudioChunk, MicrophoneAudioCapture
from .asr import FunASRParaformerASR, FunASRRealtimeASR, TranscriptionResult, WhisperASR
from .cloud_speech import AzureSpeechTranslationSession, CloudSubtitle, stream_microphone_to_azure
from .config import AppConfig, config
from .terminology import build_hotword_text
from .translator import ArgosTranslator, MarianMTTranslator, NLLBTranslator, Translator


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
DATA_ROOT = Path(os.getenv("SUBTITLE_STUDIO_DATA_DIR") or ROOT)
RECORDINGS_DIR = DATA_ROOT / "recordings"
RECORDING_RESUME_SECONDS = 5 * 60
CLOUD_MONTHLY_SECONDS_LIMIT_DEFAULT = 5 * 60 * 60
CLOUD_QUOTA_GUARD_INTERVAL_SECONDS = 5
CLOUD_USAGE_LEDGER_PATH = DATA_ROOT / "sync-meta" / "cloud-usage-quota.json"
active_recording_path: Path | None = None
last_recording_stop_at = 0.0
RECORDING_PATTERNS = ("rec-*.wav", "session-*.wav")


azure_usage_cache: dict[str, Any] = {
    "fetchedAt": 0.0,
    "payload": None,
    "lastGoodPayload": None,
}
active_cloud_sessions: dict[str, float] = {}

app = FastAPI(title="Low Latency Real Time Translator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> FileResponse:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


app.mount("/static", NoCacheStaticFiles(directory=FRONTEND_DIR), name="static")


@dataclass
class ASRJob:
    chunk: AudioChunk


@dataclass
class TranslateJob:
    sequence_id: str
    source_text: str
    start_seconds: float
    end_seconds: float
    audio_duration_seconds: float
    captured_at: float
    asr_ms: float
    transcribed_at: float = field(default_factory=time.perf_counter)
    draft_sequence_ids: list[str] = field(default_factory=list)


@dataclass
class ContextBufferDecision:
    ready: list[TranslateJob] = field(default_factory=list)
    detail: str = ""


@dataclass
class SubtitleJob:
    sequence_id: str
    source_text: str
    translated_text: str
    start_seconds: float
    end_seconds: float
    audio_duration_seconds: float
    asr_ms: float
    translate_ms: float
    total_latency_ms: float
    engine: str
    is_final: bool = True
    draft_sequence_ids: list[str] = field(default_factory=list)


@dataclass
class UtteranceUpdate:
    draft: SubtitleJob | None = None
    ready: TranslateJob | None = None


@dataclass
class TurnDecision:
    is_noise: bool
    is_new_turn: bool


class SubtitleTurnDetector:
    def __init__(self, pause_seconds: float, min_words: int, noise_phrases: str) -> None:
        self.pause_seconds = pause_seconds
        self.min_words = min_words
        self.noise_phrases = {
            self._normalize_text(item)
            for item in noise_phrases.split(",")
            if self._normalize_text(item)
        }
        self.last_end_seconds: float | None = None
        self.last_received_at: float | None = None

    def classify(self, subtitle: CloudSubtitle) -> TurnDecision:
        normalized = self._normalize_text(subtitle.source_text)
        words = normalized.split()
        if not normalized or normalized in self.noise_phrases:
            return TurnDecision(is_noise=True, is_new_turn=False)

        if self.last_end_seconds is None or self.last_received_at is None:
            is_new_turn = True
        else:
            audio_gap = subtitle.start_seconds - self.last_end_seconds
            wall_gap = subtitle.received_at - self.last_received_at
            is_new_turn = max(audio_gap, wall_gap) >= self.pause_seconds

        self.last_end_seconds = max(subtitle.end_seconds, subtitle.start_seconds)
        self.last_received_at = subtitle.received_at
        return TurnDecision(is_noise=False, is_new_turn=is_new_turn)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9'\s]", " ", text.lower())).strip()


class LocalUtteranceAggregator:
    SENTENCE_END_RE = re.compile(r"[.!?\u3002\uff01\uff1f][\"')\]]*$")

    def __init__(self, active_config: AppConfig) -> None:
        self.pause_seconds = active_config.segmenter_pause_seconds
        self.max_words = active_config.segmenter_max_words
        self.max_seconds = active_config.segmenter_max_seconds
        self.is_chinese = active_config.source_language == "zho_Hans"
        self.min_chinese_final_chars = 28
        self.max_chinese_final_chars = 72
        self.idle_chinese_final_chars = 16
        if self.is_chinese:
            self.pause_seconds = max(self.pause_seconds, 0.6)
            self.max_seconds = min(max(self.max_seconds, 3.5), 5.5)
        self.sequence_index = 0
        self.reset()

    def reset(self) -> None:
        self.sequence_id = ""
        self.source_text = ""
        self.start_seconds = 0.0
        self.end_seconds = 0.0
        self.audio_duration_seconds = 0.0
        self.captured_at = time.perf_counter()
        self.last_update_at = 0.0
        self.asr_ms = 0.0

    @property
    def has_text(self) -> bool:
        return bool(self.source_text.strip())

    def add_asr_result(self, item: TranscriptionResult, job: ASRJob, asr_ms: float) -> UtteranceUpdate:
        if self.is_chinese:
            clean_text = self._clean_realtime_chinese_text(item.text)
            if not clean_text or self._is_low_information_chinese(clean_text):
                return UtteranceUpdate()
            if self.source_text and self._is_realtime_duplicate_chinese(self.source_text, clean_text):
                return UtteranceUpdate()
            item = TranscriptionResult(clean_text, item.start_seconds, item.end_seconds)

        if not self.has_text:
            self.sequence_index += 1
            self.sequence_id = f"local-utterance-{self.sequence_index}"
            self.start_seconds = item.start_seconds
            self.captured_at = job.chunk.captured_at

        previous_end = self.end_seconds
        previous_text = self.source_text
        self.source_text = self._merge_text(self.source_text, item.text)
        if self.source_text == previous_text:
            return UtteranceUpdate()
        self.end_seconds = max(self.end_seconds, item.end_seconds)
        self.audio_duration_seconds = max(self.audio_duration_seconds, self.end_seconds - self.start_seconds)
        self.last_update_at = time.perf_counter()
        self.asr_ms += asr_ms

        draft = (
            self._subtitle(is_final=False, engine_suffix="draft")
            if not self.is_chinese or self._should_emit_chinese_draft(previous_text, self.source_text)
            else None
        )
        if not self._should_mark_ready(previous_end, item):
            return UtteranceUpdate(draft=draft)

        return UtteranceUpdate(draft=draft, ready=self.mark_ready())

    def mark_ready(self) -> TranslateJob | None:
        if not self.has_text:
            return None
        job = TranslateJob(
            sequence_id=self.sequence_id,
            source_text=self.source_text.strip(),
            start_seconds=self.start_seconds,
            end_seconds=self.end_seconds,
            audio_duration_seconds=max(0.0, self.audio_duration_seconds),
            captured_at=self.captured_at,
            asr_ms=self.asr_ms,
            draft_sequence_ids=[self.sequence_id],
        )
        self.reset()
        return job

    def mark_ready_if_idle(self) -> TranslateJob | None:
        if not self.has_text or not self.last_update_at:
            return None
        idle_seconds = time.perf_counter() - self.last_update_at
        if idle_seconds < self.pause_seconds:
            return None
        text = self.source_text.strip()
        if self.is_chinese:
            chinese_length = self._chinese_length(text)
            if chinese_length >= self.idle_chinese_final_chars:
                return self.mark_ready()
            if chinese_length >= 8 and idle_seconds >= self.pause_seconds * 1.8:
                return self.mark_ready()
            return None
        words = SubtitleTurnDetector._normalize_text(text).split()
        min_idle_words = max(5, min(10, self.max_words // 3))
        if len(words) < min_idle_words and not self._looks_sentence_complete(text, words):
            if idle_seconds < self.pause_seconds * 2.5:
                return None
        return self.mark_ready()

    def _subtitle(self, is_final: bool, engine_suffix: str) -> SubtitleJob:
        return SubtitleJob(
            sequence_id=self.sequence_id,
            source_text=self.source_text.strip(),
            translated_text="",
            start_seconds=self.start_seconds,
            end_seconds=self.end_seconds,
            audio_duration_seconds=max(0.0, self.audio_duration_seconds),
            asr_ms=self.asr_ms,
            translate_ms=0,
            total_latency_ms=(time.perf_counter() - self.captured_at) * 1000,
            engine=f"local-{engine_suffix}",
            is_final=is_final,
            draft_sequence_ids=[self.sequence_id],
        )

    def _should_mark_ready(self, previous_end: float, item: TranscriptionResult) -> bool:
        text = self.source_text.strip()
        words = SubtitleTurnDetector._normalize_text(text).split()
        duration = self.end_seconds - self.start_seconds
        if self.is_chinese:
            chinese_length = self._chinese_length(text)
            gap = item.start_seconds - previous_end if previous_end else 0.0
            if self._looks_sentence_complete(text, words) and chinese_length >= self.min_chinese_final_chars:
                return True
            if chinese_length >= self.max_chinese_final_chars and duration >= 2.0:
                return True
            if duration >= self.max_seconds and chinese_length >= self.min_chinese_final_chars:
                return True
            return gap >= self.pause_seconds and chinese_length >= self.idle_chinese_final_chars
        if self._looks_sentence_complete(text, words):
            return True
        if len(words) >= self.max_words and duration >= self.pause_seconds * 2:
            return True
        if duration >= self.max_seconds and len(words) >= 8:
            return True
        gap = item.start_seconds - previous_end if previous_end else 0.0
        return gap >= self.pause_seconds and len(words) >= 8

    @classmethod
    def _looks_sentence_complete(cls, text: str, words: list[str]) -> bool:
        if re.search(r"[\u4e00-\u9fff]", text):
            if cls._chinese_length(text) < 6:
                return False
            return bool(cls.SENTENCE_END_RE.search(text))
        if len(words) < 10:
            return False
        return bool(cls.SENTENCE_END_RE.search(text))

    @staticmethod
    def _chinese_length(text: str) -> int:
        return len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text))

    @staticmethod
    def _clean_realtime_chinese_text(text: str) -> str:
        cleaned = LocalUtteranceAggregator._normalize_local_text(text)
        cleaned = re.sub(r"\s+", "", cleaned)
        cleaned = re.sub(r"<\s*\|\s*[^>]+?\s*\|\s*>", "", cleaned)
        cleaned = re.sub(r"([。！？；，、,.!?]){2,}", r"\1", cleaned)
        return LocalUtteranceAggregator._suppress_cjk_repetition(cleaned).strip()

    @staticmethod
    def _is_low_information_chinese(text: str) -> bool:
        compact = re.sub(r"\s+", "", text)
        if LocalUtteranceAggregator._chinese_length(compact) < 6:
            return True
        filler_removed = re.sub(
            r"(我觉得|还有就是|然后|所以|就是|这个|那个|嗯|啊|呃|呢|吧|对吧|其实|没有问题|谢谢)+",
            "",
            compact,
        )
        filler_removed = re.sub(r"[\u3002\uff01\uff1f\uff0c\uff1b\uff1a\u3001,.!?;:]+", "", filler_removed)
        if LocalUtteranceAggregator._chinese_length(filler_removed) < 8 and LocalUtteranceAggregator._chinese_length(compact) < 24:
            return True
        filler_hits = len(re.findall(r"(我觉得|还有就是|然后|所以|就是|这个|那个|嗯|啊|呃)", compact))
        return filler_hits >= 5 and LocalUtteranceAggregator._chinese_length(filler_removed) < 18

    @staticmethod
    def _is_realtime_duplicate_chinese(current: str, incoming: str) -> bool:
        compact_current = re.sub(r"\s+", "", current)
        compact_incoming = re.sub(r"\s+", "", incoming)
        if not compact_current or not compact_incoming:
            return False
        recent = compact_current[-220:]
        if compact_incoming in recent:
            return True
        if len(compact_incoming) >= 18:
            ratio = SequenceMatcher(None, recent[-max(60, len(compact_incoming)) :], compact_incoming).ratio()
            if ratio >= 0.9:
                return True
        return False

    @staticmethod
    def _should_emit_chinese_draft(previous: str, current: str) -> bool:
        compact_previous = re.sub(r"\s+", "", previous)
        compact_current = re.sub(r"\s+", "", current)
        current_length = LocalUtteranceAggregator._chinese_length(compact_current)
        if current_length < 6:
            return False
        if not compact_previous:
            return current_length >= 6
        if compact_current == compact_previous:
            return False
        added = max(0, current_length - LocalUtteranceAggregator._chinese_length(compact_previous))
        if added >= 3:
            return True
        if not compact_current.startswith(compact_previous):
            ratio = SequenceMatcher(None, compact_previous[-120:], compact_current[-120:]).ratio()
            return ratio < 0.9 and current_length >= 8
        return False

    @staticmethod
    def _merge_text(current: str, incoming: str) -> str:
        clean_current = LocalUtteranceAggregator._normalize_local_text(current)
        clean_incoming = LocalUtteranceAggregator._normalize_local_text(incoming)
        if not clean_current:
            return clean_incoming
        if not clean_incoming:
            return clean_current
        if LocalUtteranceAggregator._contains_cjk(clean_current) or LocalUtteranceAggregator._contains_cjk(clean_incoming):
            return LocalUtteranceAggregator._merge_cjk_text(clean_current, clean_incoming)

        current_words = clean_current.split()
        incoming_words = clean_incoming.split()
        max_overlap = min(6, len(current_words), len(incoming_words))
        for overlap in range(max_overlap, 0, -1):
            left = " ".join(current_words[-overlap:]).lower().strip(".,!?;:")
            right = " ".join(incoming_words[:overlap]).lower().strip(".,!?;:")
            if left == right:
                return LocalUtteranceAggregator._normalize_local_text(" ".join([*current_words, *incoming_words[overlap:]]))
        return LocalUtteranceAggregator._normalize_local_text(f"{clean_current} {clean_incoming}")

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", text))

    @staticmethod
    def _merge_cjk_text(current: str, incoming: str) -> str:
        compact_current = re.sub(r"\s+", "", current)
        compact_incoming = re.sub(r"\s+", "", incoming)
        if not compact_current:
            return LocalUtteranceAggregator._suppress_cjk_repetition(incoming)
        if not compact_incoming:
            return current
        if compact_incoming in compact_current[-80:]:
            return current
        if compact_current[-80:] in compact_incoming:
            return LocalUtteranceAggregator._suppress_cjk_repetition(incoming)

        current_for_overlap = re.sub(r"[\u3002\uff01\uff1f,.!?;:\uff0c\u3001]+$", "", compact_current)
        incoming_for_overlap = re.sub(r"^[\u3002\uff01\uff1f,.!?;:\uff0c\u3001]+", "", compact_incoming)
        recent = current_for_overlap[-240:]
        if len(incoming_for_overlap) >= 24:
            ratio = SequenceMatcher(None, recent[-max(80, len(incoming_for_overlap)) :], incoming_for_overlap).ratio()
            if ratio >= 0.92:
                return compact_current
            match = SequenceMatcher(None, recent, incoming_for_overlap).find_longest_match(0, len(recent), 0, len(incoming_for_overlap))
            if match.b == 0 and match.size >= 20:
                tail = incoming_for_overlap[match.size :]
                if LocalUtteranceAggregator._chinese_length(tail) < 8:
                    return compact_current
                return LocalUtteranceAggregator._normalize_local_text(
                    LocalUtteranceAggregator._suppress_cjk_repetition(f"{compact_current}{tail}")
                )
        max_overlap = min(48, len(current_for_overlap), len(incoming_for_overlap))
        for overlap in range(max_overlap, 1, -1):
            fragment = incoming_for_overlap[:overlap]
            if overlap < 4 and not re.search(r"[A-Za-z0-9]", fragment):
                continue
            if current_for_overlap[-overlap:] == fragment:
                return LocalUtteranceAggregator._normalize_local_text(
                    LocalUtteranceAggregator._suppress_cjk_repetition(
                        f"{current_for_overlap}{incoming_for_overlap[overlap:]}"
                    )
                )

        max_overlap = min(36, len(compact_current), len(compact_incoming))
        for overlap in range(max_overlap, 3, -1):
            if compact_current[-overlap:] == compact_incoming[:overlap]:
                return LocalUtteranceAggregator._normalize_local_text(
                    LocalUtteranceAggregator._suppress_cjk_repetition(f"{compact_current}{compact_incoming[overlap:]}")
                )

        recent = compact_current[-240:]
        for prefix_length in range(min(42, len(compact_incoming)), 1, -1):
            prefix = compact_incoming[:prefix_length]
            if prefix_length < 6 and not re.search(r"[A-Za-z0-9]", prefix):
                continue
            if prefix in recent:
                return LocalUtteranceAggregator._normalize_local_text(
                    LocalUtteranceAggregator._suppress_cjk_repetition(f"{compact_current}{compact_incoming[prefix_length:]}")
                )
        return LocalUtteranceAggregator._normalize_local_text(
            LocalUtteranceAggregator._suppress_cjk_repetition(f"{compact_current}{compact_incoming}")
        )

    @staticmethod
    def _suppress_cjk_repetition(text: str) -> str:
        compact = re.sub(r"\s+", "", text)
        if len(compact) < 24:
            return compact
        return LocalUtteranceAggregator._suppress_cjk_repetition_v2(compact)

        for _ in range(4):
            next_compact = re.sub(
                r"([\u4e00-\u9fffA-Za-z0-9]{2,12})([\uff0c,\u3001\u3002\uff01\uff1f!?]?)(\1)",
                r"\1\2",
                compact,
            )
            if next_compact == compact:
                break
            compact = next_compact

        for block_size in range(min(40, len(compact) // 2), 7, -1):
            while len(compact) >= block_size * 2 and compact[-block_size:] == compact[-2 * block_size : -block_size]:
                compact = compact[:-block_size]

        parts = [part for part in re.findall(r"[^。！？]+[。！？]?", compact) if part.strip()]
        if len(parts) < 3:
            return compact

        kept: list[str] = []
        recent: list[str] = []
        for part in parts:
            body = re.sub(r"[。！？]+$", "", part).strip()
            if len(body) < 4:
                kept.append(part)
                continue
            duplicate = False
            for previous in recent[-5:]:
                if body == previous or body in previous or previous in body:
                    duplicate = True
                    break
                if min(len(body), len(previous)) >= 10 and SequenceMatcher(None, body, previous).ratio() >= 0.86:
                    duplicate = True
                    break
            if duplicate:
                continue
            kept.append(part)
            recent.append(body)
        return "".join(kept).strip()

    @staticmethod
    def _suppress_cjk_repetition_v2(compact: str) -> str:
        for _ in range(4):
            next_compact = re.sub(
                r"([\u4e00-\u9fffA-Za-z0-9]{2,12})([\uff0c,\u3001\u3002\uff01\uff1f!?]?)(\1)",
                r"\1\2",
                compact,
            )
            if next_compact == compact:
                break
            compact = next_compact

        for block_size in range(min(40, len(compact) // 2), 7, -1):
            while len(compact) >= block_size * 2 and compact[-block_size:] == compact[-2 * block_size : -block_size]:
                compact = compact[:-block_size]

        parts = [part for part in re.findall(r"[^\u3002\uff01\uff1f!?]+[\u3002\uff01\uff1f!?]?", compact) if part.strip()]
        if len(parts) < 3:
            return compact

        kept: list[str] = []
        recent: list[str] = []
        for part in parts:
            body = re.sub(r"[\u3002\uff01\uff1f!?]+$", "", part).strip()
            if len(body) < 4:
                kept.append(part)
                continue
            duplicate = False
            for previous in recent[-5:]:
                if body == previous or body in previous or previous in body:
                    duplicate = True
                    break
                if min(len(body), len(previous)) >= 10 and SequenceMatcher(None, body, previous).ratio() >= 0.86:
                    duplicate = True
                    break
            if duplicate:
                continue
            kept.append(part)
            recent.append(body)
        return "".join(kept).strip()

    @staticmethod
    def _normalize_local_text(text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""

        cleaned = strip_subtitle_markup(cleaned)
        cleaned = re.sub(r"(?:\s*[\\/|]{2,}\s*)+", " ", cleaned)
        cleaned = re.sub(r"(?:\s*\.\s*){3,}", "... ", cleaned)
        cleaned = re.sub(r"([!?.,])(?:\s*\1){1,}", r"\1", cleaned)
        cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
        cleaned = re.sub(r"([,.!?;:])([A-Za-z])", r"\1 \2", cleaned)
        cleaned = re.sub(r"\s*([\u3002\uff01\uff1f\uff0c\uff1b\uff1a])\s*", r"\1", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()


def strip_subtitle_markup(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"\{\\[^{}]*\}", " ", cleaned)
    cleaned = re.sub(r"\{(?:\\[A-Za-z][A-Za-z0-9]*[^{}]*)+\}", " ", cleaned)
    cleaned = re.sub(
        r"\\(?:fn|fs|shad|bord|blur|be|b|i|u|r|p|q|a|k|kf|ko|pos|move|org|clip|iclip|fad|fade|c|[1-4]c|[1-4]a|alpha|fscx|fscy|frz|frx|fry|an)[^\\\s{}]*",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[{}]", " ", cleaned)
    cleaned = re.sub(r"</?[^>\s]+(?:\s+[^>]*)?>", " ", cleaned)
    cleaned = re.sub(r"\b\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\s*(?:-->|-)\s*\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?", " ", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


class ContextualTranslationBuffer:
    DEPENDENT_START_RE = re.compile(
        r"^(and|but|so|then|also|because|which|that|this|these|those|it|they|he|she|we|you|"
        r"its|their|his|her|our|your|therefore|however|meanwhile)\b",
        re.IGNORECASE,
    )

    def __init__(self, active_config: AppConfig) -> None:
        self.enabled = active_config.context_buffer_enabled
        self.min_words = active_config.context_buffer_min_words
        self.max_words = active_config.context_buffer_max_words
        self.max_wait_seconds = active_config.context_buffer_max_wait_seconds
        self.pending: TranslateJob | None = None
        self.pending_since = 0.0

    def add(self, job: TranslateJob) -> ContextBufferDecision:
        if not self.enabled:
            return ContextBufferDecision(ready=[job])

        now = time.perf_counter()
        if self.pending is None:
            if self._should_hold(job):
                self.pending = job
                self.pending_since = now
                return ContextBufferDecision(detail="Buffering short translation context.")
            return ContextBufferDecision(ready=[job])

        merged = self._merge_jobs(self.pending, job)
        if self._word_count(merged.source_text) > self.max_words:
            ready = [self.pending, job]
            self.pending = None
            self.pending_since = 0.0
            return ContextBufferDecision(
                ready=ready,
                detail="Released buffered context without merging; translation window is full.",
            )
        self.pending = None
        self.pending_since = 0.0
        return ContextBufferDecision(
            ready=[merged],
            detail="Merged buffered context for translation.",
        )

    def flush_if_idle(self) -> ContextBufferDecision:
        if self.pending is None:
            return ContextBufferDecision()
        if time.perf_counter() - self.pending_since < self.max_wait_seconds:
            return ContextBufferDecision()
        job = self.pending
        self.pending = None
        self.pending_since = 0.0
        return ContextBufferDecision(
            ready=[job],
            detail="Flushed buffered context after short wait.",
        )

    def _should_hold(self, job: TranslateJob) -> bool:
        text = job.source_text.strip()
        words = SubtitleTurnDetector._normalize_text(text).split()
        if not words:
            return False
        if len(words) >= self.max_words:
            return False
        if len(words) < self.min_words:
            return True
        return bool(self.DEPENDENT_START_RE.search(text))

    @staticmethod
    def _word_count(text: str) -> int:
        return len(SubtitleTurnDetector._normalize_text(text).split())

    @staticmethod
    def _merge_jobs(left: TranslateJob, right: TranslateJob) -> TranslateJob:
        source_text = LocalUtteranceAggregator._merge_text(left.source_text, right.source_text)
        return TranslateJob(
            sequence_id=f"{left.sequence_id}+{right.sequence_id}",
            source_text=source_text,
            start_seconds=min(left.start_seconds, right.start_seconds),
            end_seconds=max(left.end_seconds, right.end_seconds),
            audio_duration_seconds=max(left.end_seconds, right.end_seconds) - min(left.start_seconds, right.start_seconds),
            captured_at=min(left.captured_at, right.captured_at),
            asr_ms=left.asr_ms + right.asr_ms,
            transcribed_at=max(left.transcribed_at, right.transcribed_at),
            draft_sequence_ids=[*left.draft_sequence_ids, *right.draft_sequence_ids],
        )


class ChineseReadingBuffer:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.min_chars = 120
        self.idle_min_chars = 64
        self.max_chars = 220
        self.idle_flush_seconds = 3.8
        self.pending: TranslateJob | None = None
        self.pending_since = 0.0
        self.pending_updated_at = 0.0

    def add(self, job: TranslateJob) -> ContextBufferDecision:
        if not self.enabled:
            return ContextBufferDecision(ready=[job])

        now = time.perf_counter()
        if self.pending is None:
            self.pending = job
            self.pending_since = now
        else:
            self.pending = ContextualTranslationBuffer._merge_jobs(self.pending, job)
        self.pending_updated_at = now

        char_count = LocalUtteranceAggregator._chinese_length(self.pending.source_text)
        if char_count >= self.max_chars:
            return self._release("Released polished Chinese reading block.")
        return ContextBufferDecision(detail="Buffering final Chinese text for readability.")

    def flush_if_idle(self) -> ContextBufferDecision:
        if self.pending is None:
            return ContextBufferDecision()
        if time.perf_counter() - self.pending_updated_at < self.idle_flush_seconds:
            return ContextBufferDecision()
        if LocalUtteranceAggregator._chinese_length(self.pending.source_text) < self.idle_min_chars:
            return ContextBufferDecision()
        return self._release("Flushed polished Chinese reading block.")

    def _release(self, detail: str) -> ContextBufferDecision:
        if self.pending is None:
            return ContextBufferDecision()
        job = self.pending
        self.pending = None
        self.pending_since = 0.0
        self.pending_updated_at = 0.0
        polished = polish_chinese_reading_text(job.source_text)
        return ContextBufferDecision(
            ready=[
                TranslateJob(
                    sequence_id=job.sequence_id,
                    source_text=polished,
                    start_seconds=job.start_seconds,
                    end_seconds=job.end_seconds,
                    audio_duration_seconds=job.audio_duration_seconds,
                    captured_at=job.captured_at,
                    asr_ms=job.asr_ms,
                    transcribed_at=job.transcribed_at,
                    draft_sequence_ids=job.draft_sequence_ids,
                )
            ],
            detail=detail,
        )


def polish_chinese_reading_text(text: str) -> str:
    cleaned = LocalUtteranceAggregator._normalize_local_text(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", cleaned)
    cleaned = cleaned.replace(",", "\uff0c").replace(";", "\uff1b").replace(":", "\uff1a")
    cleaned = cleaned.replace("!", "\uff01").replace("?", "\uff1f")
    cleaned = re.sub(r"\.{1,}", "\u3002", cleaned)
    cleaned = re.sub(r"[\u3002]{2,}", "\u3002", cleaned)
    cleaned = re.sub(r"[\uff0c]{2,}", "\uff0c", cleaned)
    cleaned = re.sub(r"\s*([\uff0c\u3002\uff01\uff1f\uff1b\uff1a])\s*", r"\1", cleaned)
    cleaned = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", cleaned)
    cleaned = re.sub(r"(?<![A-Za-z])IJR(?![A-Za-z])", "IJRR", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(\u7684){2,}", "\u7684", cleaned)
    cleaned = re.sub(r"(\u8fd9)(?:\uff0c?\u8fd9)+", r"\1", cleaned)
    cleaned = re.sub(r"(\u90a3)(?:\uff0c?\u90a3)+", r"\1", cleaned)
    cleaned = re.sub(r"([\u4e00-\u9fff])\1{2,}", r"\1", cleaned)
    cleaned = re.sub(
        r"(^|[\uff0c\u3002\uff01\uff1f\uff1b])(?:\u55ef|\u554a|\u5443|\u5462|\u8fd9\u4e2a|\u90a3\u4e2a)[\uff0c\u3002\uff01\uff1f\uff1b]?",
        r"\1",
        cleaned,
    )
    cleaned = re.sub(r"\u7684\u7684\u4e00\u4e9b", "\u7684\u4e00\u4e9b", cleaned)
    cleaned = re.sub(r"(?:\u6211\u4eec\u8981)?\u628a\u8fd9\u3002", "", cleaned)
    cleaned = re.sub(r"\u8fd9\u4e5f\u662f\u8fd9[\uff0c\u3002]?\u8fd9", "\u8fd9\u4e5f\u662f", cleaned)
    cleaned = re.sub(r"[\uff0c]{2,}", "\uff0c", cleaned)
    cleaned = re.sub(r"[\u3002]{2,}", "\u3002", cleaned)

    parts = re.findall(r"[^。！？；]+[。！？；]?", cleaned)
    if len(parts) <= 1:
        return normalize_chinese_reading_terms(cleaned)

    polished_parts: list[str] = []
    carry = ""
    for raw_part in parts:
        part = raw_part.strip()
        if not part:
            continue
        body = re.sub(r"[。！？；]+$", "", part)
        ending_match = re.search(r"([。！？；]+)$", part)
        ending = ending_match.group(1)[-1] if ending_match else ""
        length = LocalUtteranceAggregator._chinese_length(body)
        if carry:
            if length < 12 or body.endswith(("\u7684", "\u4e86", "\u5373", "\u4e4b\u540e")):
                carry += body
            else:
                carry += "\uff0c" + body
        else:
            carry = body
        carry_length = LocalUtteranceAggregator._chinese_length(carry)
        if carry_length >= 24 or ending in ("\uff01", "\uff1f"):
            polished_parts.append(carry + (ending or "\u3002"))
            carry = ""

    if carry:
        polished_parts.append(carry + "\u3002")
    return normalize_chinese_reading_terms("".join(polished_parts).strip())


def normalize_chinese_reading_terms(text: str) -> str:
    normalized = re.sub(r"UC(?=IJRR\b)", "UC\uff0c", text)
    normalized = re.sub(r"\bUCBerkeley\b", "UC Berkeley", normalized)
    normalized = re.sub(r"(?<=[A-Za-z])(?=MPC|MPPI|MDP|POMDP|IJRR|IROS|ICRA|CoRL|ScienceRobotics)", " ", normalized)
    normalized = normalized.replace("ScienceRobotics", "Science Robotics")
    return normalized


def realtime_subtitle_polish_enabled() -> bool:
    value = os.getenv("REALTIME_SUBTITLE_POLISH_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off", "rule", "rules"}


def realtime_subtitle_polish_model() -> str:
    return (
        os.getenv("OLLAMA_SUBTITLE_MODEL", "")
        or os.getenv("OLLAMA_NOTES_MODEL", "")
        or "qwen3:14b"
    ).strip()


def realtime_subtitle_polish_url() -> str:
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
    return f"{host}/api/generate"


def realtime_subtitle_polish_tags_url() -> str:
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
    return f"{host}/api/tags"


def realtime_subtitle_polish_timeout_seconds() -> float:
    try:
        return max(2.0, float(os.getenv("REALTIME_SUBTITLE_POLISH_TIMEOUT_SECONDS", "10")))
    except ValueError:
        return 10.0


def realtime_ollama_model_available(model: str) -> bool:
    now = time.perf_counter()
    cached_at = float(getattr(realtime_ollama_model_available, "_cached_at", 0.0))
    cached_model = str(getattr(realtime_ollama_model_available, "_cached_model", ""))
    cached_ok = bool(getattr(realtime_ollama_model_available, "_cached_ok", False))
    if cached_model == model and now - cached_at < 30:
        return cached_ok

    ok = False
    try:
        with urllib.request.urlopen(realtime_subtitle_polish_tags_url(), timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        model_names = [str(item.get("name") or "") for item in payload.get("models", [])]
        ok = any(name == model or name.startswith(f"{model}:") for name in model_names)
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        ok = False

    setattr(realtime_ollama_model_available, "_cached_at", now)
    setattr(realtime_ollama_model_available, "_cached_model", model)
    setattr(realtime_ollama_model_available, "_cached_ok", ok)
    return ok


def polish_chinese_with_ollama(text: str) -> str:
    cleaned = polish_chinese_reading_text(text)
    if not realtime_subtitle_polish_enabled():
        return cleaned
    if LocalUtteranceAggregator._chinese_length(cleaned) < 18:
        return cleaned

    model = realtime_subtitle_polish_model()
    if not model:
        return cleaned
    if not realtime_ollama_model_available(model):
        return cleaned

    prompt = "\n".join(
        [
            "/no_think",
            "你是实时会议字幕的中文技术编辑。",
            "请把下面这段中文 ASR 结果润色成自然、准确、简洁的简体中文最终字幕。",
            "要求：",
            "1. 只修正明显的语音识别错误、重复、口头碎片和不通顺表达。",
            "2. 不新增事实，不扩写，不总结，不改变说话原意。",
            "3. 保留英文缩写和术语，例如 MP、MDP、reward、state、trajectory、policy、强化学习。",
            "4. 输出一段中文即可，不要解释，不要项目符号。",
            "",
            f"ASR：{cleaned}",
            "",
            "最终字幕：",
        ]
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 2048,
            "num_predict": 180,
        },
    }
    request = urllib.request.Request(
        realtime_subtitle_polish_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=realtime_subtitle_polish_timeout_seconds()) as response:
            result = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return cleaned

    polished = str(result.get("response") or "").strip()
    polished = re.sub(r"<think>.*?</think>", "", polished, flags=re.DOTALL | re.IGNORECASE)
    polished = re.sub(r"^\s*(?:[-*]|\d+[.)]|最终字幕[:：])\s*", "", polished).strip()
    polished = polished.strip("` \n\r\t")
    if not polished or LocalUtteranceAggregator._chinese_length(polished) < 8:
        return cleaned
    return polish_chinese_reading_text(polished)


def compact_subtitle_for_comparison(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text or "").lower()


def chinese_subtitle_polish_is_safe(source: str, polished: str) -> bool:
    source_len = LocalUtteranceAggregator._chinese_length(source)
    polished_len = LocalUtteranceAggregator._chinese_length(polished)
    if polished_len < 8:
        return False
    if source_len >= 40 and polished_len > max(int(source_len * 1.45), source_len + 80):
        return False
    if source_len >= 80 and polished_len < int(source_len * 0.35):
        return False

    source_compact = compact_subtitle_for_comparison(source)
    polished_compact = compact_subtitle_for_comparison(polished)
    if source_len >= 60 and source_compact and polished_compact:
        similarity = SequenceMatcher(None, source_compact, polished_compact).ratio()
        if similarity < 0.36:
            return False

    source_terms = {
        term.upper()
        for term in re.findall(r"\b[A-Za-z][A-Za-z0-9+.-]{1,}\b", source)
        if len(term) >= 2
    }
    polished_terms = {
        term.upper()
        for term in re.findall(r"\b[A-Za-z][A-Za-z0-9+.-]{1,}\b", polished)
        if len(term) >= 2
    }
    dropped_terms = source_terms - polished_terms
    if len(source_terms) >= 3 and len(dropped_terms) > max(2, len(source_terms) // 2):
        return False
    return True


def update_chinese_final_context(previous: str, current: str, limit: int = 260) -> str:
    combined = polish_chinese_reading_text(f"{previous}{current}") if previous else polish_chinese_reading_text(current)
    if len(combined) <= limit:
        return combined
    return combined[-limit:]


def remove_chinese_context_overlap(previous_context: str, current: str) -> str:
    previous = (previous_context or "").strip()
    text = (current or "").strip()
    if not previous or not text:
        return text
    max_overlap = min(100, len(previous), len(text))
    for overlap in range(max_overlap, 5, -1):
        if previous[-overlap:] == text[:overlap]:
            return text[overlap:].lstrip("\uff0c\u3002\uff01\uff1f\uff1b, .!?;")

    previous_tail = compact_subtitle_for_comparison(previous[-160:])
    text_compact = compact_subtitle_for_comparison(text)
    for overlap in range(min(80, len(previous_tail), len(text_compact)), 9, -1):
        if previous_tail[-overlap:] == text_compact[:overlap]:
            # The compact match confirms overlap, but removing the full current
            # prefix safely needs exact text. Keep the model output if unsure.
            return text
    return text


def polish_chinese_with_ollama(text: str, previous_context: str = "") -> str:
    cleaned = polish_chinese_reading_text(text)
    if not realtime_subtitle_polish_enabled():
        return cleaned
    if LocalUtteranceAggregator._chinese_length(cleaned) < 18:
        return cleaned

    model = realtime_subtitle_polish_model()
    if not model:
        return cleaned
    if not realtime_ollama_model_available(model):
        return cleaned

    domain_terms = build_hotword_text(language="zh", limit=120, include_defaults=True)
    context_lines = (
        [
            "Previous final subtitles for context only. Do not repeat this content:",
            previous_context.strip(),
            "",
        ]
        if previous_context.strip()
        else []
    )
    prompt = "\n".join(
        [
            "/no_think",
            "You are a faithful Chinese technical subtitle editor.",
            "The topic is usually robotics, reinforcement learning, robot locomotion, and paper discussion.",
            "Rewrite the Chinese ASR text into readable final subtitles in Simplified Chinese.",
            f"Term hints: {domain_terms}",
            "Rules:",
            "1. Remove filler words, obvious repeated fragments, and broken sentence starts.",
            "2. Merge fragments into natural complete sentences while preserving the speaker's meaning.",
            "3. Correct only recognition errors that are strongly supported by context.",
            "4. Do not add facts, summaries, opinions, names, years, institutions, or paper titles.",
            "5. Preserve technical terms such as MPC, MPPI, MDP, reward, state, trajectory, policy, UC Berkeley, CMU, MIT, Stanford, IJRR, IROS, ICRA, CoRL, Science Robotics.",
            "6. If a term is uncertain, keep the original ASR wording instead of guessing.",
            "7. Use the previous subtitles only to keep continuity. Output only the current ASR content.",
            "8. Output 2 to 5 coherent Chinese sentences only. No explanation. No bullets.",
            "",
            *context_lines,
            f"ASR: {cleaned}",
            "",
            "Final subtitles:",
        ]
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.05,
            "num_ctx": 4096,
            "num_predict": 320,
        },
    }
    request = urllib.request.Request(
        realtime_subtitle_polish_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=realtime_subtitle_polish_timeout_seconds()) as response:
            result = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return cleaned

    polished = str(result.get("response") or "").strip()
    polished = re.sub(r"<think>.*?</think>", "", polished, flags=re.DOTALL | re.IGNORECASE)
    polished = re.sub(
        "^\\s*(?:[-*]|\\d+[.)]|Final subtitles?[:\\uff1a]|Final Chinese subtitles?[:\\uff1a])\\s*",
        "",
        polished,
        flags=re.IGNORECASE,
    ).strip()
    polished = polished.strip("` \n\r\t")
    if not polished or LocalUtteranceAggregator._chinese_length(polished) < 8:
        return cleaned
    polished = polish_chinese_reading_text(polished)
    if not chinese_subtitle_polish_is_safe(cleaned, polished):
        return cleaned
    return polished


class IdentityTranslator:
    engine_name = "identity"

    async def translate(
        self,
        text: str,
        source_language: str | None = None,
        target_language: str | None = None,
    ) -> str:
        return text.strip()


class Runtime:
    def __init__(self) -> None:
        self.asr: WhisperASR | FunASRRealtimeASR | None = None
        self.asr_backend = ""
        self.final_asr: FunASRParaformerASR | None = None
        self.final_asr_backend = ""
        self.translator: Translator | None = None
        self.current_config = config
        self.lock = asyncio.Lock()

    async def ensure_models(self, next_config: AppConfig) -> None:
        async with self.lock:
            if next_config.translation_engine == "azure":
                self.current_config = next_config
                return

            next_asr_model = effective_asr_model(next_config.asr_model_size, next_config.source_language)
            next_asr_backend = "funasr" if should_use_realtime_funasr(next_config) else "faster-whisper"
            next_final_asr_backend = "paraformer-zh" if should_use_final_paraformer(next_config) else ""
            current_asr_model = effective_asr_model(
                self.current_config.asr_model_size,
                self.current_config.source_language,
            )
            needs_asr = (
                self.asr is None
                or self.asr_backend != next_asr_backend
                or current_asr_model != next_asr_model
                or self.current_config.asr_device != next_config.asr_device
                or self.current_config.asr_compute_type != next_config.asr_compute_type
                or self.current_config.asr_beam_size != next_config.asr_beam_size
                or self.current_config.asr_best_of != next_config.asr_best_of
                or self.current_config.asr_patience != next_config.asr_patience
                or self.current_config.asr_condition_on_previous_text != next_config.asr_condition_on_previous_text
                or self.current_config.asr_no_speech_threshold != next_config.asr_no_speech_threshold
                or self.current_config.asr_log_prob_threshold != next_config.asr_log_prob_threshold
                or self.current_config.asr_compression_ratio_threshold != next_config.asr_compression_ratio_threshold
                or self.current_config.asr_hallucination_silence_threshold != next_config.asr_hallucination_silence_threshold
                or self.current_config.asr_repetition_penalty != next_config.asr_repetition_penalty
                or self.current_config.asr_no_repeat_ngram_size != next_config.asr_no_repeat_ngram_size
                or self.current_config.asr_hotwords_enabled != next_config.asr_hotwords_enabled
                or self.current_config.asr_use_default_hotwords != next_config.asr_use_default_hotwords
            )
            needs_final_asr = (
                next_final_asr_backend
                and (
                    self.final_asr is None
                    or self.final_asr_backend != next_final_asr_backend
                    or self.current_config.asr_device != next_config.asr_device
                )
            )
            translation_is_identity = next_config.source_language == next_config.target_language
            needs_translator = (
                self.translator is None
                or self.current_config.translation_engine != next_config.translation_engine
                or self.current_config.source_language != next_config.source_language
                or self.current_config.target_language != next_config.target_language
                or self.current_config.asr_device != next_config.asr_device
                or self.current_config.nllb_model_name != next_config.nllb_model_name
                or self.current_config.marian_en_zh_model_name != next_config.marian_en_zh_model_name
                or self.current_config.marian_es_zh_model_name != next_config.marian_es_zh_model_name
            )

            if needs_asr:
                if next_asr_backend == "funasr":
                    print("[load] ASR iic/SenseVoiceSmall on cpu", flush=True)
                    self.asr = await asyncio.to_thread(
                        FunASRRealtimeASR,
                        "iic/SenseVoiceSmall",
                        next_config.asr_device,
                    )
                else:
                    print(f"[load] ASR {next_asr_model} on {next_config.asr_device}/{next_config.asr_compute_type}", flush=True)
                    self.asr = await asyncio.to_thread(
                        WhisperASR,
                        next_asr_model,
                        next_config.asr_device,
                        next_config.asr_compute_type,
                        next_config.asr_beam_size,
                        next_config.asr_best_of,
                        next_config.asr_patience,
                        next_config.asr_condition_on_previous_text,
                        next_config.asr_no_speech_threshold,
                        next_config.asr_log_prob_threshold,
                        next_config.asr_compression_ratio_threshold,
                        next_config.asr_hallucination_silence_threshold,
                        next_config.asr_repetition_penalty,
                        next_config.asr_no_repeat_ngram_size,
                        next_config.asr_hotwords_enabled,
                        next_config.asr_use_default_hotwords,
                    )
                self.asr_backend = next_asr_backend

            if needs_final_asr:
                print("[load] Final ASR paraformer-zh + fsmn-vad + ct-punc", flush=True)
                try:
                    self.final_asr = await asyncio.to_thread(
                        FunASRParaformerASR,
                        "paraformer-zh",
                        next_config.asr_device,
                        True,
                    )
                    self.final_asr_backend = next_final_asr_backend
                except Exception as exc:
                    print(f"[load] Final ASR unavailable; falling back to live ASR only: {exc}", flush=True)
                    self.final_asr = None
                    self.final_asr_backend = ""
            elif not next_final_asr_backend:
                if is_local_chinese_identity(next_config):
                    print(f"[load] Final ASR skipped: {final_paraformer_status_detail(next_config)}", flush=True)
                self.final_asr = None
                self.final_asr_backend = ""

            if needs_translator:
                if translation_is_identity:
                    print(f"[load] Identity translation {next_config.source_language}->{next_config.target_language}", flush=True)
                    self.translator = IdentityTranslator()
                elif next_config.translation_engine == "argos":
                    print(f"[load] Argos {next_config.source_language}->{next_config.target_language}", flush=True)
                    self.translator = await asyncio.to_thread(
                        ArgosTranslator,
                        next_config.source_language,
                        next_config.target_language,
                    )
                elif next_config.translation_engine == "marianmt":
                    print("[load] MarianMT", flush=True)
                    self.translator = await asyncio.to_thread(
                        MarianMTTranslator,
                        next_config.marian_en_zh_model_name,
                        next_config.marian_es_zh_model_name,
                        next_config.asr_device,
                    )
                else:
                    print("[load] NLLB", flush=True)
                    self.translator = await asyncio.to_thread(
                        NLLBTranslator,
                        next_config.nllb_model_name,
                        next_config.source_language,
                        next_config.target_language,
                        next_config.asr_device,
                    )

            self.current_config = next_config


runtime = Runtime()


class FunASRStreamingRuntime:
    def __init__(self) -> None:
        self.model: FunASRStreamingASR | None = None
        self.lock = asyncio.Lock()

    async def ensure_model(self, config: FunASRStreamingConfig) -> FunASRStreamingASR:
        async with self.lock:
            if (
                self.model is None
                or self.model.model_name != config.model_name
                or self.model.device != config.effective_device
            ):
                self.model = await asyncio.to_thread(FunASRStreamingASR, config)
            return self.model


funasr_streaming_runtime = FunASRStreamingRuntime()


def public_config_payload(active_config: AppConfig) -> dict[str, Any]:
    return {
        "cloud_configured": bool((active_config.azure_speech_key or "").strip() and (active_config.azure_speech_region or "").strip()),
        "cloud_speech_key_set": bool((active_config.azure_speech_key or "").strip()),
        "funasr_configured": importlib.util.find_spec("funasr") is not None,
    }


def env_enabled(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", "off", ""}


def azure_monitor_config() -> dict[str, str]:
    return {
        "tenant_id": os.getenv("AZURE_TENANT_ID", "").strip(),
        "client_id": os.getenv("AZURE_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("AZURE_CLIENT_SECRET", "").strip(),
        "resource_id": os.getenv("AZURE_SPEECH_RESOURCE_ID", "").strip(),
        "monthly_seconds_limit": str(cloud_monthly_seconds_limit()),
    }


def azure_monitor_configured() -> bool:
    settings = azure_monitor_config()
    return bool(
        settings["tenant_id"]
        and settings["client_id"]
        and settings["client_secret"]
        and settings["resource_id"]
    )


def utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def month_start_utc(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def next_month_start_utc(now: datetime) -> datetime:
    if now.month == 12:
        return datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)


def cloud_quota_month_key(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y-%m")


def cloud_monthly_seconds_limit() -> float:
    raw = os.getenv("AZURE_SPEECH_MONTHLY_SECONDS_LIMIT", "").strip()
    if not raw:
        return float(CLOUD_MONTHLY_SECONDS_LIMIT_DEFAULT)
    try:
        parsed = float(raw)
    except ValueError:
        return float(CLOUD_MONTHLY_SECONDS_LIMIT_DEFAULT)
    return max(1.0, parsed)


def read_cloud_usage_ledger(now: datetime | None = None) -> dict[str, Any]:
    month_key = cloud_quota_month_key(now)
    if not CLOUD_USAGE_LEDGER_PATH.exists():
        return {"monthKey": month_key, "seconds": 0.0}
    try:
        payload = json.loads(CLOUD_USAGE_LEDGER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"monthKey": month_key, "seconds": 0.0}
    if payload.get("monthKey") != month_key:
        return {"monthKey": month_key, "seconds": 0.0}
    return {
        "monthKey": month_key,
        "seconds": max(0.0, float(payload.get("seconds") or 0)),
        "updatedAt": payload.get("updatedAt") or "",
    }


def write_cloud_usage_ledger(payload: dict[str, Any]) -> None:
    CLOUD_USAGE_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLOUD_USAGE_LEDGER_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def add_cloud_usage_seconds(seconds: float, now: datetime | None = None) -> None:
    if seconds <= 0:
        return
    current = now or datetime.now(timezone.utc)
    payload = read_cloud_usage_ledger(current)
    payload["seconds"] = round(float(payload.get("seconds") or 0) + seconds, 2)
    payload["updatedAt"] = utc_iso(current)
    write_cloud_usage_ledger(payload)


def active_cloud_session_seconds(now: float | None = None) -> float:
    current = now or time.time()
    return sum(max(0.0, current - started_at) for started_at in active_cloud_sessions.values())


def register_cloud_session() -> str:
    session_id = f"cloud-{time.time_ns()}"
    active_cloud_sessions[session_id] = time.time()
    return session_id


def finish_cloud_session(session_id: str) -> float:
    started_at = active_cloud_sessions.pop(session_id, None)
    if started_at is None:
        return 0.0
    elapsed = max(0.0, time.time() - started_at)
    add_cloud_usage_seconds(elapsed)
    return elapsed


def apply_cloud_quota_fields(payload: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    monthly_limit = cloud_monthly_seconds_limit()
    remote_month_seconds = max(0.0, float(payload.get("azureMonthSeconds", payload.get("monthSeconds")) or 0))
    ledger = read_cloud_usage_ledger(current)
    local_tracked_seconds = max(0.0, float(ledger.get("seconds") or 0))
    active_seconds = active_cloud_session_seconds()
    tracked_month_seconds = max(remote_month_seconds, local_tracked_seconds)
    remaining_seconds = max(0.0, monthly_limit - tracked_month_seconds - active_seconds)
    payload["monthSeconds"] = round(tracked_month_seconds, 2)
    payload["azureMonthSeconds"] = round(remote_month_seconds, 2)
    payload["localTrackedSeconds"] = round(local_tracked_seconds, 2)
    payload["activeSessionSeconds"] = round(active_seconds, 2)
    payload["monthlyLimitSeconds"] = round(monthly_limit, 2)
    payload["remainingSeconds"] = round(remaining_seconds, 2)
    payload["quotaExceeded"] = remaining_seconds <= 0
    payload["quotaResetAt"] = utc_iso(next_month_start_utc(current))
    return payload


def local_cloud_quota_payload(message: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "configured": False,
        "source": "local_quota",
        "usageMode": "seconds",
        "metric": "local_audio_seconds",
        "daySeconds": 0,
        "monthSeconds": 0,
        "message": message,
        "syncedAt": utc_iso(datetime.now(timezone.utc)),
    }
    return apply_cloud_quota_fields(payload)


def cloud_quota_denial_message(payload: dict[str, Any]) -> str:
    if not payload.get("quotaExceeded"):
        return ""
    reset_at = payload.get("quotaResetAt") or utc_iso(next_month_start_utc(datetime.now(timezone.utc)))
    used = float(payload.get("monthSeconds") or 0) + float(payload.get("activeSessionSeconds") or 0)
    limit = float(payload.get("monthlyLimitSeconds") or cloud_monthly_seconds_limit())
    return (
        f"Cloud monthly quota reached: {used / 3600:.2f}h used of {limit / 3600:.2f}h. "
        f"Quota resets at {reset_at}."
    )


def http_json(url: str, method: str = "GET", data: dict[str, str] | None = None, token: str = "") -> dict[str, Any]:
    encoded_data = None
    headers = {"Accept": "application/json"}
    if data is not None:
        encoded_data = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error: Exception | None = None
    for _ in range(2):
        request = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Cloud request failed: {exc.code} {detail[:240]}") from exc
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
            time.sleep(0.8)
    raise RuntimeError(f"Cloud request failed: {last_error}") from last_error


def azure_monitor_token(settings: dict[str, str]) -> str:
    token_url = f"https://login.microsoftonline.com/{settings['tenant_id']}/oauth2/v2.0/token"
    payload = http_json(
        token_url,
        method="POST",
        data={
            "client_id": settings["client_id"],
            "client_secret": settings["client_secret"],
            "grant_type": "client_credentials",
            "scope": "https://management.azure.com/.default",
        },
    )
    token = str(payload.get("access_token") or "")
    if not token:
        raise RuntimeError("Cloud usage token response did not include an access token.")
    return token


def azure_metric_total(token: str, resource_id: str, metric_name: str, start: datetime, end: datetime) -> float:
    query = urllib.parse.urlencode(
        {
            "api-version": "2023-10-01",
            "metricnames": metric_name,
            "timespan": f"{utc_iso(start)}/{utc_iso(end)}",
            "interval": "PT1H",
            "aggregation": "Total",
        }
    )
    url = f"https://management.azure.com{resource_id}/providers/microsoft.insights/metrics?{query}"
    payload = http_json(url, token=token)
    total = 0.0
    for metric in payload.get("value", []):
        for series in metric.get("timeseries", []):
            for point in series.get("data", []):
                total += float(point.get("total") or 0)
    return total


def azure_audio_seconds(token: str, resource_id: str, start: datetime, end: datetime) -> float:
    return azure_metric_total(token, resource_id, "AudioSecondsTranslated", start, end)


def fetch_azure_usage_payload() -> dict[str, Any]:
    settings = azure_monitor_config()
    if not azure_monitor_configured():
        return local_cloud_quota_payload(
            "Cloud usage sync needs tenant, client, secret, and speech resource id. Enforcing the local monthly quota ledger."
        ) | {
            "ok": True,
            "configured": False,
            "source": "not_configured",
            "message": "Cloud usage sync needs tenant, client, secret, and speech resource id. Enforcing the local monthly quota ledger.",
        }
    now = datetime.now(timezone.utc)
    token = azure_monitor_token(settings)
    try:
        day_seconds = azure_audio_seconds(token, settings["resource_id"], now - timedelta(hours=24), now)
        month_seconds = azure_audio_seconds(token, settings["resource_id"], month_start_utc(now), now)
    except RuntimeError:
        day_calls = azure_metric_total(token, settings["resource_id"], "TotalCalls", now - timedelta(hours=24), now)
        month_calls = azure_metric_total(token, settings["resource_id"], "TotalCalls", month_start_utc(now), now)
        return apply_cloud_quota_fields({
            "ok": True,
            "configured": True,
            "source": "cloud_usage",
            "usageMode": "calls",
            "metric": "calls",
            "daySeconds": 0,
            "monthSeconds": 0,
            "dayCallCount": round(day_calls, 2),
            "monthCallCount": round(month_calls, 2),
            "monthlyLimitSeconds": None,
            "remainingSeconds": None,
            "message": "Cloud usage service does not expose audio-second usage for this speech resource. Showing call activity instead.",
            "syncedAt": utc_iso(now),
        }, now)
    return apply_cloud_quota_fields({
        "ok": True,
        "configured": True,
        "source": "cloud_usage",
        "usageMode": "seconds",
        "metric": "audio_seconds",
        "daySeconds": round(day_seconds, 2),
        "monthSeconds": round(month_seconds, 2),
        "syncedAt": utc_iso(now),
    }, now)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return public_config_payload(runtime.current_config)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "message": "Backend is running", "config": public_config_payload(runtime.current_config)}


async def current_cloud_usage_payload(use_cache: bool = True) -> dict[str, Any]:
    cached_payload = azure_usage_cache.get("payload")
    if use_cache and cached_payload is not None and time.time() - float(azure_usage_cache.get("fetchedAt") or 0) < 60:
        return apply_cloud_quota_fields(dict(cached_payload))
    try:
        payload = await asyncio.to_thread(fetch_azure_usage_payload)
    except RuntimeError as exc:
        last_good = azure_usage_cache.get("lastGoodPayload")
        if isinstance(last_good, dict):
            payload = dict(last_good)
            payload["stale"] = True
            payload["message"] = "Cloud sync temporarily unavailable. Showing last successful cloud usage."
        else:
            payload = local_cloud_quota_payload(
                f"Cloud sync temporarily unavailable. Enforcing the local monthly quota ledger. {exc}"
            )
    azure_usage_cache["payload"] = payload
    azure_usage_cache["fetchedAt"] = time.time()
    if payload.get("ok") and payload.get("configured"):
        azure_usage_cache["lastGoodPayload"] = dict(payload)
    return dict(payload)


@app.get("/api/cloud-usage")
async def cloud_usage() -> dict[str, Any]:
    return await current_cloud_usage_payload()


@app.get("/api/azure-usage")
async def azure_usage() -> dict[str, Any]:
    return await cloud_usage()


@app.post("/api/end-meeting")
async def end_meeting() -> dict[str, Any]:
    global active_recording_path, last_recording_stop_at
    ended_recording = str(active_recording_path) if active_recording_path is not None else ""
    active_recording_path = None
    last_recording_stop_at = 0.0
    return {"ok": True, "message": "Meeting ended", "endedRecording": ended_recording}


def recording_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            if frame_rate:
                return wav_file.getnframes() / frame_rate
    except (OSError, wave.Error):
        return 0.0
    return 0.0


def format_file_size(size: int) -> str:
    value = float(max(0, size))
    units = ["B", "KB", "MB", "GB"]
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.1f} {units[unit_index]}"


@app.get("/api/recordings")
async def list_recordings() -> dict[str, Any]:
    recordings = sorted_recordings()
    return {"ok": True, "recordings": [recording_payload(path) for path in recordings[:50]]}


def sorted_recordings() -> list[Path]:
    recordings: list[Path] = []
    for pattern in RECORDING_PATTERNS:
        recordings.extend(RECORDINGS_DIR.glob(pattern))
    return sorted(
        dict.fromkeys(recordings),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def recording_payload(path: Path) -> dict[str, Any]:
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime)
    duration_seconds = recording_duration_seconds(path)
    return {
        "path": str(path),
        "name": path.name,
        "displayName": modified_at.strftime("%m/%d %H:%M"),
        "sizeBytes": stat.st_size,
        "modifiedAt": modified_at.isoformat(timespec="seconds"),
        "durationSeconds": round(duration_seconds, 1),
    }


def build_config(payload: dict[str, Any]) -> AppConfig:
    merged = asdict(config)
    for key, value in payload.items():
        if key in merged and value not in (None, ""):
            merged[key] = value

    if merged["source_language"] not in ("eng_Latn", "spa_Latn", "jpn_Jpan", "zho_Hans"):
        merged["source_language"] = "eng_Latn"
    merged["target_language"] = "zho_Hans"
    merged["azure_source_language"] = azure_language_code(merged["source_language"])
    merged["azure_target_language"] = "zh-Hans"

    merged["chunk_seconds"] = max(1.0, min(5.0, float(merged["chunk_seconds"])))
    merged["overlap_seconds"] = max(0.0, min(1.0, float(merged["overlap_seconds"])))
    merged["adaptive_chunking_enabled"] = bool(merged["adaptive_chunking_enabled"])
    merged["min_chunk_seconds"] = max(0.5, min(float(merged["chunk_seconds"]), float(merged["min_chunk_seconds"])))
    merged["chunk_flush_silence_seconds"] = max(0.0, min(1.0, float(merged["chunk_flush_silence_seconds"])))
    if merged["asr_compute_type"] not in ("int8", "int8_float16", "float16", "float32"):
        merged["asr_compute_type"] = "int8"
    merged["asr_beam_size"] = max(1, min(5, int(merged["asr_beam_size"])))
    merged["asr_best_of"] = max(1, min(5, int(merged["asr_best_of"])))
    merged["asr_patience"] = max(0.8, min(1.5, float(merged["asr_patience"])))
    merged["asr_condition_on_previous_text"] = bool(merged["asr_condition_on_previous_text"])
    merged["asr_no_speech_threshold"] = max(0.1, min(0.95, float(merged["asr_no_speech_threshold"])))
    merged["asr_log_prob_threshold"] = max(-3.0, min(0.0, float(merged["asr_log_prob_threshold"])))
    merged["asr_compression_ratio_threshold"] = max(1.2, min(4.0, float(merged["asr_compression_ratio_threshold"])))
    merged["asr_hallucination_silence_threshold"] = max(0.2, min(3.0, float(merged["asr_hallucination_silence_threshold"])))
    merged["asr_repetition_penalty"] = max(1.0, min(1.3, float(merged["asr_repetition_penalty"])))
    merged["asr_no_repeat_ngram_size"] = max(0, min(5, int(merged["asr_no_repeat_ngram_size"])))
    merged["asr_hotwords_enabled"] = bool(merged["asr_hotwords_enabled"])
    merged["asr_use_default_hotwords"] = bool(merged["asr_use_default_hotwords"])
    merged["max_subtitles"] = max(1, min(5, int(merged["max_subtitles"])))
    merged["queue_max_size"] = max(1, min(4, int(merged["queue_max_size"])))
    merged["audio_sample_rate"] = int(merged["audio_sample_rate"])
    merged["audio_channels"] = int(merged["audio_channels"])
    merged["vad_rms_threshold"] = float(merged["vad_rms_threshold"])
    merged["system_vad_rms_threshold"] = max(0.004, min(0.05, float(merged["system_vad_rms_threshold"])))
    if merged["audio_source"] not in ("microphone", "system"):
        merged["audio_source"] = "microphone"
    merged["turn_detector_enabled"] = bool(merged["turn_detector_enabled"])
    merged["turn_pause_seconds"] = max(0.6, min(4.0, float(merged["turn_pause_seconds"])))
    merged["noise_min_words"] = max(1, min(5, int(merged["noise_min_words"])))
    merged["segmenter_enabled"] = bool(merged["segmenter_enabled"])
    merged["segmenter_pause_seconds"] = max(0.4, min(2.0, float(merged["segmenter_pause_seconds"])))
    merged["segmenter_max_words"] = max(8, min(40, int(merged["segmenter_max_words"])))
    merged["segmenter_max_seconds"] = max(3.0, min(20.0, float(merged["segmenter_max_seconds"])))
    merged["context_buffer_enabled"] = bool(merged["context_buffer_enabled"])
    merged["context_buffer_min_words"] = max(4, min(24, int(merged["context_buffer_min_words"])))
    merged["context_buffer_max_words"] = max(12, min(80, int(merged["context_buffer_max_words"])))
    merged["context_buffer_max_wait_seconds"] = max(0.2, min(2.0, float(merged["context_buffer_max_wait_seconds"])))
    merged["quality_final_mode"] = bool(merged["quality_final_mode"])
    return AppConfig(**merged)


def whisper_language(source_language: str) -> str:
    if source_language == "spa_Latn":
        return "es"
    if source_language == "jpn_Jpan":
        return "ja"
    if source_language == "zho_Hans":
        return "zh"
    return "en"


def effective_asr_model(model_size: str, source_language: str) -> str:
    if source_language in ("spa_Latn", "jpn_Jpan", "zho_Hans"):
        if model_size.endswith(".en"):
            return model_size.removesuffix(".en")
    return model_size


def should_use_realtime_funasr(active_config: AppConfig) -> bool:
    return active_config.translation_engine != "azure" and active_config.source_language == "zho_Hans"


def is_local_chinese_identity(active_config: AppConfig) -> bool:
    return (
        active_config.translation_engine != "azure"
        and active_config.source_language == "zho_Hans"
        and active_config.target_language == "zho_Hans"
    )


def is_quality_final_recording_only(active_config: AppConfig) -> bool:
    return is_local_chinese_identity(active_config) and active_config.quality_final_mode


def available_physical_memory_gb() -> float | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.ullAvailPhys / (1024**3)
    except Exception:
        return None


def final_paraformer_min_free_gb() -> float:
    try:
        return max(0.0, float(os.getenv("LOCAL_CHINESE_FINAL_ASR_MIN_FREE_GB", "5.5")))
    except ValueError:
        return 5.5


def should_use_final_paraformer(active_config: AppConfig) -> bool:
    if not is_local_chinese_identity(active_config):
        return False
    value = os.getenv("LOCAL_CHINESE_FINAL_ASR_ENABLED", "auto").strip().lower()
    if value in {"0", "false", "no", "off"}:
        return False
    if value in {"1", "true", "yes", "on", "force"}:
        return True
    free_gb = available_physical_memory_gb()
    min_free_gb = final_paraformer_min_free_gb()
    return free_gb is None or free_gb >= min_free_gb


def final_paraformer_status_detail(active_config: AppConfig) -> str:
    if not is_local_chinese_identity(active_config):
        return "not a local Chinese identity session"
    value = os.getenv("LOCAL_CHINESE_FINAL_ASR_ENABLED", "auto").strip().lower()
    if value in {"0", "false", "no", "off"}:
        return "disabled by LOCAL_CHINESE_FINAL_ASR_ENABLED"
    if value in {"1", "true", "yes", "on", "force"}:
        return "forced on"
    free_gb = available_physical_memory_gb()
    min_free_gb = final_paraformer_min_free_gb()
    if free_gb is None:
        return "auto memory check unavailable"
    if free_gb < min_free_gb:
        return f"low free memory {free_gb:.1f}GB < {min_free_gb:.1f}GB"
    return f"free memory {free_gb:.1f}GB >= {min_free_gb:.1f}GB"


def user_facing_model_error(exc: Exception, active_config: AppConfig, effective_model: str) -> str:
    message = str(exc)
    if active_config.source_language == "zho_Hans" and active_config.translation_engine != "azure":
        if "LocalEntryNotFoundError" in message or "ConnectTimeout" in message or "UNEXPECTED_EOF" in message:
            return (
                "Local Chinese mode needs FunASR `iic/SenseVoiceSmall`. "
                "It is not fully downloaded yet, and the model download connection failed. "
                "Use Cloud mode for now, or download SenseVoiceSmall before using local Chinese."
            )
    return message


def azure_language_code(source_language: str) -> str:
    if source_language == "spa_Latn":
        return "es-ES"
    if source_language == "jpn_Jpan":
        return "ja-JP"
    if source_language == "zho_Hans":
        return "zh-CN"
    return "en-US"


def effective_vad_rms_threshold(active_config: AppConfig) -> float:
    if active_config.audio_source == "system":
        return max(active_config.vad_rms_threshold, active_config.system_vad_rms_threshold)
    return active_config.vad_rms_threshold


def session_recording_path() -> Path:
    global active_recording_path
    now = time.time()
    if (
        active_recording_path is not None
        and active_recording_path.exists()
        and now - last_recording_stop_at <= RECORDING_RESUME_SECONDS
    ):
        return active_recording_path

    timestamp = datetime.now().strftime("%m%d-%H%M%S")
    active_recording_path = RECORDINGS_DIR / f"rec-{timestamp}.wav"
    return active_recording_path


def create_queue(max_size: int) -> asyncio.Queue:
    return asyncio.Queue(maxsize=max_size)


def put_latest(queue_: asyncio.Queue, item: object) -> None:
    while queue_.full():
        try:
            queue_.get_nowait()
            queue_.task_done()
        except asyncio.QueueEmpty:
            break
    queue_.put_nowait(item)


def enqueue_translation(queue_: asyncio.Queue, item: object) -> None:
    queue_.put_nowait(item)


def enqueue_subtitle(queue_: asyncio.Queue, item: object) -> None:
    queue_.put_nowait(item)


async def send_status(websocket: WebSocket, status: str, detail: str | None = None) -> None:
    payload: dict[str, Any] = {"type": "status", "status": status}
    if detail:
        payload["detail"] = detail
    await websocket.send_json(payload)


async def watch_control_messages(websocket: WebSocket, stop_event: asyncio.Event) -> None:
    try:
        while not stop_event.is_set():
            message = await websocket.receive_json()
            if message.get("action") == "stop":
                stop_event.set()
    except WebSocketDisconnect:
        stop_event.set()


async def cloud_quota_guard_worker(status_queue: asyncio.Queue, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(CLOUD_QUOTA_GUARD_INTERVAL_SECONDS)
        quota_payload = await current_cloud_usage_payload(use_cache=True)
        denial = cloud_quota_denial_message(quota_payload)
        if denial:
            put_latest(
                status_queue,
                {
                    "type": "notice",
                    "label": "Quota reached",
                    "detail": denial,
                },
            )
            stop_event.set()
            return


async def browser_audio_to_azure_worker(
    websocket: WebSocket,
    session: AzureSpeechTranslationSession,
    recording_path: Path,
    status_queue: asyncio.Queue,
    stop_event: asyncio.Event,
    sample_rate: int = 16_000,
) -> None:
    global active_recording_path
    active_recording_path = recording_path
    wav_file: wave.Wave_write | None = None
    last_audio_notice_at = 0.0
    try:
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        wav_file = wave.open(str(recording_path), "wb")
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        put_latest(
            status_queue,
            {
                "type": "notice",
                "label": "Recording",
                "detail": str(recording_path),
            },
        )
        while not stop_event.is_set():
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                stop_event.set()
                break
            if message.get("text"):
                try:
                    payload = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue
                if payload.get("action") == "stop":
                    stop_event.set()
                    break
                continue
            data = message.get("bytes") or b""
            if not data:
                continue
            if len(data) % 2:
                data = data[:-1]
            if not data:
                continue
            pcm16 = np.frombuffer(data, dtype=np.int16)
            samples = (pcm16.astype(np.float32) / 32768.0).clip(-1.0, 1.0)
            wav_file.writeframes(data)
            session.write_audio(samples)
            now = time.perf_counter()
            if now - last_audio_notice_at >= 1.0:
                rms = float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0
                put_latest(
                    status_queue,
                    {
                        "type": "notice",
                        "label": "Browser audio" if rms >= 0.003 else "No browser audio",
                        "detail": f"rms={rms:.4f}",
                    },
                )
                last_audio_notice_at = now
    except WebSocketDisconnect:
        stop_event.set()
    finally:
        if wav_file is not None:
            wav_file.close()


async def audio_capture_worker(
    capture: MicrophoneAudioCapture,
    audio_queue: asyncio.Queue,
    status_queue: asyncio.Queue,
    active_config: AppConfig,
    stop_event: asyncio.Event,
) -> None:
    vad_rms_threshold = effective_vad_rms_threshold(active_config)
    async for chunk in capture.chunks():
        if stop_event.is_set():
            break
        if chunk.rms < vad_rms_threshold:
            put_latest(
                status_queue,
                {
                    "type": "notice",
                    "label": "Silent",
                    "detail": f"rms={chunk.rms:.4f}; gate={vad_rms_threshold:.4f}",
                },
            )
            continue
        put_latest(audio_queue, ASRJob(chunk=chunk))


async def recording_only_drain_worker(
    capture: MicrophoneAudioCapture,
    stop_event: asyncio.Event,
) -> None:
    async for _frame in capture.frames():
        if stop_event.is_set():
            break


async def asr_worker(
    audio_queue: asyncio.Queue,
    translate_queue: asyncio.Queue,
    subtitle_queue: asyncio.Queue,
    status_queue: asyncio.Queue,
    active_config: AppConfig,
    stop_event: asyncio.Event,
) -> None:
    assert runtime.asr is not None
    aggregator = LocalUtteranceAggregator(active_config)
    use_final_paraformer = is_local_chinese_identity(active_config) and runtime.final_asr is not None
    final_target_seconds = 58.0 if is_local_chinese_identity(active_config) else 12.0
    final_min_boundary_seconds = 45.0 if is_local_chinese_identity(active_config) else 4.0
    final_max_seconds = 75.0 if is_local_chinese_identity(active_config) else 12.0
    final_boundary_idle_seconds = 1.2 if is_local_chinese_identity(active_config) else 3.8
    final_overlap_seconds = 2.0 if is_local_chinese_identity(active_config) else 0.0
    final_samples: list[np.ndarray] = []
    final_start_seconds = 0.0
    final_end_seconds = 0.0
    final_captured_at = 0.0
    final_updated_at = 0.0

    def source_confirmation_subtitle(job: TranslateJob) -> SubtitleJob:
        return SubtitleJob(
            sequence_id=job.sequence_id,
            source_text=job.source_text,
            translated_text="",
            start_seconds=job.start_seconds,
            end_seconds=job.end_seconds,
            audio_duration_seconds=job.audio_duration_seconds,
            asr_ms=job.asr_ms,
            translate_ms=0,
            total_latency_ms=(time.perf_counter() - job.captured_at) * 1000,
            engine="local-source-confirmed",
            is_final=True,
            draft_sequence_ids=job.draft_sequence_ids,
        )

    async def flush_final_paraformer(reason: str, keep_tail: bool = False) -> None:
        nonlocal final_samples, final_start_seconds, final_end_seconds, final_captured_at, final_updated_at
        if not use_final_paraformer or runtime.final_asr is None or not final_samples:
            return
        samples = np.concatenate(final_samples).astype(np.float32, copy=False)
        if samples.size < int(active_config.audio_sample_rate * 4):
            return
        start_seconds = final_start_seconds
        end_seconds = final_end_seconds
        captured_at = final_captured_at or time.perf_counter()
        tail_samples: np.ndarray | None = None
        tail_seconds = 0.0
        if keep_tail and final_overlap_seconds > 0:
            tail_count = min(samples.size, int(active_config.audio_sample_rate * final_overlap_seconds))
            if samples.size - tail_count >= int(active_config.audio_sample_rate * 4):
                tail_samples = samples[-tail_count:].copy()
                tail_seconds = tail_count / active_config.audio_sample_rate

        if tail_samples is not None:
            final_samples = [tail_samples]
            final_start_seconds = max(start_seconds, end_seconds - tail_seconds)
            final_end_seconds = end_seconds
            final_captured_at = time.perf_counter()
            final_updated_at = time.perf_counter()
        else:
            final_samples = []
            final_start_seconds = 0.0
            final_end_seconds = 0.0
            final_captured_at = 0.0
            final_updated_at = 0.0

        started = time.perf_counter()
        put_latest(status_queue, {"type": "status", "status": "Transcribing", "detail": f"Final ASR {reason}."})
        final_results = await runtime.final_asr.transcribe(samples, start_seconds, language="zh")
        asr_ms = (time.perf_counter() - started) * 1000
        text = ""
        for result in final_results:
            text = LocalUtteranceAggregator._merge_text(text, result.text)
        text = text.strip()
        if not text:
            return
        enqueue_translation(
            translate_queue,
            TranslateJob(
                sequence_id=f"local-final-{int(start_seconds * 1000)}-{int(end_seconds * 1000)}",
                source_text=text,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                audio_duration_seconds=max(0.0, end_seconds - start_seconds),
                captured_at=captured_at,
                asr_ms=asr_ms,
                draft_sequence_ids=[],
            ),
        )

    def append_final_audio(job: ASRJob) -> None:
        nonlocal final_start_seconds, final_end_seconds, final_captured_at, final_updated_at
        if not use_final_paraformer:
            return
        samples = job.chunk.samples.astype(np.float32, copy=False)
        if not final_samples:
            final_start_seconds = job.chunk.start_seconds
            final_captured_at = job.chunk.captured_at
        else:
            overlap_seconds = max(0.0, final_end_seconds - job.chunk.start_seconds)
            overlap_samples = min(len(samples), int(overlap_seconds * active_config.audio_sample_rate))
            if overlap_samples >= len(samples):
                final_end_seconds = max(final_end_seconds, job.chunk.end_seconds)
                final_updated_at = time.perf_counter()
                return
            if overlap_samples > 0:
                samples = samples[overlap_samples:]
            gap_seconds = job.chunk.start_seconds - final_end_seconds
            if gap_seconds > 0.02:
                gap_samples = int(gap_seconds * active_config.audio_sample_rate)
                final_samples.append(np.zeros(gap_samples, dtype=np.float32))
        final_samples.append(samples)
        final_end_seconds = max(final_end_seconds, job.chunk.end_seconds)
        final_updated_at = time.perf_counter()

    while not stop_event.is_set():
        try:
            job: ASRJob = await asyncio.wait_for(audio_queue.get(), timeout=0.2)
        except asyncio.TimeoutError:
            final_duration = final_end_seconds - final_start_seconds
            if (
                use_final_paraformer
                and final_samples
                and final_duration >= final_min_boundary_seconds
                and time.perf_counter() - final_updated_at >= final_boundary_idle_seconds
            ):
                await flush_final_paraformer("speech boundary")
            pending_job = aggregator.mark_ready_if_idle()
            if pending_job is not None:
                if use_final_paraformer:
                    enqueue_subtitle(subtitle_queue, source_confirmation_subtitle(pending_job))
                else:
                    enqueue_translation(translate_queue, pending_job)
                put_latest(status_queue, {"type": "status", "status": "Translating", "detail": "Translating completed sentence."})
            continue

        append_final_audio(job)
        if use_final_paraformer and final_samples and final_end_seconds - final_start_seconds >= final_max_seconds:
            await flush_final_paraformer("max quality window", keep_tail=True)

        started = time.perf_counter()
        put_latest(status_queue, {"type": "status", "status": "Transcribing"})
        transcriptions = await runtime.asr.transcribe(
            job.chunk.samples,
            job.chunk.start_seconds,
            language=whisper_language(active_config.source_language),
        )
        asr_ms = (time.perf_counter() - started) * 1000
        audio_queue.task_done()

        if not transcriptions:
            pending_job = aggregator.mark_ready_if_idle()
            if pending_job is not None:
                if use_final_paraformer:
                    enqueue_subtitle(subtitle_queue, source_confirmation_subtitle(pending_job))
                else:
                    enqueue_translation(translate_queue, pending_job)
            put_latest(status_queue, {"type": "status", "status": "Listening", "detail": "No speech detected."})
            continue

        final_sentence_boundary = False
        for item in transcriptions:
            update = aggregator.add_asr_result(item, job, asr_ms)
            if update.draft is not None:
                enqueue_subtitle(subtitle_queue, update.draft)
            if update.ready is not None:
                final_sentence_boundary = True
                if use_final_paraformer:
                    enqueue_subtitle(subtitle_queue, source_confirmation_subtitle(update.ready))
                else:
                    enqueue_translation(translate_queue, update.ready)

        if (
            use_final_paraformer
            and final_sentence_boundary
            and final_samples
            and final_end_seconds - final_start_seconds >= final_target_seconds
        ):
            await flush_final_paraformer("sentence boundary")

    if use_final_paraformer and final_samples:
        await flush_final_paraformer("session end")


async def translate_worker(
    translate_queue: asyncio.Queue,
    subtitle_queue: asyncio.Queue,
    status_queue: asyncio.Queue,
    active_config: AppConfig,
    stop_event: asyncio.Event,
) -> None:
    assert runtime.translator is not None
    context_buffer = ContextualTranslationBuffer(active_config)
    chinese_reading_buffer = ChineseReadingBuffer(is_local_chinese_identity(active_config))
    recent_chinese_final_context = ""

    async def process_translate_job(job: TranslateJob) -> None:
        nonlocal recent_chinese_final_context
        started = time.perf_counter()
        put_latest(
            status_queue,
            {
                "type": "status",
                "status": "Translating",
                "detail": "Polishing final Chinese text." if is_local_chinese_identity(active_config) else None,
            },
        )
        if is_local_chinese_identity(active_config):
            translated = await asyncio.to_thread(
                polish_chinese_with_ollama,
                job.source_text,
                recent_chinese_final_context,
            )
            translated = remove_chinese_context_overlap(recent_chinese_final_context, translated)
            recent_chinese_final_context = update_chinese_final_context(recent_chinese_final_context, translated)
        elif active_config.source_language == active_config.target_language:
            translated = job.source_text
        else:
            translated = await runtime.translator.translate(
                job.source_text,
                active_config.source_language,
                active_config.target_language,
            )
        translate_ms = (time.perf_counter() - started) * 1000
        total_latency_ms = (time.perf_counter() - job.captured_at) * 1000

        enqueue_subtitle(
            subtitle_queue,
            SubtitleJob(
                sequence_id=job.sequence_id,
                source_text=job.source_text,
                translated_text=translated,
                start_seconds=job.start_seconds,
                end_seconds=job.end_seconds,
                audio_duration_seconds=job.audio_duration_seconds,
                asr_ms=job.asr_ms,
                translate_ms=translate_ms,
                total_latency_ms=total_latency_ms,
                engine=runtime.translator.engine_name,
                is_final=True,
                draft_sequence_ids=job.draft_sequence_ids,
            ),
        )
        put_latest(status_queue, {"type": "status", "status": "Listening", "detail": "Waiting for speech."})

    async def process_ready_jobs(jobs: list[TranslateJob]) -> None:
        for ready_job in jobs:
            if chinese_reading_buffer.enabled:
                decision = chinese_reading_buffer.add(ready_job)
                if decision.detail:
                    put_latest(status_queue, {"type": "status", "status": "Translating", "detail": decision.detail})
                for readable_job in decision.ready:
                    await process_translate_job(readable_job)
            else:
                await process_translate_job(ready_job)

    while not stop_event.is_set():
        try:
            job: TranslateJob = await asyncio.wait_for(translate_queue.get(), timeout=0.2)
        except asyncio.TimeoutError:
            reading_decision = chinese_reading_buffer.flush_if_idle()
            if reading_decision.detail:
                put_latest(status_queue, {"type": "status", "status": "Translating", "detail": reading_decision.detail})
            try:
                for readable_job in reading_decision.ready:
                    await process_translate_job(readable_job)
            except Exception as exc:
                put_latest(status_queue, {"type": "status", "status": "Error", "detail": f"Translation failed: {exc}"})
                continue
            decision = context_buffer.flush_if_idle()
            if decision.detail:
                put_latest(status_queue, {"type": "status", "status": "Translating", "detail": decision.detail})
            try:
                await process_ready_jobs(decision.ready)
            except Exception as exc:
                put_latest(status_queue, {"type": "status", "status": "Error", "detail": f"Translation failed: {exc}"})
            continue

        try:
            decision = context_buffer.add(job)
            if decision.detail:
                put_latest(status_queue, {"type": "status", "status": "Translating", "detail": decision.detail})
            await process_ready_jobs(decision.ready)
        except Exception as exc:
            put_latest(status_queue, {"type": "status", "status": "Error", "detail": f"Translation failed: {exc}"})
        finally:
            translate_queue.task_done()


async def websocket_push_worker(
    websocket: WebSocket,
    subtitle_queue: asyncio.Queue,
    status_queue: asyncio.Queue,
    stop_event: asyncio.Event,
    active_config: AppConfig | None = None,
) -> None:
    turn_detector = (
        SubtitleTurnDetector(
            active_config.turn_pause_seconds,
            active_config.noise_min_words,
            active_config.noise_phrases,
        )
        if active_config is not None and active_config.turn_detector_enabled
        else None
    )
    while not stop_event.is_set():
        status_task = asyncio.create_task(status_queue.get())
        subtitle_task = asyncio.create_task(subtitle_queue.get())
        done, pending = await asyncio.wait(
            {status_task, subtitle_task},
            return_when=asyncio.FIRST_COMPLETED,
            timeout=0.2,
        )

        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if not done:
            continue

        for task in done:
            payload = task.result()
            if isinstance(payload, SubtitleJob):
                perf = {
                    "audioSeconds": round(payload.audio_duration_seconds, 2),
                    "asrMs": round(payload.asr_ms, 1),
                    "translateMs": round(payload.translate_ms, 1),
                    "totalLatencyMs": round(payload.total_latency_ms, 1),
                    "engine": payload.engine,
                }
                await websocket.send_json(
                    {
                        "type": "subtitle",
                        "sequenceId": payload.sequence_id,
                        "sourceText": payload.source_text,
                        "translatedText": payload.translated_text,
                        "start": round(payload.start_seconds, 2),
                        "end": round(payload.end_seconds, 2),
                        "isFinal": payload.is_final,
                        "draftSequenceIds": payload.draft_sequence_ids,
                        "perf": perf,
                    }
                )
                print(f"[perf] {perf} text={payload.source_text!r}", flush=True)
                subtitle_queue.task_done()
            elif isinstance(payload, CloudSubtitle):
                turn_meta: dict[str, Any] = {}
                if turn_detector is not None and payload.is_final:
                    decision = turn_detector.classify(payload)
                    if decision.is_noise:
                        turn_meta["isNoise"] = True
                    elif len(SubtitleTurnDetector._normalize_text(payload.source_text).split()) < active_config.noise_min_words:
                        turn_meta["isShort"] = True
                    turn_meta["isNewTurn"] = decision.is_new_turn

                total_latency_ms = (time.perf_counter() - payload.received_at) * 1000
                perf = {
                    "audioSeconds": round(payload.end_seconds - payload.start_seconds, 2),
                    "asrMs": 0,
                    "translateMs": 0,
                    "totalLatencyMs": round(total_latency_ms, 1),
                    "engine": "azure",
                    "final": payload.is_final,
                }
                await websocket.send_json(
                    {
                        "type": "subtitle",
                        "sequenceId": payload.sequence_id,
                        "sourceText": payload.source_text,
                        "translatedText": payload.translated_text,
                        "start": round(payload.start_seconds, 2),
                        "end": round(payload.end_seconds, 2),
                        "isFinal": payload.is_final,
                        "perf": perf,
                        **turn_meta,
                    }
                )
                print(f"[azure] {perf} text={payload.source_text!r}", flush=True)
                subtitle_queue.task_done()
            else:
                await websocket.send_json(payload)
                status_queue.task_done()


async def send_funasr_event(websocket: WebSocket, event_type: str, text: str, **extra: Any) -> None:
    await websocket.send_json(
        {
            "type": event_type,
            "text": text,
            "timestamp": int(time.time() * 1000),
            "latency_ms": round(float(extra.pop("latency_ms", 0.0)), 1),
            **extra,
        }
    )


async def watch_funasr_control_messages(websocket: WebSocket, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            message = await websocket.receive_json()
        except WebSocketDisconnect:
            stop_event.set()
            return
        except Exception:
            continue
        if message.get("action") in {"stop", "end"}:
            stop_event.set()
            return


def funasr_streaming_config(payload: dict[str, Any]) -> FunASRStreamingConfig:
    config_payload = payload.get("config") or {}
    chunk_size = config_payload.get("chunk_size") or ASR_CHUNK_SIZE
    if not isinstance(chunk_size, list) or len(chunk_size) != 3:
        chunk_size = ASR_CHUNK_SIZE
    device = str(config_payload.get("asr_device") or ASR_DEVICE).lower()
    if device not in {"auto", "cuda", "cpu"}:
        device = "auto"
    return FunASRStreamingConfig(
        model_name=str(config_payload.get("model_name") or "").strip()
        or "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
        sample_rate=ASR_SAMPLE_RATE,
        chunk_ms=int(config_payload.get("chunk_ms") or ASR_CHUNK_MS),
        chunk_size=[int(item) for item in chunk_size],
        enable_punctuation=bool(config_payload.get("enable_punctuation", ASR_ENABLE_PUNCTUATION)),
        enable_vad=bool(config_payload.get("enable_vad", ASR_ENABLE_VAD)),
        device=device,  # type: ignore[arg-type]
    )


@app.websocket("/ws/asr/funasr")
async def funasr_streaming_subtitles(websocket: WebSocket) -> None:
    await websocket.accept()
    stop_event = asyncio.Event()
    capture: StreamingAudioCapture | None = None
    control_task: asyncio.Task | None = None
    state = SubtitleState()
    heard_speech = False
    silence_chunks = 0
    silence_flush_chunks = 3

    try:
        start_message = await websocket.receive_json()
        if start_message.get("action") != "start":
            await send_funasr_event(websocket, "error", "Expected start action.")
            return

        config_payload = start_message.get("config") or {}
        streaming_config = funasr_streaming_config(start_message)
        await send_funasr_event(
            websocket,
            "status",
            f"Loading {ASR_ENGINE}: {streaming_config.model_name}",
            engine=ASR_ENGINE,
            sample_rate=ASR_SAMPLE_RATE,
            chunk_ms=streaming_config.chunk_ms,
            chunk_size=streaming_config.chunk_size,
        )
        asr_model = await funasr_streaming_runtime.ensure_model(streaming_config)
        asr_model.reset_cache()

        capture = StreamingAudioCapture(
            audio_source=str(config_payload.get("audio_source") or "microphone"),
            recording_path=session_recording_path(),
            sample_rate=ASR_SAMPLE_RATE,
            chunk_ms=streaming_config.chunk_ms,
            queue_maxsize=int(config_payload.get("queue_max_size") or ASR_QUEUE_MAXSIZE),
        )
        capture.start()
        control_task = asyncio.create_task(watch_funasr_control_messages(websocket, stop_event))

        source_notice = capture.source_notice()
        await send_funasr_event(
            websocket,
            "status",
            f"{source_notice.get('label')}: {source_notice.get('detail')}",
            status="Listening",
        )
        recording_notice = capture.recording_notice()
        if recording_notice is not None:
            await send_funasr_event(
                websocket,
                "status",
                "Recording",
                status="Recording",
                recordingPath=recording_notice.get("detail", ""),
            )
        await send_funasr_event(
            websocket,
            "status",
            "本地中文实时字幕：FunASR Streaming",
            status="Listening",
            model=asr_model.model_name,
            device=asr_model.device,
        )

        async for chunk in capture.chunks():
            if stop_event.is_set():
                break
            chunk_started = time.perf_counter()
            result = await asyncio.to_thread(
                asr_model.transcribe_pcm_chunk,
                chunk.pcm16,
                is_final=False,
                captured_at=chunk.captured_at,
            )
            event = state.update(result)
            if event is not None:
                await websocket.send_json(event)
            if result.text:
                heard_speech = True

            if chunk.is_silence:
                silence_chunks += 1
            else:
                silence_chunks = 0

            if heard_speech and silence_chunks >= silence_flush_chunks and state.current_partial:
                final_result = await asyncio.to_thread(
                    asr_model.transcribe_pcm_chunk,
                    chunk.pcm16,
                    is_final=True,
                    captured_at=chunk.captured_at,
                )
                final_event = state.update(final_result) or state.force_finalize(final_result.latency_ms)
                if final_event is not None:
                    await websocket.send_json(final_event)
                heard_speech = False
                silence_chunks = 0

            elapsed_ms = (time.perf_counter() - chunk_started) * 1000
            if elapsed_ms > streaming_config.chunk_ms:
                print(
                    f"[funasr-streaming] warning: chunk processing {elapsed_ms:.1f}ms exceeds chunk {streaming_config.chunk_ms}ms",
                    flush=True,
                )

        if state.current_partial:
            silence = np.zeros(int(ASR_SAMPLE_RATE * 0.2), dtype=np.int16).tobytes()
            final_result = await asyncio.to_thread(
                asr_model.transcribe_pcm_chunk,
                silence,
                is_final=True,
                captured_at=time.perf_counter(),
            )
            final_event = state.update(final_result) or state.force_finalize(final_result.latency_ms)
            if final_event is not None:
                await websocket.send_json(final_event)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await send_funasr_event(websocket, "error", str(exc))
        except Exception:
            pass
    finally:
        global last_recording_stop_at
        last_recording_stop_at = time.time()
        stop_event.set()
        if capture is not None:
            await capture.stop()
        if control_task is not None:
            control_task.cancel()
            await asyncio.gather(control_task, return_exceptions=True)
        print(f"[funasr-streaming] transcript chars={len(state.transcript_text())}", flush=True)


@app.websocket("/ws/subtitles")
async def subtitles(websocket: WebSocket) -> None:
    await websocket.accept()
    capture: MicrophoneAudioCapture | None = None
    azure_session: AzureSpeechTranslationSession | None = None
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task] = []
    active_config: AppConfig | None = None
    effective_model = ""
    cloud_session_id = ""

    try:
        start_message = await websocket.receive_json()
        if start_message.get("action") != "start":
            await send_status(websocket, "Error", "Expected start action.")
            return

        active_config = build_config(start_message.get("config", {}))
        effective_model = effective_asr_model(active_config.asr_model_size, active_config.source_language)
        recording_only_quality = is_quality_final_recording_only(active_config)
        uses_dual_chinese_asr = should_use_final_paraformer(active_config) and not recording_only_quality
        uses_local_chinese_identity = is_local_chinese_identity(active_config)
        display_asr_model = (
            "Quality Final recording only"
            if recording_only_quality
            else "Live SenseVoiceSmall; final Paraformer-zh"
            if uses_dual_chinese_asr
            else "Live SenseVoiceSmall; final off"
            if uses_local_chinese_identity
            else "SenseVoiceSmall"
            if should_use_realtime_funasr(active_config)
            else effective_model
        )
        use_browser_audio = (
            active_config.translation_engine == "azure"
            and str((start_message.get("config") or {}).get("audio_transport") or "").lower() == "browser"
        )
        if active_config.translation_engine == "azure":
            quota_payload = await current_cloud_usage_payload(use_cache=False)
            quota_denial = cloud_quota_denial_message(quota_payload)
            if quota_denial:
                await send_status(websocket, "Error", quota_denial)
                return
            remaining = float(quota_payload.get("remainingSeconds") or 0)
            await send_status(
                websocket,
                "Connecting cloud",
                f"Cloud speech translation. Monthly quota remaining: {remaining / 3600:.2f}h.",
            )
        else:
            await send_status(
                websocket,
                "Preparing recording" if recording_only_quality else "Loading models",
                (
                    "Quality Final records first and runs local FunASR after End."
                    if recording_only_quality
                    else f"ASR {display_asr_model}; translator {active_config.translation_engine}"
                ),
            )
            if not recording_only_quality:
                await runtime.ensure_models(active_config)

        audio_queue = create_queue(active_config.queue_max_size)
        translate_queue = asyncio.Queue()
        subtitle_queue = asyncio.Queue()
        status_queue = create_queue(max(3, active_config.queue_max_size))

        if not use_browser_audio:
            capture = MicrophoneAudioCapture(
                sample_rate=active_config.audio_sample_rate,
                channels=active_config.audio_channels,
                chunk_seconds=active_config.chunk_seconds,
                overlap_seconds=active_config.overlap_seconds,
                adaptive_chunking_enabled=active_config.adaptive_chunking_enabled,
                min_chunk_seconds=active_config.min_chunk_seconds,
                chunk_flush_silence_seconds=active_config.chunk_flush_silence_seconds,
                chunk_flush_rms_threshold=effective_vad_rms_threshold(active_config),
                audio_source=active_config.audio_source,
                recording_path=session_recording_path(),
            )
            capture.start()
            put_latest(status_queue, capture.source_notice())
            recording_notice = capture.recording_notice()
            if recording_notice is not None:
                put_latest(status_queue, recording_notice)
            print(
                f"[audio] requested={active_config.audio_source} "
                f"selected={capture.selected_source_label}: {capture.selected_source_detail}",
                flush=True,
            )

        if active_config.translation_engine == "azure":
            cloud_session_id = register_cloud_session()
            azure_session = AzureSpeechTranslationSession(
                active_config,
                asyncio.get_running_loop(),
                subtitle_queue,
                status_queue,
            )
            if use_browser_audio:
                await azure_session.start()
                recording_path = session_recording_path()
                tasks = [
                    asyncio.create_task(cloud_quota_guard_worker(status_queue, stop_event)),
                    asyncio.create_task(
                        browser_audio_to_azure_worker(
                            websocket,
                            azure_session,
                            recording_path,
                            status_queue,
                            stop_event,
                            active_config.audio_sample_rate,
                        )
                    ),
                    asyncio.create_task(
                        websocket_push_worker(
                            websocket,
                            subtitle_queue,
                            status_queue,
                            stop_event,
                            active_config,
                        )
                    ),
                ]
                await send_status(
                    websocket,
                    "Listening",
                    "Cloud speech translation from browser audio.",
                )
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                return
            await azure_session.start()
            tasks = [
                asyncio.create_task(watch_control_messages(websocket, stop_event)),
                asyncio.create_task(cloud_quota_guard_worker(status_queue, stop_event)),
                asyncio.create_task(stream_microphone_to_azure(capture, azure_session, stop_event)),
                asyncio.create_task(
                    websocket_push_worker(
                        websocket,
                        subtitle_queue,
                        status_queue,
                        stop_event,
                        active_config,
                    )
                ),
            ]
            await send_status(
                websocket,
                "Listening",
                f"Cloud speech translation from {capture.selected_source_label}: {capture.selected_source_detail}",
            )
        elif recording_only_quality:
            tasks = [
                asyncio.create_task(watch_control_messages(websocket, stop_event)),
                asyncio.create_task(recording_only_drain_worker(capture, stop_event)),
                asyncio.create_task(
                    websocket_push_worker(
                        websocket,
                        subtitle_queue,
                        status_queue,
                        stop_event,
                        active_config,
                    )
                ),
            ]
            await send_status(
                websocket,
                "Recording",
                "Quality Final: recording only. End meeting to build the final Chinese transcript.",
            )
        else:
            tasks = [
                asyncio.create_task(watch_control_messages(websocket, stop_event)),
                asyncio.create_task(audio_capture_worker(capture, audio_queue, status_queue, active_config, stop_event)),
                asyncio.create_task(asr_worker(audio_queue, translate_queue, subtitle_queue, status_queue, active_config, stop_event)),
                asyncio.create_task(translate_worker(translate_queue, subtitle_queue, status_queue, active_config, stop_event)),
                asyncio.create_task(websocket_push_worker(websocket, subtitle_queue, status_queue, stop_event)),
            ]
            await send_status(
                websocket,
                "Listening",
                (
                    f"{active_config.translation_engine} / live {runtime.asr.model_size}"
                    f" / final {runtime.final_asr.model_size if runtime.final_asr else 'off'}"
                    f" / {runtime.asr.device}"
                )
                if uses_local_chinese_identity
                else f"{active_config.translation_engine} / {runtime.asr.device} / {runtime.asr.model_size}",
            )
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            detail = (
                user_facing_model_error(exc, active_config, effective_model)
                if active_config is not None
                else str(exc)
            )
            await send_status(websocket, "Error", detail)
        except Exception:
            pass
    finally:
        global last_recording_stop_at
        last_recording_stop_at = time.time()
        stop_event.set()
        if cloud_session_id:
            elapsed = finish_cloud_session(cloud_session_id)
            azure_usage_cache["fetchedAt"] = 0.0
            azure_usage_cache["payload"] = None
            print(f"[quota] recorded cloud session {elapsed:.1f}s", flush=True)
        if azure_session is not None:
            await azure_session.stop()
        if capture is not None:
            capture.stop()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
