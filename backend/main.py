from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import sys
import time
import wave
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
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
POST_MEETING_TIMEOUT_SECONDS = 8 * 60
active_post_meeting_process: asyncio.subprocess.Process | None = None

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
    data = asdict(active_config)
    azure_configured = bool(
        (active_config.azure_speech_key or "").strip()
        and (active_config.azure_speech_region or "").strip()
    )
    data["azure_speech_key"] = ""
    data["azure_speech_key_set"] = bool((active_config.azure_speech_key or "").strip())
    data["azure_configured"] = azure_configured
    return data


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
    asr_engine = choose_post_meeting_asr_engine()
    processed: list[dict[str, Any]] = []
    logs: list[str] = []

    for audio_path in audio_paths:
        processed.append(await process_one_recording(audio_path, script_path, asr_engine, logs))

    if len(processed) > 1:
        combined = write_combined_minutes(processed)
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
        }

    return {**processed[0], "log": "\n".join(logs), "asrEngine": asr_engine}


async def process_one_recording(
    audio_path: Path,
    script_path: Path,
    asr_engine: str,
    logs: list[str],
) -> dict[str, Any]:
    global active_post_meeting_process
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script_path),
        str(audio_path),
        "--asr-engine",
        asr_engine,
        "--device",
        "auto",
        cwd=str(ROOT),
        env=post_meeting_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    active_post_meeting_process = process
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=POST_MEETING_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise HTTPException(status_code=504, detail="Post-meeting processing timed out. Try a shorter recording or cached local models.") from exc
    finally:
        if active_post_meeting_process is process:
            active_post_meeting_process = None

    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    if process.returncode != 0:
        detail = (stderr_text or stdout_text or "Post-meeting processing failed.").strip()
        raise HTTPException(status_code=500, detail=detail[-2000:])
    logs.append(stdout_text.strip())

    transcript_path = audio_path.with_suffix(".transcript.md")
    minutes_path = audio_path.with_suffix(".minutes.md")
    minutes_docx_path = audio_path.with_suffix(".minutes.docx")
    if minutes_path.exists():
        write_minutes_docx(minutes_path, minutes_docx_path)
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


@app.post("/api/cancel-process-recording")
async def cancel_process_recording() -> dict[str, Any]:
    process = active_post_meeting_process
    if process is None or process.returncode is not None:
        return {"ok": True, "cancelled": False}
    process.kill()
    return {"ok": True, "cancelled": True}


def choose_post_meeting_asr_engine() -> str:
    requested_engine = os.getenv("POST_MEETING_ASR_ENGINE", "faster-whisper").strip().lower()
    if requested_engine != "funasr":
        return "faster-whisper"
    funasr_model_dir = ROOT / ".model-cache" / "models" / "iic" / "SenseVoiceSmall"
    if funasr_model_dir.exists() and importlib.util.find_spec("funasr") is not None:
        return "funasr"
    return "faster-whisper"


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
    duration_seconds = 0.0
    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            if frame_rate:
                duration_seconds = wav_file.getnframes() / frame_rate
    except (OSError, wave.Error):
        duration_seconds = 0.0
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

    if merged["source_language"] not in ("eng_Latn", "spa_Latn"):
        merged["source_language"] = "eng_Latn"
    merged["target_language"] = "zho_Hans"
    merged["azure_source_language"] = azure_language_code(merged["source_language"])
    merged["azure_target_language"] = "zh-Hans"

    merged["chunk_seconds"] = max(1.0, min(5.0, float(merged["chunk_seconds"])))
    merged["overlap_seconds"] = max(0.0, min(1.0, float(merged["overlap_seconds"])))
    if merged["asr_compute_type"] not in ("int8", "int8_float16", "float16", "float32"):
        merged["asr_compute_type"] = "int8"
    merged["asr_beam_size"] = max(1, min(5, int(merged["asr_beam_size"])))
    merged["asr_best_of"] = max(1, min(5, int(merged["asr_best_of"])))
    merged["asr_patience"] = max(0.8, min(1.5, float(merged["asr_patience"])))
    merged["asr_condition_on_previous_text"] = bool(merged["asr_condition_on_previous_text"])
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
    if source_language == "spa_Latn":
        return "es"
    return "en"


def effective_asr_model(model_size: str, source_language: str) -> str:
    if source_language == "spa_Latn":
        if model_size.endswith(".en"):
            return model_size.removesuffix(".en")
    return model_size


def azure_language_code(source_language: str) -> str:
    if source_language == "spa_Latn":
        return "es-ES"
    return "en-US"


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
