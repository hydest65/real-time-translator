from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DevicePreference = Literal["auto", "cuda", "cpu"]
TranslationEngine = Literal["argos", "marianmt", "nllb", "azure"]
LatencyMode = Literal["realtime", "balanced"]
AudioSource = Literal["microphone", "system"]
TranslationQuality = Literal["fast", "balanced", "quality"]


@dataclass
class AppConfig:
    asr_model_size: str = "base.en"
    asr_device: DevicePreference = "cuda"
    asr_compute_type: str = "int8"
    source_language: str = "eng_Latn"
    target_language: str = "zho_Hans"
    translation_engine: TranslationEngine = "azure"
    latency_mode: LatencyMode = "realtime"
    translation_quality: TranslationQuality = "balanced"
    audio_source: AudioSource = "microphone"
    audio_sample_rate: int = 16_000
    audio_channels: int = 1
    chunk_seconds: float = 3.0
    overlap_seconds: float = 0.5
    max_subtitles: int = 1
    queue_max_size: int = 2
    buffer_max_wait_seconds: float = 4.0
    buffer_min_words: int = 8
    buffer_max_words: int = 18
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
    segmenter_pause_seconds: float = 0.9
    segmenter_max_words: int = 22
    segmenter_max_seconds: float = 10.0
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.io/v1"
    minimax_model: str = "MiniMax-M2.7"
    minimax_timeout_seconds: float = 6.0


config = AppConfig()
