"""로컬 LLM 클라이언트 (Ollama). 설계: docs/03_FDT_설계.md §8.1

기본 모델: qwen2.5:7b-instruct-q4_K_M (tool calling 지원, VRAM 8GB 적합).
환경변수 FDT_OLLAMA_URL, FDT_LLM_MODEL 로 덮어쓴다.
"""
from __future__ import annotations

from typing import Any

import httpx

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_K_M"


class OllamaClient:
    def __init__(self, url: str = DEFAULT_URL, model: str = DEFAULT_MODEL, timeout: float = 120.0):
        self.url, self.model, self.timeout = url, model, timeout

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             temperature: float = 0.0, json_mode: bool = False) -> dict[str, Any]:
        """POST /api/chat (stream=false). 응답 message 를 그대로 반환. §8.1"""
        raise NotImplementedError

    def available(self) -> bool:
        """서버 응답 + 모델 존재 확인."""
        raise NotImplementedError
