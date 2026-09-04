"""대화 턴 JSONL 로거. 설계: PLAN.md Task A.

경로 계약(SESSIONLOG.md 확정 사양): `<로그루트>/<YYYY-MM-DD>/<surface>-<session_id>.jsonl`
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any


_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_-]")
_MAX_NAME_LEN = 80


def _safe_name(value: Any) -> str:
    """파일명에 안전하게 쓸 수 있도록 값을 정규화한다.

    `[A-Za-z0-9_-]` 이외의 문자는 `_` 로 치환하고 최대 80자로 자른다.
    값이 비었으면(치환 후 빈 문자열 포함) `unknown` 을 반환한다.
    ``../`` 나 슬래시가 섞여 있어도 전부 `_` 로 바뀌므로 로그 루트 밖으로
    나가는 경로를 만들 수 없다.
    """
    text = "" if value is None else str(value)
    text = _UNSAFE_CHARS.sub("_", text)[:_MAX_NAME_LEN]
    return text or "unknown"


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

    def path_for(self, record: dict[str, Any]) -> Path:
        """레코드로부터 로그 파일 경로를 계산한다.

        `<로그루트>/<YYYY-MM-DD>/<surface>-<session_id>.jsonl`.
        `ts` 가 없거나 파싱할 수 없으면 오늘 날짜로 폴백한다. `surface`,
        `session_id` 는 `_safe_name` 으로 정규화되어 로그 루트를 벗어나지
        않는다. 다른 모듈(웹 조회 API 등)이 같은 규칙으로 경로를 재계산할
        때 재사용한다.
        """
        directory = self._resolve_dir()
        record_dict = record if isinstance(record, dict) else {}
        try:
            record_date = self._record_date(record_dict)
        except Exception:
            record_date = date.today()
        surface = _safe_name(record_dict.get("surface"))
        session_id = _safe_name(record_dict.get("session_id"))
        return directory / record_date.isoformat() / f"{surface}-{session_id}.jsonl"

    def log_turn(self, record: dict[str, Any]) -> Path:
        """필수 필드를 확인하고 한 턴을 append한다. 실패는 경고만 남긴다."""
        directory = self._resolve_dir()
        # 검증 전 폴백 경로: 실패 시에도 새 구조(날짜 디렉터리)와 같은
        # 모양의 Path 를 반환하기 위해 미리 잡아 둔다. 실제로 쓰이지는 않는다.
        path = directory / date.today().isoformat() / "unknown-unknown.jsonl"
        try:
            if not isinstance(record, dict):
                raise TypeError("record must be a dict")
            missing = sorted(_REQUIRED_KEYS.difference(record))
            if missing:
                raise ValueError(f"missing required keys: {', '.join(missing)}")
            if record.get("schema_version") != 1:
                raise ValueError("schema_version must be 1")
            path = self.path_for(record)
            payload = dict(record)
            if isinstance(payload.get("ts"), datetime):
                payload["ts"] = payload["ts"].isoformat(timespec="milliseconds")
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            with _WRITE_LOCK:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
        except Exception as exc:  # logging must never take down the service
            _LOGGER.warning("턴 로그 기록 실패: %s", exc)
        return path


__all__ = ["TurnLogger"]
