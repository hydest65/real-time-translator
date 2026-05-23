from __future__ import annotations

import csv
import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GLOSSARY_PATH = PROJECT_ROOT / "backend" / "glossary.csv"

DEFAULT_TERMS = (
    "Teams",
    "Codex",
    "Azure",
    "Whisper",
    "Argos",
    "HVAC",
    "MEP",
    "BIM",
    "cleanroom",
    "commissioning",
    "validation",
    "equipment",
    "energy efficiency",
    "maintenance",
    "system",
    "unit",
    "decision",
    "project",
    "gowning",
    "smock",
    "bouffant cap",
    "booties",
    "ESD wrist strap",
    "ISO Class 5",
    "ISO Class 7",
    "AHU",
    "FFU",
    "HEPA",
    "ULPA",
    "BMS",
    "EMS",
    "WFI",
    "CIP",
    "SIP",
    "VHP",
    "CDA",
    "UPW",
    "P&ID",
    "Level +6.00",
    "6 inch",
)

HEADER_NAMES = {
    "source",
    "target",
    "english",
    "chinese",
    "term",
    "phrase",
    "aliases",
    "alias",
    "notes",
}

SOURCE_COLUMNS = ("source", "english", "term", "phrase")
ALIAS_COLUMNS = ("aliases", "alias")


def build_meeting_prompt(language: str = "en", limit: int = 80, include_defaults: bool = True) -> str:
    terms = build_hotword_terms(language=language, limit=limit, include_defaults=include_defaults)
    if not terms:
        return "English speech transcript."
    return "Engineering meeting transcript. Common terms include " + ", ".join(terms) + "."


def build_hotword_text(language: str = "en", limit: int = 80, include_defaults: bool = True) -> str:
    return ", ".join(build_hotword_terms(language=language, limit=limit, include_defaults=include_defaults))


def build_azure_phrase_list(
    extra_terms: str = "",
    source_language: str = "en-US",
    limit: int = 500,
    include_defaults: bool = True,
) -> list[str]:
    language = "es" if source_language.lower().startswith("es") else "en"
    return build_hotword_terms(extra_terms=extra_terms, language=language, limit=limit, include_defaults=include_defaults)


def build_hotword_terms(
    extra_terms: str = "",
    language: str = "en",
    limit: int = 80,
    include_defaults: bool = True,
) -> list[str]:
    terms: list[str] = list(DEFAULT_TERMS) if include_defaults else []
    terms.extend(split_terms(os.getenv("AZURE_PHRASE_LIST", "")))
    terms.extend(split_terms(os.getenv("ASR_PROMPT_TERMS", "")))
    terms.extend(split_terms(extra_terms))
    terms.extend(load_glossary_terms(language=language))
    return unique_clean_terms(terms, limit=limit)


def load_glossary_terms(language: str = "en", path: Path | None = None) -> list[str]:
    glossary_path = path or glossary_path_from_env()
    if not glossary_path.exists():
        return []

    try:
        with glossary_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
    except OSError:
        return []

    if not rows:
        return []

    header = [cell.strip().lower() for cell in rows[0]]
    has_header = any(cell in HEADER_NAMES for cell in header)
    terms: list[str] = []
    data_rows = rows[1:] if has_header else rows

    if has_header:
        source_indexes = [index for index, name in enumerate(header) if name in SOURCE_COLUMNS]
        alias_indexes = [index for index, name in enumerate(header) if name in ALIAS_COLUMNS]
        if not source_indexes:
            source_indexes = [0]
        for row in data_rows:
            for index in source_indexes:
                terms.extend(cell_terms(row, index))
            for index in alias_indexes:
                terms.extend(split_terms(value_at(row, index)))
        return terms

    for row in data_rows:
        if not row:
            continue
        first = clean_term(row[0])
        if first and first.lower() not in HEADER_NAMES:
            terms.append(first)
        if len(row) >= 3:
            terms.extend(split_terms(row[2]))
    return terms


def glossary_path_from_env() -> Path:
    raw = os.getenv("TERMINOLOGY_GLOSSARY_PATH", "").strip()
    if not raw:
        return DEFAULT_GLOSSARY_PATH
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def cell_terms(row: list[str], index: int) -> list[str]:
    value = value_at(row, index)
    if not value:
        return []
    return [value]


def value_at(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return row[index]


def split_terms(value: str) -> list[str]:
    return [term.strip() for term in re.split(r"[,;\n|]+", value or "") if term.strip()]


def unique_clean_terms(terms: list[str], limit: int) -> list[str]:
    unique_terms: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = clean_term(term)
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        unique_terms.append(normalized)
        if len(unique_terms) >= limit:
            break
    return unique_terms


def clean_term(value: str) -> str:
    term = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n\"'")
    if len(term) > 64:
        return ""
    if not re.search(r"[A-Za-z0-9]", term):
        return ""
    return term
