from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

import numpy as np

from .audio_capture import MicrophoneAudioCapture
from .config import AppConfig, load_dotenv_file
from .terminology import build_azure_phrase_list


@dataclass
class CloudSubtitle:
    sequence_id: str
    source_text: str
    translated_text: str
    start_seconds: float
    end_seconds: float
    is_final: bool
    received_at: float = field(default_factory=time.perf_counter)


def float32_to_pcm16_bytes(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


class AzureSpeechTranslationSession:
    """Stream microphone audio to Azure Speech Translation and emit continuous subtitles."""

    engine_name = "azure"

    def __init__(
        self,
        active_config: AppConfig,
        loop: asyncio.AbstractEventLoop,
        result_queue: asyncio.Queue,
        status_queue: asyncio.Queue,
    ) -> None:
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError as exc:
            raise RuntimeError(
                "Azure Speech SDK is not installed. Run: python -m pip install azure-cognitiveservices-speech"
            ) from exc

        load_dotenv_file()
        key = active_config.azure_speech_key or os.getenv("AZURE_SPEECH_KEY", "")
        region = active_config.azure_speech_region or os.getenv("AZURE_SPEECH_REGION", "")
        if not key or not region:
            raise RuntimeError("Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION before using Azure Cloud.")

        self.speechsdk = speechsdk
        self.loop = loop
        self.result_queue = result_queue
        self.status_queue = status_queue
        self.started_at = time.perf_counter()
        self.closed = False
        self.final_sequence = 0

        speech_config = speechsdk.translation.SpeechTranslationConfig(subscription=key, region=region)
        speech_config.speech_recognition_language = active_config.azure_source_language
        speech_config.add_target_language(active_config.azure_target_language)

        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=active_config.audio_sample_rate,
            bits_per_sample=16,
            channels=active_config.audio_channels,
        )
        self.push_stream = speechsdk.audio.PushAudioInputStream(stream_format=stream_format)
        audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)
        self.recognizer = speechsdk.translation.TranslationRecognizer(
            translation_config=speech_config,
            audio_config=audio_config,
        )
        phrase_list = speechsdk.PhraseListGrammar.from_recognizer(self.recognizer)
        phrases = build_azure_phrase_list(
            active_config.azure_phrase_list,
            source_language=active_config.azure_source_language,
        )
        for phrase in phrases:
            phrase_list.addPhrase(phrase)
        if phrases:
            print(f"[terms] Azure phrase list loaded: {len(phrases)} terms", flush=True)

        self.target_language = active_config.azure_target_language
        self.recognizer.recognizing.connect(self._on_recognizing)
        self.recognizer.recognized.connect(self._on_recognized)
        self.recognizer.canceled.connect(self._on_canceled)

    async def start(self) -> None:
        await asyncio.to_thread(self.recognizer.start_continuous_recognition_async().get)

    async def stop(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.push_stream.close()
        finally:
            await asyncio.to_thread(self.recognizer.stop_continuous_recognition_async().get)

    def write_audio(self, samples: np.ndarray) -> None:
        if self.closed:
            return
        self.push_stream.write(float32_to_pcm16_bytes(samples))

    def _on_recognizing(self, event) -> None:
        self._enqueue_result(event.result, is_final=False)

    def _on_recognized(self, event) -> None:
        self._enqueue_result(event.result, is_final=True)

    def _on_canceled(self, event) -> None:
        detail = getattr(event, "error_details", "") or str(getattr(event, "reason", "Canceled"))
        self.loop.call_soon_threadsafe(
            put_latest_threadsafe,
            self.status_queue,
            {"type": "status", "status": "Error", "detail": f"Azure canceled: {detail}"},
        )

    def _enqueue_result(self, result, is_final: bool) -> None:
        source_text = (getattr(result, "text", "") or "").strip()
        translations = getattr(result, "translations", {}) or {}
        translated_text = (translations.get(self.target_language, "") or "").strip()
        if not source_text and not translated_text:
            return

        now = time.perf_counter()
        start_seconds, end_seconds = self._timing(result, now)
        if is_final:
            self.final_sequence += 1
            sequence_id = f"azure-final-{self.final_sequence}"
        else:
            sequence_id = "azure-live"

        item = CloudSubtitle(
            sequence_id=sequence_id,
            source_text=source_text,
            translated_text=translated_text,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            is_final=is_final,
            received_at=now,
        )
        self.loop.call_soon_threadsafe(put_latest_threadsafe, self.result_queue, item)

    def _timing(self, result, now: float) -> tuple[float, float]:
        offset = getattr(result, "offset", None)
        duration = getattr(result, "duration", None)
        if offset is not None and duration is not None:
            start_seconds = max(0.0, float(offset) / 10_000_000)
            end_seconds = max(start_seconds, float(offset + duration) / 10_000_000)
            return start_seconds, end_seconds
        start_seconds = max(0.0, (now - self.started_at) - 2.0)
        end_seconds = max(start_seconds, now - self.started_at)
        return start_seconds, end_seconds


def put_latest_threadsafe(queue_: asyncio.Queue, item: object) -> None:
    while queue_.full():
        try:
            queue_.get_nowait()
            queue_.task_done()
        except asyncio.QueueEmpty:
            break
    queue_.put_nowait(item)


async def stream_microphone_to_azure(
    capture: MicrophoneAudioCapture,
    session: AzureSpeechTranslationSession,
    stop_event: asyncio.Event,
) -> None:
    last_audio_notice_at = 0.0
    async for frame in capture.frames():
        if stop_event.is_set():
            break
        now = time.perf_counter()
        if now - last_audio_notice_at >= 1.0:
            rms = float(np.sqrt(np.mean(np.square(frame)))) if len(frame) else 0.0
            label = "Audio OK" if rms >= 0.003 else "No system audio"
            put_latest_threadsafe(
                session.status_queue,
                {"type": "notice", "label": label, "detail": f"rms={rms:.4f}"},
            )
            last_audio_notice_at = now
        session.write_audio(frame)
