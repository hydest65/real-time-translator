from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.terminology import build_hotword_text, build_meeting_prompt

DEFAULT_MODEL_CACHE = PROJECT_ROOT / ".model-cache"
DEFAULT_HF_CACHE = DEFAULT_MODEL_CACHE / "huggingface"
DEFAULT_MODEL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MODELSCOPE_CACHE", str(DEFAULT_MODEL_CACHE))
os.environ.setdefault("HF_HOME", str(DEFAULT_HF_CACHE))
os.environ.setdefault("HF_HUB_CACHE", str(DEFAULT_HF_CACHE / "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE", str(DEFAULT_HF_CACHE / "transformers"))


def load_dotenv_file() -> None:
    env_path = PROJECT_ROOT / ".env"
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


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


FUNASR_MODEL_BY_QUALITY = {
    "fast": "iic/SenseVoiceSmall",
    "balanced": "paraformer-zh",
    "high": "paraformer-zh",
}

FUNASR_LOCAL_MODEL_DIRS = {
    "iic/SenseVoiceSmall": DEFAULT_MODEL_CACHE / "models" / "iic" / "SenseVoiceSmall",
    "paraformer-zh": DEFAULT_MODEL_CACHE / "models" / "iic" / "speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "fsmn-vad": DEFAULT_MODEL_CACHE / "models" / "iic" / "speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "ct-punc": DEFAULT_MODEL_CACHE / "models" / "iic" / "punc_ct-transformer_cn-en-common-vocab471067-large",
}


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str = "Speaker ?"


@dataclass
class SpeakerSegment:
    start: float
    end: float
    speaker: str


@dataclass
class TopicSection:
    title: str
    start: float
    end: float
    bullets: list[str]


QUALITY_PRESETS = {
    "fast": {
        "model": "base.en",
        "compute_type": "int8",
        "beam_size": 1,
        "best_of": 1,
        "patience": 1.0,
    },
    "balanced": {
        "model": "small.en",
        "compute_type": "int8",
        "beam_size": 2,
        "best_of": 2,
        "patience": 1.0,
    },
    "high": {
        "model": "medium.en",
        "compute_type": "int8",
        "beam_size": 3,
        "best_of": 3,
        "patience": 1.2,
    },
}


def format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def transcribe_audio(args: argparse.Namespace) -> list[TranscriptSegment]:
    if args.asr_engine == "azure-batch":
        return transcribe_audio_azure_batch(args)
    if args.asr_engine == "azure-fast":
        return transcribe_audio_azure_fast(args)
    if args.asr_engine == "funasr":
        return transcribe_audio_funasr(args)
    return transcribe_audio_faster_whisper(args)


def transcribe_audio_azure_fast(args: argparse.Namespace) -> list[TranscriptSegment]:
    key = os.getenv("AZURE_SPEECH_KEY", "").strip()
    region = os.getenv("AZURE_SPEECH_REGION", "").strip()
    endpoint = (
        os.getenv("AZURE_FAST_TRANSCRIPTION_ENDPOINT", "").strip()
        or os.getenv("AZURE_SPEECH_ENDPOINT", "").strip()
    )
    if not endpoint:
        if not region:
            raise SystemExit("Set AZURE_SPEECH_REGION or AZURE_FAST_TRANSCRIPTION_ENDPOINT for Azure Fast Transcription.")
        endpoint = f"https://{region}.api.cognitive.microsoft.com"
    if not key:
        raise SystemExit("Set AZURE_SPEECH_KEY for Azure Fast Transcription.")

    api_version = os.getenv("AZURE_FAST_TRANSCRIPTION_API_VERSION", "2024-11-15").strip() or "2024-11-15"
    locale = azure_fast_locale(args.language)
    max_speakers = max(2, min(35, int(args.azure_fast_max_speakers or 5)))
    use_locales = env_flag("AZURE_FAST_TRANSCRIPTION_USE_LOCALES", False)
    definition = {}
    if use_locales:
        definition["locales"] = [locale]
    if args.azure_fast_diarization:
        definition["diarization"] = {
            "enabled": True,
            "maxSpeakers": max_speakers,
        }
    url = f"{endpoint.rstrip('/')}/speechtotext/transcriptions:transcribe?api-version={api_version}"
    locale_message = locale if use_locales else "auto"
    print(f"Using Azure Fast Transcription: locale={locale_message}, diarization={bool(args.azure_fast_diarization)}, maxSpeakers={max_speakers}")
    try:
        response = post_azure_fast_transcription(url, key, args.audio, definition, args.azure_fast_timeout_seconds)
    except SystemExit as exc:
        detail = str(exc)
        can_fallback = (
            env_flag("AZURE_FAST_SDK_FALLBACK", True)
            and (
                "InvalidModel" in detail
                or "InvalidLocale" in detail
                or "Diarization is currently not supported" in detail
            )
        )
        if not can_fallback:
            raise
        print("Azure Fast is unavailable for this resource; falling back to Azure Speech SDK file transcription.")
        return transcribe_audio_azure_sdk(args)
    return normalize_azure_fast_output(response)


def azure_fast_locale(language: str) -> str:
    language = (language or "").strip()
    aliases = {
        "": "en-US",
        "auto": "en-US",
        "en": "en-US",
        "eng": "en-US",
        "english": "en-US",
        "zh": "zh-CN",
        "zho": "zh-CN",
        "chinese": "zh-CN",
    }
    return aliases.get(language.lower(), language)


def post_azure_fast_transcription(
    url: str,
    key: str,
    audio: Path,
    definition: dict[str, object],
    timeout_seconds: int,
) -> dict[str, object]:
    boundary = "----SubtitleStudioAzureFastBoundary"
    audio_bytes = audio.read_bytes()
    definition_json = json.dumps(definition, ensure_ascii=False)
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            b'Content-Disposition: form-data; name="definition"\r\n',
            b"Content-Type: application/json\r\n\r\n",
            definition_json.encode("utf-8"),
            b"\r\n",
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="audio"; filename="{audio.name}"\r\n'.encode("utf-8"),
            b"Content-Type: audio/wav\r\n\r\n",
            audio_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Ocp-Apim-Subscription-Key": key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(30, timeout_seconds)) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Azure Fast Transcription failed: HTTP {exc.code} {detail[:1200]}") from exc
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Azure Fast Transcription failed: {exc}") from exc


def normalize_azure_fast_output(output: dict[str, object]) -> list[TranscriptSegment]:
    phrases = output.get("phrases")
    if not isinstance(phrases, list):
        return []
    segments: list[TranscriptSegment] = []
    for phrase in phrases:
        if not isinstance(phrase, dict):
            continue
        text = str(phrase.get("text") or "").strip()
        if not text:
            continue
        offset_ms = phrase.get("offsetMilliseconds", phrase.get("offset", 0))
        duration_ms = phrase.get("durationMilliseconds", phrase.get("duration", 0))
        try:
            start = float(offset_ms or 0) / 1000.0
            duration = float(duration_ms or 0) / 1000.0
        except (TypeError, ValueError):
            start = 0.0
            duration = 0.0
        speaker = phrase.get("speaker")
        speaker_label = "Speaker ?"
        if speaker is not None:
            try:
                speaker_label = f"SPEAKER_{int(speaker):02d}"
            except (TypeError, ValueError):
                speaker_label = f"SPEAKER_{speaker}"
        segments.append(
            TranscriptSegment(
                start=start,
                end=start + max(0.0, duration),
                text=text,
                speaker=speaker_label,
            )
        )
    return segments


def transcribe_audio_azure_sdk(args: argparse.Namespace) -> list[TranscriptSegment]:
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError as exc:
        raise SystemExit("Install azure-cognitiveservices-speech to use Azure Speech file transcription.") from exc

    key = os.getenv("AZURE_SPEECH_KEY", "").strip()
    region = os.getenv("AZURE_SPEECH_REGION", "").strip()
    if not key:
        raise SystemExit("Set AZURE_SPEECH_KEY for Azure Speech file transcription.")
    if not region:
        raise SystemExit("Set AZURE_SPEECH_REGION for Azure Speech file transcription.")

    locale = azure_fast_locale(args.language)
    print(f"Using Azure Speech SDK file transcription: locale={locale}, speakerSeparation=False")
    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_config.speech_recognition_language = locale
    speech_config.output_format = speechsdk.OutputFormat.Detailed
    audio_config = speechsdk.audio.AudioConfig(filename=str(args.audio))
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

    done = threading.Event()
    errors: list[str] = []
    segments: list[TranscriptSegment] = []

    def on_recognized(event) -> None:
        result = event.result
        if result.reason != speechsdk.ResultReason.RecognizedSpeech:
            return
        text = (result.text or "").strip()
        if not text:
            return
        start = float(getattr(result, "offset", 0) or 0) / 10_000_000.0
        duration = float(getattr(result, "duration", 0) or 0) / 10_000_000.0
        segments.append(
            TranscriptSegment(
                start=start,
                end=start + max(0.0, duration),
                text=text,
                speaker="Speaker ?",
            )
        )

    def on_canceled(event) -> None:
        details = getattr(event, "error_details", "") or ""
        if details:
            errors.append(str(details))
        done.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.canceled.connect(on_canceled)
    recognizer.session_stopped.connect(lambda _event: done.set())

    recognizer.start_continuous_recognition_async().get()
    timeout_seconds = max(60, int(args.azure_fast_timeout_seconds or 600))
    if not done.wait(timeout_seconds):
        recognizer.stop_continuous_recognition_async().get()
        raise SystemExit("Azure Speech file transcription timed out.")
    recognizer.stop_continuous_recognition_async().get()
    if errors and not segments:
        raise SystemExit(f"Azure Speech file transcription failed: {errors[0]}")
    return segments


