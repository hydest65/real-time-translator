from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


DevicePreference = Literal["auto", "cuda", "cpu"]
TranslationEngine = Literal["argos", "marianmt", "nllb", "azure"]
AudioSource = Literal["microphone", "system"]
RecordingFormat = Literal["flac", "wav"]


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
        if name and value and not os.environ.get(name):
            os.environ[name] = value


load_dotenv_file()


@dataclass
class AppConfig:
    asr_model_size: str = "small.en"
    asr_device: DevicePreference = "cuda"
    asr_compute_type: str = "int8"
    asr_beam_size: int = 3
    asr_best_of: int = 3
    asr_patience: float = 1.2
    asr_condition_on_previous_text: bool = False
    asr_no_speech_threshold: float = 0.58
    asr_log_prob_threshold: float = -1.1
    asr_compression_ratio_threshold: float = 2.4
    asr_hallucination_silence_threshold: float = 1.2
    asr_repetition_penalty: float = 1.08
    asr_no_repeat_ngram_size: int = 3
    asr_hotwords_enabled: bool = False
    asr_use_default_hotwords: bool = False
    source_language: str = "eng_Latn"
    target_language: str = "zho_Hans"
    translation_engine: TranslationEngine = "azure"
    audio_source: AudioSource = "system"
    recording_format: RecordingFormat = "flac"
    audio_sample_rate: int = 16_000
    audio_channels: int = 1
    chunk_seconds: float = 2.0
    overlap_seconds: float = 0.3
    adaptive_chunking_enabled: bool = True
    min_chunk_seconds: float = 1.0
    chunk_flush_silence_seconds: float = 0.35
    max_subtitles: int = 1
    queue_max_size: int = 2
    vad_rms_threshold: float = 0.008
    system_vad_rms_threshold: float = 0.016
    nllb_model_name: str = "facebook/nllb-200-distilled-600M"
    marian_en_zh_model_name: str = "Helsinki-NLP/opus-mt-en-zh"
    marian_es_zh_model_name: str = "Helsinki-NLP/opus-mt-es-zh"
    azure_speech_key: str = field(default_factory=lambda: os.getenv("AZURE_SPEECH_KEY", ""))
    azure_speech_region: str = field(default_factory=lambda: os.getenv("AZURE_SPEECH_REGION", ""))
    azure_source_language: str = "en-US"
    azure_target_language: str = "zh-Hans"
    azure_phrase_list: str = field(default_factory=lambda: os.getenv("AZURE_PHRASE_LIST", ""))
    turn_detector_enabled: bool = True
    turn_pause_seconds: float = 1.6
    noise_min_words: int = 2
    noise_phrases: str = "uh,um,ah,er,mm,hmm,ok,okay,yeah,yep,nope"
    segmenter_enabled: bool = True
    segmenter_pause_seconds: float = 0.9
    segmenter_max_words: int = 28
    segmenter_max_seconds: float = 8.0
    context_buffer_enabled: bool = False
    context_buffer_min_words: int = 10
    context_buffer_max_words: int = 42
    context_buffer_max_wait_seconds: float = 0.8


config = AppConfig()
