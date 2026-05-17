from __future__ import annotations

import asyncio
import queue
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
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
    captured_at: float = field(default_factory=time.perf_counter)

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class AppendableWavWriter:
    """Append mono PCM16 frames to a WAV file and keep the header valid."""

    def __init__(self, path: Path, sample_rate: int) -> None:
        self.path = path
        self.sample_rate = sample_rate
        self.file = None
        self.data_size = 0

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.exists() and self.path.stat().st_size >= 44
        self.file = self.path.open("r+b" if exists else "w+b")
        if exists:
            self.file.seek(40)
            self.data_size = struct.unpack("<I", self.file.read(4))[0]
            self.file.seek(44 + self.data_size)
        else:
            self.data_size = 0
            self.file.write(self._header(0))
            self.file.seek(44)

    def writeframes(self, data: bytes) -> None:
        if self.file is None:
            return
        self.file.write(data)
        self.data_size += len(data)

    def close(self) -> None:
        if self.file is None:
            return
        self.file.seek(0)
        self.file.write(self._header(self.data_size))
        self.file.close()
        self.file = None

    def _header(self, data_size: int) -> bytes:
        byte_rate = self.sample_rate * 2
        block_align = 2
        return (
            b"RIFF"
            + struct.pack("<I", 36 + data_size)
            + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, self.sample_rate, byte_rate, block_align, 16)
            + b"data"
            + struct.pack("<I", data_size)
        )


