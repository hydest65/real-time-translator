from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class MeetingNotesContext:
    title: str = ""
    participants: str = ""
    keywords: str = ""
    background: str = ""

    def is_empty(self) -> bool:
        return not any((self.title, self.participants, self.keywords, self.background))

    def to_prompt_block(self) -> str:
        lines = []
        if self.title:
            lines.append(f"Meeting title: {self.title}")
        if self.participants:
            lines.append(f"Participants: {self.participants}")
        if self.keywords:
            lines.append(f"Keywords / terminology: {self.keywords}")
        if self.background:
            lines.append(f"Project context: {self.background}")
        return "\n".join(lines).strip()


@dataclass
class NotesRefinementResult:
    text: str
    changed: bool
    status: str
    detail: str = ""


def normalize_meeting_notes_context(value: Any) -> MeetingNotesContext:
    if not isinstance(value, dict):
        return MeetingNotesContext()
    return MeetingNotesContext(
        title=clean_context_field(value.get("title")),
        participants=clean_context_field(value.get("participants")),
        keywords=clean_context_field(value.get("keywords")),
        background=clean_context_field(value.get("background")),
    )


def clean_context_field(value: Any, limit: int = 1200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def notes_refinement_enabled() -> bool:
    if os.getenv("POST_MEETING_NOTES_REWRITE_ENABLED", "").strip():
        value = os.getenv("POST_MEETING_NOTES_REWRITE_ENABLED", "1").strip().lower()
    else:
        value = os.getenv("POST_MEETING_LLM_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off", "rule", "rules"}


def notes_refinement_provider() -> str:
    return os.getenv("POST_MEETING_NOTES_REWRITE_PROVIDER", os.getenv("POST_MEETING_LLM_PROVIDER", "ollama")).strip().lower()


def notes_refinement_model() -> str:
    return (
        os.getenv("POST_MEETING_NOTES_REWRITE_MODEL", "")
        or os.getenv("OLLAMA_NOTES_MODEL", "")
        or "qwen3:14b"
    ).strip()


def notes_refinement_timeout_seconds() -> float:
    try:
        return max(10.0, float(os.getenv("POST_MEETING_NOTES_REWRITE_TIMEOUT_SECONDS", "180")))
    except ValueError:
        return 180.0


def notes_refinement_url() -> str:
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
    return f"{host}/api/generate"


def refine_meeting_minutes(
    *,
    minutes_text: str,
    transcript_text: str,
    context: MeetingNotesContext,
    notes_language: str,
) -> NotesRefinementResult:
    base = str(minutes_text or "").strip()
    if not base:
        return NotesRefinementResult(text=base, changed=False, status="skipped", detail="No minutes text.")
    if not notes_refinement_enabled():
        return NotesRefinementResult(text=base, changed=False, status="disabled")
    if notes_refinement_provider() != "ollama":
        return NotesRefinementResult(text=base, changed=False, status="skipped", detail="Only Ollama rewrite is wired.")

    model = notes_refinement_model()
    if not model:
        return NotesRefinementResult(text=base, changed=False, status="skipped", detail="No rewrite model.")

    speaker_evidence = speaker_discussion_evidence(
        transcript_text,
        int(os.getenv("POST_MEETING_NOTES_REWRITE_SPEAKER_EVIDENCE_CHARS", "6000")),
    )
    prompt = build_refinement_prompt(
        minutes_text=base,
        transcript_text=transcript_text,
        context=context,
        notes_language=notes_language,
        speaker_evidence=speaker_evidence,
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "top_p": 0.85,
            "num_ctx": int(os.getenv("POST_MEETING_NOTES_REWRITE_CONTEXT", "8192")),
        },
    }
    request = urllib.request.Request(
        notes_refinement_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=notes_refinement_timeout_seconds()) as response:
            result = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return NotesRefinementResult(text=base, changed=False, status="failed", detail=str(exc))

    refined = clean_model_minutes(str(result.get("response") or ""))
    if not refined:
        return NotesRefinementResult(text=base, changed=False, status="failed", detail="Empty model response.")
    if not refined_minutes_is_safe(base, refined):
        return NotesRefinementResult(text=base, changed=False, status="rejected", detail="Rewrite failed safety checks.")
    if speaker_evidence and contains_ambiguous_speaker_pronoun(refined):
        return NotesRefinementResult(
            text=base,
            changed=False,
            status="rejected",
            detail="Rewrite used ambiguous speaker pronouns.",
        )
    return NotesRefinementResult(text=refined, changed=True, status="rewritten", detail=f"Ollama model: {model}")


