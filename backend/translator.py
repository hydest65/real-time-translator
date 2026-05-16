from __future__ import annotations

import asyncio
import csv
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HF_CACHE = PROJECT_ROOT / ".cache" / "huggingface"
DEFAULT_HF_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(DEFAULT_HF_CACHE))
os.environ.setdefault("HF_HUB_CACHE", str(DEFAULT_HF_CACHE / "hub"))

GLOSSARY_PATH = PROJECT_ROOT / "backend" / "glossary.csv"
GLOSSARY_SEPARATOR_RE = re.compile(r"\s*[;；|]\s*")


@dataclass(frozen=True)
class GlossaryRule:
    source_term: str
    target_term: str
    wrong_outputs: tuple[str, ...]
    trigger_terms: tuple[str, ...]


@dataclass(frozen=True)
class ProtectedText:
    text: str
    terms: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PostProcessResult:
    text: str
    polish_time_ms: float
    glossary_time_ms: float


_GLOSSARY_RULES: list[GlossaryRule] | None = None
_GLOSSARY_MTIME: float | None = None
_GLOSSARY_DUPLICATES: list[str] = []

PROTECTED_TERM_RE = re.compile(
    r"""
    (?<![A-Za-z0-9])
    (
        [A-Z]{2,8}-\d{1,4}[A-Z]? |
        [A-Z]{2,8}\d{1,4}[A-Z]? |
        R(?:oom)?[-\s]?\d{2,5}[A-Z]? |
        Level\s*[+-]?\s*\d+(?:\.\d+)? |
        [+-]?\d+(?:\.\d+)?\s*(?:mm|cm|m|inch|inches|in|kg|g|mg|L|l|mL|ml|Pa|kPa|bar|psi|°C|C|%|ppm)\b |
        (?:AHU|WFI|CIP|SIP|BMS|EMS|HEPA|VHP|FAT|SAT|URS|GMP|P&ID|HAZOP|MEP|BIM|CQV|DQ|IQ|OQ|PQ|VMP|SOP|CAPA|PW|UPW|CDA|PCW|FFU|MAU|AMC|CDS|VMB|CVD|PVD|CMP|FEOL|BEOL)
    )
    (?![A-Za-z0-9])
    """,
    re.IGNORECASE | re.VERBOSE,
)


class Translator(Protocol):
    engine_name: str

    async def translate(
        self,
        text: str,
        source_language: str | None = None,
        target_language: str | None = None,
    ) -> str:
        ...


def nllb_to_short_code(language: str | None) -> str:
    if language == "zho_Hans":
        return "zh"
    return "en"


def load_glossary_rules() -> list[GlossaryRule]:
    global _GLOSSARY_DUPLICATES, _GLOSSARY_MTIME, _GLOSSARY_RULES

    try:
        mtime = GLOSSARY_PATH.stat().st_mtime
    except FileNotFoundError:
        _GLOSSARY_MTIME = None
        _GLOSSARY_RULES = []
        return []

    if _GLOSSARY_RULES is not None and _GLOSSARY_MTIME == mtime:
        return _GLOSSARY_RULES

    rules: list[GlossaryRule] = []
    seen_keys: dict[str, int] = {}
    duplicates: list[str] = []
    with GLOSSARY_PATH.open("r", encoding="utf-8-sig", newline="") as glossary_file:
        reader = csv.DictReader(glossary_file)
        for row_number, row in enumerate(reader, start=2):
            source_term = (row.get("source_term") or "").strip()
            target_term = (row.get("target_term") or "").strip()
            if not source_term or not target_term:
                continue

            duplicate_key = source_term.casefold()
            if duplicate_key in seen_keys:
                duplicates.append(f"{source_term} at rows {seen_keys[duplicate_key]} and {row_number}")
            else:
                seen_keys[duplicate_key] = row_number

            wrong_outputs = tuple(_split_glossary_terms(row.get("wrong_outputs") or ""))
            trigger_terms = _dedupe_terms(
                [source_term, *_split_glossary_terms(row.get("trigger_terms") or "")]
            )
            rules.append(
                GlossaryRule(
                    source_term=source_term,
                    target_term=target_term,
                    wrong_outputs=wrong_outputs,
                    trigger_terms=tuple(trigger_terms),
                )
            )

    _GLOSSARY_MTIME = mtime
    _GLOSSARY_RULES = rules
    _GLOSSARY_DUPLICATES = duplicates
    return rules


