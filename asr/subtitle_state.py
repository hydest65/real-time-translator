from __future__ import annotations

import time
from dataclasses import dataclass, field

from .funasr_streaming import FunASRStreamingResult


@dataclass
class SubtitleState:
    """Track partial and final subtitles without repeated screen refreshes."""

    current_partial: str = ""
    last_pushed_partial: str = ""
    last_push_at: float = 0.0
    min_partial_chars: int = 3
    max_partial_wait_seconds: float = 0.45
    final_history: list[str] = field(default_factory=list)

    def update(self, result: FunASRStreamingResult) -> dict | None:
        text = self._clean(result.text)
        if result.event_type == "partial":
            if not text:
                return None
            merged_text = self._merge_stream_text(self.current_partial, text)
            if not merged_text:
                return None
            self.current_partial = merged_text
            if not self._should_push_partial(merged_text):
                return None
            self.last_pushed_partial = merged_text
            self.last_push_at = time.perf_counter()
            return self._event("partial", merged_text, result)

        final_text = self._merge_stream_text(self.current_partial, text) if text else self.current_partial
        final_text = self._clean(final_text)
        self.current_partial = ""
        self.last_pushed_partial = ""
        self.last_push_at = 0.0
        if not final_text:
            return None
        if self.final_history and self.final_history[-1] == final_text:
            return None
        self.final_history.append(final_text)
        return self._event("final", final_text, result)

    def force_finalize(self, latency_ms: float = 0.0) -> dict | None:
        text = self._clean(self.current_partial)
        self.current_partial = ""
        self.last_pushed_partial = ""
        self.last_push_at = 0.0
        if not text or (self.final_history and self.final_history[-1] == text):
            return None
        self.final_history.append(text)
        return {
            "type": "final",
            "text": text,
            "timestamp": int(time.time() * 1000),
            "latency_ms": round(latency_ms, 1),
        }

    def transcript_text(self) -> str:
        return "\n".join(self.final_history)

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(str(text or "").split()).strip()

    def _should_push_partial(self, merged_text: str) -> bool:
        if merged_text == self.last_pushed_partial:
            return False
        if not self.last_pushed_partial:
            return self._compact_len(merged_text) >= 2

        added_chars = self._compact_len(merged_text) - self._compact_len(self.last_pushed_partial)
        if added_chars >= self.min_partial_chars:
            return True

        if self._ends_with_pause(merged_text):
            return True

        waited = time.perf_counter() - self.last_push_at if self.last_push_at else 0.0
        return waited >= self.max_partial_wait_seconds and added_chars > 0

    @staticmethod
    def _compact_len(text: str) -> int:
        return len("".join(str(text or "").split()))

    @staticmethod
    def _ends_with_pause(text: str) -> bool:
        pause_marks = ("\u3002", "\uff01", "\uff1f", "\uff0c", "\uff1b", ".", "!", "?", ",", ";")
        return str(text or "").rstrip().endswith(pause_marks)

    @classmethod
    def _merge_stream_text(cls, current: str, incoming: str) -> str:
        current = cls._clean(current)
        incoming = cls._clean(incoming)
        if not incoming:
            return current
        if not current:
            return incoming
        if incoming == current or current.endswith(incoming):
            return current
        if incoming.startswith(current):
            return incoming

        overlap = cls._suffix_prefix_overlap(current, incoming)
        if overlap:
            return cls._clean(f"{current}{incoming[overlap:]}")
        return cls._clean(f"{current}{incoming}")

    @staticmethod
    def _suffix_prefix_overlap(left: str, right: str) -> int:
        max_len = min(len(left), len(right))
        for size in range(max_len, 0, -1):
            if left[-size:] == right[:size]:
                return size
        return 0

    @staticmethod
    def _event(event_type: str, text: str, result: FunASRStreamingResult) -> dict:
        return {
            "type": event_type,
            "text": text,
            "timestamp": int(time.time() * 1000),
            "latency_ms": round(result.latency_ms, 1),
            "inference_ms": round(result.inference_ms, 1),
            "rtf": round(result.rtf, 3),
            "model": result.model_name,
            "device": result.device,
        }
