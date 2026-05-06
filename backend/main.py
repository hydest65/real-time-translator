from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .audio_capture import AudioChunk, MicrophoneAudioCapture
from .asr import TranscriptionResult, WhisperASR
from .cloud_speech import AzureSpeechTranslationSession, CloudSubtitle, stream_microphone_to_azure
from .config import AppConfig, config
from .sentence_builder import SentenceBuilder
from .transcript_stabilizer import TranscriptStabilizer
from .translator import (
    ArgosTranslator,
    MarianMTTranslator,
    NLLBTranslator,
    Translator,
    glossary_duplicates,
    post_process_translation,
)


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="Low Latency Real Time Translator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@dataclass
class ASRJob:
    chunk: AudioChunk
    vad_ms: float = 0.0
    enqueued_at: float = field(default_factory=time.perf_counter)


@dataclass
class TranslateJob:
    sequence_id: str
    source_text: str
    start_seconds: float
    end_seconds: float
    audio_duration_seconds: float
    captured_at: float
    asr_ms: float
    audio_capture_ms: float
    vad_ms: float
    queue_wait_ms: float
    gpu_memory_mb: float
    transcribed_at: float = field(default_factory=time.perf_counter)


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
    audio_capture_ms: float = 0.0
    vad_ms: float = 0.0
    queue_wait_ms: float = 0.0
    glossary_ms: float = 0.0
    polish_ms: float = 0.0
    gpu_memory_mb: float = 0.0
    polish_stage: str = "rule_polished"


@dataclass
class SegmentMetric:
    segment_id: str
    audio_capture_ms: float
    vad_ms: float
    asr_time_ms: float
    translation_time_ms: float
    glossary_time_ms: float
    polish_time_ms: float
    queue_wait_ms: float
    total_latency_ms: float
    gpu_memory_mb: float
    dropped_chunks_count: int
    audio_queue_length: int
    translate_queue_length: int
    created_at: float = field(default_factory=time.time)


class PipelineMetrics:
    def __init__(self) -> None:
        self.recent_segments: deque[SegmentMetric] = deque(maxlen=50)
        self.dropped_chunks_count = 0
        self.audio_queue_length = 0
        self.translate_queue_length = 0
        self.last_low_volume_warning_at = 0.0

    def record_segment(self, metric: SegmentMetric) -> None:
        self.recent_segments.append(metric)

    def increment_dropped_chunks(self, count: int = 1) -> None:
        self.dropped_chunks_count += count

    def update_queue_lengths(self, audio_queue: asyncio.Queue | None = None, translate_queue: asyncio.Queue | None = None) -> None:
        if audio_queue is not None:
            self.audio_queue_length = audio_queue.qsize()
        if translate_queue is not None:
            self.translate_queue_length = translate_queue.qsize()

    def summary(self) -> dict[str, Any]:
        segments = list(self.recent_segments)
        if not segments:
            return {
                "segments": 0,
                "average_latency_ms": 0,
                "max_latency_ms": 0,
                "average_asr_time_ms": 0,
                "average_translation_time_ms": 0,
                "dropped_chunks_count": self.dropped_chunks_count,
                "current_audio_queue_length": self.audio_queue_length,
                "current_translate_queue_length": self.translate_queue_length,
                "glossary_duplicates": glossary_duplicates(),
            }

        def avg(values: list[float]) -> float:
            return round(sum(values) / len(values), 1) if values else 0

        return {
            "segments": len(segments),
            "average_latency_ms": avg([item.total_latency_ms for item in segments]),
            "max_latency_ms": round(max(item.total_latency_ms for item in segments), 1),
            "average_asr_time_ms": avg([item.asr_time_ms for item in segments]),
            "average_translation_time_ms": avg([item.translation_time_ms for item in segments]),
            "average_glossary_time_ms": avg([item.glossary_time_ms for item in segments]),
            "average_polish_time_ms": avg([item.polish_time_ms for item in segments]),
            "average_queue_wait_ms": avg([item.queue_wait_ms for item in segments]),
            "dropped_chunks_count": self.dropped_chunks_count,
            "current_audio_queue_length": self.audio_queue_length,
            "current_translate_queue_length": self.translate_queue_length,
            "latest_segments": [asdict(item) for item in segments[-5:]],
            "glossary_duplicates": glossary_duplicates(),
        }