def glossary_duplicates() -> list[str]:
    load_glossary_rules()
    return list(_GLOSSARY_DUPLICATES)


def _split_glossary_terms(value: str) -> list[str]:
    return [item.strip() for item in GLOSSARY_SEPARATOR_RE.split(value) if item.strip()]


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(term)
    return result


def apply_glossary_rules(source_text: str, translated_text: str) -> str:
    fixed = translated_text
    for rule in sorted(load_glossary_rules(), key=_rule_specificity, reverse=True):
        if not _rule_matches_source(source_text, rule):
            continue

        replacement_candidates = _dedupe_terms([*rule.wrong_outputs, rule.source_term])
        for candidate in sorted(replacement_candidates, key=len, reverse=True):
            fixed = _replace_term_case_insensitive(fixed, candidate, rule.target_term)
    return fixed


def _rule_specificity(rule: GlossaryRule) -> int:
    return max((len(term) for term in [rule.source_term, *rule.wrong_outputs]), default=0)


def _rule_matches_source(source_text: str, rule: GlossaryRule) -> bool:
    return any(_term_matches_source(source_text, term) for term in rule.trigger_terms)


def _term_matches_source(source_text: str, term: str) -> bool:
    normalized_source = source_text.casefold()
    normalized_term = term.casefold().strip()
    if not normalized_term:
        return False
    if re.search(r"[a-z0-9]", normalized_term):
        escaped = re.escape(normalized_term)
        escaped = re.sub(r"\\\s+", r"\\s+", escaped)
        return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", normalized_source))
    return normalized_term in normalized_source


def _replace_term_case_insensitive(text: str, candidate: str, target: str) -> str:
    if not candidate:
        return text
    if re.search(r"[A-Za-z0-9]", candidate):
        pattern = re.compile(re.escape(candidate), re.IGNORECASE)
        return pattern.sub(target, text)
    return text.replace(candidate, target)