def transcribe_audio_azure_batch(args: argparse.Namespace) -> list[TranscriptSegment]:
    key = os.getenv("AZURE_SPEECH_KEY", "").strip()
    region = os.getenv("AZURE_SPEECH_REGION", "").strip()
    endpoint = os.getenv("AZURE_BATCH_TRANSCRIPTION_ENDPOINT", "").strip()
    container_sas = os.getenv("AZURE_BATCH_CONTAINER_SAS_URL", "").strip()
    if not key:
        raise SystemExit("Set AZURE_SPEECH_KEY for Azure Batch Transcription.")
    if not endpoint:
        if not region:
            raise SystemExit("Set AZURE_SPEECH_REGION or AZURE_BATCH_TRANSCRIPTION_ENDPOINT for Azure Batch Transcription.")
        endpoint = f"https://{region}.api.cognitive.microsoft.com"
    if not container_sas:
        raise SystemExit("Set AZURE_BATCH_CONTAINER_SAS_URL to an Azure Blob container SAS URL for Batch Transcription.")

    locale = azure_fast_locale(args.language)
    max_speakers = max(2, min(35, int(args.azure_batch_max_speakers or 5)))
    print("Azure Batch: uploading recording")
    audio_url = upload_audio_to_blob_container(args.audio, container_sas)
    print(f"Using Azure Batch Transcription: locale={locale}, diarization=True, maxSpeakers={max_speakers}")
    print("Azure Batch: submitting job")
    job = submit_azure_batch_job(endpoint, key, audio_url, args.audio.name, locale, max_speakers, args.azure_batch_ttl_hours)
    print("Azure Batch: waiting for transcription")
    result = wait_for_azure_batch_job(job, key, args.azure_batch_poll_seconds, args.azure_batch_timeout_seconds)
    print("Azure Batch: downloading result")
    return normalize_azure_batch_output(result)


