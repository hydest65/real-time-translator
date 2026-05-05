from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HF_CACHE = PROJECT_ROOT / ".cache" / "huggingface"
DEFAULT_HF_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(DEFAULT_HF_CACHE))
os.environ.setdefault("HF_HUB_CACHE", str(DEFAULT_HF_CACHE / "hub"))


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
            return second_hop.translate(first_hop.translate(cleaned).strip()).strip()
        if translation is None:
            raise RuntimeError(f"Argos translation unavailable for {source_code}->{target_code}.")
        return translation.translate(cleaned).strip()


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
        tokenizer, model = self._get_model(source_language)
        inputs = tokenizer(cleaned, return_tensors="pt", truncation=True, max_length=128)
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self.torch.inference_mode():
            output_tokens = model.generate(**inputs, max_new_tokens=96, num_beams=1)
        return tokenizer.batch_decode(output_tokens, skip_special_tokens=True)[0].strip()


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

        self.tokenizer.src_lang = source_language
        inputs = self.tokenizer(cleaned, return_tensors="pt", truncation=True, max_length=128)
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
        return self.tokenizer.batch_decode(output_tokens, skip_special_tokens=True)[0].strip()