@dataclass
class UtteranceUpdate:
    draft: SubtitleJob | None = None
    ready: TranslateJob | None = None
    ready_jobs: list[TranslateJob] = field(default_factory=list)


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
    SENTENCE_END_RE = re.compile(r"[.!?。！？][\"')\]]*$")

    MIN_READY_WORDS = 9
    MIN_IDLE_READY_WORDS = 8
    MIN_FORCED_READY_WORDS = 6
    SHORT_BUFFER_MAX_SECONDS = 3.0
    DUPLICATE_TIME_WINDOW_SECONDS = 2.4
    DUPLICATE_SIMILARITY = 0.88
    SOFT_PERIOD_MIN_WORDS = 12
    DANGLING_END_WORDS = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "because",
        "but",
        "by",
        "for",
        "from",
        "if",
        "in",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "then",
        "to",
        "was",
        "were",
        "when",
        "which",
        "while",
        "with",
    }
    CONTINUATION_START_WORDS = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "because",
        "but",
        "by",
        "can",
        "could",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "need",
        "needs",
        "of",
        "on",
        "or",
        "should",
        "so",
        "that",
        "the",
        "then",
        "there",
        "this",
        "to",
        "was",
        "we",
        "were",
        "which",
        "while",
        "will",
        "with",
        "would",
    }
    FALSE_PERIOD_BEFORE_WORDS = CONTINUATION_START_WORDS | {
        "approved",
        "away",
        "back",
        "comfortable",
        "compared",
        "covering",
        "depends",
        "different",
        "does",
        "fits",
        "ground",
        "head",
        "mock",
        "mocks",
        "mouth",
        "nose",
        "or",
        "operation",
        "operations",
        "properly",
        "portion",
        "room",
        "six",
        "small",
        "surfaces",
        "touch",
        "your",
    }
    INTERNAL_FALSE_PERIOD_BEFORE_WORDS = FALSE_PERIOD_BEFORE_WORDS - {
        "a",
        "an",
        "the",
        "this",
        "that",
        "it",
        "next",
        "we",
        "there",
    } | {
        "completely",
        "head",
        "if",
        "on",
        "that",
    }

    def __init__(self, active_config: AppConfig) -> None:
        self.pause_seconds = active_config.segmenter_pause_seconds
        self.max_words = active_config.segmenter_max_words
        self.max_seconds = active_config.segmenter_max_seconds
        self.sequence_index = 0
        self.recent_ready_signatures: list[str] = []
        self.recent_asr_items: list[tuple[str, float, float]] = []
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
        self.audio_capture_ms = 0.0
        self.vad_ms = 0.0
        self.queue_wait_ms = 0.0
        self.gpu_memory_mb = 0.0

    @property
    def has_text(self) -> bool:
        return bool(self.source_text.strip())

    def add_asr_result(self, item: TranscriptionResult, job: ASRJob, asr_ms: float) -> UtteranceUpdate:
        cleaned_item_text = self._normalize_local_text(item.text)
        if self._is_duplicate_asr(cleaned_item_text, item):
            return UtteranceUpdate()

        if not self.has_text:
            self.sequence_index += 1
            self.sequence_id = f"local-utterance-{self.sequence_index}"
            self.start_seconds = item.start_seconds
            self.captured_at = job.chunk.captured_at

        previous_end = self.end_seconds
        self.source_text = self._merge_text(self.source_text, cleaned_item_text)
        self.end_seconds = max(self.end_seconds, item.end_seconds)
        self.audio_duration_seconds = max(self.audio_duration_seconds, self.end_seconds - self.start_seconds)
        self.last_update_at = time.perf_counter()
        self.asr_ms += asr_ms
        self.audio_capture_ms += job.chunk.audio_capture_ms
        self.vad_ms += job.vad_ms
        self.queue_wait_ms += max(0.0, (time.perf_counter() - job.enqueued_at) * 1000)
        self.gpu_memory_mb = max(self.gpu_memory_mb, gpu_memory_mb())

        draft = self._subtitle(is_final=False, engine_suffix="draft")
        if not self._should_mark_ready(previous_end, item):
            return UtteranceUpdate(draft=draft)

        return UtteranceUpdate(draft=draft, ready=self.mark_ready())

    def mark_ready(self) -> TranslateJob | None:
        if not self.has_text:
            return None
        signature = self._text_signature(self.source_text)
        if signature and any(
            signature == recent or SequenceMatcher(None, signature, recent).ratio() >= self.DUPLICATE_SIMILARITY
            for recent in self.recent_ready_signatures
        ):
            self.reset()
            return None
        if signature:
            self.recent_ready_signatures = [*self.recent_ready_signatures, signature][-8:]
        job = TranslateJob(
            sequence_id=self.sequence_id,
            source_text=self.source_text.strip(),
            start_seconds=self.start_seconds,
            end_seconds=self.end_seconds,
            audio_duration_seconds=max(0.0, self.audio_duration_seconds),
            captured_at=self.captured_at,
            asr_ms=self.asr_ms,
            audio_capture_ms=self.audio_capture_ms,
            vad_ms=self.vad_ms,
            queue_wait_ms=self.queue_wait_ms,
            gpu_memory_mb=self.gpu_memory_mb,
        )
        self.reset()
        return job

    def mark_ready_if_idle(self) -> TranslateJob | None:
        if not self.has_text or not self.last_update_at:
            return None
        if time.perf_counter() - self.last_update_at < self.pause_seconds:
            return None
        words = SubtitleTurnDetector._normalize_text(self.source_text).split()
        if not self._is_ready_for_translation(self.source_text, words, is_idle=True):
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
            audio_capture_ms=self.audio_capture_ms,
            vad_ms=self.vad_ms,
            queue_wait_ms=self.queue_wait_ms,
            gpu_memory_mb=self.gpu_memory_mb,
        )

    def _should_mark_ready(self, previous_end: float, item: TranscriptionResult) -> bool:
        text = self.source_text.strip()
        words = SubtitleTurnDetector._normalize_text(text).split()
        if self._is_ready_for_translation(text, words):
            return True
        if (
            self.end_seconds - self.start_seconds >= self.SHORT_BUFFER_MAX_SECONDS
            and len(words) >= self.MIN_FORCED_READY_WORDS
            and not self._has_dangling_end(words)
        ):
            return True
        if len(words) >= self.max_words and not self._has_dangling_end(words):
            return True
        if (
            self.end_seconds - self.start_seconds >= self.max_seconds
            and len(words) >= self.MIN_FORCED_READY_WORDS
            and not self._has_dangling_end(words)
        ):
            return True
        gap = item.start_seconds - previous_end if previous_end else 0.0
        return (
            gap >= self.pause_seconds
            and len(words) >= self.MIN_IDLE_READY_WORDS
            and not self._has_dangling_end(words)
        )

    @classmethod
    def _looks_sentence_complete(cls, text: str, words: list[str]) -> bool:
        if len(words) < cls.MIN_READY_WORDS or cls._has_dangling_end(words):
            return False
        if not cls.SENTENCE_END_RE.search(text):
            return False
        if text.rstrip().endswith(".") and len(words) < cls.SOFT_PERIOD_MIN_WORDS:
            return False
        return True

    @classmethod
    def _is_ready_for_translation(cls, text: str, words: list[str], is_idle: bool = False) -> bool:
        if len(words) < cls.MIN_FORCED_READY_WORDS or cls._has_dangling_end(words):
            return False
        if cls._looks_sentence_complete(text, words):
            return True
        minimum_words = cls.MIN_IDLE_READY_WORDS if is_idle else cls.MIN_READY_WORDS
        return len(words) >= minimum_words

    @classmethod
    def _has_dangling_end(cls, words: list[str]) -> bool:
        return bool(words) and words[-1].lower().strip("'") in cls.DANGLING_END_WORDS

    @staticmethod
    def _merge_text(current: str, incoming: str) -> str:
        clean_current = LocalUtteranceAggregator._normalize_local_text(current)
        clean_incoming = LocalUtteranceAggregator._normalize_local_text(incoming)
        if not clean_current:
            return clean_incoming
        if not clean_incoming:
            return clean_current

        current_signature = LocalUtteranceAggregator._text_signature(clean_current)
        incoming_signature = LocalUtteranceAggregator._text_signature(clean_incoming)
        if incoming_signature and incoming_signature in current_signature:
            return clean_current
        if current_signature and current_signature in incoming_signature:
            return clean_incoming

        current_words = clean_current.split()
        incoming_words = clean_incoming.split()
        max_overlap = min(20, len(current_words), len(incoming_words))
        for overlap in range(max_overlap, 0, -1):
            left = LocalUtteranceAggregator._text_signature(" ".join(current_words[-overlap:]))
            right = LocalUtteranceAggregator._text_signature(" ".join(incoming_words[:overlap]))
            if left == right:
                return LocalUtteranceAggregator._normalize_local_text(" ".join([*current_words, *incoming_words[overlap:]]))
        return LocalUtteranceAggregator._normalize_local_text(
            LocalUtteranceAggregator._join_boundary_text(clean_current, clean_incoming)
        )

    @classmethod
    def _join_boundary_text(cls, current: str, incoming: str) -> str:
        adjusted_current = cls._remove_soft_boundary_period(current, incoming)
        adjusted_incoming = incoming
        first_word = SubtitleTurnDetector._normalize_text(incoming).split()
        if adjusted_current != current and first_word and first_word[0] in cls.CONTINUATION_START_WORDS:
            adjusted_incoming = incoming[:1].lower() + incoming[1:]
        return f"{adjusted_current} {adjusted_incoming}"

    @classmethod
    def _remove_soft_boundary_period(cls, current: str, incoming: str) -> str:
        stripped = current.rstrip()
        if not stripped.endswith("."):
            return current
        current_words = SubtitleTurnDetector._normalize_text(stripped).split()
        incoming_words = SubtitleTurnDetector._normalize_text(incoming).split()
        first_incoming = incoming_words[0] if incoming_words else ""
        if (
            first_incoming in cls.CONTINUATION_START_WORDS
            or (incoming[:1].islower() and first_incoming)
        ):
            return stripped[:-1].rstrip()
        return current

    @staticmethod
    def _normalize_local_text(text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""

        cleaned = re.sub(r"(?:\s*[\\/|]{2,}\s*)+", " ", cleaned)
        cleaned = re.sub(r"(?:\s*\.\s*){3,}", "... ", cleaned)
        cleaned = re.sub(r"(\b[A-Za-z]+)-\s+([A-Za-z])", r"\1 \2", cleaned)
        cleaned = re.sub(r"([!?.,])(?:\s*\1){1,}", r"\1", cleaned)
        cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
        cleaned = re.sub(r"([,.!?;:])([A-Za-z])", r"\1 \2", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = LocalUtteranceAggregator._repair_domain_asr_words(cleaned)
        cleaned = LocalUtteranceAggregator._repair_false_sentence_breaks(cleaned)
        cleaned = LocalUtteranceAggregator._collapse_repeated_phrases(cleaned)
        return cleaned.strip()

    @classmethod
    def _repair_false_sentence_breaks(cls, text: str) -> str:
        cleaned = text
        cleaned = re.sub(
            r"\b([A-Za-z][A-Za-z'-]*)[.!?]\s+\1\b",
            r"\1",
            cleaned,
            flags=re.IGNORECASE,
        )
        continuation_pattern = "|".join(sorted(map(re.escape, cls.INTERNAL_FALSE_PERIOD_BEFORE_WORDS), key=len, reverse=True))
        cleaned = re.sub(
            rf"\b([A-Za-z][A-Za-z'-]*)\.\s+({continuation_pattern})\b",
            lambda match: cls._join_false_period_match(match),
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\b(of|to|for|with|and|or|in|on|at|by)\.\s+", r"\1 ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b([A-Za-z]{4,})\s+\1s\b", r"\1s", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(gloves?)\s+(a specific type)\b", r"\1, \2", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(clean)\s+(removals?)\s+room\s+(coveralls?)\b", r"cleanroom \3", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(for)\s+(a\s+for\s+an)\b", r"for an", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            rf"\b([A-Za-z][A-Za-z'-]*)\.\s+({continuation_pattern})\b",
            lambda match: cls._join_false_period_match(match),
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()

    @staticmethod
    def _join_false_period_match(match: re.Match[str]) -> str:
        return f"{match.group(1)} {match.group(2).lower()}"

    @staticmethod
    def _repair_domain_asr_words(text: str) -> str:
        cleaned = text
        if re.search(r"\bsmock\b", cleaned, flags=re.IGNORECASE):
            cleaned = re.sub(r"\bmock(s)?\b", lambda match: f"smock{match.group(1) or ''}", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\bsmall\s+smock\b", "smock", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bzip\s+the\s+small\s+mock\b", "zip the smock", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bgounding\s+up\b", "gowning up", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bclean\s+room\b", "cleanroom", cleaned, flags=re.IGNORECASE)
        return cleaned

    @staticmethod
    def _text_signature(text: str) -> str:
        return " ".join(SubtitleTurnDetector._normalize_text(text).split())

    def _is_duplicate_asr(self, text: str, item: TranscriptionResult) -> bool:
        signature = self._text_signature(text)
        if not signature:
            return True

        self.recent_asr_items = [
            entry
            for entry in self.recent_asr_items
            if item.start_seconds - entry[1] <= self.DUPLICATE_TIME_WINDOW_SECONDS
        ]
        for recent_signature, recent_start, recent_end in self.recent_asr_items:
            time_overlap = min(item.end_seconds, recent_end) - max(item.start_seconds, recent_start)
            similarity = SequenceMatcher(None, signature, recent_signature).ratio()
            if signature == recent_signature or (
                similarity >= self.DUPLICATE_SIMILARITY
                and (abs(item.start_seconds - recent_start) <= self.DUPLICATE_TIME_WINDOW_SECONDS or time_overlap > 0)
            ):
                return True

        self.recent_asr_items.append((signature, item.start_seconds, item.end_seconds))
        self.recent_asr_items = self.recent_asr_items[-12:]
        return False

    @staticmethod
    def _collapse_repeated_phrases(text: str) -> str:
        words = text.split()
        if len(words) < 6:
            return text

        result: list[str] = []
        index = 0
        while index < len(words):
            collapsed = False
            max_phrase_words = min(8, (len(words) - index) // 2)
            for phrase_words in range(max_phrase_words, 1, -1):
                phrase = words[index : index + phrase_words]
                phrase_signature = LocalUtteranceAggregator._text_signature(" ".join(phrase))
                if not phrase_signature:
                    continue

                repeat_count = 1
                cursor = index + phrase_words
                while cursor + phrase_words <= len(words):
                    candidate = words[cursor : cursor + phrase_words]
                    candidate_signature = LocalUtteranceAggregator._text_signature(" ".join(candidate))
                    if candidate_signature != phrase_signature:
                        break
                    repeat_count += 1
                    cursor += phrase_words

                if repeat_count >= 2:
                    result.extend(phrase)
                    index = cursor
                    collapsed = True
                    break

            if not collapsed:
                result.append(words[index])
                index += 1

        return " ".join(result)


class StableTranscriptPipeline:
    """New local pipeline: ASR chunks -> stable transcript -> natural sentences."""

    def __init__(self, active_config: AppConfig) -> None:
        self.stabilizer = TranscriptStabilizer()
        self.builder = SentenceBuilder(
            min_words=max(10, min(active_config.segmenter_max_words, 14)),
            idle_min_words=8,
            max_words=active_config.segmenter_max_words,
            max_seconds=max(5.0, active_config.segmenter_max_seconds),
            idle_seconds=max(1.0, active_config.segmenter_pause_seconds),
        )
        self.sequence_index = 0
        self.active_sequence_id = ""
        self.active_start_seconds = 0.0
        self.active_captured_at = time.perf_counter()
        self.audio_capture_ms = 0.0
        self.vad_ms = 0.0
        self.queue_wait_ms = 0.0
        self.asr_ms = 0.0
        self.gpu_memory_mb = 0.0
        self.last_end_seconds = 0.0

    def accept_asr_result(self, item: TranscriptionResult, job: ASRJob, asr_ms: float) -> UtteranceUpdate:
        stable = self.stabilizer.accept(item.text)
        if stable.is_duplicate and not stable.delta_text:
            return UtteranceUpdate()

        self._ensure_active(item.start_seconds, job.chunk.captured_at)
        self._accumulate_metrics(job, asr_ms)
        self.last_end_seconds = max(self.last_end_seconds, item.end_seconds)

        update = self.builder.accept(stable.delta_text, item.start_seconds, item.end_seconds)
        draft = self._draft(update.draft_text, item.end_seconds)
        ready_jobs = self._jobs_from_sentences(update.final_sentences)
        return UtteranceUpdate(draft=draft, ready=ready_jobs[0] if ready_jobs else None, ready_jobs=ready_jobs)

    def flush_if_idle(self) -> UtteranceUpdate:
        update = self.builder.flush_if_idle(self.last_end_seconds)
        ready_jobs = self._jobs_from_sentences(update.final_sentences)
        draft = self._draft(update.draft_text, self.last_end_seconds) if update.draft_text else None
        return UtteranceUpdate(draft=draft, ready=ready_jobs[0] if ready_jobs else None, ready_jobs=ready_jobs)

    def _ensure_active(self, start_seconds: float, captured_at: float) -> None:
        if self.active_sequence_id:
            return
        self.sequence_index += 1
        self.active_sequence_id = f"local-sentence-{self.sequence_index}"
        self.active_start_seconds = start_seconds
        self.active_captured_at = captured_at

    def _accumulate_metrics(self, job: ASRJob, asr_ms: float) -> None:
        self.audio_capture_ms += job.chunk.audio_capture_ms
        self.vad_ms += job.vad_ms
        self.queue_wait_ms += max(0.0, (time.perf_counter() - job.enqueued_at) * 1000)
        self.asr_ms += asr_ms
        self.gpu_memory_mb = max(self.gpu_memory_mb, gpu_memory_mb())

    def _draft(self, text: str, end_seconds: float) -> SubtitleJob | None:
        if not self.active_sequence_id or not text.strip():
            return None
        return SubtitleJob(
            sequence_id=self.active_sequence_id,
            source_text=text.strip(),
            translated_text="",
            start_seconds=self.active_start_seconds,
            end_seconds=max(end_seconds, self.active_start_seconds),
            audio_duration_seconds=max(0.0, end_seconds - self.active_start_seconds),
            asr_ms=self.asr_ms,
            translate_ms=0,
            total_latency_ms=(time.perf_counter() - self.active_captured_at) * 1000,
            engine="local-stable-draft",
            is_final=False,
            audio_capture_ms=self.audio_capture_ms,
            vad_ms=self.vad_ms,
            queue_wait_ms=self.queue_wait_ms,
            gpu_memory_mb=self.gpu_memory_mb,
        )

    def _jobs_from_sentences(self, sentences) -> list[TranslateJob]:
        jobs: list[TranslateJob] = []
        for sentence in sentences:
            text = sentence.text.strip()
            if not text:
                continue
            self._ensure_active(sentence.started_at, self.active_captured_at)
            jobs.append(
                TranslateJob(
                    sequence_id=self.active_sequence_id,
                    source_text=text,
                    start_seconds=self.active_start_seconds,
                    end_seconds=sentence.ended_at,
                    audio_duration_seconds=max(0.0, sentence.ended_at - self.active_start_seconds),
                    captured_at=self.active_captured_at,
                    asr_ms=self.asr_ms,
                    audio_capture_ms=self.audio_capture_ms,
                    vad_ms=self.vad_ms,
                    queue_wait_ms=self.queue_wait_ms,
                    gpu_memory_mb=self.gpu_memory_mb,
                )
            )
            self.active_sequence_id = ""
            self.active_start_seconds = sentence.ended_at
            self.active_captured_at = time.perf_counter()
            self.audio_capture_ms = 0.0
            self.vad_ms = 0.0
            self.queue_wait_ms = 0.0
            self.asr_ms = 0.0
            self.gpu_memory_mb = 0.0
        return jobs


class Runtime:
    def __init__(self) -> None:
        self.asr: WhisperASR | None = None
        self.translator: Translator | None = None
        self.current_config = config
        self.lock = asyncio.Lock()

    async def ensure_models(self, next_config: AppConfig) -> None:
        async with self.lock:
            if next_config.translation_engine == "azure":
                self.current_config = next_config
                return

            next_asr_model = effective_asr_model(next_config.asr_model_size, next_config.source_language)
            current_asr_model = effective_asr_model(
                self.current_config.asr_model_size,
                self.current_config.source_language,
            )
            needs_asr = (
                self.asr is None
                or current_asr_model != next_asr_model
                or self.current_config.asr_device != next_config.asr_device
                or self.current_config.asr_compute_type != next_config.asr_compute_type
            )
            needs_translator = (
                self.translator is None
                or self.current_config.translation_engine != next_config.translation_engine
                or self.current_config.source_language != next_config.source_language
                or self.current_config.target_language != next_config.target_language
                or self.current_config.asr_device != next_config.asr_device
                or self.current_config.nllb_model_name != next_config.nllb_model_name
                or self.current_config.marian_en_zh_model_name != next_config.marian_en_zh_model_name
            )

            if needs_asr:
                print(f"[load] ASR {next_asr_model} on {next_config.asr_device}/{next_config.asr_compute_type}", flush=True)
                self.asr = await asyncio.to_thread(
                    WhisperASR,
                    next_asr_model,
                    next_config.asr_device,
                    next_config.asr_compute_type,
                )

            if needs_translator:
                if next_config.translation_engine == "argos":
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
pipeline_metrics = PipelineMetrics()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return asdict(runtime.current_config)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "message": "Backend is running", "config": asdict(runtime.current_config)}


@app.get("/metrics")
async def metrics() -> dict[str, Any]:
    return pipeline_metrics.summary()


def build_config(payload: dict[str, Any]) -> AppConfig:
    merged = asdict(config)
    for key, value in payload.items():
        if key in merged and value not in (None, ""):
            merged[key] = value

    merged["source_language"] = "eng_Latn"
    merged["target_language"] = "zho_Hans"
    merged["azure_source_language"] = azure_language_code(merged["source_language"])
    merged["azure_target_language"] = "zh-Hans"

    merged["chunk_seconds"] = max(1.0, min(5.0, float(merged["chunk_seconds"])))
    merged["overlap_seconds"] = max(0.0, min(1.0, float(merged["overlap_seconds"])))
    merged["max_subtitles"] = max(1, min(5, int(merged["max_subtitles"])))
    merged["queue_max_size"] = max(1, min(4, int(merged["queue_max_size"])))
    merged["audio_sample_rate"] = int(merged["audio_sample_rate"])
    merged["audio_channels"] = int(merged["audio_channels"])
    merged["vad_rms_threshold"] = float(merged["vad_rms_threshold"])
    if merged["audio_source"] not in ("microphone", "system"):
        merged["audio_source"] = "microphone"
    merged["turn_detector_enabled"] = bool(merged["turn_detector_enabled"])
    merged["turn_pause_seconds"] = max(0.6, min(4.0, float(merged["turn_pause_seconds"])))
    merged["noise_min_words"] = max(1, min(5, int(merged["noise_min_words"])))
    merged["segmenter_enabled"] = bool(merged["segmenter_enabled"])
    merged["segmenter_pause_seconds"] = max(0.4, min(2.0, float(merged["segmenter_pause_seconds"])))
    merged["segmenter_max_words"] = max(8, min(40, int(merged["segmenter_max_words"])))
    merged["segmenter_max_seconds"] = max(3.0, min(20.0, float(merged["segmenter_max_seconds"])))
    return AppConfig(**merged)


def whisper_language(source_language: str) -> str:
    return "en"


def effective_asr_model(model_size: str, source_language: str) -> str:
    return model_size


def azure_language_code(source_language: str) -> str:
    return "en-US"


def create_queue(max_size: int) -> asyncio.Queue:
    return asyncio.Queue(maxsize=max_size)


def put_latest(queue_: asyncio.Queue, item: object) -> int:
    dropped = 0
    while queue_.full():
        try:
            queue_.get_nowait()
            queue_.task_done()
            dropped += 1
        except asyncio.QueueEmpty:
            break
    queue_.put_nowait(item)
    return dropped


def enqueue_translation(queue_: asyncio.Queue, item: object) -> int:
    return put_latest(queue_, item)


def gpu_memory_mb() -> float:
    try:
        import torch

        if not torch.cuda.is_available():
            return 0.0
        return round(torch.cuda.memory_allocated() / (1024 * 1024), 1)
    except Exception:
        return 0.0


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
    consecutive_silent_chunks = 0
    low_volume_threshold = active_config.vad_rms_threshold * 1.8
    async for chunk in capture.chunks():
        if stop_event.is_set():
            break
        vad_started = time.perf_counter()
        vad_ms = (time.perf_counter() - vad_started) * 1000
        if chunk.rms < active_config.vad_rms_threshold:
            consecutive_silent_chunks += 1
            if consecutive_silent_chunks == 1 or consecutive_silent_chunks % 8 == 0:
                put_latest(
                    status_queue,
                    {
                        "type": "notice",
                        "label": "Silent",
                        "detail": f"rms={chunk.rms:.4f}; skipped before ASR",
                    },
                )
            continue

        consecutive_silent_chunks = 0
        if chunk.rms < low_volume_threshold:
            now = time.perf_counter()
            if now - pipeline_metrics.last_low_volume_warning_at > 2.0:
                pipeline_metrics.last_low_volume_warning_at = now
                put_latest(
                    status_queue,
                    {
                        "type": "notice",
                        "label": "Low volume",
                        "detail": f"rms={chunk.rms:.4f}; speech may be unstable",
                    },
                )

        dropped = put_latest(audio_queue, ASRJob(chunk=chunk, vad_ms=vad_ms))
        if dropped:
            pipeline_metrics.increment_dropped_chunks(dropped)
        pipeline_metrics.update_queue_lengths(audio_queue=audio_queue)


async def asr_worker(
    audio_queue: asyncio.Queue,
    translate_queue: asyncio.Queue,
    subtitle_queue: asyncio.Queue,
    status_queue: asyncio.Queue,
    active_config: AppConfig,
    stop_event: asyncio.Event,
) -> None:
    assert runtime.asr is not None
    transcript_pipeline = StableTranscriptPipeline(active_config)
    max_chunk_queue_wait_seconds = 3.0
    while not stop_event.is_set():
        try:
            job: ASRJob = await asyncio.wait_for(audio_queue.get(), timeout=0.2)
        except asyncio.TimeoutError:
            idle_update = transcript_pipeline.flush_if_idle()
            if idle_update.draft is not None:
                put_latest(subtitle_queue, idle_update.draft)
            if idle_update.ready_jobs:
                for pending_job in idle_update.ready_jobs:
                    enqueue_translation(translate_queue, pending_job)
                pipeline_metrics.update_queue_lengths(audio_queue=audio_queue, translate_queue=translate_queue)
                put_latest(status_queue, {"type": "status", "status": "Translating", "detail": "Translating completed sentence."})
            continue

        queue_wait_seconds = time.perf_counter() - job.enqueued_at
        if queue_wait_seconds > max_chunk_queue_wait_seconds:
            pipeline_metrics.increment_dropped_chunks()
            audio_queue.task_done()
            pipeline_metrics.update_queue_lengths(audio_queue=audio_queue, translate_queue=translate_queue)
            put_latest(
                status_queue,
                {
                    "type": "notice",
                    "label": "Dropped stale audio",
                    "detail": f"chunk waited {queue_wait_seconds:.1f}s before ASR",
                },
            )
            continue

        started = time.perf_counter()
        put_latest(status_queue, {"type": "status", "status": "Transcribing"})
        transcriptions = await runtime.asr.transcribe(
            job.chunk.samples,
            job.chunk.start_seconds,
            language=whisper_language(active_config.source_language),
        )
        asr_ms = (time.perf_counter() - started) * 1000
        audio_queue.task_done()
        pipeline_metrics.update_queue_lengths(audio_queue=audio_queue, translate_queue=translate_queue)

        if not transcriptions:
            idle_update = transcript_pipeline.flush_if_idle()
            if idle_update.draft is not None:
                put_latest(subtitle_queue, idle_update.draft)
            if idle_update.ready_jobs:
                for pending_job in idle_update.ready_jobs:
                    enqueue_translation(translate_queue, pending_job)
                pipeline_metrics.update_queue_lengths(audio_queue=audio_queue, translate_queue=translate_queue)
            put_latest(status_queue, {"type": "status", "status": "Listening", "detail": "No speech detected."})
            continue

        for item in transcriptions:
            update = transcript_pipeline.accept_asr_result(item, job, asr_ms)
            if update.draft is not None:
                put_latest(subtitle_queue, update.draft)
            if update.ready_jobs:
                for ready_job in update.ready_jobs:
                    enqueue_translation(translate_queue, ready_job)
                pipeline_metrics.update_queue_lengths(audio_queue=audio_queue, translate_queue=translate_queue)


async def translate_worker(
    translate_queue: asyncio.Queue,
    subtitle_queue: asyncio.Queue,
    status_queue: asyncio.Queue,
    active_config: AppConfig,
    stop_event: asyncio.Event,
) -> None:
    assert runtime.translator is not None

    async def process_translate_job(job: TranslateJob) -> None:
        started = time.perf_counter()
        put_latest(status_queue, {"type": "status", "status": "Translating"})
        raw_translated = await runtime.translator.translate(
            job.source_text,
            active_config.source_language,
            active_config.target_language,
        )
        translate_ms = (time.perf_counter() - started) * 1000
        post_processed = post_process_translation(job.source_text, raw_translated)
        total_latency_ms = (time.perf_counter() - job.captured_at) * 1000
        current_gpu_memory_mb = max(job.gpu_memory_mb, gpu_memory_mb())

        pipeline_metrics.record_segment(
            SegmentMetric(
                segment_id=job.sequence_id,
                audio_capture_ms=job.audio_capture_ms,
                vad_ms=job.vad_ms,
                asr_time_ms=job.asr_ms,
                translation_time_ms=translate_ms,
                glossary_time_ms=post_processed.glossary_time_ms,
                polish_time_ms=post_processed.polish_time_ms,
                queue_wait_ms=job.queue_wait_ms,
                total_latency_ms=total_latency_ms,
                gpu_memory_mb=current_gpu_memory_mb,
                dropped_chunks_count=pipeline_metrics.dropped_chunks_count,
                audio_queue_length=pipeline_metrics.audio_queue_length,
                translate_queue_length=translate_queue.qsize(),
            )
        )

        put_latest(
            subtitle_queue,
            SubtitleJob(
                sequence_id=job.sequence_id,
                source_text=job.source_text,
                translated_text=post_processed.text,
                start_seconds=job.start_seconds,
                end_seconds=job.end_seconds,
                audio_duration_seconds=job.audio_duration_seconds,
                asr_ms=job.asr_ms,
                translate_ms=translate_ms,
                total_latency_ms=total_latency_ms,
                engine=runtime.translator.engine_name,
                is_final=True,
                audio_capture_ms=job.audio_capture_ms,
                vad_ms=job.vad_ms,
                queue_wait_ms=job.queue_wait_ms,
                glossary_ms=post_processed.glossary_time_ms,
                polish_ms=post_processed.polish_time_ms,
                gpu_memory_mb=current_gpu_memory_mb,
                polish_stage="rule_polished",
            ),
        )
        put_latest(status_queue, {"type": "status", "status": "Listening", "detail": "Waiting for speech."})

    while not stop_event.is_set():
        try:
            job: TranslateJob = await asyncio.wait_for(translate_queue.get(), timeout=0.2)
        except asyncio.TimeoutError:
            continue

        try:
            await process_translate_job(job)
        except Exception as exc:
            put_latest(status_queue, {"type": "status", "status": "Error", "detail": f"Translation failed: {exc}"})
        finally:
            translate_queue.task_done()
            pipeline_metrics.update_queue_lengths(translate_queue=translate_queue)


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
    emitted_segments: dict[str, float] = {}
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
                now = time.perf_counter()
                is_update = payload.polish_stage == "llm_polished"
                first_emitted_at = emitted_segments.get(payload.sequence_id)
                if is_update and (first_emitted_at is None or now - first_emitted_at > 1.0):
                    subtitle_queue.task_done()
                    continue
                if not is_update:
                    emitted_segments[payload.sequence_id] = now
                perf = {
                    "audioSeconds": round(payload.audio_duration_seconds, 2),
                    "audioCaptureMs": round(payload.audio_capture_ms, 1),
                    "vadMs": round(payload.vad_ms, 1),
                    "asrMs": round(payload.asr_ms, 1),
                    "translateMs": round(payload.translate_ms, 1),
                    "glossaryMs": round(payload.glossary_ms, 1),
                    "polishMs": round(payload.polish_ms, 1),
                    "queueWaitMs": round(payload.queue_wait_ms, 1),
                    "totalLatencyMs": round(payload.total_latency_ms, 1),
                    "gpuMemoryMb": round(payload.gpu_memory_mb, 1),
                    "engine": payload.engine,
                    "stage": payload.polish_stage,
                }
                await websocket.send_json(
                    {
                        "type": "subtitle_update" if is_update else "subtitle",
                        "segmentId": payload.sequence_id,
                        "sequenceId": payload.sequence_id,
                        "sourceText": payload.source_text,
                        "translatedText": payload.translated_text,
                        "start": round(payload.start_seconds, 2),
                        "end": round(payload.end_seconds, 2),
                        "isFinal": payload.is_final,
                        "polishStage": payload.polish_stage,
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


@app.websocket("/ws/subtitles")
async def subtitles(websocket: WebSocket) -> None:
    await websocket.accept()
    capture: MicrophoneAudioCapture | None = None
    azure_session: AzureSpeechTranslationSession | None = None
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task] = []

    try:
        start_message = await websocket.receive_json()
        if start_message.get("action") != "start":
            await send_status(websocket, "Error", "Expected start action.")
            return

        active_config = build_config(start_message.get("config", {}))
        effective_model = effective_asr_model(active_config.asr_model_size, active_config.source_language)
        if active_config.translation_engine == "azure":
            await send_status(websocket, "Connecting cloud", "Azure Speech Translation")
        else:
            await send_status(
                websocket,
                "Loading models",
                f"ASR {effective_model}; translator {active_config.translation_engine}",
            )
            await runtime.ensure_models(active_config)

        audio_queue = create_queue(active_config.queue_max_size)
        translate_queue = create_queue(3)
        subtitle_queue = create_queue(max(6, active_config.queue_max_size))
        status_queue = create_queue(max(3, active_config.queue_max_size))

        capture = MicrophoneAudioCapture(
            sample_rate=active_config.audio_sample_rate,
            channels=active_config.audio_channels,
            chunk_seconds=active_config.chunk_seconds,
            overlap_seconds=active_config.overlap_seconds,
            audio_source=active_config.audio_source,
        )
        capture.start()

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
            await send_status(websocket, "Listening", "Azure Speech Translation")
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
                f"{active_config.translation_engine} / {runtime.asr.device} / {runtime.asr.model_size}",
            )
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await send_status(websocket, "Error", str(exc))
        except Exception:
            pass
    finally:
        stop_event.set()
        if azure_session is not None:
            await azure_session.stop()
        if capture is not None:
            capture.stop()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
