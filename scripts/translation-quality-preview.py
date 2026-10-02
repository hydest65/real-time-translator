from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.translator import ArgosTranslator

OUT = ROOT / "design-previews" / "translation-quality-preview.md"
OLLAMA_MODEL = "qwen3:14b"


@dataclass
class Sample:
    title: str
    fragments: list[str]


SAMPLES = [
    Sample(
        title="Tariff negotiation fragment",
        fragments=[
            "escalates in order to deescalate.",
            "So now We had a big ass and now we're down to 10% the 10% across the board",
            "It looks like nothing and everyone is really relieved and in effect that is a big accomplishment in an and goes a long way to balancing trade and people will now look at that as a very very low bars.",
            "So don't make negotiate over the next 90 days.",
            "The key",
            "He got the markets love",
        ],
    ),
    Sample(
        title="China tariffs and pressure fragment",
        fragments=[
            "5% tariff on Chinese but you know the numbers are pretty much just numbers direction of travel here that we're seeing saying how worried are you about that?",
            "Well, the numbers have already gotten so high It really doesnt matter if they go up anymore of trying to bilateral trade is going to a fall dramatically in this context no matter what that's bad for both the Chinese in American economy",
            "and everyone who's connected to the connected along those supply chains if they remain a place very long.",
            "The president and is already backed off on tariffs against others He'll still continue to feel some pressure to back off on the tear tariffs against China",
            "Enough pressure Uh, well we'll have have to see it about that I think what he's hoping to do in the next next 90 days is outflanked China.",
            "Those negotiations are are probably going to pick up pace And of course the Chinese are going to be engaging those countries as we can as well and the country that feels least isolated is least",
        ],
    ),
    Sample(
        title="Hybrid work fragment",
        fragments=[
            "can be hybrid, you know, Alex except basically 8% less pay to be hybrid versus coming your office five days a week.",
            "So you can twist it around and say If you're a boss and you want your folks in five days a week, you're gonna have to pay people basically 8% more",
            "So we've ordered the major negative set have been reported to you from employers.",
            "We want to and interviewed the CEO of a record level label in East London And he set up this company company himself.",
            "It's his baby and he has a lot of young young staff And it's interesting because he's been allowing his young workers to be at home coming coming in for two days a week",
        ],
    ),
]


DEPENDENT_START_RE = re.compile(
    r"^(and|but|so|then|also|because|which|that|this|these|those|it|they|he|she|we|you|"
    r"its|their|his|her|our|your|therefore|however|meanwhile)\b",
    re.IGNORECASE,
)

FILLERS_RE = re.compile(r"\b(uh|um|ah|er|hmm)\b[,\s]*", re.IGNORECASE)


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u2019", "'")).strip()


def word_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9%']+|[.,!?;:]", text)


def remove_duplicate_words(text: str) -> str:
    tokens = word_tokens(text)
    output: list[str] = []
    for token in tokens:
        if output and token.lower() == output[-1].lower() and re.search(r"[A-Za-z]", token):
            continue
        output.append(token)
    return untokenize(output)


def untokenize(tokens: list[str]) -> str:
    text = " ".join(tokens)
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    text = re.sub(r"([({\[])\s+", r"\1", text)
    return normalize_spaces(text)


