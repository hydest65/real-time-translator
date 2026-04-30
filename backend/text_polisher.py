from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import requests

from .config import AppConfig


@dataclass
class PolishResult:
    text: str
    engine: str


class MiniMaxTextPolisher:
    """Improve final Chinese subtitles without blocking Azure live captions."""

    engine_name = "minimax"

    def __init__(self, active_config: AppConfig) -> None:
        self.api_key = active_config.minimax_api_key or os.getenv("MINIMAX_API_KEY", "")
        self.base_url = (active_config.minimax_base_url or os.getenv("MINIMAX_BASE_URL", "")).rstrip("/")
        self.model = active_config.minimax_model or os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
        self.timeout_seconds = active_config.minimax_timeout_seconds
        self.enabled = bool(self.api_key and self.base_url and self.model)

    async def polish(self, source_text: str, azure_translation: str, mode: str) -> PolishResult | None:
        if not self.enabled:
            return None
        return await asyncio.to_thread(self._polish_sync, source_text, azure_translation, mode)

    def _polish_sync(self, source_text: str, azure_translation: str, mode: str) -> PolishResult | None:
        prompt = build_prompt(source_text, azure_translation, mode)
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": DOMAIN_SUBTITLE_TRANSLATOR_PROMPT,
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 180,
                "max_completion_tokens": 180,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message") or {}
        text = strip_thinking(str(message.get("content") or ""))
        if not text:
            return None
        return PolishResult(text=text, engine=self.engine_name)


DOMAIN_SUBTITLE_TRANSLATOR_PROMPT = """You are a professional real-time subtitle translator for engineering, pharmaceutical facility, chemical process, cleanroom, utility, HVAC, and modular construction meetings.

Translate English, Japanese, or Spanish source text into natural Simplified Chinese subtitles.

Rules:
1. Automatically identify the source language: English, Japanese, or Spanish.
2. Translate accurately into Simplified Chinese.
3. Keep the Chinese concise, natural, professional, and suitable for real-time subtitles.
4. Do not add, omit, explain, summarize, or speculate.
5. If the source text is incomplete or fragmented, translate only the clear meaning and do not guess.
6. Preserve all numbers, units, dimensions, equipment tags, room numbers, drawing numbers, document numbers, revision numbers, company names, product names, and system names.
7. Preserve common technical abbreviations, including AHU, BMS, EMS, HVAC, HEPA, ULPA, WFI, PW, CIP, SIP, CUSP, URS, DQ, IQ, OQ, PQ, FAT, SAT, P&ID, PFD, GA, GMP, cGMP, GEP, GAMP, VHP, BIBO, RABS, OEB, OEL, API, HPAPI, ATEX, HAZOP, LOPA, SIL, EHS, HSE, MEP, BIM, IFC, RFI, NCR, CAPA.
8. Use professional Chinese terminology for engineering design, pharmaceutical manufacturing, cleanroom, HVAC, utilities, process piping, automation, fire protection, validation, commissioning, and modular construction.
9. Prefer short subtitle-style output. Usually keep the output within 30-45 Chinese characters unless technical meaning requires more.
10. Output only the final Simplified Chinese subtitle, without quotation marks, labels, explanations, or extra notes.

Key terminology:
- utility / utilities -> 公用工程
- cleanroom -> 洁净室 / 洁净区
- ceiling -> 吊顶
- duct -> 风管
- supply air -> 送风
- return air -> 回风
- exhaust air -> 排风
- AHU -> AHU / 空调机组
- BMS -> BMS / 楼宇自控系统
- EMS -> EMS / 环境监测系统
- tie-in point -> 接驳点
- pipe rack -> 管架 / 管廊
- chilled water -> 冷冻水
- cooling water -> 冷却水
- compressed air -> 压缩空气
- clean steam / pure steam -> 纯蒸汽
- purified water / PW -> 纯化水 / PW
- water for injection / WFI -> 注射用水 / WFI
- CIP -> 在线清洗 / CIP
- SIP -> 在线灭菌 / SIP
- isolator -> 隔离器
- RABS -> 限制进入屏障系统 / RABS
- OEB -> 职业暴露等级 / OEB
- OEL -> 职业暴露限值 / OEL
- API -> 原料药 / API
- HPAPI -> 高活性原料药 / HPAPI
- modular construction -> 模块化建设
- module -> 模块
- skid -> 撬装模块
- prefabrication -> 预制
- FAT -> 工厂验收测试 / FAT
- SAT -> 现场验收测试 / SAT
- commissioning -> 调试
- qualification -> 确认
- validation -> 验证"""


def build_prompt(source_text: str, azure_translation: str, mode: str) -> str:
    if mode == "quality":
        return (
            "Translate this source subtitle into Simplified Chinese according to the system rules. "
            "Return only the final Chinese subtitle.\n\n"
            f"Source: {source_text}"
        )
    return (
        "Improve or retranslate this live subtitle according to the system rules. "
        "Use the source as the authority. Use the current Chinese only as a reference. "
        "Return only the final Chinese subtitle.\n\n"
        f"Source: {source_text}\n"
        f"Current Chinese: {azure_translation}"
    )


def strip_thinking(text: str) -> str:
    cleaned = text.replace("<think>", "").replace("</think>", "").strip()
    if "\n" in cleaned:
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        cleaned = lines[-1] if lines else cleaned
    for prefix in ("Chinese:", "Translation:", "Simplified Chinese:", "中文：", "中文:", "译文：", "译文:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    return cleaned.strip("\"' ")


def has_minimax_config(active_config: AppConfig) -> bool:
    api_key = active_config.minimax_api_key or os.getenv("MINIMAX_API_KEY", "")
    base_url = (active_config.minimax_base_url or os.getenv("MINIMAX_BASE_URL", "")).rstrip("/")
    model = active_config.minimax_model or os.getenv("MINIMAX_MODEL", "")
    return bool(api_key and base_url and model)
