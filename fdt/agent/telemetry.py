"""대화 턴 JSONL 로거. 설계: PLAN.md Task A."""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any


_REQUIRED_KEYS = frozenset(
    {
        "ts",
        "schema_version",
        "surface",
        "session_id",
        "turn",
        "profile_id",
        "persona",
        "as_of",
        "llm_model",
        "user_message",
        "reply",
        "route",
        "tool_calls",
        "faithful",
        "first_faithful",
        "attempt",
        "fallback",
        "violations",
        "verdict_conflict",
        "latency_ms",
        "llm_calls",
        "tokens",
        "llm_error",
    }
)
_WRITE_LOCK = threading.Lock()
_LOGGER = logging.getLogger(__name__)


class TurnLogger:
    """대화 턴을 날짜별 UTF-8 JSONL 파일에 추가한다."""

    def __init__(self, log_dir: Path | None = None):
        self._log_dir = Path(log_dir) if log_dir is not None else None

    @property
    def log_dir(self) -> Path:
        """현재 로그 디렉터리를 반환한다."""
        return self._resolve_dir()

    def _resolve_dir(self) -> Path:
        if self._log_dir is not None:
            return self._log_dir
        configured = os.getenv("FDT_TURN_LOG_DIR")
        if configured:
            return Path(configured)
        return Path(__file__).resolve().parents[2] / "log" / "turns"

    @staticmethod
    def _record_date(record: dict[str, Any]) -> date:
        value = record["ts"]
        if isinstance(value, datetime):
            return value.date()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()

    def log_turn(self, record: dict[str, Any]) -> Path:
        """필수 필드를 확인하고 한 턴을 append한다. 실패는 경고만 남긴다."""
        directory = self._resolve_dir()
        path = directory / f"{date.today().isoformat()}.jsonl"
        try:
            if not isinstance(record, dict):
                raise TypeError("record must be a dict")
            missing = sorted(_REQUIRED_KEYS.difference(record))
            if missing:
                raise ValueError(f"missing required keys: {', '.join(missing)}")
            if record.get("schema_version") != 1:
                raise ValueError("schema_version must be 1")
            path = directory / f"{self._record_date(record).isoformat()}.jsonl"
            payload = dict(record)
            if isinstance(payload.get("ts"), datetime):
                payload["ts"] = payload["ts"].isoformat(timespec="milliseconds")
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            with _WRITE_LOCK:
                directory.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
        except Exception as exc:  # logging must never take down the service
            _LOGGER.warning("턴 로그 기록 실패: %s", exc)
        return path


__all__ = ["TurnLogger"]