class MicrophoneAudioCapture:
    """Capture microphone or system audio and yield mono float32 audio."""

    def __init__(
        self,
        sample_rate: int,
        channels: int,
        chunk_seconds: float,
        overlap_seconds: float = 0.5,
        audio_source: str = "microphone",
        recording_path: Path | None = None,
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
        self._recording_path = recording_path
        self._recording_wave: AppendableWavWriter | None = None
        self._recording_lock = threading.Lock()
        self.selected_source_label = "Audio input"
        self.selected_source_detail = "Not started"

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        self._accept_audio(self._normalize_audio(indata, self._input_sample_rate))

    def _normalize_audio(self, audio: np.ndarray, source_rate: int) -> np.ndarray:
        normalized = np.asarray(audio, dtype=np.float32)
        if normalized.ndim > 1:
            normalized = normalized.mean(axis=1)
        normalized = np.nan_to_num(normalized, nan=0.0, posinf=0.0, neginf=0.0)
        normalized = np.clip(normalized, -1.0, 1.0)
        if int(source_rate) != int(self.sample_rate):
            normalized = resample_linear(normalized, source_rate, self.sample_rate)
        return normalized.astype(np.float32, copy=False)

    def _accept_audio(self, audio: np.ndarray) -> None:
        self._write_recording(audio)
        self._queue.put(audio)

    def _open_recording(self) -> None:
        if self._recording_path is None:
            return
        try:
            self._recording_wave = AppendableWavWriter(self._recording_path, self.sample_rate)
            self._recording_wave.open()
        except Exception as exc:
            print(f"[recording] disabled: {exc}", flush=True)
            self._recording_wave = None
            self._recording_path = None

    def _write_recording(self, audio: np.ndarray) -> None:
        if self._recording_wave is None or len(audio) == 0:
            return
        pcm16 = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
        with self._recording_lock:
            if self._recording_wave is not None:
                self._recording_wave.writeframes(pcm16.tobytes())

    def start(self) -> None:
        if self._stream is not None or self._system_recorder is not None:
            return

        self._stopped = False
        self._next_start_sample = 0
        self._open_recording()

        if self.audio_source == "system" and self._start_system_loopback():
            return

        self._device = self._select_device()
        if self._device is not None:
            device_info = sd.query_devices(self._device)
            device_name = str(device_info.get("name") or f"device {self._device}")
            self._input_sample_rate = int(device_info.get("default_samplerate") or self.sample_rate)
            input_channels = min(self.channels, int(device_info.get("max_input_channels") or self.channels))
            if self.audio_source == "system":
                self.selected_source_label = "System fallback"
                self.selected_source_detail = f"{device_name} ({self._input_sample_rate} Hz)"
                print(
                    f"[audio] system source: {self._device} {device_name}",
                    flush=True,
                )
            else:
                self.selected_source_label = "Microphone"
                self.selected_source_detail = f"{device_name} ({self._input_sample_rate} Hz)"
        else:
            self._input_sample_rate = self.sample_rate
            input_channels = self.channels
            self.selected_source_label = "Default microphone"
            self.selected_source_detail = f"Windows default input ({self._input_sample_rate} Hz)"

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

        loopback_name = str(getattr(loopback, "name", "") or "default speaker loopback")
        self.selected_source_label = "System loopback"
        self.selected_source_detail = f"{loopback_name} ({self._input_sample_rate} Hz)"
        print(f"[audio] system loopback: {loopback_name}", flush=True)

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
                self._accept_audio(self._normalize_audio(audio, self.sample_rate))
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

        with self._recording_lock:
            if self._recording_wave is not None:
                self._recording_wave.close()
                self._recording_wave = None

        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _select_device(self) -> int | None:
        if self.audio_source != "system":
            return None

        devices = list(sd.query_devices())
        default_output_name = self._default_output_name()
        output_tokens = self._audio_name_tokens(default_output_name)
        loopback_terms = (
            "loopback",
            "what u hear",
            "speaker",
            "speakers",
            "headphone",
            "headphones",
            "output",
            "\u626c\u58f0\u5668",
            "\u7535\u8111\u626c\u58f0\u5668",
            "\u8033\u673a",
        )
        stereo_mix_terms = (
            "stereo mix",
            "\u7acb\u4f53\u58f0\u6df7\u97f3",
            "stereo input",
        )
        candidates: list[tuple[int, int, str]] = []
        for index, device in enumerate(devices):
            channels = int(device.get("max_input_channels") or 0)
            if channels <= 0:
                continue
            name = str(device.get("name") or "").lower()
            has_loopback_term = any(term.lower() in name for term in loopback_terms)
            has_stereo_mix_term = any(term.lower() in name for term in stereo_mix_terms)
            if not has_loopback_term and not has_stereo_mix_term:
                continue

            score = 50
            if has_stereo_mix_term:
                score = 0
            elif output_tokens and has_loopback_term:
                name_tokens = self._audio_name_tokens(name)
                overlap = len(output_tokens.intersection(name_tokens))
                if overlap:
                    score = 20
                else:
                    score = 30
            elif has_loopback_term:
                score = 40

            if has_stereo_mix_term:
                score -= 5
            elif "loopback" in name:
                score -= 5
            if "\u7535\u8111\u626c\u58f0\u5668" in name:
                score += 10

            candidates.append((score, index, name))

        if not candidates:
            raise RuntimeError(
                "System audio input was not found. Enable Stereo Mix or choose microphone input."
            )
        candidates.sort()
        return candidates[0][1]

    @staticmethod
    def _default_output_name() -> str:
        try:
            device = sd.query_devices(kind="output")
        except Exception:
            return ""
        return str(device.get("name") or "")

    @staticmethod
    def _audio_name_tokens(name: str) -> set[str]:
        lowered = name.lower()
        separators = "()[]{}-_.,;:/\\\r\n\t"
        for separator in separators:
            lowered = lowered.replace(separator, " ")
        ignored = {
            "audio",
            "driver",
            "device",
            "input",
            "output",
            "with",
            "for",
            "and",
            "the",
            "hd",
        }
        tokens = {token for token in lowered.split() if len(token) >= 3 and token not in ignored}
        if "\u626c\u58f0\u5668" in lowered:
            tokens.add("\u626c\u58f0\u5668")
        if "\u7535\u8111\u626c\u58f0\u5668" in lowered:
            tokens.add("\u7535\u8111\u626c\u58f0\u5668")
        if "\u8033\u673a" in lowered:
            tokens.add("\u8033\u673a")
        return tokens

    def source_notice(self) -> dict[str, str]:
        return {
            "type": "notice",
            "label": self.selected_source_label,
            "detail": self.selected_source_detail,
        }

    def recording_notice(self) -> dict[str, str] | None:
        if self._recording_path is None:
            return None
        return {
            "type": "notice",
            "label": "Recording",
            "detail": str(self._recording_path),
        }

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
