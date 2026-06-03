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

    prompt = build_refinement_prompt(
        minutes_text=base,
        transcript_text=transcript_text,
        context=context,
        notes_language=notes_language,
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
    return NotesRefinementResult(text=refined, changed=True, status="rewritten", detail=f"Ollama model: {model}")


def build_refinement_prompt(
    *,
    minutes_text: str,
    transcript_text: str,
    context: MeetingNotesContext,
    notes_language: str,
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
            "For every important topic, explain what was discussed, the concrete discussion points, details, or examples mentioned, "
            "why it matters, and any decisions, risks, open questions, or next steps that were actually stated.",
            "Do not collapse a major topic into one vague sentence. Prefer 3-6 specific bullets per major topic "
            "when the transcript supports that much detail.",
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
            "Transcript reference:",
            transcript_excerpt,
            "",
            "Return only the improved Markdown minutes.",
        ]
    )


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
