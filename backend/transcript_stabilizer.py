from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class StabilizedTranscript:
    delta_text: str
    full_text: str
    is_duplicate: bool = False


class TranscriptStabilizer:
    """Build a stable rolling English transcript from overlapping ASR chunks."""

    CONTINUATION_START_WORDS = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "because",
        "but",
        "by",
        "can",
        "completely",
        "compared",
        "could",
        "for",
        "from",
        "has",
        "have",
        "if",
        "in",
        "is",
        "it",
        "need",
        "needs",
        "of",
        "on",
        "or",
        "should",
        "so",
        "that",
        "the",
        "then",
        "there",
        "this",
        "to",
        "was",
        "we",
        "were",
        "which",
        "while",
        "will",
        "with",
        "would",
    }
    FALSE_PERIOD_CONTINUATION_WORDS = CONTINUATION_START_WORDS - {
        "a",
        "an",
        "it",
        "next",
        "the",
        "there",
        "this",
        "we",
    } | {
        "away",
        "comfortable",
        "compared",
        "completely",
        "different",
        "fits",
        "ground",
        "properly",
        "six",
        "small",
        "that",
    }
    DOMAIN_FIXES = (
        (re.compile(r"\bgounding\s+up\b", re.IGNORECASE), "gowning up"),
        (re.compile(r"\bclean\s+room\b", re.IGNORECASE), "cleanroom"),
        (re.compile(r"\bclean\s+removals?\s+room\s+coveralls?\b", re.IGNORECASE), "cleanroom coveralls"),
        (re.compile(r"\bfor\s+a\s+for\s+an\b", re.IGNORECASE), "for an"),
        (re.compile(r"\bobtain-\s+clean\b", re.IGNORECASE), "obtain clean"),
        (re.compile(r"\btie\s+and\s+tie\s+their\s+hair\b", re.IGNORECASE), "tie their hair"),
        (re.compile(r"\bISO\s+class\s+5\s+or\s+six\s+cleanroom\b", re.IGNORECASE), "ISO class 5 or ISO class 6 cleanroom"),
    )

    def __init__(self, max_transcript_words: int = 240) -> None:
        self.max_transcript_words = max_transcript_words
        self.full_text = ""
        self.recent_signatures: list[str] = []

    def accept(self, text: str) -> StabilizedTranscript:
        fragment = self.clean_fragment(text)
        signature = self.signature(fragment)
        if not signature:
            return StabilizedTranscript(delta_text="", full_text=self.full_text, is_duplicate=True)
        if self._is_recent_duplicate(signature):
            return StabilizedTranscript(delta_text="", full_text=self.full_text, is_duplicate=True)

        delta = self._new_delta(fragment)
        delta_signature = self.signature(delta)
        if not delta_signature:
            self._remember(signature)
            return StabilizedTranscript(delta_text="", full_text=self.full_text, is_duplicate=True)

        self.full_text = self._trim_transcript(self._join_text(self.full_text, delta))
        self._remember(signature)
        return StabilizedTranscript(delta_text=delta, full_text=self.full_text)

    @classmethod
    def clean_fragment(cls, text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""
        cleaned = re.sub(r"(?:\s*[\\/|]{2,}\s*)+", " ", cleaned)
        cleaned = re.sub(r"(?:\s*\.\s*){3,}", "... ", cleaned)
        cleaned = re.sub(r"(\b[A-Za-z]+)-\s+([A-Za-z])", r"\1 \2", cleaned)
        cleaned = re.sub(r"([!?.,])(?:\s*\1){1,}", r"\1", cleaned)
        cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
        cleaned = re.sub(r"([,.!?;:])([A-Za-z])", r"\1 \2", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = cls._repair_false_periods(cleaned)
        for pattern, replacement in cls.DOMAIN_FIXES:
            cleaned = pattern.sub(replacement, cleaned)
        cleaned = cls._collapse_repeated_words(cleaned)
        cleaned = cls._collapse_repeated_phrases(cleaned)
        return cleaned.strip()

    @classmethod
    def _repair_false_periods(cls, text: str) -> str:
        cleaned = re.sub(
            r"\b([A-Za-z][A-Za-z'-]*)[.!?]\s+\1\b",
            r"\1",
            text,
            flags=re.IGNORECASE,
        )
        continuation = "|".join(sorted(map(re.escape, cls.FALSE_PERIOD_CONTINUATION_WORDS), key=len, reverse=True))
        cleaned = re.sub(
            rf"\b([A-Za-z][A-Za-z'-]*)\.\s+({continuation})\b",
            lambda match: f"{match.group(1)} {match.group(2).lower()}",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\b(the)\.\s+(head|finger|palm|glove|hood|face|bouffant)\b",
            r"\1 \2",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\b(of|to|for|with|and|or|in|on|at|by)\.\s+", r"\1 ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()

    @staticmethod
    def _collapse_repeated_words(text: str) -> str:
        cleaned = re.sub(r"\b([A-Za-z]{3,})\s+\1\b", r"\1", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b([A-Za-z]{4,})\s+\1s\b", r"\1s", cleaned, flags=re.IGNORECASE)
        return cleaned

    @classmethod
    def _collapse_repeated_phrases(cls, text: str) -> str:
        words = text.split()
        if len(words) < 6:
            return text
        result: list[str] = []
        index = 0
        while index < len(words):
            collapsed = False
            max_phrase_words = min(8, (len(words) - index) // 2)
            for phrase_words in range(max_phrase_words, 1, -1):
                phrase = words[index : index + phrase_words]
                phrase_signature = cls.signature(" ".join(phrase))
                if not phrase_signature:
                    continue
                cursor = index + phrase_words
                repeat_count = 1
                while cursor + phrase_words <= len(words):
                    candidate = words[cursor : cursor + phrase_words]
                    if cls.signature(" ".join(candidate)) != phrase_signature:
                        break
                    repeat_count += 1
                    cursor += phrase_words
                if repeat_count >= 2:
                    result.extend(phrase)
                    index = cursor
                    collapsed = True
                    break
            if not collapsed:
                result.append(words[index])
                index += 1
        return " ".join(result)

    def _new_delta(self, fragment: str) -> str:
        if not self.full_text:
            return fragment
        transcript_words = self.full_text.split()
        fragment_words = fragment.split()
        if not fragment_words:
            return ""

        tail_words = transcript_words[-40:]
        tail_signature = self.signature(" ".join(tail_words))
        fragment_signature = self.signature(fragment)
        if fragment_signature and fragment_signature in tail_signature:
            return ""

        max_overlap = min(30, len(tail_words), len(fragment_words))
        best_overlap = 0
        for overlap in range(max_overlap, 0, -1):
            left = self.signature(" ".join(tail_words[-overlap:]))
            right = self.signature(" ".join(fragment_words[:overlap]))
            if left and right and (left == right or SequenceMatcher(None, left, right).ratio() >= 0.92):
                best_overlap = overlap
                break

        if best_overlap:
            return " ".join(fragment_words[best_overlap:]).strip()
        return fragment

    @classmethod
    def _join_text(cls, current: str, delta: str) -> str:
        if not current:
            return delta.strip()
        if not delta:
            return current.strip()
        current = current.rstrip()
        delta = delta.strip()
        first_word = cls.signature(delta).split()
        if current.endswith(".") and first_word and first_word[0] in cls.CONTINUATION_START_WORDS:
            current = current[:-1].rstrip()
            delta = delta[:1].lower() + delta[1:]
        return cls.clean_fragment(f"{current} {delta}")

    def _trim_transcript(self, text: str) -> str:
        words = text.split()
        if len(words) <= self.max_transcript_words:
            return text
        return " ".join(words[-self.max_transcript_words:])

    def _is_recent_duplicate(self, signature: str) -> bool:
        return any(
            signature == recent or SequenceMatcher(None, signature, recent).ratio() >= 0.94
            for recent in self.recent_signatures[-10:]
        )

    def _remember(self, signature: str) -> None:
        self.recent_signatures = [*self.recent_signatures, signature][-16:]

    @staticmethod
    def signature(text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9'\s]", " ", text.casefold())).strip()
