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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .audio_capture import AudioChunk, MicrophoneAudioCapture
from .asr import TranscriptionResult, WhisperASR
from .cloud_speech import AzureSpeechTranslationSession, CloudSubtitle, stream_microphone_to_azure
from .config import AppConfig, config
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
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


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
    SENTENCE_END_RE = re.compile(r"[.!?。！？][\"')\]]*$")

    def __init__(self, active_config: AppConfig) -> None:
        self.pause_seconds = active_config.segmenter_pause_seconds
        self.max_words = active_config.segmenter_max_words
        self.max_seconds = active_config.segmenter_max_seconds
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
        if not self.has_text:
            self.sequence_index += 1
            self.sequence_id = f"local-utterance-{self.sequence_index}"
            self.start_seconds = item.start_seconds
            self.captured_at = job.chunk.captured_at

        previous_end = self.end_seconds
        self.source_text = self._merge_text(self.source_text, item.text)
        self.end_seconds = max(self.end_seconds, item.end_seconds)
        self.audio_duration_seconds = max(self.audio_duration_seconds, self.end_seconds - self.start_seconds)
        self.last_update_at = time.perf_counter()
        self.asr_ms += asr_ms

        draft = self._subtitle(is_final=False, engine_suffix="draft")
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
        if len(words) < 10:
            return False
        return bool(cls.SENTENCE_END_RE.search(text))

    @staticmethod
    def _merge_text(current: str, incoming: str) -> str:
        clean_current = LocalUtteranceAggregator._normalize_local_text(current)
        clean_incoming = LocalUtteranceAggregator._normalize_local_text(incoming)
        if not clean_current:
            return clean_incoming
        if not clean_incoming:
            return clean_current

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
    def _normalize_local_text(text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""

        cleaned = re.sub(r"(?:\s*[\\/|]{2,}\s*)+", " ", cleaned)
        cleaned = re.sub(r"(?:\s*\.\s*){3,}", "... ", cleaned)
        cleaned = re.sub(r"([!?.,])(?:\s*\1){1,}", r"\1", cleaned)
        cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
        cleaned = re.sub(r"([,.!?;:])([A-Za-z])", r"\1 \2", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()


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


def public_config_payload(active_config: AppConfig) -> dict[str, Any]:
    azure_configured = bool(
        (active_config.azure_speech_key or "").strip()
        and (active_config.azure_speech_region or "").strip()
    )
    post_meeting_asr_requested = requested_post_meeting_asr_engine()
    azure_batch_configured = is_azure_batch_configured(active_config)
    return {
        "cloud_configured": azure_configured,
        "cloud_batch_configured": azure_batch_configured,
        "cloud_speech_key_set": bool((active_config.azure_speech_key or "").strip()),
        "post_meeting_asr_requested": post_meeting_asr_requested.replace("azure-", "cloud-"),
        "post_meeting_asr_effective": choose_post_meeting_asr_engine().replace("azure-", "cloud-"),
    }


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
    asr_engine = choose_post_meeting_asr_engine(payload.get("engine"), notes_language)
    processed: list[dict[str, Any]] = []
    logs: list[str] = []
    notes_mode_message = post_meeting_mode_message(payload.get("engine"), asr_engine, notes_language)

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
            processed.append(
                await process_one_recording(
                    audio_path,
                    script_path,
                    asr_engine,
                    notes_language,
                    logs,
                    index,
                    len(audio_paths),
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


def set_post_meeting_progress(**updates: Any) -> None:
    post_meeting_progress.update(updates)
    post_meeting_progress["ok"] = True
    post_meeting_progress["updatedAt"] = updates.get("updated_at", time.time())
    post_meeting_progress["percent"] = max(0, min(100, int(post_meeting_progress.get("percent") or 0)))


async def process_one_recording(
    audio_path: Path,
    script_path: Path,
    asr_engine: str,
    notes_language: str,
    logs: list[str],
    index: int,
    total: int,
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
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script_path),
        str(audio_path),
        "--asr-engine",
        asr_engine,
        "--language",
        notes_language,
        "--notes-language",
        "en",
        "--device",
        post_meeting_device(),
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


def choose_post_meeting_asr_engine(ui_engine: object = "", notes_language: str = "en") -> str:
    if str(ui_engine or "").strip().lower() and str(ui_engine or "").strip().lower() != "azure":
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
    while not stop_event.is_set():
        try:
            job: ASRJob = await asyncio.wait_for(audio_queue.get(), timeout=0.2)
        except asyncio.TimeoutError:
            pending_job = aggregator.mark_ready_if_idle()
            if pending_job is not None:
                enqueue_translation(translate_queue, pending_job)
                put_latest(status_queue, {"type": "status", "status": "Translating", "detail": "Translating completed sentence."})
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

        if not transcriptions:
            pending_job = aggregator.mark_ready_if_idle()
            if pending_job is not None:
                enqueue_translation(translate_queue, pending_job)
            put_latest(status_queue, {"type": "status", "status": "Listening", "detail": "No speech detected."})
            continue

        for item in transcriptions:
            update = aggregator.add_asr_result(item, job, asr_ms)
            if update.draft is not None:
                put_latest(subtitle_queue, update.draft)
            if update.ready is not None:
                enqueue_translation(translate_queue, update.ready)


async def translate_worker(
    translate_queue: asyncio.Queue,
    subtitle_queue: asyncio.Queue,
    status_queue: asyncio.Queue,
    active_config: AppConfig,
    stop_event: asyncio.Event,
) -> None:
    assert runtime.translator is not None
    context_buffer = ContextualTranslationBuffer(active_config)

    async def process_translate_job(job: TranslateJob) -> None:
        started = time.perf_counter()
        put_latest(status_queue, {"type": "status", "status": "Translating"})
        translated = await runtime.translator.translate(
            job.source_text,
            active_config.source_language,
            active_config.target_language,
        )
        translate_ms = (time.perf_counter() - started) * 1000
        total_latency_ms = (time.perf_counter() - job.captured_at) * 1000

        put_latest(
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
            await process_translate_job(ready_job)

    while not stop_event.is_set():
        try:
            job: TranslateJob = await asyncio.wait_for(translate_queue.get(), timeout=0.2)
        except asyncio.TimeoutError:
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
            await send_status(websocket, "Connecting cloud", "Cloud speech translation")
        else:
            await send_status(
                websocket,
                "Loading models",
                f"ASR {effective_model}; translator {active_config.translation_engine}",
            )
            await runtime.ensure_models(active_config)

        audio_queue = create_queue(active_config.queue_max_size)
        translate_queue = asyncio.Queue()
        subtitle_queue = create_queue(max(6, active_config.queue_max_size))
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
