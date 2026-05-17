from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_CACHE = PROJECT_ROOT / ".model-cache"
DEFAULT_HF_CACHE = DEFAULT_MODEL_CACHE / "huggingface"
DEFAULT_MODEL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MODELSCOPE_CACHE", str(DEFAULT_MODEL_CACHE))
os.environ.setdefault("HF_HOME", str(DEFAULT_HF_CACHE))
os.environ.setdefault("HF_HUB_CACHE", str(DEFAULT_HF_CACHE / "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE", str(DEFAULT_HF_CACHE / "transformers"))

DEFAULT_MEETING_PROMPT = (
    "Engineering meeting transcript. Common terms include Teams, Codex, Azure, "
    "Whisper, Argos, HVAC, MEP, BIM, cleanroom, commissioning, validation, "
    "equipment, energy efficiency, maintenance, system, unit, decision, project."
)

FUNASR_MODEL_BY_QUALITY = {
    "fast": "iic/SenseVoiceSmall",
    "balanced": "iic/SenseVoiceSmall",
    "high": "iic/SenseVoiceSmall",
}

FUNASR_LOCAL_MODEL_DIRS = {
    "iic/SenseVoiceSmall": DEFAULT_MODEL_CACHE / "models" / "iic" / "SenseVoiceSmall",
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
    if args.asr_engine == "funasr":
        return transcribe_audio_funasr(args)
    return transcribe_audio_faster_whisper(args)


def transcribe_audio_faster_whisper(args: argparse.Namespace) -> list[TranscriptSegment]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "faster-whisper is not installed. Run: python -m pip install -r backend\\requirements.txt"
        ) from exc

    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    segments, _ = model.transcribe(
        str(args.audio),
        language=args.language,
        vad_filter=True,
        beam_size=args.beam_size,
        best_of=args.best_of,
        patience=args.patience,
        temperature=0,
        condition_on_previous_text=True,
        initial_prompt=DEFAULT_MEETING_PROMPT if args.language == "en" else None,
        hotwords=DEFAULT_MEETING_PROMPT if args.language == "en" else None,
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
                    start=float(segment.start),
                    end=float(segment.end),
                    text=text,
                )
            )
    return results


def transcribe_audio_funasr(args: argparse.Namespace) -> list[TranscriptSegment]:
    try:
        from funasr import AutoModel
        import torch
    except ImportError as exc:
        raise SystemExit(
            "FunASR is not installed. Install it separately first: python -m pip install funasr"
        ) from exc

    model_name = resolve_funasr_model(args.funasr_model or FUNASR_MODEL_BY_QUALITY[args.quality])
    vad_model = resolve_funasr_model(args.funasr_vad_model or "fsmn-vad")
    punc_model = resolve_funasr_model(args.funasr_punc_model or "ct-punc")
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
    output = model.generate(
        input=str(args.audio),
        language="auto" if args.language == "auto" else args.language,
        use_itn=True,
        batch_size_s=args.funasr_batch_size,
    )
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

    pipeline = Pipeline.from_pretrained(args.diarization_model, use_auth_token=token)
    diarization = pipeline(str(args.audio))
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


def split_readable_sentences(text: str) -> list[str]:
    normalized = clean_sentence(text)
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+", normalized)
    return [clean_sentence(part) for part in parts if len(clean_sentence(part)) >= 8]


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


def minutes_markdown(audio: Path, transcript: list[TranscriptSegment]) -> str:
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


def write_outputs(
    audio: Path,
    transcript: list[TranscriptSegment],
    speakers: list[SpeakerSegment],
) -> None:
    output_base = audio.with_suffix("")
    transcript_path = output_base.with_suffix(".transcript.md")
    minutes_path = output_base.with_suffix(".minutes.md")
    transcript_path.write_text(transcript_markdown(audio, transcript) + "\n", encoding="utf-8")
    minutes_path.write_text(minutes_markdown(audio, transcript) + "\n", encoding="utf-8")
    print(f"Wrote {transcript_path}")
    print(f"Wrote {minutes_path}")

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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Turn a recorded meeting WAV into transcript and meeting-minutes Markdown files.",
    )
    parser.add_argument("audio", type=Path, help="Path to recordings/session-*.wav")
    parser.add_argument(
        "--asr-engine",
        choices=["faster-whisper", "funasr"],
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
    parser.add_argument("--funasr-model", default="", help="Override FunASR model. Default: iic/SenseVoiceSmall")
    parser.add_argument("--funasr-vad-model", default="", help="Override FunASR VAD model. Default: fsmn-vad")
    parser.add_argument("--funasr-punc-model", default="", help="Override FunASR punctuation model. Default: ct-punc")
    parser.add_argument("--funasr-batch-size", type=int, default=60, help="FunASR batch_size_s. Default: 60")
    args = parser.parse_args()

    if not args.audio.exists():
        raise SystemExit(f"Audio file not found: {args.audio}")

    preset = QUALITY_PRESETS[args.quality]
    args.model = args.model or preset["model"]
    args.compute_type = args.compute_type or preset["compute_type"]
    args.beam_size = args.beam_size or preset["beam_size"]
    args.best_of = args.best_of or preset["best_of"]
    args.patience = args.patience or preset["patience"]
    print(
        "Using quality preset "
        f"{args.quality}: engine={args.asr_engine}, "
        f"model={args.model if args.asr_engine == 'faster-whisper' else args.funasr_model or FUNASR_MODEL_BY_QUALITY[args.quality]}, "
        f"compute={args.compute_type}, "
        f"beam={args.beam_size}, best_of={args.best_of}"
    )

    transcript = transcribe_audio(args)
    speakers = diarize_audio(args) if args.diarize else []
    assign_speakers(transcript, speakers)
    assign_fallback_turns(transcript)
    write_outputs(args.audio, transcript, speakers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
