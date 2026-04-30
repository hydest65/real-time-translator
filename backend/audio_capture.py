from __future__ import annotations

import asyncio
import queue
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import numpy as np
import sounddevice as sd


@dataclass
class AudioChunk:
    samples: np.ndarray
    start_seconds: float
    end_seconds: float
    rms: float
    captured_at: float = field(default_factory=time.perf_counter)

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class MicrophoneAudioCapture:
    """Capture microphone or system-mix audio and yield mono float32 audio."""

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
        self._stopped = True
        self._next_start_sample = 0
        self._device: int | None = None
        self._input_sample_rate = sample_rate

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        audio = indata.copy()
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = audio.astype(np.float32)
        if int(self._input_sample_rate) != int(self.sample_rate):
            audio = resample_linear(audio, self._input_sample_rate, self.sample_rate)
        self._queue.put(audio)

    def start(self) -> None:
        if self._stream is not None:
            return
        self._stopped = False
        self._next_start_sample = 0
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

    def stop(self) -> None:
        self._stopped = True
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
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
            "立体声混音",
            "what u hear",
            "speaker",
            "speakers",
            "扬声器",
            "电脑扬声器",
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
                yield AudioChunk(samples=samples, start_seconds=start, end_seconds=end, rms=rms)

                buffer = buffer[step_samples:]
                self._next_start_sample += step_samples

    async def frames(self) -> AsyncIterator[np.ndarray]:
        """Yield short raw microphone frames for cloud streaming recognizers."""

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
