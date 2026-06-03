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
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from html import escape
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
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .aliyun_tingwu import (
    diagnose_tingwu_setup,
    process_tingwu_recording,
    render_tingwu_minutes,
    render_tingwu_transcript,
)
from .audio_capture import AudioChunk, MicrophoneAudioCapture
from .asr import FunASRParaformerASR, FunASRRealtimeASR, TranscriptionResult, WhisperASR
from .cloud_speech import AzureSpeechTranslationSession, CloudSubtitle, stream_microphone_to_azure
from .config import AppConfig, config
from .notes_quality import MeetingNotesContext, normalize_meeting_notes_context, refine_meeting_minutes
from .terminology import build_hotword_text
from .translator import ArgosTranslator, MarianMTTranslator, NLLBTranslator, Translator


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
RECORDINGS_DIR = ROOT / "recordings"
RECORDING_RESUME_SECONDS = 5 * 60
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
active_recording_path: Path | None = None
last_recording_stop_at = 0.0
RECORDING_PATTERNS = ("rec-*.wav", "session-*.wav")
MINUTES_PATTERNS = ("rec-*.minutes.docx", "rec-*.minutes.md", "session-*.minutes.docx", "session-*.minutes.md")
POST_MEETING_TIMEOUT_SECONDS = 30 * 60
active_post_meeting_process: asyncio.subprocess.Process | None = None
post_meeting_progress: dict[str, Any] = {
    "ok": True,
    "running": False,
    "percent": 0,
    "stage": "idle",
    "message": "No meeting-notes job is running.",
    "recording": "",
    "current": 0,
    "total": 0,
    "startedAt": 0.0,
    "updatedAt": time.time(),
}


def post_meeting_device() -> str:
    requested = os.getenv("POST_MEETING_ASR_DEVICE", "").strip().lower()
    if requested in {"cuda", "cpu", "auto"}:
        return requested
    return "cpu"


azure_usage_cache: dict[str, Any] = {
    "fetchedAt": 0.0,
    "payload": None,
    "lastGoodPayload": None,
}

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
    azure_configured = bool(
        (active_config.azure_speech_key or "").strip()
        and (active_config.azure_speech_region or "").strip()
    )
    aliyun_status = aliyun_tingwu_config_status()
    post_meeting_asr_requested = requested_post_meeting_asr_engine()
    azure_batch_configured = is_azure_batch_configured(active_config)
    try:
        post_meeting_asr_effective = choose_post_meeting_asr_engine()
    except HTTPException:
        post_meeting_asr_effective = "not-configured"
    return {
        "cloud_configured": azure_configured,
        "cloud_batch_configured": azure_batch_configured,
        "aliyun_tingwu_enabled": aliyun_status["enabled"],
        "aliyun_tingwu_configured": aliyun_status["configured"],
        "aliyun_tingwu_missing": aliyun_status["missing"],
        "aliyun_tingwu_upload_provider": aliyun_status["upload_provider"],
        "funasr_configured": importlib.util.find_spec("funasr") is not None,
        "cloud_speech_key_set": bool((active_config.azure_speech_key or "").strip()),
        "post_meeting_asr_requested": post_meeting_asr_requested.replace("azure-", "cloud-"),
        "post_meeting_asr_effective": post_meeting_asr_effective.replace("azure-", "cloud-"),
        "post_meeting_llm_enabled": post_meeting_llm_enabled(),
        "post_meeting_llm_provider": post_meeting_llm_provider(),
        "post_meeting_llm_model": post_meeting_llm_model(),
        "post_meeting_llm_fallback": post_meeting_llm_fallback_enabled(),
        "post_meeting_llm_device": os.getenv("TRANSFORMERS_NOTES_DEVICE", "auto").strip() or "auto",
    }


