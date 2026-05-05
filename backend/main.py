from __future__ import annotations

import asyncio
import re
import time
from dataclasses import asdict, dataclass, field
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
from .translator import ArgosTranslator, MarianMTTranslator, NLLBTranslator, Translator


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
        self.recent_ready_signatures: list[str] = []
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
        signature = self._text_signature(self.source_text)
        if signature and signature in self.recent_ready_signatures:
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
        )
        self.reset()
        return job

    def mark_ready_if_idle(self) -> TranslateJob | None:
        if not self.has_text or not self.last_update_at:
            return None
        if time.perf_counter() - self.last_update_at < self.pause_seconds:
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
        )

    def _should_mark_ready(self, previous_end: float, item: TranscriptionResult) -> bool:
        text = self.source_text.strip()
        words = SubtitleTurnDetector._normalize_text(text).split()
        if self._looks_sentence_complete(text, words):
            return True
        if len(words) >= self.max_words:
            return True
        if self.end_seconds - self.start_seconds >= self.max_seconds:
            return True
        gap = item.start_seconds - previous_end if previous_end else 0.0
        return gap >= self.pause_seconds and len(words) >= 4

    @classmethod
    def _looks_sentence_complete(cls, text: str, words: list[str]) -> bool:
        if len(words) < 7:
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
        cleaned = LocalUtteranceAggregator._collapse_repeated_phrases(cleaned)
        return cleaned.strip()

    @staticmethod
    def _text_signature(text: str) -> str:
        return " ".join(SubtitleTurnDetector._normalize_text(text).split())

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


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return asdict(runtime.current_config)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "message": "Backend is running", "config": asdict(runtime.current_config)}


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
    async for chunk in capture.chunks():
        if stop_event.is_set():
            break
        if chunk.rms < active_config.vad_rms_threshold:
            put_latest(
                status_queue,
                {
                    "type": "notice",
                    "label": "Silent",
                    "detail": f"rms={chunk.rms:.4f}",
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
        translate_queue = asyncio.Queue()
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