def upload_audio_to_blob_container(audio: Path, container_sas_url: str) -> str:
    parsed = urllib.parse.urlsplit(container_sas_url)
    if not parsed.scheme or not parsed.netloc or not parsed.query:
        raise SystemExit("AZURE_BATCH_CONTAINER_SAS_URL must be a full container SAS URL.")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", audio.name)
    blob_name = f"subtitle-studio/{int(time.time())}-{uuid.uuid4().hex[:8]}-{safe_name}"
    container_path = parsed.path.rstrip("/")
    blob_path = f"{container_path}/{urllib.parse.quote(blob_name)}"
    upload_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, blob_path, parsed.query, ""))
    request = urllib.request.Request(
        upload_url,
        data=audio.read_bytes(),
        headers={
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": "audio/wav",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=300):
            pass
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Azure Blob upload failed: HTTP {exc.code} {detail[:1200]}") from exc
    except (OSError, TimeoutError) as exc:
        raise SystemExit(f"Azure Blob upload failed: {exc}") from exc
    return upload_url


def submit_azure_batch_job(
    endpoint: str,
    key: str,
    audio_url: str,
    audio_name: str,
    locale: str,
    max_speakers: int,
    ttl_hours: int,
) -> dict[str, object]:
    api_version = os.getenv("AZURE_BATCH_TRANSCRIPTION_API_VERSION", "v3.2").strip() or "v3.2"
    url = f"{endpoint.rstrip('/')}/speechtotext/{api_version}/transcriptions"
    payload = {
        "contentUrls": [audio_url],
        "locale": locale,
        "displayName": f"Subtitle Studio {audio_name} {int(time.time())}",
        "properties": {
            "diarizationEnabled": True,
            "diarization": {
                "speakers": {
                    "minCount": 1,
                    "maxCount": max_speakers,
                }
            },
            "wordLevelTimestampsEnabled": False,
            "displayFormWordLevelTimestampsEnabled": True,
            "punctuationMode": "DictatedAndAutomatic",
            "profanityFilterMode": "None",
            "timeToLiveHours": max(6, min(744, int(ttl_hours or 48))),
        },
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Azure Batch submit failed: HTTP {exc.code} {detail[:1200]}") from exc
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Azure Batch submit failed: {exc}") from exc


def wait_for_azure_batch_job(
    job: dict[str, object],
    key: str,
    poll_seconds: int,
    timeout_seconds: int,
) -> dict[str, object]:
    self_url = str(job.get("self") or "")
    if not self_url:
        raise SystemExit("Azure Batch submit response did not include a job URL.")
    headers = {"Ocp-Apim-Subscription-Key": key}
    deadline = time.time() + max(60, timeout_seconds)
    poll_interval = max(5, min(60, int(poll_seconds or 10)))
    while time.time() < deadline:
        status_job = get_json(self_url, headers)
        status = str(status_job.get("status") or "")
        print(f"Azure Batch status: {status}")
        if status.lower() == "succeeded":
            files_url = str((status_job.get("links") or {}).get("files") or "")
            return download_azure_batch_transcription(files_url, headers)
        if status.lower() in {"failed", "failedvalidation"}:
            raise SystemExit(f"Azure Batch transcription failed: {json.dumps(status_job)[:1200]}")
        time.sleep(poll_interval)
    raise SystemExit("Azure Batch transcription timed out.")


def get_json(url: str, headers: dict[str, str]) -> dict[str, object]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def download_azure_batch_transcription(files_url: str, headers: dict[str, str]) -> dict[str, object]:
    if not files_url:
        raise SystemExit("Azure Batch job did not include a files URL.")
    files = get_json(files_url, headers)
    values = files.get("values")
    if not isinstance(values, list):
        raise SystemExit("Azure Batch files response did not include values.")
    for item in values:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").lower()
        name = str(item.get("name") or "").lower()
        content_url = str((item.get("links") or {}).get("contentUrl") or "")
        if content_url and (kind == "transcription" or name.endswith(".json")):
            return get_json(content_url, {})
    raise SystemExit("Azure Batch transcription result file was not found.")


def normalize_azure_batch_output(output: dict[str, object]) -> list[TranscriptSegment]:
    phrases = output.get("recognizedPhrases") or output.get("phrases")
    if not isinstance(phrases, list):
        return []
    segments: list[TranscriptSegment] = []
    for phrase in phrases:
        if not isinstance(phrase, dict):
            continue
        text = azure_batch_phrase_text(phrase)
        if not text:
            continue
        start = azure_batch_seconds(phrase.get("offsetInTicks", phrase.get("offset", phrase.get("offsetMilliseconds", 0))))
        duration = azure_batch_seconds(phrase.get("durationInTicks", phrase.get("duration", phrase.get("durationMilliseconds", 0))))
        speaker = phrase.get("speaker")
        speaker_label = "Speaker ?"
        if speaker is not None:
            try:
                speaker_label = f"SPEAKER_{int(speaker):02d}"
            except (TypeError, ValueError):
                speaker_label = f"SPEAKER_{speaker}"
        segments.append(TranscriptSegment(start=start, end=start + max(0.0, duration), text=text, speaker=speaker_label))
    return sorted(segments, key=lambda item: (item.start, item.end))


def azure_batch_phrase_text(phrase: dict[str, object]) -> str:
    nbest = phrase.get("nBest")
    if isinstance(nbest, list) and nbest:
        first = nbest[0]
        if isinstance(first, dict):
            return str(first.get("display") or first.get("displayText") or first.get("lexical") or "").strip()
    return str(phrase.get("text") or phrase.get("display") or "").strip()


def azure_batch_seconds(value: object) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if number > 100000:
        return number / 10_000_000.0
    if number > 1000:
        return number / 1000.0
    return number


def transcribe_audio_faster_whisper(args: argparse.Namespace) -> list[TranscriptSegment]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "faster-whisper is not installed. Run: python -m pip install -r backend\\requirements-local.txt"
        ) from exc

    meeting_prompt = build_meeting_prompt(limit=100)
    hotword_text = build_hotword_text(limit=100)
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    duration = wav_duration_seconds(args.audio)
    chunk_seconds = max(0, int(args.asr_chunk_seconds or 0))
    if chunk_seconds and duration > chunk_seconds * 1.2:
        return transcribe_audio_faster_whisper_chunked(model, args, chunk_seconds, meeting_prompt, hotword_text)
    return transcribe_faster_whisper_path(model, args, args.audio, 0.0, meeting_prompt, hotword_text)


def transcribe_audio_faster_whisper_chunked(
    model: object,
    args: argparse.Namespace,
    chunk_seconds: int,
    meeting_prompt: str,
    hotword_text: str,
) -> list[TranscriptSegment]:
    with tempfile.TemporaryDirectory(prefix="meeting-asr-", dir=str(DEFAULT_MODEL_CACHE)) as temp_dir_name:
        chunks = build_wav_chunks(args.audio, Path(temp_dir_name), chunk_seconds)
        if not chunks:
            return transcribe_faster_whisper_path(model, args, args.audio, 0.0, meeting_prompt, hotword_text)
        print(f"Using chunked ASR: {len(chunks)} chunk(s), {chunk_seconds}s each")
        results: list[TranscriptSegment] = []
        for index, (chunk_path, offset_seconds) in enumerate(chunks, start=1):
            print(f"ASR chunk {index}/{len(chunks)} at {format_time(offset_seconds)}")
            results.extend(
                transcribe_faster_whisper_path(
                    model,
                    args,
                    chunk_path,
                    offset_seconds,
                    meeting_prompt,
                    hotword_text,
                )
            )
        return sorted(results, key=lambda item: (item.start, item.end))


def transcribe_faster_whisper_path(
    model: object,
    args: argparse.Namespace,
    audio_path: Path,
    offset_seconds: float,
    meeting_prompt: str,
    hotword_text: str,
) -> list[TranscriptSegment]:
    segments, _ = model.transcribe(
        str(audio_path),
        language=args.language,
        vad_filter=True,
        beam_size=args.beam_size,
        best_of=args.best_of,
        patience=args.patience,
        temperature=0,
        condition_on_previous_text=True,
        initial_prompt=meeting_prompt if args.language == "en" else None,
        hotwords=hotword_text if args.language == "en" else None,
        vad_parameters={
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 250,
        },
    )

    results: list[TranscriptSegment] = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            results.append(
                TranscriptSegment(
                    start=offset_seconds + float(segment.start),
                    end=offset_seconds + float(segment.end),
                    text=text,
                )
            )
    return results


def wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            if frame_rate:
                return wav_file.getnframes() / frame_rate
    except (OSError, wave.Error):
        return 0.0
    return 0.0


def build_wav_chunks(audio: Path, temp_dir: Path, chunk_seconds: int) -> list[tuple[Path, float]]:
    if chunk_seconds <= 0:
        return []
    chunks: list[tuple[Path, float]] = []
    try:
        with wave.open(str(audio), "rb") as source:
            params = source.getparams()
            frame_rate = source.getframerate()
            total_frames = source.getnframes()
            chunk_frames = max(1, int(chunk_seconds * frame_rate))
            for chunk_index, start_frame in enumerate(range(0, total_frames, chunk_frames), start=1):
                source.setpos(start_frame)
                frames_to_read = min(chunk_frames, total_frames - start_frame)
                frames = source.readframes(frames_to_read)
                if not frames:
                    continue
                chunk_path = temp_dir / f"{audio.stem}.chunk-{chunk_index:04d}.wav"
                with wave.open(str(chunk_path), "wb") as target:
                    target.setparams(params)
                    target.writeframes(frames)
                chunks.append((chunk_path, start_frame / frame_rate if frame_rate else 0.0))
    except (OSError, wave.Error):
        return []
    return chunks


def transcribe_audio_funasr(args: argparse.Namespace) -> list[TranscriptSegment]:
    try:
        from funasr import AutoModel
        import torch
    except ImportError as exc:
        raise SystemExit(
            "FunASR is not installed. Install it separately first: python -m pip install funasr"
        ) from exc

    model_name = resolve_funasr_model(args.funasr_model or FUNASR_MODEL_BY_QUALITY[args.quality])
    vad_model = args.funasr_vad_model or "fsmn-vad"
    punc_model = args.funasr_punc_model or "ct-punc"
    device = args.device
    if device == "auto" or (device == "cuda" and not torch.cuda.is_available()):
        device = "cpu"
    model = AutoModel(
        model=model_name,
        vad_model=vad_model,
        punc_model=punc_model,
        device=device,
        disable_update=True,
    )
    generate_args = {
        "input": str(args.audio),
        "language": "auto" if args.language == "auto" else args.language,
        "use_itn": True,
        "batch_size_s": args.funasr_batch_size,
    }
    hotword_text = build_hotword_text(limit=100)
    if hotword_text:
        generate_args["hotword"] = hotword_text
    output = model.generate(**generate_args)
    return normalize_funasr_output(output)


def resolve_funasr_model(model_name: str) -> str:
    local_dir = FUNASR_LOCAL_MODEL_DIRS.get(model_name)
    if local_dir is not None and local_dir.exists():
        return str(local_dir)
    return model_name


def normalize_funasr_output(output: object) -> list[TranscriptSegment]:
    if isinstance(output, dict):
        records = [output]
    elif isinstance(output, list):
        records = output
    else:
        records = []

    segments: list[TranscriptSegment] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        sentence_info = record.get("sentence_info")
        if isinstance(sentence_info, list):
            for sentence in sentence_info:
                if not isinstance(sentence, dict):
                    continue
                text = str(sentence.get("text") or "").strip()
                if not text:
                    continue
                start = float(sentence.get("start") or 0) / 1000.0
                end = float(sentence.get("end") or sentence.get("timestamp") or 0) / 1000.0
                if end <= start:
                    end = start
                segments.append(TranscriptSegment(start=start, end=end, text=text))
            continue

        text = str(record.get("text") or "").strip()
        if text:
            segments.append(TranscriptSegment(start=0.0, end=0.0, text=text))
    return segments


def describe_asr_model(args: argparse.Namespace) -> str:
    if args.asr_engine == "faster-whisper":
        return args.model
    if args.asr_engine == "funasr":
        return args.funasr_model or FUNASR_MODEL_BY_QUALITY[args.quality]
    return args.asr_engine


def diarize_audio(args: argparse.Namespace) -> list[SpeakerSegment]:
    token = args.hf_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    if not token:
        raise SystemExit("Set HF_TOKEN first, or run without --diarize.")

    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise SystemExit(
            "pyannote.audio is not installed. Install it in a separate environment, or run without --diarize."
        ) from exc

    try:
        pipeline = Pipeline.from_pretrained(args.diarization_model, token=token)
    except TypeError:
        pipeline = Pipeline.from_pretrained(args.diarization_model, use_auth_token=token)

    try:
        import numpy as np
        import torch
        from scipy.io import wavfile
    except ImportError:
        diarization = pipeline(str(args.audio))
    else:
        sample_rate, samples = wavfile.read(str(args.audio))
        samples = np.asarray(samples)
        if samples.ndim == 1:
            samples = samples[None, :]
        else:
            samples = samples.T
        if np.issubdtype(samples.dtype, np.integer):
            samples = samples.astype("float32") / float(np.iinfo(samples.dtype).max)
        else:
            samples = samples.astype("float32")
        waveform = torch.from_numpy(samples)
        diarization = pipeline({"waveform": waveform, "sample_rate": int(sample_rate)})
    if hasattr(diarization, "speaker_diarization"):
        diarization = diarization.speaker_diarization
    speakers: list[SpeakerSegment] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        speakers.append(
            SpeakerSegment(
                start=float(turn.start),
                end=float(turn.end),
                speaker=str(speaker),
            )
        )
    return speakers


def assign_speakers(
    transcript: list[TranscriptSegment],
    speakers: list[SpeakerSegment],
) -> list[TranscriptSegment]:
    if not speakers:
        return transcript

    for item in transcript:
        scores: dict[str, float] = {}
        for speaker in speakers:
            overlap = max(0.0, min(item.end, speaker.end) - max(item.start, speaker.start))
            if overlap > 0:
                scores[speaker.speaker] = scores.get(speaker.speaker, 0.0) + overlap
        if scores:
            item.speaker = max(scores.items(), key=lambda pair: pair[1])[0]
    return transcript


def assign_fallback_turns(transcript: list[TranscriptSegment], pause_seconds: float = 1.8) -> list[TranscriptSegment]:
    if not transcript:
        return transcript
    if any(item.speaker != "Speaker ?" for item in transcript):
        return transcript

    turn_index = 1
    previous_end = transcript[0].end
    for index, item in enumerate(transcript):
        if index > 0 and item.start - previous_end >= pause_seconds:
            turn_index += 1
        item.speaker = f"Turn {turn_index:02d}"
        previous_end = max(previous_end, item.end)
    return transcript


def transcript_markdown(audio: Path, transcript: list[TranscriptSegment]) -> str:
    lines = [
        "# Meeting Transcript",
        "",
        f"- Audio: `{audio.name}`",
        "",
        "Speaker labels are anonymous clusters when diarization is enabled. They are not verified real names.",
        "",
        "## Full Transcript",
        "",
    ]
    for item in transcript:
        lines.append(f"### {item.speaker} · {format_time(item.start)}-{format_time(item.end)}")
        lines.append("")
        lines.append(clean_sentence(item.text) or item.text)
        lines.append("")
    return "\n".join(lines)


def clean_sentence(text: str) -> str:
    cleaned = re.sub(r"<\s*\|\s*[^>]+?\s*\|\s*>", " ", text)
    replacements = {
        "S pe ech": "Speech",
        "S peech": "Speech",
        "withi tn": "within",
        "P hili ppi nes": "Philippines",
        "H ungar y": "Hungary",
        "C hina": "China",
        "A sia": "Asia",
        "B eijing": "Beijing",
        "S atu rda y": "Saturday",
    }
    for bad, good in replacements.items():
        cleaned = cleaned.replace(bad, good)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"([,.;:!?]){2,}", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -\t\r\n,.;")


def is_chinese_language(language: str | None) -> bool:
    return str(language or "").strip().lower().startswith("zh")


def readable_unit_count(text: str) -> int:
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    if cjk_count >= 6:
        return cjk_count
    return len(str(text or "").split())


def split_readable_sentences(text: str) -> list[str]:
    normalized = clean_sentence(text)
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+", normalized)
    return [clean_sentence(part) for part in parts if readable_unit_count(clean_sentence(part)) >= 8]


def transcript_sentences(transcript: list[TranscriptSegment]) -> list[tuple[TranscriptSegment, str]]:
    results: list[tuple[TranscriptSegment, str]] = []
    for item in transcript:
        for sentence in split_readable_sentences(item.text):
            results.append((item, sentence))
    return results


def pick_items(
    sentences: list[tuple[TranscriptSegment, str]],
    keywords: list[str],
    limit: int,
    min_length: int = 12,
) -> list[tuple[TranscriptSegment, str]]:
    picked: list[tuple[TranscriptSegment, str]] = []
    seen: set[str] = set()
    for item, sentence in sentences:
        lowered = sentence.lower()
        if len(sentence) < min_length or lowered in seen:
            continue
        if any(keyword in lowered for keyword in keywords):
            picked.append((item, sentence))
            seen.add(lowered)
        if len(picked) >= limit:
            break
    return picked


def discussion_blocks(transcript: list[TranscriptSegment], block_seconds: int = 300) -> list[tuple[float, float, str]]:
    blocks: list[tuple[float, float, list[str]]] = []
    current_start = 0.0
    current_end = 0.0
    current_text: list[str] = []
    for item in transcript:
        text = clean_sentence(item.text)
        if not text:
            continue
        if not current_text:
            current_start = item.start
        if current_text and item.start - current_start >= block_seconds:
            blocks.append((current_start, current_end, current_text))
            current_start = item.start
            current_text = []
        current_end = item.end
        current_text.append(text)
    if current_text:
        blocks.append((current_start, current_end, current_text))

    readable: list[tuple[float, float, str]] = []
    for start, end, texts in blocks:
        joined = clean_sentence(" ".join(texts))
        if len(joined) > 520:
            joined = joined[:520].rsplit(" ", 1)[0].rstrip(" ,.;") + "..."
        readable.append((start, end, joined))
    return readable


def speaker_sections(transcript: list[TranscriptSegment]) -> dict[str, list[TranscriptSegment]]:
    sections: dict[str, list[TranscriptSegment]] = {}
    for item in transcript:
        if clean_sentence(item.text):
            sections.setdefault(item.speaker or "Speaker ?", []).append(item)
    return sections


def truncate_chinese_text(text: str, max_units: int = 90) -> str:
    cleaned = clean_sentence(text)
    if readable_unit_count(cleaned) <= max_units:
        return cleaned
    if len(re.findall(r"[\u4e00-\u9fff]", cleaned)) >= 6:
        return cleaned[:max_units].rstrip("，。；、,. ") + "。"
    words = cleaned.split()
    return " ".join(words[:max_units]).rstrip(" ,.;") + "."


def chinese_summary_points(paragraphs: list[tuple[float, float, str]], limit: int = 5) -> list[str]:
    points: list[str] = []
    seen: set[str] = set()
    for _, _, paragraph in paragraphs:
        candidate = (split_readable_sentences(paragraph) or [paragraph])[0]
        candidate = truncate_chinese_text(candidate, 88)
        key = re.sub(r"\s+", "", candidate)
        if readable_unit_count(candidate) >= 8 and key not in seen:
            points.append(candidate)
            seen.add(key)
        if len(points) >= limit:
            break
    return points


def chinese_topic_sections(paragraphs: list[tuple[float, float, str]], limit: int = 8) -> list[TopicSection]:
    sections: list[TopicSection] = []
    for index, (start, end, paragraph) in enumerate(paragraphs[:limit], start=1):
        bullets = [
            truncate_chinese_text(sentence, 70)
            for sentence in split_readable_sentences(paragraph)[:3]
            if readable_unit_count(sentence) >= 8
        ]
        if not bullets and paragraph:
            bullets = [truncate_chinese_text(paragraph, 70)]
        sections.append(
            TopicSection(
                title=f"议题 {index}",
                start=start,
                end=end,
                bullets=bullets,
            )
        )
    return sections


def chinese_minutes_markdown(audio: Path, transcript: list[TranscriptSegment]) -> str:
    cleaned_transcript = [
        TranscriptSegment(
            start=item.start,
            end=item.end,
            text=clean_sentence(item.text),
            speaker=item.speaker,
        )
        for item in transcript
    ]
    usable = [item for item in cleaned_transcript if readable_unit_count(item.text) >= 6]
    sentences = transcript_sentences(usable)
    paragraphs = build_natural_paragraphs(usable, max_words=160, max_seconds=100)
    total_start = min((item.start for item in usable), default=0.0)
    total_end = max((item.end for item in usable), default=0.0)
    sections = speaker_sections(usable)
    speakers = sorted(sections)
    summary_points = chinese_summary_points(paragraphs)
    topics = chinese_topic_sections(paragraphs)
    decisions = extract_chinese_decisions(sentences)
    actions = extract_chinese_action_items(sentences)
    risks = extract_chinese_risks(sentences)
    is_substantive = sum(readable_unit_count(item.text) for item in usable) >= 80 and len(sentences) >= 3

    lines = [
        "# 中文会议纪要",
        "",
        f"- 音频：`{audio.name}`",
        f"- 时长：{format_time(total_start)}-{format_time(total_end)}",
        f"- 说话人：{', '.join(speakers) if speakers else '未区分'}",
        "- 来源：会后 ASR 转写，正式分享前建议人工复核。",
        "",
        "## 1. 摘要",
        "",
    ]
    if not is_substantive:
        lines.append("- 录音内容较短、较嘈杂或转写内容不足，暂时无法可靠生成完整会议纪要。")
    elif summary_points:
        for point in summary_points:
            lines.append(f"- {point}")
    else:
        lines.append("- 未检测到足够清晰的摘要内容。")

    lines.extend(["", "## 2. 议题时间线", ""])
    if topics:
        for topic in topics:
            lines.append(f"### {format_time(topic.start)}-{format_time(topic.end)} | {topic.title}")
            for bullet in topic.bullets:
                lines.append(f"- {bullet}")
            lines.append("")
    else:
        lines.append("- 未检测到可分段的议题内容。")

    lines.extend(["", "## 3. 关键讨论", ""])
    if paragraphs:
        for start, end, paragraph in paragraphs:
            lines.append(f"### {format_time(start)}-{format_time(end)}")
            lines.append(truncate_chinese_text(paragraph, 180))
            lines.append("")
    else:
        lines.append("- 未检测到可读讨论段落。")

    lines.extend(["", "## 4. 决议", ""])
    if decisions:
        for item, sentence in decisions:
            lines.append(f"- [{item.speaker} {format_time(item.start)}] {sentence}")
    else:
        lines.append("- 未检测到明确决议。")

    lines.extend(["", "## 5. 行动项", ""])
    if actions:
        for item, sentence in actions:
            lines.append(f"- [ ] [{item.speaker} {format_time(item.start)}] {sentence}")
    else:
        lines.append("- 未检测到明确行动项。")

    lines.extend(["", "## 6. 风险与待确认问题", ""])
    if risks:
        for item, sentence in risks:
            lines.append(f"- [{item.speaker} {format_time(item.start)}] {sentence}")
    else:
        lines.append("- 未检测到明确风险或待确认问题。")

    lines.extend(["", "## 7. 说话人记录", ""])
    if sections:
        for speaker, items in sections.items():
            lines.append(f"### {speaker}")
            for item in items[:18]:
                lines.append(f"- {format_time(item.start)} {clean_sentence(item.text)}")
            if len(items) > 18:
                lines.append(f"- 另有 {len(items) - 18} 条记录见完整转写。")
            lines.append("")
    else:
        lines.append("- 当前录音未启用说话人分离。")

    lines.extend(["", "## 8. 完整转写", ""])
    for item in usable:
        lines.append(f"- {format_time(item.start)}-{format_time(item.end)} `{item.speaker}` {item.text}")
    return "\n".join(lines)


def minutes_markdown(audio: Path, transcript: list[TranscriptSegment], notes_language: str = "en") -> str:
    if is_chinese_language(notes_language):
        return chinese_minutes_markdown(audio, transcript)
    cleaned_transcript = [
        TranscriptSegment(
            start=item.start,
            end=item.end,
            text=clean_sentence(item.text),
            speaker=item.speaker,
        )
        for item in transcript
    ]
    usable = [item for item in cleaned_transcript if len(item.text.strip()) >= 8]
    sentences = transcript_sentences(usable)
    total_start = min((item.start for item in usable), default=0.0)
    total_end = max((item.end for item in usable), default=0.0)
    sections = speaker_sections(usable)
    speakers = sorted(sections)
    highlights = [pair for pair in sentences if len(pair[1]) >= 35][:10]
    decisions = pick_items(
        sentences,
        ["decide", "decided", "agreed", "confirmed", "approved", "final", "决定", "确认", "同意", "批准", "采用"],
        8,
    )
    actions = pick_items(
        sentences,
        [
            "need", "needs", "should", "must", "follow up", "action", "todo", "next",
            "confirm", "owner", "deadline", "send", "check", "review",
            "需要", "应该", "必须", "跟进", "确认", "负责人", "截止", "下一步", "检查", "发送", "复核",
        ],
        12,
    )
    risks = pick_items(
        sentences,
        ["risk", "issue", "problem", "blocked", "concern", "unclear", "pending", "delay", "风险", "问题", "阻塞", "待定", "延迟"],
        8,
    )
    readable_word_count = sum(len(sentence.split()) for _, sentence in sentences)
    is_substantive = readable_word_count >= 80 and len(sentences) >= 3

    lines = [
        "# Meeting Notes",
        "",
        "This document is generated from post-meeting transcription. It contains the English master notes first, followed by a Chinese reading version.",
        "",
        "## English Version",
        "",
        f"- Audio: `{audio.name}`",
        f"- Duration: {format_time(total_start)}-{format_time(total_end)}",
        f"- Speakers: {', '.join(speakers) if speakers else 'Not separated'}",
        "- Source: post-meeting ASR transcript. Review before sharing.",
        "",
        "## 1. Quick Summary",
        "",
    ]
    if not is_substantive:
        lines.append("- The recording did not contain enough clean meeting discussion to generate reliable professional minutes.")
        lines.append("- The readable transcript is kept below for review. Please use a clearer or longer recording for decisions and action items.")
    elif highlights:
        for _, sentence in highlights[:5]:
            lines.append(f"- {sentence}")
    else:
        lines.append("- No substantial transcript text was captured yet.")

    lines.extend(["", "## 2. Key Discussion", ""])
    blocks = discussion_blocks(usable)
    if blocks:
        for start, end, text in blocks:
            lines.append(f"### {format_time(start)}-{format_time(end)}")
            lines.append(text)
            lines.append("")
    else:
        lines.append("- No readable discussion blocks were detected.")

    lines.extend(["", "## 3. Decisions", ""])
    if not is_substantive:
        lines.append("- Not enough clean meeting content to infer decisions safely.")
    elif decisions:
        for item, sentence in decisions:
            lines.append(f"- [{item.speaker} {format_time(item.start)}] {sentence}")
    else:
        lines.append("- No clear decisions detected automatically.")

    lines.extend(["", "## 4. Action Items", ""])
    if not is_substantive:
        lines.append("- Not enough clean meeting content to infer action items safely.")
    elif actions:
        for item, sentence in actions:
            lines.append(f"- [ ] [{item.speaker} {format_time(item.start)}] {sentence}")
    else:
        lines.append("- No clear action items detected automatically.")

    lines.extend(["", "## 5. Risks / Open Questions", ""])
    if not is_substantive:
        lines.append("- Main risk: the source recording is too short or too noisy for dependable meeting-note extraction.")
    elif risks:
        for item, sentence in risks:
            lines.append(f"- [{item.speaker} {format_time(item.start)}] {sentence}")
    else:
        lines.append("- No obvious risks or open questions detected automatically.")

    lines.extend(["", "## 6. Speaker Notes", ""])
    if sections:
        for speaker, items in sections.items():
            lines.append(f"### {speaker}")
            for item in items[:18]:
                lines.append(f"- {format_time(item.start)} {clean_sentence(item.text)}")
            if len(items) > 18:
                lines.append(f"- ... {len(items) - 18} more entries in full transcript")
            lines.append("")
    else:
        lines.append("- Speaker separation is not available for this recording.")

    lines.extend(["", "## 7. Full Transcript", ""])
    for item in usable:
        lines.append(f"- {format_time(item.start)}-{format_time(item.end)} `{item.speaker}` {item.text}")

    zh_highlights = translate_sentences_to_chinese([sentence for _, sentence in highlights[:5]])
    zh_discussions = translate_sentences_to_chinese([text for _, _, text in discussion_blocks(usable)[:3]])
    lines.extend(["", "## 中文版本", ""])
    lines.extend(
        [
            f"- 音频文件：`{audio.name}`",
            f"- 时长：{format_time(total_start)}-{format_time(total_end)}",
            f"- 说话人：{', '.join(speakers) if speakers else '未分离'}",
            "- 来源：英文会后转写与英文纪要。分享前仍需人工复核。",
            "",
            "## 1. 会议摘要",
            "",
        ]
    )
    if not is_substantive:
        lines.append("- 本次录音没有足够清晰、完整的会议讨论内容，因此不能可靠生成正式会议决议和行动项。")
        lines.append("- 下方保留已清理的英文转写片段，建议使用更长、更清晰的录音重新生成。")
    elif zh_highlights:
        for sentence in zh_highlights:
            lines.append(f"- {sentence}")
    else:
        lines.append("- 中文翻译引擎不可用，暂时无法生成中文摘要。")

    lines.extend(["", "## 2. 关键讨论", ""])
    if zh_discussions:
        for sentence in zh_discussions:
            lines.append(f"- {sentence}")
    elif blocks:
        lines.append("- 中文翻译引擎不可用。请参考上方英文关键讨论。")
    else:
        lines.append("- 未检测到可读的讨论段落。")

    lines.extend(["", "## 3. 会议决议", ""])
    if not is_substantive:
        lines.append("- 内容不足，不能安全推断会议决议。")
    elif decisions:
        zh_decisions = translate_sentences_to_chinese([sentence for _, sentence in decisions])
        for sentence in zh_decisions or [sentence for _, sentence in decisions]:
            lines.append(f"- {sentence}")
    else:
        lines.append("- 未自动检测到明确决议。")

    lines.extend(["", "## 4. 行动项", ""])
    if not is_substantive:
        lines.append("- 内容不足，不能安全推断行动项。")
    elif actions:
        zh_actions = translate_sentences_to_chinese([sentence for _, sentence in actions])
        for sentence in zh_actions or [sentence for _, sentence in actions]:
            lines.append(f"- [ ] {sentence}")
    else:
        lines.append("- 未自动检测到明确行动项。")

    lines.extend(["", "## 5. 风险与待确认问题", ""])
    if not is_substantive:
        lines.append("- 主要风险：录音过短、语音不清晰或转写质量不足，导致纪要无法可靠生成。")
    elif risks:
        zh_risks = translate_sentences_to_chinese([sentence for _, sentence in risks])
        for sentence in zh_risks or [sentence for _, sentence in risks]:
            lines.append(f"- {sentence}")
    else:
        lines.append("- 未自动检测到明显风险或待确认问题。")

    return "\n".join(lines)


def translate_sentences_to_chinese(sentences: list[str]) -> list[str]:
    cleaned = [sentence for sentence in sentences if sentence.strip()]
    if not cleaned:
        return []
    try:
        import argostranslate.translate
    except ImportError:
        return []

    try:
        languages = argostranslate.translate.get_installed_languages()
        source = next((item for item in languages if item.code == "en"), None)
        target = next((item for item in languages if item.code == "zh"), None)
        if source is None or target is None:
            return []
        translation = source.get_translation(target)
        return [translation.translate(sentence).strip() for sentence in cleaned]
    except Exception:
        return []


def build_natural_paragraphs(
    transcript: list[TranscriptSegment],
    max_words: int = 95,
    max_seconds: int = 90,
) -> list[tuple[float, float, str]]:
    paragraphs: list[tuple[float, float, list[str]]] = []
    current_start = 0.0
    current_end = 0.0
    current_words = 0
    current_text: list[str] = []
    previous_speaker = ""

    for item in transcript:
        text = clean_sentence(item.text)
        if not text:
            continue
        words = readable_unit_count(text)
        starts_new = (
            bool(current_text)
            and (
                item.speaker != previous_speaker
                or item.start - current_start >= max_seconds
                or current_words + words > max_words
            )
        )
        if starts_new:
            paragraphs.append((current_start, current_end, current_text))
            current_text = []
            current_words = 0
        if not current_text:
            current_start = item.start
        current_end = item.end
        previous_speaker = item.speaker
        current_words += words
        current_text.append(text)

    if current_text:
        paragraphs.append((current_start, current_end, current_text))

    return [
        (start, end, polish_english_paragraph(join_transcript_parts(parts)))
        for start, end, parts in paragraphs
        if clean_sentence(" ".join(parts))
    ]


def join_transcript_parts(parts: list[str]) -> str:
    sentences: list[str] = []
    for part in parts:
        text = clean_sentence(part)
        if not text:
            continue
        if not re.search(r"[.!?]$", text):
            text += "."
        sentences.append(text)
    return " ".join(sentences)


def polish_english_paragraph(text: str) -> str:
    polished = clean_sentence(text)
    polished = re.sub(r"\b(and|but)\s+\1\b", r"\1", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\b(the|a|an)\s+\1\b", r"\1", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\b(like|you know),?\s+", "", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\s+", " ", polished)
    return polished.strip()


def extract_summary_points(paragraphs: list[tuple[float, float, str]], limit: int = 5) -> list[str]:
    points: list[str] = []
    seen: set[str] = set()
    for _, _, paragraph in paragraphs:
        sentences = split_readable_sentences(paragraph) or [paragraph]
        candidate = sentences[0]
        candidate = re.sub(r"^(so|and|but|well),?\s+", "", candidate, flags=re.IGNORECASE)
        words = candidate.split()
        if len(words) > 30:
            candidate = " ".join(words[:30]).rstrip(" ,.;") + "."
        key = candidate.lower()
        if len(candidate.split()) >= 8 and key not in seen:
            points.append(candidate)
            seen.add(key)
        if len(points) >= limit:
            break
    return points


TOPIC_STOPWORDS = {
    "about", "above", "after", "again", "against", "all", "also", "and", "another", "are", "because",
    "been", "before", "being", "between", "both", "but", "can", "could", "did", "does", "doing",
    "done", "for", "from", "get", "going", "got", "had", "has", "have", "here", "how", "into",
    "item", "just", "like", "mean", "more", "move", "much", "need", "next", "now", "one", "only", "our", "out", "over",
    "really", "right", "said", "same", "see", "should", "some", "something", "that", "the", "their",
    "them", "then", "there", "these", "they", "thing", "things", "this", "those", "through", "time", "topic",
    "too", "use", "very", "want", "was", "way", "well", "were", "what", "when", "where", "which",
    "who", "why", "will", "with", "would", "yeah", "you", "your",
}

TOPIC_SHIFT_RE = re.compile(
    r"^(next|now|moving on|let'?s move|let'?s talk|another topic|switching to|on the other hand|"
    r"separately|the next question|the next item|for the next part)\b",
    re.IGNORECASE,
)


def build_topic_sections(paragraphs: list[tuple[float, float, str]], limit: int = 8) -> list[TopicSection]:
    groups: list[list[tuple[float, float, str]]] = []
    current: list[tuple[float, float, str]] = []
    current_keywords: set[str] = set()
    previous_end = 0.0

    for paragraph in paragraphs:
        start, end, text = paragraph
        keywords = set(topic_keywords(text, limit=8))
        gap = start - previous_end if current else 0.0
        overlap = len(current_keywords.intersection(keywords))
        starts_new = bool(current) and (
            gap >= 90
            or TOPIC_SHIFT_RE.search(text.strip()) is not None
            or (len(current_keywords) >= 4 and len(keywords) >= 4 and overlap <= 1)
        )
        if starts_new:
            groups.append(current)
            current = []
            current_keywords = set()
        current.append(paragraph)
        current_keywords.update(keywords)
        previous_end = end

    if current:
        groups.append(current)

    sections: list[TopicSection] = []
    for index, group in enumerate(groups[:limit], start=1):
        combined = " ".join(text for _, _, text in group)
        keywords = topic_keywords(combined, limit=3)
        title = " / ".join(keyword.title() for keyword in keywords) if keywords else f"Topic {index}"
        bullets = topic_bullets(group)
        sections.append(
            TopicSection(
                title=f"Topic {index}: {title}",
                start=group[0][0],
                end=group[-1][1],
                bullets=bullets,
            )
        )
    return sections


def topic_keywords(text: str, limit: int = 5) -> list[str]:
    words = [
        word.lower()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9&+\-']{2,}", text)
        if word.lower() not in TOPIC_STOPWORDS and len(word) >= 4
    ]
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for index, word in enumerate(words):
        counts[word] = counts.get(word, 0) + 1
        first_seen.setdefault(word, index)
    ranked = sorted(counts, key=lambda word: (-counts[word], first_seen[word], word))
    return ranked[:limit]


def topic_bullets(group: list[tuple[float, float, str]], limit: int = 3) -> list[str]:
    bullets: list[str] = []
    seen: set[str] = set()
    for _, _, paragraph in group:
        for sentence in split_readable_sentences(paragraph) or [paragraph]:
            cleaned = clean_sentence(sentence)
            key = cleaned.lower()
            if len(cleaned.split()) < 7 or key in seen:
                continue
            bullets.append(cleaned)
            seen.add(key)
            if len(bullets) >= limit:
                return bullets
    return bullets


def extract_decisions(sentences: list[tuple[TranscriptSegment, str]], limit: int = 8) -> list[tuple[TranscriptSegment, str]]:
    patterns = [
        r"\bwe (decided|agreed|confirmed|approved|selected|chose)\b",
        r"\bit was (decided|agreed|confirmed|approved)\b",
        r"\bthe decision is\b",
        r"\bfinal decision\b",
    ]
    return pick_regex_items(sentences, patterns, limit)


def extract_action_items(sentences: list[tuple[TranscriptSegment, str]], limit: int = 10) -> list[tuple[TranscriptSegment, str]]:
    patterns = [
        r"\b(can you|could you|please)\b.*\b(send|check|review|confirm|prepare|update|share|follow up)\b",
        r"\b(i|we|they) (will|shall|need to|should|must|have to)\b.*\b(send|check|review|confirm|prepare|update|share|follow up|finish|submit)\b",
        r"\b(action item|todo|next step|follow up)\b",
        r"\bby (monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next week|today)\b",
    ]
    return pick_regex_items(sentences, patterns, limit)


def extract_risks(sentences: list[tuple[TranscriptSegment, str]], limit: int = 8) -> list[tuple[TranscriptSegment, str]]:
    patterns = [
        r"\b(risk|issue|problem|concern|blocked|blocker|delay|unclear|pending)\b",
        r"\b(not enough|failed|missing)\b",
    ]
    return pick_regex_items(sentences, patterns, limit)


def extract_chinese_decisions(sentences: list[tuple[TranscriptSegment, str]], limit: int = 8) -> list[tuple[TranscriptSegment, str]]:
    patterns = [
        r"(决定|确定|确认|同意|通过|批准|采用|定下来|结论是)",
        r"(最终|暂定).{0,12}(方案|做法|时间|负责人)",
    ]
    return pick_regex_items(sentences, patterns, limit)


def extract_chinese_action_items(sentences: list[tuple[TranscriptSegment, str]], limit: int = 10) -> list[tuple[TranscriptSegment, str]]:
    patterns = [
        r"(需要|要|请|麻烦|负责|跟进|推进|准备|整理|发送|检查|确认|复核|更新|提交)",
        r"(下一步|后续|会后|今天|明天|本周|下周|截止|时间节点)",
    ]
    return pick_regex_items(sentences, patterns, limit)


def extract_chinese_risks(sentences: list[tuple[TranscriptSegment, str]], limit: int = 8) -> list[tuple[TranscriptSegment, str]]:
    patterns = [
        r"(风险|问题|阻塞|卡点|延迟|不清楚|不确定|待确认|缺少|失败|担心|注意)",
    ]
    return pick_regex_items(sentences, patterns, limit)


def pick_regex_items(
    sentences: list[tuple[TranscriptSegment, str]],
    patterns: list[str],
    limit: int,
) -> list[tuple[TranscriptSegment, str]]:
    picked: list[tuple[TranscriptSegment, str]] = []
    seen: set[str] = set()
    for item, sentence in sentences:
        normalized = clean_sentence(sentence)
        lowered = normalized.lower()
        if readable_unit_count(normalized) < 5 or lowered in seen:
            continue
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns):
            picked.append((item, normalized))
            seen.add(lowered)
        if len(picked) >= limit:
            break
    return picked


def chinese_reading_lines(english_lines: list[str]) -> list[str]:
    translated = translate_sentences_to_chinese(english_lines)
    if not translated:
        return []
    return [polish_chinese_text(text) for text in translated]


def polish_chinese_text(text: str) -> str:
    polished = text.strip()
    replacements = {
        "读房间": "观察现场氛围",
        "看看房间": "观察现场氛围",
        "阅读房间": "观察现场氛围",
        "有权利说不": "有拒绝的空间",
        "没有权利拒绝": "缺少拒绝的空间",
        "年轻人或年轻人": "年轻员工或初级员工",
        "年假申请": "年假申请",
        "嗡嗡作响的新公司": "热门的新兴公司",
        "通过屋顶": "非常高",
        "不能拒绝他们": "很难拒绝上级或公司要求",
    }
    for bad, good in replacements.items():
        polished = polished.replace(bad, good)
    polished = re.sub(r"\s+", "", polished)
    return polished


def notes_llm_enabled() -> bool:
    value = os.getenv("POST_MEETING_LLM_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off", "rule", "rules"}


def notes_llm_provider() -> str:
    return os.getenv("POST_MEETING_LLM_PROVIDER", "ollama").strip().lower() or "ollama"


def ollama_notes_model() -> str:
    return os.getenv("OLLAMA_NOTES_MODEL", "qwen3:14b").strip() or "qwen3:14b"


def ollama_notes_url() -> str:
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
    return f"{host}/api/chat"


def ollama_timeout_seconds() -> int:
    try:
        return max(10, int(os.getenv("POST_MEETING_LLM_TIMEOUT_SECONDS", "120")))
    except ValueError:
        return 120


def transformers_notes_model() -> str:
    return (
        os.getenv("TRANSFORMERS_NOTES_MODEL", "")
        or os.getenv("HF_NOTES_MODEL", "")
        or os.getenv("POST_MEETING_TRANSFORMERS_MODEL", "")
        or "google/gemma-4-E2B-it"
    ).strip()


def transformers_notes_device() -> str:
    requested = os.getenv("TRANSFORMERS_NOTES_DEVICE", "auto").strip().lower()
    if requested in {"cpu", "cuda"}:
        return requested
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def transformers_notes_max_new_tokens() -> int:
    try:
        return max(256, min(4096, int(os.getenv("TRANSFORMERS_NOTES_MAX_NEW_TOKENS", "1400"))))
    except ValueError:
        return 1400


def transcript_for_writer(transcript: list[TranscriptSegment], max_chars: int = 14000) -> str:
    rows: list[str] = []
    for item in transcript:
        text = clean_sentence(item.text)
        if not text:
            continue
        rows.append(f"[{format_time(item.start)}-{format_time(item.end)}] {item.speaker}: {text}")
    body = "\n".join(rows)
    if len(body) <= max_chars:
        return body
    return body[:max_chars].rsplit("\n", 1)[0].rstrip()


def ollama_minutes_markdown(
    audio: Path,
    transcript: list[TranscriptSegment],
    total_start: float,
    total_end: float,
    speakers: list[str],
) -> str:
    if not notes_llm_enabled():
        return ""
    source = transcript_for_writer(transcript)
    if len(source.split()) < 80:
        return ""
    model = ollama_notes_model()
    system_prompt = (
        "You are a professional bilingual meeting-notes writer. "
        "Create concise, faithful meeting minutes from an ASR transcript. "
        "Do not invent decisions or action items. If none are explicit, say none detected. "
        "Do not map speaker labels or personal names; use neutral owner wording such as the team or the relevant party. "
        "Keep protected terms, acronyms, numbers, units, device IDs, and room/level labels unchanged. "
        "Write natural English first, then a natural Simplified Chinese reading version. "
        "Return Markdown only."
    )
    user_prompt = f"""
Audio: {audio.name}
Duration: {format_time(total_start)}-{format_time(total_end)}
Speakers: {', '.join(speakers) if speakers else 'Not separated'}

Required Markdown structure:
# Meeting Notes

## English Version
- Audio: `{audio.name}`
- Duration: {format_time(total_start)}-{format_time(total_end)}
- Speakers: {', '.join(speakers) if speakers else 'Not separated'}
- Source: post-meeting ASR transcript. Review before sharing.

## 1. Executive Summary
## 2. Topic Timeline
## 3. Key Discussion
## 4. Decisions
## 5. Action Items
## 6. Risks / Open Questions
## 7. Speaker Notes

## 中文阅读版
## 1. 摘要
## 2. 讨论内容
## 3. 决议
## 4. 行动项
## 5. 风险与待确认问题

Rules:
- Use bullet points under each section.
- Under Topic Timeline, create a new topic when the transcript changes subject, moves to a new agenda item, or has a meaningful time gap.
- Each topic should include an approximate time range, a short title, and 2-3 faithful bullets.
- Keep the topic list concise; prefer 3-8 main topics over many tiny fragments.
- Do not treat generic statements as action items.
- Include owners or timestamps only when the transcript clearly provides them.
- Chinese should be rewritten naturally, not literal sentence-by-sentence translation.
- If a section has no explicit evidence, write "No explicit ... detected." / "未检测到明确..."

Transcript:
{source}
""".strip()
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {
            "temperature": 0.2,
            "num_ctx": 8192,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        ollama_notes_url(),
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=ollama_timeout_seconds()) as response:
            result = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return ""

    content = str((result.get("message") or {}).get("content") or "").strip()
    if not content or "# Meeting Notes" not in content or "## English Version" not in content:
        return ""
    content = content.replace("```markdown", "").replace("```", "").strip()
    print(f"Used Ollama notes writer: {model}")
    return content + "\n\n---\n\nGenerated with Ollama model `" + model + "`.\n"


def transformers_minutes_markdown(
    audio: Path,
    transcript: list[TranscriptSegment],
    total_start: float,
    total_end: float,
    speakers: list[str],
) -> str:
    if not notes_llm_enabled():
        return ""
    source = transcript_for_writer(transcript)
    if len(source.split()) < 80:
        return ""

    model_name = transformers_notes_model()
    device = transformers_notes_device()
    system_prompt = (
        "You are a professional bilingual meeting-notes writer. "
        "Create concise, faithful meeting minutes from an ASR transcript. "
        "Do not invent decisions or action items. Return Markdown only."
    )
    user_prompt = f"""
Audio: {audio.name}
Duration: {format_time(total_start)}-{format_time(total_end)}
Speakers: {', '.join(speakers) if speakers else 'Not separated'}

Write this exact Markdown structure:
# Meeting Notes

## English Version
- Audio: `{audio.name}`
- Duration: {format_time(total_start)}-{format_time(total_end)}
- Speakers: {', '.join(speakers) if speakers else 'Not separated'}
- Source: post-meeting ASR transcript. Review before sharing.

## 1. Executive Summary
## 2. Topic Timeline
## 3. Key Discussion
## 4. Decisions
## 5. Action Items
## 6. Risks / Open Questions
## 7. Speaker Notes

## 中文阅读版
## 1. 摘要
## 2. 讨论内容
## 3. 决议
## 4. 行动项
## 5. 风险与待确认问题

Rules:
- Use concise bullet points.
- Stay faithful to the transcript.
- Do not invent decisions, owners, deadlines, or action items.
- If a section has no explicit evidence, say none detected.
- Chinese should be natural Simplified Chinese, not word-by-word translation.

Transcript:
{source}
""".strip()

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoModelForImageTextToText, AutoTokenizer

        token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or None
        print(f"Notes model: preparing {model_name}", flush=True)
        print("Notes model: downloading or loading tokenizer", flush=True)
        tokenizer = AutoTokenizer.from_pretrained(model_name, token=token)
        model_kwargs = {"token": token} if token else {}
        print("Notes model: downloading or loading weights", flush=True)
        try:
            model = AutoModelForCausalLM.from_pretrained(model_name, **model_kwargs)
        except Exception:
            model = AutoModelForImageTextToText.from_pretrained(model_name, **model_kwargs)

        if device == "cuda":
            model = model.to("cuda")
        else:
            model = model.to("cpu")
        model.eval()
        print(f"Notes model: ready on {device}", flush=True)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if hasattr(tokenizer, "apply_chat_template"):
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        else:
            prompt = f"{system_prompt}\n\n{user_prompt}\n\nMeeting Notes:\n"

        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=8192)
        inputs = {key: value.to(model.device) for key, value in inputs.items()}
        print("Notes model: refining meeting notes", flush=True)
        with torch.inference_mode():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=transformers_notes_max_new_tokens(),
                do_sample=False,
                temperature=None,
                pad_token_id=tokenizer.eos_token_id,
            )
        generated_ids = output_ids[0][inputs["input_ids"].shape[-1]:]
        content = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
    except Exception as exc:
        print(f"Direct Transformers notes writer unavailable: {exc}", flush=True)
        return ""

    if not content or "# Meeting Notes" not in content or "## English Version" not in content:
        return ""
    content = content.replace("```markdown", "").replace("```", "").strip()
    print(f"Used direct Transformers notes writer: {model_name} on {device}", flush=True)
    return content + "\n\n---\n\nGenerated with direct Transformers model `" + model_name + "`.\n"


