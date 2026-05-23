from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
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
        words = len(text.split())
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
        if len(normalized.split()) < 5 or lowered in seen:
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


def ollama_notes_enabled() -> bool:
    value = os.getenv("POST_MEETING_LLM_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off", "rule", "rules"}


def ollama_notes_model() -> str:
    return os.getenv("OLLAMA_NOTES_MODEL", "gemma4:e2b").strip() or "gemma4:e2b"


def ollama_notes_url() -> str:
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
    return f"{host}/api/chat"


def ollama_timeout_seconds() -> int:
    try:
        return max(10, int(os.getenv("POST_MEETING_LLM_TIMEOUT_SECONDS", "120")))
    except ValueError:
        return 120


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
    if not ollama_notes_enabled():
        return ""
    source = transcript_for_writer(transcript)
    if len(source.split()) < 80:
        return ""
    model = ollama_notes_model()
    system_prompt = (
        "You are a professional bilingual meeting-notes writer. "
        "Create concise, faithful meeting minutes from an ASR transcript. "
        "Do not invent decisions or action items. If none are explicit, say none detected. "
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
## 2. Key Discussion
## 3. Decisions
## 4. Action Items
## 5. Risks / Open Questions
## 6. Speaker Notes

## 中文阅读版
## 1. 摘要
## 2. 讨论内容
## 3. 决议
## 4. 行动项
## 5. 风险与待确认问题

Rules:
- Use bullet points under each section.
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
    paragraphs = build_natural_paragraphs(usable)
    total_start = min((item.start for item in usable), default=0.0)
    total_end = max((item.end for item in usable), default=0.0)
    sections = speaker_sections(usable)
    speakers = sorted(sections)
    summary_points = extract_summary_points(paragraphs)
    decisions = extract_decisions(sentences)
    actions = extract_action_items(sentences)
    risks = extract_risks(sentences)
    readable_word_count = sum(len(sentence.split()) for _, sentence in sentences)
    is_substantive = readable_word_count >= 80 and len(sentences) >= 3
    llm_minutes = ollama_minutes_markdown(audio, usable, total_start, total_end, speakers)
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

    lines.extend(["", "## 2. Discussion Notes", ""])
    if paragraphs:
        for start, end, paragraph in paragraphs:
            lines.append(f"### {format_time(start)}-{format_time(end)}")
            lines.append(paragraph)
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
        lines.append("- No explicit decisions were detected.")

    lines.extend(["", "## 4. Action Items", ""])
    if not is_substantive:
        lines.append("- Not enough clean meeting content to infer action items safely.")
    elif actions:
        for item, sentence in actions:
            lines.append(f"- [ ] [{item.speaker} {format_time(item.start)}] {sentence}")
    else:
        lines.append("- No explicit action items were detected.")

    lines.extend(["", "## 5. Risks / Open Questions", ""])
    if not is_substantive:
        lines.append("- Main risk: the source recording is too short, unclear, or incomplete for dependable note extraction.")
    elif risks:
        for item, sentence in risks:
            lines.append(f"- [{item.speaker} {format_time(item.start)}] {sentence}")
    else:
        lines.append("- No explicit risks or open questions were detected.")

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