def protect_source_text(text: str) -> ProtectedText:
    terms: list[tuple[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        original = match.group(0)
        placeholder = f"ZXPROTECTED{len(terms)}ZX"
        terms.append((placeholder, original))
        return placeholder

    protected = PROTECTED_TERM_RE.sub(replace, text)
    return ProtectedText(text=protected, terms=tuple(terms))


def restore_protected_terms(text: str, protected: ProtectedText) -> str:
    restored = text
    for placeholder, original in protected.terms:
        restored = re.sub(re.escape(placeholder), original, restored, flags=re.IGNORECASE)
    return restored


def restore_missing_protected_terms(source_text: str, translated_text: str) -> str:
    protected = protect_source_text(source_text)
    missing = [
        original
        for _, original in protected.terms
        if original.casefold() not in translated_text.casefold()
        and not _has_glossary_rendering(source_text, original, translated_text)
    ]
    if not missing:
        return translated_text
    suffix = " ".join(_dedupe_terms(missing))
    return f"{translated_text} {suffix}".strip()


def _has_glossary_rendering(source_text: str, original: str, translated_text: str) -> bool:
    for rule in load_glossary_rules():
        if not _rule_matches_source(source_text, rule):
            continue
        if not any(_term_matches_source(original, term) for term in rule.trigger_terms):
            continue
        rendered_terms = [rule.target_term, *rule.wrong_outputs]
        if any(term and term.casefold() in translated_text.casefold() for term in rendered_terms):
            return True
    return False


def post_process_translation(source_text: str, translated_text: str) -> PostProcessResult:
    started = time.perf_counter()
    fixed = polish_chinese_output(restore_missing_protected_terms(source_text, translated_text))
    polish_time_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    fixed = apply_glossary_rules(source_text, fixed)
    glossary_time_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    fixed = polish_chinese_output(fixed)
    polish_time_ms += (time.perf_counter() - started) * 1000
    return PostProcessResult(
        text=fixed,
        polish_time_ms=polish_time_ms,
        glossary_time_ms=glossary_time_ms,
    )


def apply_contextual_term_fixes(source_text: str, translated_text: str) -> str:
    return post_process_translation(source_text, translated_text).text


def prepare_source_for_translation(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip())
    cleaned = re.sub(r"\b(\d+(?:\.\d+)?)\s*inches\b", r"\1 inch", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(\d+(?:\.\d+)?)\s*in\b", r"\1 inch", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bLevel\s*([+-])\s*(\d)", r"Level \1\2", cleaned, flags=re.IGNORECASE)
    return cleaned


def polish_chinese_output(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", cleaned)
    cleaned = re.sub(r"\s+([，。！？；：、])", r"\1", cleaned)
    cleaned = re.sub(r"([（《“])\s+", r"\1", cleaned)
    cleaned = re.sub(r"\s+([）》”])", r"\1", cleaned)
    cleaned = cleaned.replace(",", "，").replace("?", "？").replace("!", "！")
    cleaned = re.sub(r"([。！？]){2,}", r"\1", cleaned)
    cleaned = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", cleaned)
    cleaned = re.sub(r"\s+([\u3001\uff0c\u3002\uff01\uff1f\uff1b\uff1a])", r"\1", cleaned)
    cleaned = re.sub(r"([\u3001\uff0c\uff1b\uff1a])\s+([\u4e00-\u9fff])", r"\1\2", cleaned)
    return cleaned.strip()


class ArgosTranslator:
    """Fast local translation. Installs the needed Argos package on first use."""

    engine_name = "argos"

    def __init__(self, source_language: str = "eng_Latn", target_language: str = "zho_Hans") -> None:
        import argostranslate.package
        import argostranslate.translate

        self.package = argostranslate.package
        self.translate_module = argostranslate.translate
        self.source_code = nllb_to_short_code(source_language)
        self.target_code = nllb_to_short_code(target_language)
        self._ensure_package(self.source_code, self.target_code)

    def _ensure_package(self, source_code: str, target_code: str) -> None:
        installed = self.translate_module.get_installed_languages()
        if self._find_translation(installed, source_code, target_code) is not None:
            return
        if self._can_pivot(source_code, target_code, installed):
            return
        self.package.update_package_index()
        available_packages = self.package.get_available_packages()
        package = next(
            (
                item
                for item in available_packages
                if item.from_code == source_code and item.to_code == target_code
            ),
            None,
        )
        if package is None and self._install_pivot_packages(source_code, target_code, available_packages):
            return
        if package is None:
            raise RuntimeError(f"Argos package not found for {source_code}->{target_code}.")
        self.package.install_from_path(package.download())

    def _find_translation(self, languages, source_code: str, target_code: str):
        source = next((lang for lang in languages if lang.code == source_code), None)
        target = next((lang for lang in languages if lang.code == target_code), None)
        if source is None or target is None:
            return None
        return source.get_translation(target)

    def _can_pivot(self, source_code: str, target_code: str, languages) -> bool:
        return False

    def _install_pivot_packages(self, source_code: str, target_code: str, available_packages) -> bool:
        return False

    async def translate(
        self,
        text: str,
        source_language: str | None = None,
        target_language: str | None = None,
    ) -> str:
        return await asyncio.to_thread(self._translate_sync, text, source_language, target_language)

    def _translate_sync(
        self,
        text: str,
        source_language: str | None = None,
        target_language: str | None = None,
    ) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""
        prepared = prepare_source_for_translation(cleaned)
        source_code = nllb_to_short_code(source_language) if source_language else self.source_code
        target_code = nllb_to_short_code(target_language) if target_language else self.target_code
        self._ensure_package(source_code, target_code)
        languages = self.translate_module.get_installed_languages()
        translation = self._find_translation(languages, source_code, target_code)
        if translation is None and self._can_pivot(source_code, target_code, languages):
            first_hop = self._find_translation(languages, source_code, "en")
            second_hop = self._find_translation(languages, "en", target_code)
            assert first_hop is not None
            assert second_hop is not None
            return second_hop.translate(first_hop.translate(prepared).strip()).strip()
        if translation is None:
            raise RuntimeError(f"Argos translation unavailable for {source_code}->{target_code}.")
        return translation.translate(prepared).strip()


class MarianMTTranslator:
    """Local neural translation through Helsinki-NLP MarianMT models."""

    engine_name = "marianmt"

    def __init__(
        self,
        en_zh_model_name: str,
        device_preference: str = "cuda",
    ) -> None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self.torch = torch
        self.AutoModelForSeq2SeqLM = AutoModelForSeq2SeqLM
        self.AutoTokenizer = AutoTokenizer
        self.model_name = en_zh_model_name
        self.device = self._resolve_device(device_preference)
        self._models: dict[str, tuple[object, object]] = {}

    def _resolve_device(self, device_preference: str) -> str:
        if device_preference == "cpu":
            return "cpu"
        return "cuda" if self.torch.cuda.is_available() else "cpu"

    def _get_model(self, source_language: str):
        model_name = self.model_name
        if model_name not in self._models:
            tokenizer = self.AutoTokenizer.from_pretrained(model_name)
            model = self.AutoModelForSeq2SeqLM.from_pretrained(model_name)
            model.to(self.device)
            model.eval()
            self._models[model_name] = (tokenizer, model)
        return self._models[model_name]

    async def translate(
        self,
        text: str,
        source_language: str | None = None,
        target_language: str | None = None,
    ) -> str:
        return await asyncio.to_thread(self._translate_sync, text, source_language or "eng_Latn")

    def _translate_sync(self, text: str, source_language: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""
        prepared = prepare_source_for_translation(cleaned)
        tokenizer, model = self._get_model(source_language)
        inputs = tokenizer(prepared, return_tensors="pt", truncation=True, max_length=128)
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self.torch.inference_mode():
            output_tokens = model.generate(
                **inputs,
                max_new_tokens=128,
                num_beams=4,
                length_penalty=1.05,
                no_repeat_ngram_size=3,
                early_stopping=True,
            )
        translated = tokenizer.batch_decode(output_tokens, skip_special_tokens=True)[0]
        return translated


class NLLBTranslator:
    """Slower local translation through NLLB models."""

    engine_name = "nllb"

    def __init__(
        self,
        model_name: str,
        source_language: str = "eng_Latn",
        target_language: str = "zho_Hans",
        device_preference: str = "cuda",
    ) -> None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self.torch = torch
        self.model_name = model_name
        self.source_language = source_language
        self.target_language = target_language
        self.device = self._resolve_device(device_preference)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        model_kwargs = {}
        if self.device == "cuda":
            model_kwargs["torch_dtype"] = torch.float16
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name, **model_kwargs)
        self.model.to(self.device)
        self.model.eval()

    def _resolve_device(self, device_preference: str) -> str:
        if device_preference == "cpu":
            return "cpu"
        return "cuda" if self.torch.cuda.is_available() else "cpu"

    async def translate(
        self,
        text: str,
        source_language: str | None = None,
        target_language: str | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._translate_sync,
            text,
            source_language or self.source_language,
            target_language or self.target_language,
        )

    def _translate_sync(self, text: str, source_language: str, target_language: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""
        prepared = prepare_source_for_translation(cleaned)

        self.tokenizer.src_lang = source_language
        inputs = self.tokenizer(prepared, return_tensors="pt", truncation=True, max_length=128)
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        forced_bos_token_id = getattr(self.tokenizer, "lang_code_to_id", {}).get(target_language)
        if forced_bos_token_id is None:
            forced_bos_token_id = self.tokenizer.convert_tokens_to_ids(target_language)

        with self.torch.inference_mode():
            output_tokens = self.model.generate(
                **inputs,
                forced_bos_token_id=forced_bos_token_id,
                max_new_tokens=96,
                num_beams=1,
            )
        translated = self.tokenizer.batch_decode(output_tokens, skip_special_tokens=True)[0]
        return translated
