"""로컬 LLM 클라이언트 (Ollama). 설계: docs/03_FDT_설계.md §8.1

기본 모델: qwen2.5:7b-instruct-q4_K_M (tool calling 지원, VRAM 8GB 적합).
환경변수 FDT_OLLAMA_URL, FDT_LLM_MODEL 로 덮어쓴다.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from typing import Any

import httpx

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_K_M"


class OllamaClient:
    def __init__(self, url: str | None = None, model: str | None = None, timeout: float = 120.0):
        self.url = (url or os.getenv("FDT_OLLAMA_URL", DEFAULT_URL)).rstrip("/")
        self.model = model or os.getenv("FDT_LLM_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self.reset_usage()

    def reset_usage(self) -> None:
        """현재 인스턴스의 LLM 호출 누적치를 초기화한다."""
        self._usage: dict[str, Any] = {
            "calls": 0,
            "latency_ms": 0.0,
            "latencies_ms": [],
            "tokens": {"prompt": 0, "completion": 0},
            "errors": [],
        }

    def usage_snapshot(self) -> dict[str, Any]:
        """턴 경계에서 읽을 수 있는 LLM 호출 누적치의 복사본을 반환한다."""
        errors = [dict(item) for item in self._usage["errors"]]
        return {
            "calls": int(self._usage["calls"]),
            "llm_calls": int(self._usage["calls"]),
            "latency_ms": round(float(self._usage["latency_ms"]), 3),
            "latencies_ms": [round(float(value), 3) for value in self._usage["latencies_ms"]],
            "tokens": dict(self._usage["tokens"]),
            "errors": errors,
            "llm_error": errors[-1] if errors else None,
        }

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             temperature: float = 0.0, json_mode: bool = False) -> dict[str, Any]:
        """POST /api/chat (stream=false). 응답 message 를 그대로 반환. §8.1"""
        started = time.perf_counter()
        self._usage["calls"] += 1
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": 8192},
        }
        if tools:
            payload["tools"] = tools
        if json_mode:
            payload["format"] = "json"
        try:
            response = httpx.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, Mapping):
                self._usage["tokens"]["prompt"] += _count(data.get("prompt_eval_count"))
                self._usage["tokens"]["completion"] += _count(data.get("eval_count"))
                return data.get("message", data)
            raise ValueError("Ollama 응답이 JSON 객체가 아닙니다")
        except Exception as exc:
            error = {"type": _error_type(exc), "message": str(exc)}
            self._usage["errors"].append(error)
            raise
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self._usage["latency_ms"] += elapsed
            self._usage["latencies_ms"].append(elapsed)

    def available(self) -> bool:
        """서버 응답 + 모델 존재 확인."""
        try:
            response = httpx.get(f"{self.url}/api/tags", timeout=self.timeout)
            response.raise_for_status()
            models = response.json().get("models", [])
            return any(
                isinstance(item, dict) and item.get("name") == self.model
                for item in models
            )
        except (httpx.HTTPError, ValueError, TypeError):
            return False


def _count(value: Any) -> int:
    """Ollama 사용량 필드를 안전한 음이 아닌 정수로 바꾼다."""
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _error_type(exc: Exception) -> str:
    """예외를 턴 로그의 네 가지 오류 종류로 분류한다."""
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "timeout"
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, ConnectionError)):
        return "connection"
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return "parse"
    return "other"