def env_enabled(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", "off", ""}


def normalize_tingwu_upload_provider(value: object = "") -> str:
    normalized = str(value or os.getenv("ALIYUN_TINGWU_UPLOAD_PROVIDER", "oss")).strip().lower()
    if normalized in {"relay", "tencent", "tencent-relay", "tencent_relay"}:
        return "tencent-relay"
    return "oss"


def aliyun_tingwu_config_status(upload_provider: object = "") -> dict[str, Any]:
    selected_provider = normalize_tingwu_upload_provider(upload_provider)
    required = {
        "ALIBABA_CLOUD_ACCESS_KEY_ID": os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip(),
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET": os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip(),
        "ALIYUN_TINGWU_APP_KEY": os.getenv("ALIYUN_TINGWU_APP_KEY", "").strip(),
    }
    if selected_provider == "tencent-relay":
        required["TENCENT_RELAY_BASE_URL"] = os.getenv("TENCENT_RELAY_BASE_URL", "").strip()
    else:
        required["ALIYUN_OSS_BUCKET"] = os.getenv("ALIYUN_OSS_BUCKET", "").strip()
    missing = [name for name, value in required.items() if not value]
    enabled = env_enabled("ALIYUN_TINGWU_ENABLED")
    return {
        "enabled": enabled,
        "configured": enabled and not missing,
        "missing": missing,
        "upload_provider": selected_provider,
        "region": os.getenv("ALIYUN_TINGWU_REGION", "cn-beijing").strip() or "cn-beijing",
        "endpoint": os.getenv("ALIYUN_TINGWU_ENDPOINT", "tingwu.cn-beijing.aliyuncs.com").strip()
        or "tingwu.cn-beijing.aliyuncs.com",
    }


def post_meeting_llm_enabled() -> bool:
    value = os.getenv("POST_MEETING_LLM_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off", "rule", "rules"}


def post_meeting_llm_provider() -> str:
    return os.getenv("POST_MEETING_LLM_PROVIDER", "transformers").strip().lower() or "transformers"


def post_meeting_llm_model() -> str:
    provider = post_meeting_llm_provider()
    if provider in {"transformers", "hf", "huggingface", "direct"}:
        return (
            os.getenv("TRANSFORMERS_NOTES_MODEL", "")
            or os.getenv("HF_NOTES_MODEL", "")
            or os.getenv("POST_MEETING_TRANSFORMERS_MODEL", "")
            or "google/gemma-4-E2B-it"
        ).strip()
    if provider == "ollama":
        return os.getenv("OLLAMA_NOTES_MODEL", "qwen3:14b").strip() or "qwen3:14b"
    return ""


def post_meeting_llm_fallback_enabled() -> bool:
    return os.getenv("POST_MEETING_LLM_FALLBACK", "1").strip().lower() not in {"0", "false", "no", "off"}


def azure_monitor_config() -> dict[str, str]:
    return {
        "tenant_id": os.getenv("AZURE_TENANT_ID", "").strip(),
        "client_id": os.getenv("AZURE_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("AZURE_CLIENT_SECRET", "").strip(),
        "resource_id": os.getenv("AZURE_SPEECH_RESOURCE_ID", "").strip(),
        "monthly_seconds_limit": os.getenv("AZURE_SPEECH_MONTHLY_SECONDS_LIMIT", "").strip(),
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
        return {
            "ok": True,
            "configured": False,
            "source": "not_configured",
            "message": "Cloud usage sync needs tenant, client, secret, and speech resource id.",
        }
    now = datetime.now(timezone.utc)
    token = azure_monitor_token(settings)
    try:
        day_seconds = azure_audio_seconds(token, settings["resource_id"], now - timedelta(hours=24), now)
        month_seconds = azure_audio_seconds(token, settings["resource_id"], month_start_utc(now), now)
    except RuntimeError:
        day_calls = azure_metric_total(token, settings["resource_id"], "TotalCalls", now - timedelta(hours=24), now)
        month_calls = azure_metric_total(token, settings["resource_id"], "TotalCalls", month_start_utc(now), now)
        return {
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
        }
    monthly_limit = float(settings["monthly_seconds_limit"] or 0)
    remaining_seconds = max(0.0, monthly_limit - month_seconds) if monthly_limit > 0 else None
    return {
        "ok": True,
        "configured": True,
        "source": "cloud_usage",
        "usageMode": "seconds",
        "metric": "audio_seconds",
        "daySeconds": round(day_seconds, 2),
        "monthSeconds": round(month_seconds, 2),
        "monthlyLimitSeconds": monthly_limit or None,
        "remainingSeconds": round(remaining_seconds, 2) if remaining_seconds is not None else None,
        "syncedAt": utc_iso(now),
    }


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


@app.get("/api/aliyun-tingwu-diagnostics")
async def aliyun_tingwu_diagnostics(uploadProvider: str = "") -> dict[str, Any]:
    return diagnose_tingwu_setup(uploadProvider)


@app.get("/api/cloud-usage")
async def cloud_usage() -> dict[str, Any]:
    cached_payload = azure_usage_cache.get("payload")
    if cached_payload is not None and time.time() - float(azure_usage_cache.get("fetchedAt") or 0) < 60:
        return dict(cached_payload)
    try:
        payload = await asyncio.to_thread(fetch_azure_usage_payload)
    except RuntimeError as exc:
        last_good = azure_usage_cache.get("lastGoodPayload")
        if isinstance(last_good, dict):
            payload = dict(last_good)
            payload["stale"] = True
            payload["message"] = "Cloud sync temporarily unavailable. Showing last successful cloud usage."
        else:
            payload = {
                "ok": False,
                "configured": azure_monitor_configured(),
                "source": "cloud_usage",
                "message": str(exc),
            }
    azure_usage_cache["payload"] = payload
    azure_usage_cache["fetchedAt"] = time.time()
    if payload.get("ok") and payload.get("configured"):
        azure_usage_cache["lastGoodPayload"] = dict(payload)
    return dict(payload)


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


@app.post("/api/process-recording")
async def process_recording(request: Request) -> dict[str, Any]:
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    audio_paths = resolve_recording_paths(payload.get("recordings") or payload.get("recording") or "")
    script_path = ROOT / "scripts" / "process-recording.py"
    notes_language = normalize_post_meeting_language(payload.get("notesLanguage") or payload.get("language"))
    notes_engine = payload.get("notesEngine") or payload.get("engine")
    meeting_context = normalize_meeting_notes_context(payload.get("meetingContext"))
    tingwu_upload_provider = normalize_tingwu_upload_provider(payload.get("tingwuUploadProvider"))
    asr_engine = choose_post_meeting_asr_engine(notes_engine, notes_language, tingwu_upload_provider)
    processed: list[dict[str, Any]] = []
    logs: list[str] = []
    notes_mode_message = post_meeting_mode_message(notes_engine, asr_engine, notes_language)

    set_post_meeting_progress(
        running=True,
        percent=2,
        stage="queued",
        message=notes_mode_message,
        current=0,
        total=len(audio_paths),
        recording="",
        started_at=time.time(),
    )
    try:
        for index, audio_path in enumerate(audio_paths, start=1):
            if asr_engine == "aliyun-tingwu":
                processed.append(
                    await process_one_tingwu_recording(
                        audio_path,
                        notes_language,
                        tingwu_upload_provider,
                        logs,
                        index,
                        len(audio_paths),
                        meeting_context,
                    )
                )
            else:
                processed.append(
                    await process_one_recording(
                        audio_path,
                        script_path,
                        asr_engine,
                        notes_language,
                        logs,
                        index,
                        len(audio_paths),
                        meeting_context,
                    )
                )

        if len(processed) > 1:
            set_post_meeting_progress(
                running=True,
                percent=94,
                stage="combining",
                message="Combining selected recordings into one meeting-notes document.",
                current=len(processed),
                total=len(audio_paths),
            )
            combined = write_combined_minutes(processed)
            set_post_meeting_progress(
                running=False,
                percent=100,
                stage="complete",
                message="Meeting notes are ready.",
                current=len(processed),
                total=len(audio_paths),
            )
            return {
                "ok": True,
                "recordings": [item["recording"] for item in processed],
                "recording": ", ".join(Path(item["recording"]).name for item in processed),
                "transcript": "",
                "minutes": str(combined["minutes"]),
                "minutesMarkdown": str(combined["minutesMarkdown"]),
                "minutesDocx": str(combined["minutesDocx"]),
                "transcriptText": "",
                "minutesText": combined["minutesText"],
                "log": "\n".join(logs),
                "asrEngine": asr_engine,
                "notesMode": notes_mode_message,
            }

        set_post_meeting_progress(
            running=False,
            percent=100,
            stage="complete",
            message="Meeting notes are ready.",
            current=1,
            total=len(audio_paths),
        )
        return {
            **processed[0],
            "log": "\n".join(logs),
            "asrEngine": asr_engine,
            "notesMode": notes_mode_message,
        }
    except Exception:
        set_post_meeting_progress(
            running=False,
            stage="failed",
            message="Meeting notes generation failed.",
            updated_at=time.time(),
        )
        raise


@app.get("/api/process-recording-progress")
async def process_recording_progress() -> dict[str, Any]:
    return dict(post_meeting_progress)


@app.post("/api/open-folder/{folder_kind}")
async def open_folder(folder_kind: str) -> dict[str, Any]:
    if folder_kind == "recordings":
        target = RECORDINGS_DIR
    elif folder_kind == "notes":
        minutes_path = latest_minutes_file()
        target = minutes_path.parent if minutes_path is not None else RECORDINGS_DIR
    else:
        raise HTTPException(status_code=404, detail="Unknown folder.")

    target.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(target)  # type: ignore[attr-defined]
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not open folder: {exc}") from exc
    return {"ok": True, "path": str(target)}


def set_post_meeting_progress(**updates: Any) -> None:
    post_meeting_progress.update(updates)
    post_meeting_progress["ok"] = True
    post_meeting_progress["updatedAt"] = updates.get("updated_at", time.time())
    post_meeting_progress["percent"] = max(0, min(100, int(post_meeting_progress.get("percent") or 0)))


async def process_one_tingwu_recording(
    audio_path: Path,
    notes_language: str,
    upload_provider: str,
    logs: list[str],
    index: int,
    total: int,
    meeting_context: MeetingNotesContext,
) -> dict[str, Any]:
    per_recording_span = 88 / max(1, total)
    base_percent = 4 + int((index - 1) * per_recording_span)
    max_percent = min(92, base_percent + int(per_recording_span * 0.9))
    upload_label = "Tencent Relay" if upload_provider == "tencent-relay" else "Aliyun OSS"
    total_bytes = max(1, audio_path.stat().st_size)
    set_post_meeting_progress(
        running=True,
        percent=base_percent,
        stage="uploading",
        message=f"Uploading {audio_path.name} to {upload_label} for Tingwu processing.",
        recording=audio_path.name,
        current=index,
        total=total,
    )

    def on_tingwu_progress(stage: str, message: str, extra: dict[str, Any] | None = None) -> None:
        extra = extra or {}
        next_percent = base_percent
        next_stage = stage
        next_message = message
        if stage == "compressing":
            original_size = max(0, int(extra.get("original", total_bytes) or total_bytes))
            compressed_size = max(0, int(extra.get("compressed", 0) or 0))
            next_percent = base_percent + int(max(1, per_recording_span * 0.06))
            next_stage = "compressing"
            if compressed_size:
                next_message = (
                    f"Compressed {audio_path.name} to lossless FLAC "
                    f"({format_file_size(compressed_size)} from {format_file_size(original_size)})."
                )
            else:
                next_message = f"Compressing {audio_path.name} to lossless FLAC before upload."
        elif stage == "uploading":
            uploaded = max(0, int(extra.get("uploaded", 0) or 0))
            total_upload = max(1, int(extra.get("total", total_bytes) or total_bytes))
            upload_fraction = min(1.0, uploaded / total_upload)
            next_percent = base_percent + int(max(1, per_recording_span * 0.18) * upload_fraction)
            next_message = (
                f"Uploading {audio_path.name} to {upload_label} "
                f"({format_file_size(uploaded)} / {format_file_size(total_upload)})."
            )
        elif stage == "submitting":
            next_percent = max(base_percent + int(per_recording_span * 0.22), int(post_meeting_progress.get('percent') or 0))
            next_stage = "submitting"
        elif stage == "waiting":
            status = str(extra.get("status", "") or "").strip().upper() or "RUNNING"
            current_percent = int(post_meeting_progress.get("percent") or 0)
            next_percent = min(max_percent - 8, max(current_percent + 2, base_percent + int(per_recording_span * 0.28)))
            next_stage = "waiting"
            next_message = f"Aliyun Tingwu is processing {audio_path.name} ({status})."
        elif stage == "downloading":
            next_percent = max(base_percent + int(per_recording_span * 0.82), int(post_meeting_progress.get("percent") or 0))
            next_stage = "downloading"
        set_post_meeting_progress(
            running=True,
            percent=min(max_percent, next_percent),
            stage=next_stage,
            message=next_message,
            recording=audio_path.name,
            current=index,
            total=total,
        )

    try:
        notes = await asyncio.to_thread(
            process_tingwu_recording,
            audio_path,
            notes_language,
            upload_provider,
            on_tingwu_progress,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Aliyun Tingwu meeting notes failed: {exc}") from exc

    set_post_meeting_progress(
        running=True,
        percent=max_percent,
        stage="writing",
        message=f"Writing Aliyun Tingwu meeting-notes files for {audio_path.name}.",
        recording=audio_path.name,
        current=index,
        total=total,
    )
    transcript_path = audio_path.with_suffix(".transcript.md")
    minutes_path = audio_path.with_suffix(".minutes.md")
    minutes_docx_path = audio_path.with_suffix(".minutes.docx")
    tingwu_transcript_json_path = audio_path.with_suffix(".tingwu.transcription.json")
    tingwu_summary_json_path = audio_path.with_suffix(".tingwu.summary.json")
    tingwu_meeting_json_path = audio_path.with_suffix(".tingwu.meeting.json")
    tingwu_polish_json_path = audio_path.with_suffix(".tingwu.polish.json")
    transcript_text = render_tingwu_transcript(audio_path, notes)
    minutes_text = render_tingwu_minutes(audio_path, notes, notes_language)
    minutes_text = await refine_minutes_for_recording(
        audio_path=audio_path,
        minutes_text=minutes_text,
        transcript_text=transcript_text,
        context=meeting_context,
        notes_language=notes_language,
        logs=logs,
        index=index,
        total=total,
        percent=min(96, max_percent + 1),
    )
    transcript_path.write_text(transcript_text, encoding="utf-8")
    minutes_path.write_text(minutes_text, encoding="utf-8")
    tingwu_transcript_json_path.write_text(json.dumps(notes.transcript_json, ensure_ascii=False, indent=2), encoding="utf-8")
    tingwu_summary_json_path.write_text(json.dumps(notes.summary_json, ensure_ascii=False, indent=2), encoding="utf-8")
    tingwu_meeting_json_path.write_text(json.dumps(notes.meeting_json, ensure_ascii=False, indent=2), encoding="utf-8")
    tingwu_polish_json_path.write_text(json.dumps(notes.text_polish_json, ensure_ascii=False, indent=2), encoding="utf-8")
    write_minutes_docx(minutes_path, minutes_docx_path)
    logs.append(
        "\n".join(
            [
                "Aliyun Tingwu: completed cloud meeting-notes task.",
                f"TaskId: {notes.task_id}",
                f"Segments: {len(notes.segments)}",
                f"Wrote {transcript_path}",
                f"Wrote {minutes_path}",
                f"Wrote {tingwu_summary_json_path}",
            ]
        )
    )
    set_post_meeting_progress(
        running=True,
        percent=min(96, base_percent + int(per_recording_span)),
        stage="processed",
        message=f"Finished {audio_path.name} with Aliyun Tingwu.",
        recording=audio_path.name,
        current=index,
        total=total,
    )
    return {
        "ok": True,
        "recording": str(audio_path),
        "transcript": str(transcript_path),
        "minutes": str(minutes_docx_path if minutes_docx_path.exists() else minutes_path),
        "minutesMarkdown": str(minutes_path),
        "minutesDocx": str(minutes_docx_path) if minutes_docx_path.exists() else "",
        "transcriptText": transcript_text,
        "minutesText": minutes_text,
    }


async def process_one_recording(
    audio_path: Path,
    script_path: Path,
    asr_engine: str,
    notes_language: str,
    logs: list[str],
    index: int,
    total: int,
    meeting_context: MeetingNotesContext,
) -> dict[str, Any]:
    global active_post_meeting_process
    per_recording_span = 88 / max(1, total)
    base_percent = 4 + int((index - 1) * per_recording_span)
    max_running_percent = min(92, base_percent + int(per_recording_span * 0.88))
    duration_seconds = recording_duration_seconds(audio_path)
    estimated_seconds = max(45.0, duration_seconds * 0.8)
    started_at = time.time()
    set_post_meeting_progress(
        running=True,
        percent=base_percent,
        stage="processing",
        message=f"Processing {audio_path.name} ({index}/{total}).",
        recording=audio_path.name,
        current=index,
        total=total,
    )
    command = [
        sys.executable,
        str(script_path),
        str(audio_path),
        "--asr-engine",
        asr_engine,
        "--language",
        notes_language,
        "--notes-language",
        notes_output_language(notes_language),
        "--device",
        post_meeting_device(),
    ]
    if asr_engine == "funasr" and is_chinese_post_meeting_language(notes_language):
        command.extend(["--quality", "high"])
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(ROOT),
        env=post_meeting_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    active_post_meeting_process = process
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stdout_task = asyncio.create_task(
        collect_post_meeting_stream(
            process.stdout,
            stdout_lines,
            audio_path.name,
            index,
            total,
            base_percent,
            max_running_percent,
        )
    )
    stderr_task = asyncio.create_task(collect_post_meeting_stream(process.stderr, stderr_lines))
    wait_task = asyncio.create_task(process.wait())
    try:
        while not wait_task.done():
            elapsed = time.time() - started_at
            if elapsed > POST_MEETING_TIMEOUT_SECONDS:
                raise asyncio.TimeoutError()
            fraction = min(0.95, elapsed / estimated_seconds)
            percent = min(max_running_percent, base_percent + int((max_running_percent - base_percent) * fraction))
            set_post_meeting_progress(
                running=True,
                percent=percent,
                stage="processing",
                message=f"Transcribing and summarizing {audio_path.name} ({format_progress_time(elapsed)} elapsed).",
                recording=audio_path.name,
                current=index,
                total=total,
            )
            await asyncio.sleep(1)
        await wait_task
        await asyncio.gather(stdout_task, stderr_task)
    except asyncio.TimeoutError as exc:
        process.kill()
        await wait_task
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        raise HTTPException(status_code=504, detail="Post-meeting processing timed out. Try a shorter recording or cached local models.") from exc
    finally:
        if active_post_meeting_process is process:
            active_post_meeting_process = None

    stdout_text = "\n".join(stdout_lines)
    stderr_text = "\n".join(stderr_lines)
    if process.returncode != 0:
        detail = (stderr_text or stdout_text or "Post-meeting processing failed.").strip()
        raise HTTPException(status_code=500, detail=detail[-2000:])
    logs.append(stdout_text.strip())

    transcript_path = audio_path.with_suffix(".transcript.md")
    minutes_path = audio_path.with_suffix(".minutes.md")
    minutes_docx_path = audio_path.with_suffix(".minutes.docx")
    if minutes_path.exists():
        transcript_text = transcript_path.read_text(encoding="utf-8", errors="replace") if transcript_path.exists() else ""
        minutes_text = minutes_path.read_text(encoding="utf-8", errors="replace")
        minutes_text = await refine_minutes_for_recording(
            audio_path=audio_path,
            minutes_text=minutes_text,
            transcript_text=transcript_text,
            context=meeting_context,
            notes_language=notes_language,
            logs=logs,
            index=index,
            total=total,
            percent=min(96, max_running_percent + 1),
        )
        minutes_path.write_text(minutes_text, encoding="utf-8")
        set_post_meeting_progress(
            running=True,
            percent=min(96, max_running_percent + 2),
            stage="writing",
            message=f"Writing Word document for {audio_path.name}.",
            recording=audio_path.name,
            current=index,
            total=total,
        )
        write_minutes_docx(minutes_path, minutes_docx_path)
    set_post_meeting_progress(
        running=True,
        percent=min(96, base_percent + int(per_recording_span)),
        stage="processed",
        message=f"Finished {audio_path.name} ({index}/{total}).",
        recording=audio_path.name,
        current=index,
        total=total,
    )
    return {
        "ok": True,
        "recording": str(audio_path),
        "transcript": str(transcript_path),
        "minutes": str(minutes_docx_path if minutes_docx_path.exists() else minutes_path),
        "minutesMarkdown": str(minutes_path),
        "minutesDocx": str(minutes_docx_path) if minutes_docx_path.exists() else "",
        "transcriptText": transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else "",
        "minutesText": minutes_path.read_text(encoding="utf-8") if minutes_path.exists() else "",
    }


async def refine_minutes_for_recording(
    *,
    audio_path: Path,
    minutes_text: str,
    transcript_text: str,
    context: MeetingNotesContext,
    notes_language: str,
    logs: list[str],
    index: int,
    total: int,
    percent: int,
) -> str:
    original_minutes = str(minutes_text or "").strip()
    if not original_minutes:
        return original_minutes

    set_post_meeting_progress(
        running=True,
        percent=percent,
        stage="refining",
        message=f"Refining topic-level meeting notes for {audio_path.name}.",
        recording=audio_path.name,
        current=index,
        total=total,
    )
    result = await asyncio.to_thread(
        refine_meeting_minutes,
        minutes_text=original_minutes,
        transcript_text=transcript_text,
        context=context,
        notes_language=notes_language,
    )
    if result.changed:
        raw_path = audio_path.with_suffix(".minutes.raw.md")
        raw_path.write_text(original_minutes + "\n", encoding="utf-8")
        logs.append(f"Meeting notes rewrite: rewritten ({result.detail}). Raw generated draft saved to {raw_path}.")
        return result.text.strip() + "\n"

    detail = f" ({result.detail})" if result.detail else ""
    logs.append(f"Meeting notes rewrite: {result.status}{detail}.")
    return original_minutes + "\n"


async def collect_post_meeting_stream(
    stream: asyncio.StreamReader | None,
    lines: list[str],
    recording_name: str = "",
    current: int = 0,
    total: int = 0,
    base_percent: int = 0,
    max_percent: int = 92,
) -> None:
    if stream is None:
        return
    while True:
        raw_line = await stream.readline()
        if not raw_line:
            break
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        lines.append(line)
        update_progress_from_script_line(line, recording_name, current, total, base_percent, max_percent)


def update_progress_from_script_line(
    line: str,
    recording_name: str,
    current: int,
    total: int,
    base_percent: int,
    max_percent: int,
) -> None:
    lower = line.lower()
    current_percent = int(post_meeting_progress.get("percent") or 0)
    if "azure batch: uploading" in lower:
        set_post_meeting_progress(
            running=True,
            percent=max(base_percent, 8),
            stage="uploading",
            message=f"Uploading {recording_name} to cloud storage.",
            recording=recording_name,
            current=current,
            total=total,
        )
    elif "azure batch: submitting" in lower:
        set_post_meeting_progress(
            running=True,
            percent=max(base_percent, 16),
            stage="submitting",
            message="Submitting cloud transcription job.",
            recording=recording_name,
            current=current,
            total=total,
        )
    elif "azure batch: waiting" in lower:
        set_post_meeting_progress(
            running=True,
            percent=max(base_percent, 24),
            stage="waiting",
            message="Waiting for cloud transcription and speaker separation.",
            recording=recording_name,
            current=current,
            total=total,
        )
    elif lower.startswith("azure batch status:"):
        status = line.split(":", 1)[1].strip() if ":" in line else "Running"
        set_post_meeting_progress(
            running=True,
            percent=min(max_percent, max(base_percent + 20, int(post_meeting_progress.get("percent") or 0))),
            stage="waiting",
            message=f"Cloud transcription status: {status}.",
            recording=recording_name,
            current=current,
            total=total,
        )
    elif "azure batch: downloading" in lower:
        set_post_meeting_progress(
            running=True,
            percent=min(max_percent, 86),
            stage="downloading",
            message="Downloading cloud transcription result.",
            recording=recording_name,
            current=current,
            total=total,
        )
    elif lower.startswith("asr chunk "):
        set_post_meeting_progress(
            running=True,
            percent=min(max_percent, max(base_percent + 10, int(post_meeting_progress.get("percent") or 0))),
            stage="transcribing",
            message=f"{line}.",
            recording=recording_name,
            current=current,
            total=total,
        )
    elif lower.startswith("notes model: preparing"):
        model_name = line.split(":", 1)[1].strip().replace("preparing", "", 1).strip()
        set_post_meeting_progress(
            running=True,
            percent=min(max_percent, max(current_percent, base_percent + 58)),
            stage="model",
            message=f"Preparing notes model {model_name or 'Gemma'}.",
            recording=recording_name,
            current=current,
            total=total,
        )
    elif "notes model: downloading or loading tokenizer" in lower:
        set_post_meeting_progress(
            running=True,
            percent=min(max_percent, max(current_percent, base_percent + 62)),
            stage="model_loading",
            message="Downloading or loading the notes tokenizer.",
            recording=recording_name,
            current=current,
            total=total,
        )
    elif "notes model: downloading or loading weights" in lower:
        set_post_meeting_progress(
            running=True,
            percent=min(max_percent, max(current_percent, base_percent + 68)),
            stage="model_loading",
            message="Downloading or loading the notes model weights.",
            recording=recording_name,
            current=current,
            total=total,
        )
    elif lower.startswith("notes model: ready"):
        set_post_meeting_progress(
            running=True,
            percent=min(max_percent, max(current_percent, base_percent + 76)),
            stage="model_ready",
            message=line,
            recording=recording_name,
            current=current,
            total=total,
        )
    elif "notes model: refining meeting notes" in lower:
        set_post_meeting_progress(
            running=True,
            percent=min(max_percent, max(current_percent, base_percent + 82)),
            stage="refining",
            message="Refining transcript into bilingual meeting notes.",
            recording=recording_name,
            current=current,
            total=total,
        )
    elif "used direct transformers notes writer" in lower or "used ollama notes writer" in lower:
        set_post_meeting_progress(
            running=True,
            percent=min(max_percent, max(current_percent, base_percent + 88)),
            stage="writing",
            message=line,
            recording=recording_name,
            current=current,
            total=total,
        )
    elif "direct transformers notes writer unavailable" in lower:
        set_post_meeting_progress(
            running=True,
            percent=min(max_percent, max(current_percent, base_percent + 78)),
            stage="model",
            message="Primary notes model unavailable; trying fallback or rule-based notes.",
            recording=recording_name,
            current=current,
            total=total,
        )


def recording_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            if frame_rate:
                return wav_file.getnframes() / frame_rate
    except (OSError, wave.Error):
        return 0.0
    return 0.0


def format_progress_time(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes = total // 60
    remainder = total % 60
    return f"{minutes}:{remainder:02d}"


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


@app.post("/api/cancel-process-recording")
async def cancel_process_recording() -> dict[str, Any]:
    process = active_post_meeting_process
    if process is None or process.returncode is not None:
        return {"ok": True, "cancelled": False}
    process.kill()
    set_post_meeting_progress(
        running=False,
        stage="cancelled",
        message="Meeting notes generation was cancelled.",
    )
    return {"ok": True, "cancelled": True}


def choose_post_meeting_asr_engine(
    ui_engine: object = "",
    notes_language: str = "en",
    tingwu_upload_provider: object = "",
) -> str:
    selected_engine = str(ui_engine or "").strip().lower()
    if selected_engine in {"aliyun-tingwu", "tingwu", "aliyun"}:
        status = aliyun_tingwu_config_status(tingwu_upload_provider)
        if not status["enabled"]:
            raise HTTPException(
                status_code=400,
                detail="Aliyun Tingwu is selected, but ALIYUN_TINGWU_ENABLED is not enabled in .env yet.",
            )
        if not status["configured"]:
            missing = ", ".join(status["missing"])
            raise HTTPException(
                status_code=400,
                detail=f"Aliyun Tingwu is selected, but these settings are still missing: {missing}.",
            )
        return "aliyun-tingwu"
    if selected_engine in {"azure-fast", "cloud-fast", "cloud"}:
        if is_azure_fast_configured():
            return "azure-fast"
        raise HTTPException(
            status_code=400,
            detail="Cloud Fast is selected, but Azure Speech to Text key and region are not configured yet.",
        )
    if selected_engine in {"funasr", "local-funasr", "local"}:
        if importlib.util.find_spec("funasr") is not None:
            return "funasr"
        raise HTTPException(
            status_code=400,
            detail="Local FunASR is selected, but FunASR is not installed in this environment yet.",
        )
    if selected_engine and selected_engine != "azure":
        if is_chinese_post_meeting_language(notes_language):
            if importlib.util.find_spec("funasr") is not None:
                return "funasr"
            return "faster-whisper"
        return "faster-whisper"
    requested_engine = requested_post_meeting_asr_engine()
    if requested_engine == "azure-batch":
        if is_azure_batch_configured(config):
            return "azure-batch"
        if is_chinese_post_meeting_language(notes_language) and is_azure_fast_configured():
            return "azure-fast"
        return "faster-whisper"
    if requested_engine == "azure-fast":
        if is_azure_fast_configured():
            return "azure-fast"
        return "faster-whisper"
    if requested_engine != "funasr":
        return "faster-whisper"
    funasr_model_dir = ROOT / ".model-cache" / "models" / "iic" / "SenseVoiceSmall"
    if funasr_model_dir.exists() and importlib.util.find_spec("funasr") is not None:
        return "funasr"
    return "faster-whisper"


def post_meeting_mode_message(ui_engine: object, effective_engine: str, notes_language: str = "en") -> str:
    selected_engine = str(ui_engine or "").strip().lower()
    normalized_language = str(notes_language or "").strip().lower()
    if is_chinese_post_meeting_language(notes_language):
        language_label = "Chinese voice"
    elif normalized_language.startswith("es"):
        language_label = "Spanish voice"
    else:
        language_label = "English voice"
    if selected_engine == "azure":
        if effective_engine == "azure-batch":
            return f"Cloud mode: using batch transcription for {language_label} with speaker separation."
        if effective_engine == "azure-fast":
            return f"Cloud mode: using fast transcription for {language_label}."
        return f"Cloud mode selected, but batch storage is not configured. Using local transcription for {language_label} without speaker separation."
    if selected_engine in {"azure-fast", "cloud-fast", "cloud"}:
        return f"Cloud Speech mode: using Azure Speech to Text for {language_label}, then local notes refinement. Speaker separation is not used in this mode."
    if selected_engine in {"aliyun-tingwu", "tingwu", "aliyun"}:
        return f"Aliyun Tingwu mode: cloud meeting notes for {language_label} with speaker separation and AI summary."
    if selected_engine in {"funasr", "local-funasr", "local"}:
        return f"Local mode: using FunASR transcription for {language_label} without speaker separation."
    return f"Local mode: using local transcription for {language_label} without speaker separation."


def requested_post_meeting_asr_engine() -> str:
    return os.getenv("POST_MEETING_ASR_ENGINE", "azure-batch").strip().lower()


def normalize_post_meeting_language(value: object = "") -> str:
    language = str(value or "").strip().lower()
    if language in {"zh", "zh-cn", "zh_hans", "zh-hans", "chinese", "mandarin", "cn"}:
        return "zh-CN"
    if language in {"es", "es-es", "spanish"}:
        return "es-ES"
    if language in {"auto", ""}:
        return "en"
    if language.startswith("zh"):
        return "zh-CN"
    if language.startswith("es"):
        return "es-ES"
    return "en"


def notes_output_language(language: str) -> str:
    return "zh" if is_chinese_post_meeting_language(language) else "en"


def is_chinese_post_meeting_language(language: str) -> bool:
    return str(language or "").strip().lower().startswith("zh")


def is_azure_fast_configured() -> bool:
    return bool(
        (config.azure_speech_key or "").strip()
        and (config.azure_speech_region or os.getenv("AZURE_SPEECH_ENDPOINT", "")).strip()
    )


def is_azure_batch_configured(active_config: AppConfig) -> bool:
    return bool(
        (active_config.azure_speech_key or "").strip()
        and (active_config.azure_speech_region or os.getenv("AZURE_BATCH_TRANSCRIPTION_ENDPOINT", "")).strip()
        and os.getenv("AZURE_BATCH_CONTAINER_SAS_URL", "").strip()
    )


def post_meeting_env() -> dict[str, str]:
    env = dict(os.environ)
    cache_dir = ROOT / ".cache" / "huggingface"
    cache_dir.mkdir(parents=True, exist_ok=True)
    env["HF_HOME"] = str(cache_dir)
    env["TRANSFORMERS_CACHE"] = str(cache_dir)
    return env


def resolve_recording_paths(requested_recordings: object) -> list[Path]:
    if isinstance(requested_recordings, str):
        requested_values = [requested_recordings] if requested_recordings else []
    elif isinstance(requested_recordings, list):
        requested_values = [str(item) for item in requested_recordings if str(item).strip()]
    else:
        requested_values = []

    paths: list[Path] = []
    for requested_recording in requested_values:
        requested_path = Path(str(requested_recording))
        if not requested_path.is_absolute():
            requested_path = ROOT / requested_path
        try:
            requested_path = requested_path.resolve()
            recordings_root = RECORDINGS_DIR.resolve()
            if recordings_root == requested_path.parent and requested_path.suffix.lower() == ".wav" and requested_path.exists():
                paths.append(requested_path)
        except OSError:
            pass
    if paths:
        return list(dict.fromkeys(paths))

    recordings = sorted_recordings()
    if not recordings:
        raise HTTPException(status_code=404, detail="No session recording found.")
    return [recordings[0]]


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


def write_combined_minutes(processed: list[dict[str, Any]]) -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    markdown_path = RECORDINGS_DIR / f"combined-meeting-notes-{timestamp}.minutes.md"
    docx_path = RECORDINGS_DIR / f"combined-meeting-notes-{timestamp}.minutes.docx"
    lines = [
        "# Combined Meeting Notes",
        "",
        "This document was generated from multiple selected meeting recordings.",
        "",
        "## Source Recordings",
        "",
    ]
    for item in processed:
        lines.append(f"- `{Path(item['recording']).name}`")
    lines.extend(["", "## Integrated Notes", ""])
    for index, item in enumerate(processed, start=1):
        lines.append(f"### Source {index}: {Path(item['recording']).name}")
        lines.append("")
        text = str(item.get("minutesText") or "").strip()
        if text:
            lines.append(text)
        else:
            lines.append("- No readable notes were produced for this source.")
        lines.append("")
    minutes_text = "\n".join(lines).strip() + "\n"
    markdown_path.write_text(minutes_text, encoding="utf-8")
    write_minutes_docx(markdown_path, docx_path)
    return {
        "minutes": docx_path if docx_path.exists() else markdown_path,
        "minutesMarkdown": markdown_path,
        "minutesDocx": docx_path if docx_path.exists() else "",
        "minutesText": minutes_text,
    }


@app.post("/api/open-latest-minutes")
async def open_latest_minutes() -> dict[str, Any]:
    minutes_path = latest_minutes_file()
    if minutes_path is None:
        raise HTTPException(status_code=404, detail="No meeting minutes file found.")

    try:
        os.startfile(minutes_path)  # type: ignore[attr-defined]
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not open minutes file: {exc}") from exc

    return {"ok": True, "minutes": str(minutes_path)}


def latest_minutes_file() -> Path | None:
    minutes_files = sorted(
        [path for pattern in MINUTES_PATTERNS for path in RECORDINGS_DIR.glob(pattern)],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return minutes_files[0] if minutes_files else None


@app.get("/api/latest-minutes")
async def latest_minutes() -> dict[str, Any]:
    minutes_path = latest_minutes_file()
    if minutes_path is None:
        return {"ok": True, "available": False, "minutes": ""}
    return {"ok": True, "available": True, "minutes": str(minutes_path)}


@app.get("/api/latest-minutes-file")
async def latest_minutes_file_response() -> FileResponse:
    minutes_path = latest_minutes_file()
    if minutes_path is None:
        raise HTTPException(status_code=404, detail="No meeting minutes file found.")
    return FileResponse(
        minutes_path,
        media_type=DOCX_MEDIA_TYPE if minutes_path.suffix.lower() == ".docx" else "text/markdown; charset=utf-8",
        filename=minutes_path.name,
    )


def write_minutes_docx(markdown_path: Path, docx_path: Path) -> None:
    paragraphs: list[str] = []
    for raw_line in markdown_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        style = "Body"
        text = line
        if line.startswith("# "):
            style = "Title"
            text = line[2:].strip()
        elif line.startswith("## "):
            style = "Heading1"
            text = line[3:].strip()
        elif line.startswith("### "):
            style = "Heading2"
            text = line[4:].strip()
        elif line.startswith("- [ ] "):
            style = "Bullet"
            text = "☐ " + line[6:].strip()
        elif line.startswith("- "):
            style = "Bullet"
            text = line[2:].strip()
        paragraphs.append(word_paragraph(text, style))

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(paragraphs)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080" w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("word/document.xml", document_xml)


def word_paragraph(text: str, style: str) -> str:
    safe_text = escape(text)
    if style == "Title":
        props = '<w:jc w:val="center"/><w:spacing w:after="240"/><w:rPr><w:b/><w:sz w:val="44"/><w:color w:val="304E96"/></w:rPr>'
        run_props = '<w:b/><w:sz w:val="44"/><w:color w:val="304E96"/>'
    elif style == "Heading1":
        props = '<w:spacing w:before="240" w:after="100"/><w:rPr><w:b/><w:sz w:val="30"/><w:color w:val="304E96"/></w:rPr>'
        run_props = '<w:b/><w:sz w:val="30"/><w:color w:val="304E96"/>'
    elif style == "Heading2":
        props = '<w:spacing w:before="140" w:after="80"/><w:rPr><w:b/><w:sz w:val="24"/><w:color w:val="304E96"/></w:rPr>'
        run_props = '<w:b/><w:sz w:val="24"/><w:color w:val="304E96"/>'
    elif style == "Bullet":
        props = '<w:ind w:left="360" w:hanging="180"/><w:spacing w:after="80"/>'
        run_props = '<w:sz w:val="21"/><w:color w:val="1F2A3A"/>'
        safe_text = safe_text if safe_text.startswith("☐") else "• " + safe_text
    else:
        props = '<w:spacing w:after="80"/>'
        run_props = '<w:sz w:val="21"/><w:color w:val="1F2A3A"/>'

    return (
        f"<w:p><w:pPr>{props}</w:pPr><w:r><w:rPr>{run_props}"
        '<w:rFonts w:ascii="Calibri" w:eastAsia="Microsoft YaHei" w:hAnsi="Calibri"/>'
        f"</w:rPr><w:t>{safe_text}</w:t></w:r></w:p>"
    )


def write_minutes_docx(markdown_path: Path, docx_path: Path) -> None:
    body_parts: list[str] = []
    lines = markdown_path.read_text(encoding="utf-8", errors="replace").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if is_markdown_table_line(line):
            table_lines: list[str] = []
            while index < len(lines):
                candidate = lines[index].strip()
                if not is_markdown_table_line(candidate):
                    break
                table_lines.append(candidate)
                index += 1
            table_xml = markdown_table_xml(table_lines)
            if table_xml:
                body_parts.append(table_xml)
            continue
        style = "Body"
        text = line
        if line.startswith("# "):
            style = "Title"
            text = line[2:].strip()
        elif line.startswith("## "):
            style = "Heading1"
            text = line[3:].strip()
        elif line.startswith("### "):
            style = "Heading2"
            text = line[4:].strip()
        elif line.startswith("- [ ] "):
            style = "Bullet"
            text = "[ ] " + line[6:].strip()
        elif line.startswith("- "):
            style = "Bullet"
            text = line[2:].strip()
        body_parts.append(word_paragraph_v2(text, style))
        index += 1

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body_parts)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080" w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("word/document.xml", document_xml)


def word_paragraph_v2(text: str, style: str) -> str:
    safe_text = escape(text)
    if style == "Title":
        props = '<w:jc w:val="center"/><w:spacing w:after="240"/><w:rPr><w:b/><w:sz w:val="44"/><w:color w:val="304E96"/></w:rPr>'
        run_props = '<w:b/><w:sz w:val="44"/><w:color w:val="304E96"/>'
    elif style == "Heading1":
        props = '<w:spacing w:before="240" w:after="100"/><w:rPr><w:b/><w:sz w:val="30"/><w:color w:val="304E96"/></w:rPr>'
        run_props = '<w:b/><w:sz w:val="30"/><w:color w:val="304E96"/>'
    elif style == "Heading2":
        props = '<w:spacing w:before="140" w:after="80"/><w:rPr><w:b/><w:sz w:val="24"/><w:color w:val="304E96"/></w:rPr>'
        run_props = '<w:b/><w:sz w:val="24"/><w:color w:val="304E96"/>'
    elif style == "Bullet":
        props = '<w:ind w:left="360" w:hanging="180"/><w:spacing w:after="80"/>'
        run_props = '<w:sz w:val="21"/><w:color w:val="1F2A3A"/>'
        safe_text = safe_text if safe_text.startswith("[ ]") else "- " + safe_text
    else:
        props = '<w:spacing w:after="80"/>'
        run_props = '<w:sz w:val="21"/><w:color w:val="1F2A3A"/>'

    return (
        f"<w:p><w:pPr>{props}</w:pPr><w:r><w:rPr>{run_props}"
        '<w:rFonts w:ascii="Calibri" w:eastAsia="Microsoft YaHei" w:hAnsi="Calibri"/>'
        f"</w:rPr><w:t xml:space=\"preserve\">{safe_text}</w:t></w:r></w:p>"
    )


def is_markdown_table_line(line: str) -> bool:
    return line.startswith("|") and line.endswith("|") and line.count("|") >= 2


def markdown_table_xml(lines: list[str]) -> str:
    rows = [parse_markdown_table_row(line) for line in lines if line.strip()]
    if len(rows) < 2 or not is_markdown_separator_row(rows[1]):
        return ""
    data_rows = [rows[0]] + rows[2:]
    column_count = max(len(row) for row in data_rows) if data_rows else 0
    if column_count == 0:
        return ""
    normalized_rows = [row + [""] * (column_count - len(row)) for row in data_rows]
    width = str(int(9000 / max(1, column_count)))
    xml_rows: list[str] = []
    for row_index, row in enumerate(normalized_rows):
        cells = "".join(word_table_cell(cell, width, row_index == 0) for cell in row)
        xml_rows.append(f"<w:tr>{cells}</w:tr>")
    return (
        '<w:tbl>'
        '<w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/>'
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="8" w:space="0" w:color="D0D7E6"/>'
        '<w:left w:val="single" w:sz="8" w:space="0" w:color="D0D7E6"/>'
        '<w:bottom w:val="single" w:sz="8" w:space="0" w:color="D0D7E6"/>'
        '<w:right w:val="single" w:sz="8" w:space="0" w:color="D0D7E6"/>'
        '<w:insideH w:val="single" w:sz="6" w:space="0" w:color="D0D7E6"/>'
        '<w:insideV w:val="single" w:sz="6" w:space="0" w:color="D0D7E6"/>'
        '</w:tblBorders></w:tblPr>'
        + "".join(xml_rows)
        + "</w:tbl>"
    )


def parse_markdown_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_markdown_separator_row(cells: list[str]) -> bool:
    return all(cell and set(cell.replace(":", "")) <= {"-"} for cell in cells)


def word_table_cell(text: str, width: str, is_header: bool) -> str:
    safe_text = escape(text)
    shade = '<w:shd w:val="clear" w:color="auto" w:fill="EAF0FB"/>' if is_header else ""
    bold = "<w:b/>" if is_header else ""
    return (
        "<w:tc>"
        f'<w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}</w:tcPr>'
        '<w:p><w:pPr><w:spacing w:before="40" w:after="40"/></w:pPr>'
        f'<w:r><w:rPr>{bold}<w:sz w:val="21"/><w:color w:val="1F2A3A"/>'
        '<w:rFonts w:ascii="Calibri" w:eastAsia="Microsoft YaHei" w:hAnsi="Calibri"/>'
        f"</w:rPr><w:t>{safe_text}</w:t></w:r></w:p></w:tc>"
    )


def build_config(payload: dict[str, Any]) -> AppConfig:
    merged = asdict(config)
    for key, value in payload.items():
        if key in merged and value not in (None, ""):
            merged[key] = value

    if merged["source_language"] not in ("eng_Latn", "spa_Latn", "zho_Hans"):
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
    if source_language == "zho_Hans":
        return "zh"
    return "en"


def effective_asr_model(model_size: str, source_language: str) -> str:
    if source_language in ("spa_Latn", "zho_Hans"):
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
        if active_config.translation_engine == "azure":
            await send_status(websocket, "Connecting cloud", "Cloud speech translation")
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

        if active_config.translation_engine == "azure":
            azure_session = AzureSpeechTranslationSession(
                active_config,
                asyncio.get_running_loop(),
                subtitle_queue,
                status_queue,
            )
            await azure_session.start()
            tasks = [
                asyncio.create_task(watch_control_messages(websocket, stop_event)),
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
            await send_status(websocket, "Listening", "Cloud speech translation")
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
        if azure_session is not None:
            await azure_session.stop()
        if capture is not None:
            capture.stop()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
