from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from backend.audio_capture import MicrophoneAudioCapture

from .funasr_streaming import ASR_CHUNK_MS, ASR_QUEUE_MAXSIZE, ASR_SAMPLE_RATE


@dataclass
class PCMChunk:
    pcm16: bytes
    samples: np.ndarray
    start_seconds: float
    end_seconds: float
    rms: float
    captured_at: float = field(default_factory=time.perf_counter)

    @property
    def is_silence(self) -> bool:
        return self.rms < 0.003


class StreamingAudioCapture:
    """Capture 16 kHz mono audio and emit fixed-size PCM16 chunks.

    The async queue is intentionally small. If inference falls behind, old
    chunks are dropped so latency does not grow without bound.
    """

    def __init__(
        self,
        *,
        audio_source: str = "microphone",
        recording_path: Path | None = None,
        sample_rate: int = ASR_SAMPLE_RATE,
        chunk_ms: int = ASR_CHUNK_MS,
        queue_maxsize: int = ASR_QUEUE_MAXSIZE,
    ) -> None:
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.chunk_samples = int(sample_rate * (chunk_ms / 1000))
        self.queue: asyncio.Queue[PCMChunk] = asyncio.Queue(maxsize=queue_maxsize)
        self.capture = MicrophoneAudioCapture(
            sample_rate=sample_rate,
            channels=1,
            chunk_seconds=chunk_ms / 1000,
            overlap_seconds=0,
            adaptive_chunking_enabled=False,
            min_chunk_seconds=chunk_ms / 1000,
            chunk_flush_silence_seconds=0,
            audio_source=audio_source,
            recording_path=recording_path,
        )
        self._producer_task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    def start(self) -> None:
        self.capture.start()
        self._producer_task = asyncio.create_task(self._produce())

    async def stop(self) -> None:
        self._stopped.set()
        if self._producer_task is not None:
            self._producer_task.cancel()
            await asyncio.gather(self._producer_task, return_exceptions=True)
            self._producer_task = None
        self.capture.stop()

    def source_notice(self) -> dict[str, str]:
        return self.capture.source_notice()

    def recording_notice(self) -> dict[str, str] | None:
        return self.capture.recording_notice()

    async def chunks(self):
        while not self._stopped.is_set():
            yield await self.queue.get()

    async def _produce(self) -> None:
        buffer = np.empty(0, dtype=np.float32)
        next_start_sample = 0
        async for frame in self.capture.frames():
            if self._stopped.is_set():
                break
            buffer = np.concatenate((buffer, frame.astype(np.float32, copy=False)))
            while len(buffer) >= self.chunk_samples:
                samples = buffer[: self.chunk_samples].copy()
                buffer = buffer[self.chunk_samples :]
                await self._put_chunk(samples, next_start_sample)
                next_start_sample += self.chunk_samples

    async def _put_chunk(self, samples: np.ndarray, start_sample: int) -> None:
        clipped = np.clip(samples, -1.0, 1.0)
        pcm_samples = (clipped * 32767.0).astype(np.int16)
        rms = float(np.sqrt(np.mean(np.square(clipped)))) if len(clipped) else 0.0
        chunk = PCMChunk(
            pcm16=pcm_samples.tobytes(),
            samples=pcm_samples,
            start_seconds=start_sample / self.sample_rate,
            end_seconds=(start_sample + len(pcm_samples)) / self.sample_rate,
            rms=rms,
        )
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
                print("[funasr-streaming] dropped old audio chunk to keep latency low", flush=True)
            except asyncio.QueueEmpty:
                pass
        await self.queue.put(chunk)