def build_refinement_prompt(
    *,
    minutes_text: str,
    transcript_text: str,
    context: MeetingNotesContext,
    notes_language: str,
    speaker_evidence: str = "",
) -> str:
    wants_chinese = str(notes_language or "").lower().startswith(("zh", "cn"))
    output_language = "Chinese" if wants_chinese else "English first, then a concise Chinese reading section"
    context_block = context.to_prompt_block() or "No extra meeting context was provided."
    minutes_excerpt = trim_for_prompt(minutes_text, int(os.getenv("POST_MEETING_NOTES_REWRITE_MINUTES_CHARS", "9000")))
    transcript_excerpt = trim_for_prompt(transcript_text, int(os.getenv("POST_MEETING_NOTES_REWRITE_TRANSCRIPT_CHARS", "9000")))
    return "\n".join(
        [
            "You are improving meeting minutes from a speech transcript.",
            "Rewrite the minutes into a clean, professional meeting-notes document with richer topic sections.",
            "Do not invent decisions, owners, names, dates, quantities, or risks that are not supported.",
            "Preserve useful technical terms, product names, abbreviations, numbers, and action items.",
            "Remove ASR noise, repeated words, filler phrases, and awkward machine wording.",
            "Use the transcript reference to enrich sparse generated minutes when it contains supporting detail.",
            "Make the discussion speaker-aware. When the transcript identifies speakers, each major topic should show "
            "who raised, answered, challenged, confirmed, or took ownership of the point.",
            "Hard rule: inside topic discussion bullets, never refer to an identified speaker as 他, 她, 其, 对方, he, "
            "she, or they. Repeat the speaker label or real name instead, for example 发言人 1 提到..., Speaker 2 added....",
            "Use names only if the transcript or meeting context provides real names. Otherwise use the transcript labels "
            "such as Speaker 1 / Speaker 2, or 发言人 1 / 发言人 2 for Chinese output.",
            "Do not paste long raw transcript excerpts. Paraphrase each speaker's contribution into professional notes, "
            "but keep concrete facts, numbers, examples, and concerns.",
            "For every important topic, explain what was discussed, the concrete discussion points, details, or examples mentioned, "
            "why it matters, and any decisions, risks, open questions, or next steps that were actually stated.",
            "Do not collapse a major topic into one vague sentence. Prefer 3-6 specific bullets per major topic "
            "when the transcript supports that much detail. At least 2 bullets under a major topic should be speaker-attributed "
            "when speaker evidence is available.",
            "For Chinese output, the detailed discussion bullets should read naturally, for example: "
            "发言人 1 提到...；发言人 2 补充...；会议确认...；仍待...确认。",
            "For English output, use the same structure with Speaker 1 noted..., Speaker 2 added..., The team confirmed..., "
            "Still open...",
            "If a topic is unclear, write the supported facts plainly instead of guessing missing context.",
            "Keep Markdown headings and bullet lists. Make the result ready for a Word document.",
            f"Output language: {output_language}.",
            "",
            "Meeting context:",
            context_block,
            "",
            "Current generated minutes:",
            minutes_excerpt,
            "",
            "Speaker-attributed evidence from transcript:",
            speaker_evidence or "No speaker-attributed transcript evidence was available.",
            "",
            "Transcript reference:",
            transcript_excerpt,
            "",
            "Return only the improved Markdown minutes.",
        ]
    )


def speaker_discussion_evidence(transcript_text: str, limit: int) -> str:
    """Extract compact speaker-tagged evidence so the rewrite can keep who said what."""
    cleaned_lines: list[str] = []
    seen: set[str] = set()
    for raw_line in str(transcript_text or "").splitlines():
        line = clean_transcript_evidence_line(raw_line)
        if not line:
            continue
        key = re.sub(r"\s+", "", line).lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned_lines.append(line)

    if not cleaned_lines:
        return ""

    result: list[str] = []
    total = 0
    for line in cleaned_lines:
        next_total = total + len(line) + 1
        if result and next_total > limit:
            break
        result.append(line)
        total = next_total
    return "\n".join(result)