def llm_minutes_markdown(
    audio: Path,
    transcript: list[TranscriptSegment],
    total_start: float,
    total_end: float,
    speakers: list[str],
) -> str:
    provider = notes_llm_provider()
    if provider in {"transformers", "hf", "huggingface", "direct"}:
        direct_minutes = transformers_minutes_markdown(audio, transcript, total_start, total_end, speakers)
        if direct_minutes:
            return direct_minutes
        if os.getenv("POST_MEETING_LLM_FALLBACK", "1").strip().lower() in {"0", "false", "no", "off"}:
            return ""
    return ollama_minutes_markdown(audio, transcript, total_start, total_end, speakers)


def minutes_markdown(audio: Path, transcript: list[TranscriptSegment], notes_language: str = "en") -> str:
    if is_chinese_language(notes_language):
        return chinese_minutes_markdown(audio, transcript)
    cleaned_transcript = [
        TranscriptSegment(
            start=item.start,
            end=item.end,
            text=clean_sentence(item.text),
            speaker=item.speaker,
        )
        for item in transcript
    ]
    usable = [item for item in cleaned_transcript if len(item.text.strip()) >= 8]
    sentences = transcript_sentences(usable)
    paragraphs = build_natural_paragraphs(usable)
    total_start = min((item.start for item in usable), default=0.0)
    total_end = max((item.end for item in usable), default=0.0)
    sections = speaker_sections(usable)
    speakers = sorted(sections)
    summary_points = extract_summary_points(paragraphs)
    topic_sections = build_topic_sections(paragraphs)
    decisions = extract_decisions(sentences)
    actions = extract_action_items(sentences)
    risks = extract_risks(sentences)
    readable_word_count = sum(len(sentence.split()) for _, sentence in sentences)
    is_substantive = readable_word_count >= 80 and len(sentences) >= 3
    llm_minutes = llm_minutes_markdown(audio, usable, total_start, total_end, speakers)
    if llm_minutes:
        return llm_minutes

    lines = [
        "# Meeting Notes",
        "",
        "This document is generated from post-meeting transcription. English is the master version; Chinese is a reading version for quick review.",
        "",
        "## English Version",
        "",
        f"- Audio: `{audio.name}`",
        f"- Duration: {format_time(total_start)}-{format_time(total_end)}",
        f"- Speakers: {', '.join(speakers) if speakers else 'Not separated'}",
        "- Source: post-meeting ASR transcript. Review before sharing.",
        "",
        "## 1. Executive Summary",
        "",
    ]

    if not is_substantive:
        lines.append("- The recording did not contain enough clean discussion to generate reliable professional minutes.")
    elif summary_points:
        for point in summary_points:
            lines.append(f"- {point}")
    else:
        lines.append("- No substantial transcript text was captured.")

    lines.extend(["", "## 2. Topic Timeline", ""])
    if topic_sections:
        for topic in topic_sections:
            lines.append(f"### {format_time(topic.start)}-{format_time(topic.end)} | {topic.title}")
            for bullet in topic.bullets:
                lines.append(f"- {bullet}")
            lines.append("")
    elif is_substantive:
        lines.append("- No clear topic shifts were detected automatically.")
    else:
        lines.append("- Not enough clean meeting content to segment topics reliably.")

    lines.extend(["", "## 3. Discussion Notes", ""])
    if paragraphs:
        for start, end, paragraph in paragraphs:
            lines.append(f"### {format_time(start)}-{format_time(end)}")
            lines.append(paragraph)
            lines.append("")
    else:
        lines.append("- No readable discussion blocks were detected.")

    lines.extend(["", "## 4. Decisions", ""])
    if not is_substantive:
        lines.append("- Not enough clean meeting content to infer decisions safely.")
    elif decisions:
        for item, sentence in decisions:
            lines.append(f"- [{item.speaker} {format_time(item.start)}] {sentence}")
    else:
        lines.append("- No explicit decisions were detected.")

    lines.extend(["", "## 5. Action Items", ""])
    if not is_substantive:
        lines.append("- Not enough clean meeting content to infer action items safely.")
    elif actions:
        for item, sentence in actions:
            lines.append(f"- [ ] [{item.speaker} {format_time(item.start)}] {sentence}")
    else:
        lines.append("- No explicit action items were detected.")

    lines.extend(["", "## 6. Risks / Open Questions", ""])
    if not is_substantive:
        lines.append("- Main risk: the source recording is too short, unclear, or incomplete for dependable note extraction.")
    elif risks:
        for item, sentence in risks:
            lines.append(f"- [{item.speaker} {format_time(item.start)}] {sentence}")
    else:
        lines.append("- No explicit risks or open questions were detected.")

    lines.extend(["", "## 7. Speaker Notes", ""])
    if sections:
        for speaker, items in sections.items():
            lines.append(f"### {speaker}")
            for item in items[:18]:
                lines.append(f"- {format_time(item.start)} {clean_sentence(item.text)}")
            if len(items) > 18:
                lines.append(f"- ... {len(items) - 18} more entries in full transcript")
            lines.append("")
    else:
        lines.append("- Speaker separation is not available for this recording.")

    lines.extend(["", "## 8. Full Transcript", ""])
    for item in usable:
        lines.append(f"- {format_time(item.start)}-{format_time(item.end)} `{item.speaker}` {item.text}")

    lines.extend(["", "## 中文阅读版", ""])
    lines.extend(
        [
            f"- 音频文件：`{audio.name}`",
            f"- 时长：{format_time(total_start)}-{format_time(total_end)}",
            f"- 说话人：{', '.join(speakers) if speakers else '未区分'}",
            "- 说明：中文部分用于快速阅读，正式分享前建议以英文主版本复核。",
            "",
            "## 1. 摘要",
            "",
        ]
    )

    zh_summary = chinese_reading_lines(summary_points)
    if not is_substantive:
        lines.append("- 本段录音内容较短或不够完整，暂不能可靠生成正式会议纪要。")
    elif zh_summary:
        for point in zh_summary:
            lines.append(f"- {point}")
    else:
        lines.append("- 中文翻译引擎不可用，请参考英文摘要。")

    lines.extend(["", "## 2. 讨论内容", ""])
    topic_lines: list[str] = []
    for topic in topic_sections[:5]:
        topic_lines.append(
            f"{format_time(topic.start)}-{format_time(topic.end)} {topic.title}: "
            + " ".join(topic.bullets[:2])
        )
    zh_topics = chinese_reading_lines(topic_lines)
    if zh_topics:
        lines.append("")
        lines.append("### Main Topics")
        for topic in zh_topics:
            lines.append(f"- {topic}")

    zh_discussion_source = summary_points[:3] if summary_points else [paragraph for _, _, paragraph in paragraphs[:2]]
    zh_paragraphs = chinese_reading_lines(zh_discussion_source)
    if zh_paragraphs:
        for paragraph in zh_paragraphs:
            lines.append(f"- {paragraph}")
    elif paragraphs:
        lines.append("- 中文翻译引擎不可用，请参考英文讨论内容。")
    else:
        lines.append("- 未检测到可读的讨论段落。")

    lines.extend(["", "## 3. 决议", ""])
    if not is_substantive:
        lines.append("- 内容不足，不能安全推断会议决议。")
    elif decisions:
        zh_decisions = chinese_reading_lines([sentence for _, sentence in decisions])
        for sentence in zh_decisions or [sentence for _, sentence in decisions]:
            lines.append(f"- {sentence}")
    else:
        lines.append("- 未检测到明确决议。")

    lines.extend(["", "## 4. 行动项", ""])
    if not is_substantive:
        lines.append("- 内容不足，不能安全推断行动项。")
    elif actions:
        zh_actions = chinese_reading_lines([sentence for _, sentence in actions])
        for sentence in zh_actions or [sentence for _, sentence in actions]:
            lines.append(f"- [ ] {sentence}")
    else:
        lines.append("- 未检测到明确行动项。")

    lines.extend(["", "## 5. 风险与待确认问题", ""])
    if not is_substantive:
        lines.append("- 主要风险：录音过短、语音不清晰或内容不完整，纪要可靠性有限。")
    elif risks:
        zh_risks = chinese_reading_lines([sentence for _, sentence in risks])
        for sentence in zh_risks or [sentence for _, sentence in risks]:
            lines.append(f"- {sentence}")
    else:
        lines.append("- 未检测到明确风险或待确认问题。")

    return "\n".join(lines)


