from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .transcript_stabilizer import TranscriptStabilizer


@dataclass(frozen=True)
class BuiltSentence:
    text: str
    started_at: float
    ended_at: float


@dataclass(frozen=True)
class SentenceBuilderUpdate:
    draft_text: str
    final_sentences: list[BuiltSentence] = field(default_factory=list)


class SentenceBuilder:
    """Convert stable transcript deltas into natural sentence-sized units."""

    SENTENCE_END_RE = re.compile(r"[.!?][\"')\]]*$")
    DANGLING_END_WORDS = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "because",
        "but",
        "by",
        "for",
        "from",
        "if",
        "in",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "then",
        "to",
        "was",
        "were",
        "when",
        "which",
        "while",
        "with",
    }
    STRONG_NEXT_SENTENCE_STARTS = {
        "after",
        "be sure",
        "finally",
        "first",
        "next",
        "now",
        "the next",
        "then",
    }

    def __init__(
        self,
        min_words: int = 10,
        idle_min_words: int = 8,
        max_words: int = 34,
        max_seconds: float = 7.0,
        idle_seconds: float = 1.15,
    ) -> None:
        self.min_words = min_words
        self.idle_min_words = idle_min_words
        self.max_words = max_words
        self.max_seconds = max_seconds
        self.idle_seconds = idle_seconds
        self.buffer = ""
        self.started_at = 0.0
        self.last_update_at = 0.0

    def accept(self, delta_text: str, start_seconds: float, end_seconds: float) -> SentenceBuilderUpdate:
        delta = TranscriptStabilizer.clean_fragment(delta_text)
        if not delta:
            return SentenceBuilderUpdate(draft_text=self.buffer)
        if not self.buffer:
            self.started_at = start_seconds
        self.buffer = TranscriptStabilizer._join_text(self.buffer, delta)
        self.last_update_at = time.perf_counter()
        final_sentences = self._pop_ready_sentences(end_seconds=end_seconds)
        return SentenceBuilderUpdate(draft_text=self.buffer, final_sentences=final_sentences)

    def flush_if_idle(self, end_seconds: float) -> SentenceBuilderUpdate:
        if not self.buffer or not self.last_update_at:
            return SentenceBuilderUpdate(draft_text=self.buffer)
        if time.perf_counter() - self.last_update_at < self.idle_seconds:
            return SentenceBuilderUpdate(draft_text=self.buffer)
        words = self._words(self.buffer)
        if len(words) < self.idle_min_words or self._has_dangling_end(words):
            return SentenceBuilderUpdate(draft_text=self.buffer)
        sentence = self._finalize_buffer(end_seconds=end_seconds)
        return SentenceBuilderUpdate(draft_text=self.buffer, final_sentences=[sentence] if sentence else [])

    def _pop_ready_sentences(self, end_seconds: float) -> list[BuiltSentence]:
        sentences: list[BuiltSentence] = []
        while self.buffer:
            words = self._words(self.buffer)
            if len(words) >= self.max_words and not self._has_dangling_end(words):
                sentence = self._finalize_prefix(self._choose_prefix_word_count(words), end_seconds)
            elif self._has_strong_internal_boundary(self.buffer):
                sentence = self._finalize_internal_boundary(end_seconds)
            elif len(words) >= self.min_words and self._looks_complete(self.buffer, words):
                sentence = self._finalize_buffer(end_seconds)
            elif len(words) >= self.idle_min_words and self._buffer_seconds(end_seconds) >= self.max_seconds and not self._has_dangling_end(words):
                sentence = self._finalize_buffer(end_seconds)
            else:
                break
            if sentence is None:
                break
            sentences.append(sentence)
        return sentences

    def _finalize_internal_boundary(self, end_seconds: float) -> BuiltSentence | None:
        match = re.search(r"(.+?[.!?])\s+((?:Next|Then|Finally|Now|First|After|Be sure|The next)\b.+)", self.buffer, flags=re.IGNORECASE)
        if not match:
            return None
        sentence_text = match.group(1).strip()
        remainder = match.group(2).strip()
        self.buffer = remainder
        started_at = self.started_at
        self.started_at = end_seconds
        return BuiltSentence(text=sentence_text, started_at=started_at, ended_at=end_seconds)

    def _finalize_prefix(self, word_count: int, end_seconds: float) -> BuiltSentence | None:
        words = self.buffer.split()
        if len(words) <= word_count:
            return self._finalize_buffer(end_seconds)
        sentence_text = " ".join(words[:word_count]).strip()
        self.buffer = " ".join(words[word_count:]).strip()
        started_at = self.started_at
        self.started_at = end_seconds
        return BuiltSentence(text=sentence_text, started_at=started_at, ended_at=end_seconds)

    def _finalize_buffer(self, end_seconds: float) -> BuiltSentence | None:
        text = self.buffer.strip()
        if not text:
            return None
        if not self.SENTENCE_END_RE.search(text):
            text = f"{text}."
        sentence = BuiltSentence(text=text, started_at=self.started_at, ended_at=end_seconds)
        self.buffer = ""
        self.started_at = 0.0
        self.last_update_at = 0.0
        return sentence

    def _looks_complete(self, text: str, words: list[str]) -> bool:
        if self._has_dangling_end(words):
            return False
        if self._has_dangling_comparison(text):
            return False
        if text.rstrip().endswith(".") and len(words) < self.min_words + 4:
            return False
        return bool(self.SENTENCE_END_RE.search(text))

    def _has_strong_internal_boundary(self, text: str) -> bool:
        return bool(re.search(r"[.!?]\s+(Next|Then|Finally|Now|First|After|Be sure|The next)\b", text, flags=re.IGNORECASE))

    def _buffer_seconds(self, end_seconds: float) -> float:
        if not self.started_at:
            return 0.0
        return max(0.0, end_seconds - self.started_at)

    def _choose_prefix_word_count(self, words: list[str]) -> int:
        for index in range(min(len(words), self.max_words), self.min_words, -1):
            if not self._has_dangling_end(words[:index]):
                return index
        return min(len(words), self.max_words)

    @classmethod
    def _has_dangling_end(cls, words: list[str]) -> bool:
        return bool(words) and words[-1].lower().strip("'") in cls.DANGLING_END_WORDS

    @staticmethod
    def _has_dangling_comparison(text: str) -> bool:
        tail = " ".join(text.lower().rstrip(".!?").split()[-9:])
        return "compared to" in tail and not re.search(r"\b(or|than|with)\b.+\b(compared|class|room|cleanroom)\b", tail)

    @staticmethod
    def _words(text: str) -> list[str]:
        return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9'\s]", " ", text.lower())).strip().split()