def clean_transcript_evidence_line(line: str) -> str:
    cleaned = str(line or "").strip()
    if not cleaned or cleaned.startswith("#"):
        return ""
    if "`Speaker " not in cleaned and "发言人" not in cleaned and "Speaker " not in cleaned:
        return ""
    cleaned = re.sub(r"^\s*-\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.replace("`", "")
    spoken = re.sub(r"^\d{1,2}:\d{2}(?::\d{2})?-\d{1,2}:\d{2}(?::\d{2})?\s+", "", cleaned)
    spoken = re.sub(r"^(Speaker\s+\S+|发言人\s*\S+)\s*", "", spoken, flags=re.IGNORECASE).strip(" .。")
    if not is_substantive_transcript_snippet(spoken):
        return ""
    return cleaned[:420]


def is_substantive_transcript_snippet(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return False
    filler = {
        "good morning",
        "hi good morning",
        "hello",
        "okay",
        "ok",
        "thank you",
        "thanks",
        "good",
        "ola",
    }
    if cleaned.lower().strip(" .!?") in filler:
        return False
    low_info_patterns = [
        r"\bwait a couple of minutes\b",
        r"\bwe can start\b",
        r"\bis going to join\b",
    ]
    if any(re.search(pattern, cleaned, flags=re.IGNORECASE) for pattern in low_info_patterns):
        return False
    if contains_cjk(cleaned):
        return len(cleaned) >= 12
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'/-]*", cleaned)
    return len(words) >= 6


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(text or ""))


def trim_for_prompt(text: str, limit: int) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    head = cleaned[: int(limit * 0.65)].rstrip()
    tail = cleaned[-int(limit * 0.35) :].lstrip()
    return f"{head}\n\n[... middle omitted for context window ...]\n\n{tail}"


def clean_model_minutes(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = cleaned.strip("` \n\r\t")
    cleaned = re.sub(r"^markdown\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def refined_minutes_is_safe(original: str, refined: str) -> bool:
    original_len = len(original.strip())
    refined_len = len(refined.strip())
    if refined_len < 400 and original_len > 800:
        return False
    if original_len > 0 and refined_len < int(original_len * 0.25):
        return False
    if not re.search(r"(^#|\n#|\n- |\n\d+\.)", refined):
        return False
    lower = refined.lower()
    if "i cannot" in lower or "as an ai" in lower or "无法生成" in refined:
        return False
    return True


def contains_ambiguous_speaker_pronoun(text: str) -> bool:
    """Reject speaker-aware rewrites that hide identified speakers behind pronouns."""
    cleaned = str(text or "")
    explicit_chinese_phrases = (
        "\u4ed6\u8868\u793a",
        "\u4ed6\u63d0\u5230",
        "\u4ed6\u6307\u51fa",
        "\u4ed6\u8ba4\u4e3a",
        "\u4ed6\u8865\u5145",
        "\u4ed6\u786e\u8ba4",
        "\u4ed6\u5f3a\u8c03",
        "\u4ed6\u8bf4\u660e",
        "\u4ed6\u89e3\u91ca",
        "\u4ed6\u5efa\u8bae",
        "\u4ed6\u8be2\u95ee",
        "\u4ed6\u56de\u7b54",
        "\u4ed6\u8d28\u7591",
        "\u4ed6\u8d1f\u8d23",
        "\u5bf9\u65b9\u8868\u793a",
        "\u5bf9\u65b9\u63d0\u5230",
        "\u5bf9\u65b9\u8ba4\u4e3a",
        "\u5176\u8868\u793a",
        "\u5176\u63d0\u5230",
        "\u5176\u8ba4\u4e3a",
    )
    if any(phrase in cleaned for phrase in explicit_chinese_phrases):
        return True
    chinese_patterns = [
        r"(?<!其)他(?:表示|提到|指出|认为|补充|确认|强调|说明|解释|建议|询问|回答|质疑|负责|要求|希望|担心)",
        r"(?:由|需由|需要由)他(?:来|去)?(?:确认|负责|补充|跟进|处理)",
        r"(?:其|对方)(?:表示|提到|指出|认为|补充|确认|强调|说明|解释|建议|询问|回答|质疑|负责)",
    ]
    if any(re.search(pattern, cleaned) for pattern in chinese_patterns):
        return True
    english_patterns = [
        r"\b(?:he|she|they)\s+(?:said|noted|added|confirmed|asked|answered|challenged|owned|suggested|explained)\b",
        r"\b(?:his|her|their)\s+(?:point|concern|question|answer|action|owner)\b",
    ]
    return any(re.search(pattern, cleaned, flags=re.IGNORECASE) for pattern in english_patterns)
