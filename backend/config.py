from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


DevicePreference = Literal["auto", "cuda", "cpu"]
TranslationEngine = Literal["argos", "marianmt", "nllb", "azure"]
AudioSource = Literal["microphone", "system"]


def load_dotenv_file() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            import os

            os.environ.setdefault(name, value)


load_dotenv_file()


@dataclass
class AppConfig:
    asr_model_size: str = "medium.en"
    asr_device: DevicePreference = "cuda"
    asr_compute_type: str = "int8"
    source_language: str = "eng_Latn"
    target_language: str = "zho_Hans"
    translation_engine: TranslationEngine = "argos"
    audio_source: AudioSource = "system"
    audio_sample_rate: int = 16_000
    audio_channels: int = 1
    chunk_seconds: float = 1.5
    overlap_seconds: float = 0.25
    max_subtitles: int = 1
    queue_max_size: int = 1
    vad_rms_threshold: float = 0.008
    nllb_model_name: str = "facebook/nllb-200-distilled-600M"
    marian_en_zh_model_name: str = "Helsinki-NLP/opus-mt-en-zh"
    azure_speech_key: str = ""
    azure_speech_region: str = ""
    azure_source_language: str = "en-US"
    azure_target_language: str = "zh-Hans"
    azure_phrase_list: str = ""
    turn_detector_enabled: bool = True
    turn_pause_seconds: float = 1.6
    noise_min_words: int = 2
    noise_phrases: str = "uh,um,ah,er,mm,hmm,ok,okay,yeah,yep,nope"
    segmenter_enabled: bool = True
    segmenter_pause_seconds: float = 0.8
    segmenter_max_words: int = 24
    segmenter_max_seconds: float = 6.0


config = AppConfig()
