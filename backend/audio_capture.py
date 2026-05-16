from __future__ import annotations

import asyncio
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import numpy as np
import sounddevice as sd

try:
    import soundcard as sc
except Exception:
    sc = None


@dataclass
class AudioChunk:
    samples: np.ndarray
    start_seconds: float
    end_seconds: float
    rms: float
    audio_capture_ms: float = 0.0
    captured_at: float = field(default_factory=time.perf_counter)

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class MicrophoneAudioCapture:
    """Capture microphone or system audio and yield mono float32 audio."""

    def __init__(
        self,
        sample_rate: int,
        channels: int,
        chunk_seconds: float,
        overlap_seconds: float = 0.5,
        audio_source: str = "microphone",
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_seconds = chunk_seconds
        self.audio_source = audio_source
        self.overlap_seconds = min(max(overlap_seconds, 0.0), max(chunk_seconds - 0.1, 0.0))
        self._queue: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream: Optional[sd.InputStream] = None
        self._system_recorder = None
        self._system_reader_thread: Optional[threading.Thread] = None
        self._stopped = True
        self._next_start_sample = 0
        self._device: int | None = None
        self._input_sample_rate = sample_rate

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        self._queue.put(self._normalize_audio(indata, self._input_sample_rate))

    def _normalize_audio(self, audio: np.ndarray, source_rate: int) -> np.ndarray:
        normalized = np.asarray(audio, dtype=np.float32)
        if normalized.ndim > 1:
            normalized = normalized.mean(axis=1)
        if int(source_rate) != int(self.sample_rate):
            normalized = resample_linear(normalized, source_rate, self.sample_rate)
        return normalized.astype(np.float32, copy=False)

    def start(self) -> None:
        if self._stream is not None or self._system_recorder is not None:
            return

        self._stopped = False
        self._next_start_sample = 0

        if self.audio_source == "system" and self._start_system_loopback():
            return

        self._device = self._select_device()
        if self._device is not None:
            device_info = sd.query_devices(self._device)
            self._input_sample_rate = int(device_info.get("default_samplerate") or self.sample_rate)
            input_channels = min(self.channels, int(device_info.get("max_input_channels") or self.channels))
        else:
            self._input_sample_rate = self.sample_rate
            input_channels = self.channels

        self._stream = sd.InputStream(
            samplerate=self._input_sample_rate,
            channels=max(1, input_channels),
            device=self._device,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def _start_system_loopback(self) -> bool:
        if sc is None:
            return False

        loopback = self._select_loopback_microphone()
        if loopback is None:
            return False

        try:
            self._input_sample_rate = self.sample_rate
            self._system_recorder = loopback.recorder(
                samplerate=self.sample_rate,
                channels=max(1, self.channels),
                blocksize=max(512, int(self.sample_rate * 0.1)),
            )
            self._system_recorder.__enter__()
        except Exception:
            self._system_recorder = None
            return False

        self._system_reader_thread = threading.Thread(
            target=self._read_system_loopback,
            name="system-loopback-reader",
            daemon=True,
        )
        self._system_reader_thread.start()
        return True

    def _select_loopback_microphone(self):
        if sc is None:
            return None

        try:
            speaker = sc.default_speaker()
            if speaker is None:
                return None
            speaker_name = getattr(speaker, "name", "")
            loopbacks = [
                microphone
                for microphone in sc.all_microphones(include_loopback=True)
                if getattr(microphone, "isloopback", False)
            ]
            exact_match = next((item for item in loopbacks if getattr(item, "name", "") == speaker_name), None)
            if exact_match is not None:
                return exact_match

            lowered_name = speaker_name.lower()
            substring_match = next(
                (item for item in loopbacks if lowered_name and lowered_name in getattr(item, "name", "").lower()),
                None,
            )
            if substring_match is not None:
                return substring_match
        except Exception:
            return None
        return None

    def _read_system_loopback(self) -> None:
        recorder = self._system_recorder
        if recorder is None:
            return

        frames_per_read = max(512, int(self.sample_rate * 0.1))
        try:
            while not self._stopped:
                try:
                    audio = recorder.record(numframes=frames_per_read)
                except Exception:
                    if self._stopped:
                        break
                    raise
                if audio is None or len(audio) == 0:
                    continue
                self._queue.put(self._normalize_audio(audio, self.sample_rate))
        except Exception:
            self._stopped = True

    def stop(self) -> None:
        self._stopped = True

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if self._system_recorder is not None:
            try:
                self._system_recorder.__exit__(None, None, None)
            except Exception:
                pass
            self._system_recorder = None

        if self._system_reader_thread is not None:
            self._system_reader_thread.join(timeout=1.0)
            self._system_reader_thread = None

        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _select_device(self) -> int | None:
        if self.audio_source != "system":
            return None

        devices = list(sd.query_devices())
        preferred_terms = (
            "stereo mix",
            "\u7acb\u4f53\u58f0\u6df7\u97f3",
            "stereo input",
            "what u hear",
            "loopback",
            "speaker",
            "speakers",
            "\u626c\u58f0\u5668",
            "\u7535\u8111\u626c\u58f0\u5668",
        )
        candidates = []
        for index, device in enumerate(devices):
            channels = int(device.get("max_input_channels") or 0)
            if channels <= 0:
                continue
            name = str(device.get("name") or "").lower()
            score = next((i for i, term in enumerate(preferred_terms) if term.lower() in name), None)
            if score is not None:
                candidates.append((score, index))

        if not candidates:
            raise RuntimeError(
                "System audio input was not found. Enable Stereo Mix or choose microphone input."
            )
        candidates.sort()
        return candidates[0][1]

    async def chunks(self) -> AsyncIterator[AudioChunk]:
        chunk_samples = int(self.sample_rate * self.chunk_seconds)
        step_samples = max(1, int(self.sample_rate * (self.chunk_seconds - self.overlap_seconds)))
        buffer = np.empty(0, dtype=np.float32)

        while not self._stopped:
            try:
                part = await asyncio.to_thread(self._queue.get, True, 0.2)
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue

            buffer = np.concatenate((buffer, part))
            while len(buffer) >= chunk_samples:
                samples = buffer[:chunk_samples].copy()
                rms = float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0
                start = self._next_start_sample / self.sample_rate
                end = start + (len(samples) / self.sample_rate)
                duration_seconds = len(samples) / self.sample_rate
                capture_finished_at = time.perf_counter()
                yield AudioChunk(
                    samples=samples,
                    start_seconds=start,
                    end_seconds=end,
                    rms=rms,
                    audio_capture_ms=duration_seconds * 1000,
                    captured_at=capture_finished_at - duration_seconds,
                )

                buffer = buffer[step_samples:]
                self._next_start_sample += step_samples

    async def frames(self) -> AsyncIterator[np.ndarray]:
        """Yield short raw audio frames for cloud streaming recognizers."""

        while not self._stopped:
            try:
                part = await asyncio.to_thread(self._queue.get, True, 0.2)
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            yield part.astype(np.float32)


def resample_linear(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or len(samples) == 0:
        return samples.astype(np.float32)

    duration = len(samples) / float(source_rate)
    target_length = max(1, int(duration * target_rate))
    source_x = np.linspace(0.0, duration, num=len(samples), endpoint=False)
    target_x = np.linspace(0.0, duration, num=target_length, endpoint=False)
    return np.interp(target_x, source_x, samples).astype(np.float32)