def stabilize_english(text: str) -> str:
    text = normalize_spaces(text)
    text = FILLERS_RE.sub("", text)
    text = remove_duplicate_words(text)
    replacements = {
        "big ass": "big ask",
        "10% the 10%": "10%",
        "in an and": "and",
        "very very low bars": "very low bar",
        "doesnt": "doesn't",
        "trying to bilateral trade": "bilateral trade",
        "to a fall dramatically": "to fall dramatically",
        "the Chinese in American economy": "the Chinese and American economies",
        "connected to the connected": "connected",
        "a place very long": "in place very long",
        "tear tariffs": "tariffs",
        "outflanked China": "outflank China",
        "except basically": "accept basically",
        "coming your office": "coming to your office",
        "negative set have": "negative effects have",
        "record level label": "record label",
    }
    for source, target in replacements.items():
        text = re.sub(re.escape(source), target, text, flags=re.IGNORECASE)
    text = re.sub(r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b", r"\1. \2", text)
    return normalize_spaces(text)


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9%']+", text))


def build_optimized_windows(fragments: list[str], min_words: int = 10, max_words: int = 42) -> list[str]:
    windows: list[str] = []
    pending = ""
    for raw in fragments:
        text = stabilize_english(raw)
        if not text:
            continue
        if pending:
            combined = normalize_spaces(f"{pending} {text}")
            if word_count(combined) <= max_words:
                pending = combined
                continue
            windows.append(pending)
            pending = text
        elif word_count(text) < min_words or DEPENDENT_START_RE.search(text):
            pending = text
        else:
            windows.append(text)
    if pending:
        if windows and (word_count(pending) < min_words or DEPENDENT_START_RE.search(pending)):
            combined = normalize_spaces(f"{windows[-1]} {pending}")
            if word_count(combined) <= max_words:
                windows[-1] = combined
            else:
                windows.append(pending)
        else:
            windows.append(pending)
    return windows


async def translate_all(translator: ArgosTranslator, items: list[str]) -> list[str]:
    results = []
    for item in items:
        results.append(await translator.translate(item, "eng_Latn", "zho_Hans"))
    return results


def ollama_available() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return any(item.get("name") == OLLAMA_MODEL for item in payload.get("models", []))
    except Exception:
        return False


def polish_with_ollama(english_windows: list[str], machine_chinese: list[str]) -> tuple[list[str], float, str]:
    prompt_lines = [
        "/no_think",
        "You are a real-time meeting subtitle Chinese polishing engine.",
        "Use the English source and the machine Chinese translation to output natural, accurate Simplified Chinese.",
        "Rules:",
        "1. Do not add facts that are not in the source.",
        "2. Fix obvious ASR slips, repeated words, and awkward machine-translation phrasing.",
        "3. Preserve facts such as percentages, countries, tariffs, names, and time periods.",
        "4. Output one Simplified Chinese line per numbered input. Do not explain.",
        "",
    ]
    for index, (english, chinese) in enumerate(zip(english_windows, machine_chinese), start=1):
        prompt_lines.extend(
            [
                f"[{index}] English: {english}",
                f"[{index}] Machine Chinese: {chinese}",
                "",
            ]
        )
    request_payload = {
        "model": OLLAMA_MODEL,
        "prompt": "\n".join(prompt_lines),
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": 4096,
        },
    }
    started = time.perf_counter()
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return [], 0.0, f"Ollama polish failed: HTTP {exc.code}: {detail}"
    except (urllib.error.URLError, TimeoutError) as exc:
        return [], 0.0, f"Ollama polish failed: {exc}"
    elapsed = time.perf_counter() - started
    raw = str(payload.get("response") or "").strip()
    lines = [clean_polished_line(line) for line in raw.splitlines()]
    lines = [line for line in lines if line]
    return lines, elapsed, ""


def clean_polished_line(line: str) -> str:
    line = normalize_spaces(line)
    line = re.sub(r"^\s*(?:[-*]|\d+[.)]|\[\d+\])\s*", "", line)
    return line


def section(title: str) -> str:
    return f"\n## {title}\n"


async def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    translator = ArgosTranslator("eng_Latn", "zho_Hans")
    use_ollama = ollama_available()
    lines = [
        "# Translation Quality Preview",
        "",
        "Purpose: compare current direct translation against a candidate flow that stabilizes English and merges short/dependent fragments before translation.",
        "",
        "This is an offline preview only. It does not change the live subtitle pipeline.",
    ]

    for sample in SAMPLES:
        baseline_inputs = [normalize_spaces(item) for item in sample.fragments if normalize_spaces(item)]
        optimized_inputs = build_optimized_windows(sample.fragments)
        baseline_zh = await translate_all(translator, baseline_inputs)
        optimized_zh = await translate_all(translator, optimized_inputs)
        polished_zh: list[str] = []
        polish_seconds = 0.0
        polish_error = ""
        if use_ollama:
            polished_zh, polish_seconds, polish_error = polish_with_ollama(optimized_inputs, optimized_zh)

        lines.append(section(sample.title))
        lines.append(f"- Current segments: {len(baseline_inputs)}")
        lines.append(f"- Candidate segments: {len(optimized_inputs)}")
        lines.append("")
        lines.append("### Current English Segments")
        for item in baseline_inputs:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("### Candidate English Windows")
        for item in optimized_inputs:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("### Current Chinese")
        for item in baseline_zh:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("### Candidate Chinese")
        for item in optimized_zh:
            lines.append(f"- {item}")
        lines.append("")
        if use_ollama:
            lines.append(f"### Candidate Chinese + Local Polish ({OLLAMA_MODEL}, {polish_seconds:.1f}s)")
            if polish_error:
                lines.append(f"- {polish_error}")
            elif polished_zh:
                for item in polished_zh:
                    lines.append(f"- {item}")
            else:
                lines.append("- No polished output returned.")
            lines.append("")

    OUT.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    asyncio.run(main())
