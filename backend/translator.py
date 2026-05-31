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
MARIAN_CT2_CACHE = PROJECT_ROOT / ".model-cache" / "marianmt-ct2"


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
    if language == "spa_Latn":
        return "es"
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
        if source_code == "en" or target_code != "zh":
            return False
        return (
            self._find_translation(languages, source_code, "en") is not None
            and self._find_translation(languages, "en", target_code) is not None
        )

    def _install_pivot_packages(self, source_code: str, target_code: str, available_packages) -> bool:
        if source_code == "en" or target_code != "zh":
            return False
        needed_pairs = [(source_code, "en"), ("en", target_code)]
        selected_packages = []
        for from_code, to_code in needed_pairs:
            installed = self.translate_module.get_installed_languages()
            if self._find_translation(installed, from_code, to_code) is not None:
                continue
            package = next(
                (
                    item
                    for item in available_packages
                    if item.from_code == from_code and item.to_code == to_code
                ),
                None,
            )
            if package is None:
                return False
            selected_packages.append(package)
        for package in selected_packages:
            self.package.install_from_path(package.download())
        return True

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
    """Local neural translation through MarianMT, preferring CTranslate2 when available."""

    engine_name = "marianmt"

    def __init__(
        self,
        en_zh_model_name: str,
        es_zh_model_name: str,
        device_preference: str = "cuda",
        backend: str = "auto",
        ct2_compute_type: str = "int8_float16",
    ) -> None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, MarianTokenizer

        self.torch = torch
        self.AutoModelForSeq2SeqLM = AutoModelForSeq2SeqLM
        self.AutoTokenizer = AutoTokenizer
        self.MarianTokenizer = MarianTokenizer
        self.model_names = {
            "eng_Latn": en_zh_model_name,
            "spa_Latn": es_zh_model_name,
        }
        self.device = self._resolve_device(device_preference)
        self.backend_preference = os.getenv("MARIANMT_BACKEND", backend).strip().lower() or "auto"
        self.ct2_compute_type = os.getenv("MARIANMT_CT2_COMPUTE_TYPE", ct2_compute_type).strip() or "int8_float16"
        if self.device == "cpu" and self.ct2_compute_type == "int8_float16":
            self.ct2_compute_type = "int8"
        self._torch_models: dict[str, tuple[object, object]] = {}
        self._ct2_models: dict[str, tuple[object, object]] = {}

    def _resolve_device(self, device_preference: str) -> str:
        if device_preference == "cpu":
            return "cpu"
        return "cuda" if self.torch.cuda.is_available() else "cpu"

    def _model_name_for_source(self, source_language: str) -> str:
        return self.model_names.get(source_language, self.model_names["eng_Latn"])

    def _get_torch_model(self, source_language: str):
        model_name = self.model_names.get(source_language, self.model_names["eng_Latn"])
        if model_name not in self._torch_models:
            tokenizer = self.AutoTokenizer.from_pretrained(model_name)
            model = self.AutoModelForSeq2SeqLM.from_pretrained(model_name)
            model.to(self.device)
            model.eval()
            self._torch_models[model_name] = (tokenizer, model)
        self.engine_name = "marianmt-transformers"
        return self._torch_models[model_name]

    def _get_ct2_model(self, source_language: str):
        model_name = self._model_name_for_source(source_language)
        cache_key = f"{model_name}|{self.device}|{self.ct2_compute_type}"
        if cache_key not in self._ct2_models:
            import ctranslate2

            model_dir = self._ensure_ct2_model(model_name)
            tokenizer = self.MarianTokenizer.from_pretrained(str(model_dir), local_files_only=True)
            translator = ctranslate2.Translator(
                str(model_dir),
                device=self.device,
                compute_type=self.ct2_compute_type,
            )
            self._ct2_models[cache_key] = (tokenizer, translator)
        self.engine_name = f"marianmt-ct2-{self.ct2_compute_type}"
        return self._ct2_models[cache_key]

    def _ensure_ct2_model(self, model_name: str) -> Path:
        from ctranslate2.converters import TransformersConverter

        class CompatibleTransformersConverter(TransformersConverter):
            def load_model(self, model_class, model_name_or_path, **kwargs):
                if kwargs.get("dtype") is None:
                    kwargs.pop("dtype", None)
                return super().load_model(model_class, model_name_or_path, **kwargs)

        safe_name = "".join(char if char.isalnum() or char in "._-" else "_" for char in model_name).strip("_")
        output_dir = MARIAN_CT2_CACHE / f"{safe_name}-{self.ct2_compute_type}"
        if (output_dir / "model.bin").exists():
            self._ensure_ct2_tokenizer(model_name, output_dir)
            return output_dir

        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"[load] converting MarianMT to CTranslate2 at {output_dir}", flush=True)
        converter = CompatibleTransformersConverter(model_name)
        converter.convert(
            str(output_dir),
            quantization=None if self.ct2_compute_type == "default" else self.ct2_compute_type,
            force=True,
        )
        self._ensure_ct2_tokenizer(model_name, output_dir)
        return output_dir

    def _ensure_ct2_tokenizer(self, model_name: str, output_dir: Path) -> None:
        if (output_dir / "tokenizer_config.json").exists():
            return
        try:
            tokenizer = self.MarianTokenizer.from_pretrained(model_name, local_files_only=True)
        except Exception:
            tokenizer = self.MarianTokenizer.from_pretrained(model_name)
        tokenizer.save_pretrained(str(output_dir))

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
        if self.backend_preference != "transformers":
            try:
                return self._translate_ct2(cleaned, source_language)
            except Exception as exc:
                if self.backend_preference == "ctranslate2":
                    raise
                print(f"[warn] MarianMT CTranslate2 unavailable, falling back to Transformers: {exc}", flush=True)
        return self._translate_transformers(cleaned, source_language)

    def _translate_ct2(self, text: str, source_language: str) -> str:
        tokenizer, translator = self._get_ct2_model(source_language)
        source_tokens = tokenizer.convert_ids_to_tokens(
            tokenizer.encode(text, truncation=True, max_length=128)
        )
        results = translator.translate_batch(
            [source_tokens],
            beam_size=4,
            patience=1.0,
            length_penalty=1.05,
            repetition_penalty=1.05,
            no_repeat_ngram_size=3,
            max_decoding_length=128,
            replace_unknowns=True,
        )
        target_tokens = results[0].hypotheses[0]
        target_ids = tokenizer.convert_tokens_to_ids(target_tokens)
        return tokenizer.decode(target_ids, skip_special_tokens=True).strip()

    def _translate_transformers(self, text: str, source_language: str) -> str:
        tokenizer, model = self._get_torch_model(source_language)
        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=128)
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
