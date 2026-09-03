"""페르소나 코칭 문장 생성 + 숫자 충실도 검사 (FDT-INT-01). 설계: docs/03_FDT_설계.md §8.3, §8.4"""
from __future__ import annotations

from typing import Any

from fdt.agent.llm import OllamaClient

PERSONAS: dict[str, str] = {"도도냥": "", "온순냥": "", "지방냥": ""}   # §8.3 의 시스템 프롬프트를 채운다


def allowed_numbers(engine_json: dict[str, Any]) -> set[int]:
    """엔진 결과의 모든 숫자 리프와 파생값(만원 반올림, 퍼센트) 집합. §8.4"""
    raise NotImplementedError


def extract_numbers(text: str) -> list[int]:
    """한국어 금액 표기(3만 5천원, 35,000원, 12%) 를 정수로. §8.4"""
    raise NotImplementedError


def check_faithful(text: str, engine_json: dict[str, Any]) -> tuple[bool, list[int]]:
    """텍스트의 모든 숫자가 허용 집합에 있으면 True. 위반 숫자 목록 반환."""
    raise NotImplementedError


def coach(client: OllamaClient, persona: str, intent: str, engine_json: dict[str, Any], user_text: str) -> dict[str, Any]:
    """생성 -> 검사 -> 실패 시 1회 재생성 -> 실패 시 템플릿 폴백. 반환에 faithful/fallback 플래그 포함."""
    raise NotImplementedError


def template_fallback(intent: str, engine_json: dict[str, Any], persona: str) -> str:
    """LLM 없이 숫자만 끼워 넣는 결정론 문장. §8.5"""
    raise NotImplementedError
