from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np


ASR_ENGINE = "funasr_streaming"
ASR_SAMPLE_RATE = 16_000
ASR_CHUNK_MS = 600
ASR_CHUNK_SIZE = [0, 10, 5]
ASR_ENABLE_PUNCTUATION = False
ASR_ENABLE_VAD = False
ASR_PRIMARY_MODEL = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online"
ASR_FALLBACK_MODEL = "paraformer-zh-streaming"
ASR_QUEUE_MAXSIZE = 3


def default_device() -> Literal["cuda", "cpu"]:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


ASR_DEVICE = default_device()


@dataclass
class FunASRStreamingConfig:
    model_name: str = ASR_PRIMARY_MODEL
    fallback_model_name: str = ASR_FALLBACK_MODEL
    sample_rate: int = ASR_SAMPLE_RATE
    chunk_ms: int = ASR_CHUNK_MS
    chunk_size: list[int] = field(default_factory=lambda: list(ASR_CHUNK_SIZE))
    enable_punctuation: bool = ASR_ENABLE_PUNCTUATION
    enable_vad: bool = ASR_ENABLE_VAD
    device: Literal["cuda", "cpu", "auto"] = "auto"
    encoder_chunk_look_back: int = 4
    decoder_chunk_look_back: int = 1

    @property
    def effective_device(self) -> Literal["cuda", "cpu"]:
        return default_device() if self.device == "auto" else self.device


@dataclass
class FunASRStreamingResult:
    event_type: Literal["partial", "final"]
    text: str
    latency_ms: float
    inference_ms: float
    rtf: float
    audio_ms: int
    model_name: str
    device: str


class FunASRStreamingASR:
    """Thin wrapper around FunASR AutoModel streaming inference.

    The public input format is mono PCM int16 at 16 kHz. The streaming cache is
    kept on this object and reused for every chunk until a final flush happens.
    """

    def __init__(self, config: FunASRStreamingConfig | None = None) -> None:
        self.config = config or FunASRStreamingConfig()
        self.cache: dict[str, Any] = {}
        self.model_name = self.config.model_name
        self.device = self.config.effective_device
        self.model = None
        self.load_ms = 0.0
        self._load_model()

    def _load_model(self) -> None:
        from funasr import AutoModel

        started = time.perf_counter()
        names_to_try = [self.config.model_name, self.config.fallback_model_name]
        last_error: Exception | None = None
        for model_name in dict.fromkeys(name for name in names_to_try if name):
            try:
                self.model = AutoModel(
                    model=model_name,
                    device=self.device,
                    disable_update=True,
                )
                self.model_name = model_name
                self.load_ms = (time.perf_counter() - started) * 1000
                print(
                    f"[funasr-streaming] loaded {model_name} on {self.device} in {self.load_ms:.1f} ms",
                    flush=True,
                )
                if self.device == "cpu":
                    print("[funasr-streaming] CUDA unavailable; CPU fallback may increase latency.", flush=True)
                return
            except Exception as exc:
                last_error = exc
                print(f"[funasr-streaming] load failed for {model_name}: {exc}", flush=True)

        raise RuntimeError(f"Could not load FunASR streaming model: {last_error}")

    def reset_cache(self) -> None:
        self.cache = {}

    def transcribe_pcm_chunk(
        self,
        pcm16: bytes | np.ndarray,
        *,
        is_final: bool = False,
        captured_at: float | None = None,
    ) -> FunASRStreamingResult:
        if self.model is None:
            raise RuntimeError("FunASR streaming model is not loaded.")

        audio = pcm16 if isinstance(pcm16, np.ndarray) else np.frombuffer(pcm16, dtype=np.int16)
        audio = np.asarray(audio, dtype=np.int16)
        audio_ms = int(round((len(audio) / self.config.sample_rate) * 1000)) if len(audio) else 0
        started = time.perf_counter()

        result = self._generate(audio, is_final=is_final)
        inference_ms = (time.perf_counter() - started) * 1000
        latency_ms = (time.perf_counter() - (captured_at or started)) * 1000
        rtf = (inference_ms / 1000) / max(audio_ms / 1000, 0.001)
        text = self._extract_text(result)
        event_type: Literal["partial", "final"] = "final" if is_final else "partial"

        print(
            "[funasr-streaming] "
            f"{event_type} chunk={audio_ms}ms infer={inference_ms:.1f}ms "
            f"latency={latency_ms:.1f}ms rtf={rtf:.3f} text={text!r}",
            flush=True,
        )

        if is_final:
            self.reset_cache()

        return FunASRStreamingResult(
            event_type=event_type,
            text=text,
            latency_ms=latency_ms,
            inference_ms=inference_ms,
            rtf=rtf,
            audio_ms=audio_ms,
            model_name=self.model_name,
            device=self.device,
        )

    def _generate(self, audio: np.ndarray, *, is_final: bool) -> Any:
        assert self.model is not None
        try:
            return self.model.generate(
                input=audio,
                cache=self.cache,
                is_final=is_final,
                chunk_size=self.config.chunk_size,
                encoder_chunk_look_back=self.config.encoder_chunk_look_back,
                decoder_chunk_look_back=self.config.decoder_chunk_look_back,
            )
        except (TypeError, ValueError):
            # Some FunASR builds expect float waveforms even when the capture
            # format is PCM16. Keep the external format as PCM16, then retry
            # with normalized float32 for compatibility.
            float_audio = audio.astype(np.float32) / 32768.0
            return self.model.generate(
                input=float_audio,
                cache=self.cache,
                is_final=is_final,
                chunk_size=self.config.chunk_size,
                encoder_chunk_look_back=self.config.encoder_chunk_look_back,
                decoder_chunk_look_back=self.config.decoder_chunk_look_back,
            )

    @staticmethod
    def _extract_text(result: Any) -> str:
        if isinstance(result, list):
            parts = []
            for item in result:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or ""))
                else:
                    parts.append(str(item))
            return "".join(parts).strip()
        if isinstance(result, dict):
            return str(result.get("text") or "").strip()
        return str(result or "").strip()