def write_outputs(
    audio: Path,
    transcript: list[TranscriptSegment],
    speakers: list[SpeakerSegment],
    notes_language: str = "en",
) -> None:
    output_base = audio.with_suffix("")
    transcript_path = output_base.with_suffix(".transcript.md")
    minutes_path = output_base.with_suffix(".minutes.md")
    transcript_path.write_text(transcript_markdown(audio, transcript) + "\n", encoding="utf-8")
    minutes_path.write_text(minutes_markdown(audio, transcript, notes_language) + "\n", encoding="utf-8")
    print(f"Wrote {transcript_path}")
    print(f"Wrote {minutes_path}")

    if not speakers:
        speakers = speaker_segments_from_transcript(transcript)
    if speakers:
        speakers_path = output_base.with_suffix(".speakers.md")
        lines = [
            "# Speaker Segments",
            "",
            "These are anonymous speaker clusters, not verified real names.",
            "",
        ]
        for item in speakers:
            lines.append(f"- {format_time(item.start)}-{format_time(item.end)} `{item.speaker}`")
        speakers_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote {speakers_path}")


def speaker_segments_from_transcript(transcript: list[TranscriptSegment]) -> list[SpeakerSegment]:
    segments: list[SpeakerSegment] = []
    for item in transcript:
        if item.speaker == "Speaker ?" or not item.speaker or not item.speaker.startswith("SPEAKER_"):
            continue
        if segments and segments[-1].speaker == item.speaker and item.start <= segments[-1].end + 0.8:
            segments[-1].end = max(segments[-1].end, item.end)
        else:
            segments.append(SpeakerSegment(start=item.start, end=item.end, speaker=item.speaker))
    return segments


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Turn a recorded meeting WAV into transcript and meeting-minutes Markdown files.",
    )
    parser.add_argument("audio", type=Path, help="Path to recordings/session-*.wav")
    parser.add_argument(
        "--asr-engine",
        choices=["faster-whisper", "funasr", "azure-fast", "azure-batch"],
        default="faster-whisper",
        help="ASR backend. Default: faster-whisper",
    )
    parser.add_argument(
        "--quality",
        choices=sorted(QUALITY_PRESETS),
        default="balanced",
        help="Preset for T600-class machines. Default: balanced",
    )
    parser.add_argument("--model", default="", help="Override faster-whisper model from --quality.")
    parser.add_argument("--language", default="en", help="ASR language code. Default: en")
    parser.add_argument("--notes-language", default="en", choices=["en", "zh"], help="Meeting-notes output language. Default: en")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu", "auto"], help="Default: cuda")
    parser.add_argument("--compute-type", default="", help="Override compute type from --quality.")
    parser.add_argument("--beam-size", type=int, default=0, help="Override beam size from --quality.")
    parser.add_argument("--best-of", type=int, default=0, help="Override best_of from --quality.")
    parser.add_argument("--patience", type=float, default=0.0, help="Override patience from --quality.")
    parser.add_argument("--diarize", action="store_true", help="Also run pyannote speaker diarization.")
    parser.add_argument(
        "--diarization-model",
        default="pyannote/speaker-diarization-3.1",
        help="Default: pyannote/speaker-diarization-3.1",
    )
    parser.add_argument("--hf-token", default="", help="Hugging Face token for pyannote.")
    parser.add_argument("--funasr-model", default="", help="Override FunASR model. Default: balanced/high use paraformer-zh; fast uses iic/SenseVoiceSmall")
    parser.add_argument("--funasr-vad-model", default="", help="Override FunASR VAD model. Default: fsmn-vad")
    parser.add_argument("--funasr-punc-model", default="", help="Override FunASR punctuation model. Default: ct-punc")
    parser.add_argument("--funasr-batch-size", type=int, default=60, help="FunASR batch_size_s. Default: 60")
    parser.add_argument(
        "--asr-chunk-seconds",
        type=int,
        default=600,
        help="Split long WAV files into ASR chunks. Use 0 to disable. Default: 600",
    )
    parser.add_argument("--azure-fast-diarization", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--azure-fast-max-speakers", type=int, default=5)
    parser.add_argument("--azure-fast-timeout-seconds", type=int, default=600)
    parser.add_argument("--azure-batch-max-speakers", type=int, default=5)
    parser.add_argument("--azure-batch-poll-seconds", type=int, default=10)
    parser.add_argument("--azure-batch-timeout-seconds", type=int, default=1800)
    parser.add_argument("--azure-batch-ttl-hours", type=int, default=48)
    args = parser.parse_args()

    if not args.audio.exists():
        raise SystemExit(f"Audio file not found: {args.audio}")

    preset = QUALITY_PRESETS[args.quality]
    args.model = args.model or preset["model"]
    if args.asr_engine == "faster-whisper" and is_chinese_language(args.language) and args.model.endswith(".en"):
        args.model = args.model[:-3]
    args.compute_type = args.compute_type or preset["compute_type"]
    args.beam_size = args.beam_size or preset["beam_size"]
    args.best_of = args.best_of or preset["best_of"]
    args.patience = args.patience or preset["patience"]
    if 0 < args.asr_chunk_seconds < 180:
        print("ASR chunk size below 180s can reduce context; using 180s instead.")
        args.asr_chunk_seconds = 180
    print(
        "Using quality preset "
        f"{args.quality}: engine={args.asr_engine}, "
        f"model={describe_asr_model(args)}, "
        f"compute={args.compute_type}, "
        f"beam={args.beam_size}, best_of={args.best_of}"
    )

    transcript = transcribe_audio(args)
    speakers = diarize_audio(args) if args.diarize else []
    assign_speakers(transcript, speakers)
    assign_fallback_turns(transcript)
    write_outputs(args.audio, transcript, speakers, args.notes_language)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
