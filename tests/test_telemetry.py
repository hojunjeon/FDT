import json
from pathlib import Path

import httpx

from fdt.agent.llm import OllamaClient
from fdt.agent.telemetry import TurnLogger


def _record() -> dict:
    return {
        "ts": "2026-09-04T09:12:33.123+09:00",
        "schema_version": 1,
        "surface": "cli_chat",
        "session_id": "session-1",
        "turn": 1,
        "profile_id": "A_steady",
        "persona": "온순냥",
        "as_of": "2026-09-02",
        "llm_model": None,
        "user_message": "상태 알려줘",
        "reply": "확인했어요.",
        "route": ["get_state", "coach"],
        "tool_calls": [],
        "faithful": True,
        "first_faithful": True,
        "attempt": 0,
        "fallback": True,
        "violations": [],
        "verdict_conflict": None,
        "latency_ms": {"total": 1, "engine": 1, "llm": 0},
        "llm_calls": 0,
        "tokens": {"prompt": 0, "completion": 0},
        "llm_error": None,
    }


def test_turn_logger_appends_utf8_jsonl(tmp_path: Path) -> None:
    logger = TurnLogger(tmp_path)
    path = logger.log_turn(_record())
    logger.log_turn({**_record(), "turn": 2})

    assert path == tmp_path / "2026-09-04.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["persona"] == "온순냥"


def test_turn_logger_swallow_failures(caplog, tmp_path: Path) -> None:
    logger = TurnLogger(tmp_path)
    path = logger.log_turn({})

    assert not path.exists()
    assert "턴 로그 기록 실패" in caplog.text


def test_ollama_client_accumulates_usage_and_errors(monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "ok"}, "prompt_eval_count": 4, "eval_count": 6}

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: Response())
    client = OllamaClient(timeout=0.1)
    client.chat([])
    usage = client.usage_snapshot()
    assert usage["calls"] == 1
    assert usage["tokens"] == {"prompt": 4, "completion": 6}
    assert usage["latencies_ms"] and usage["llm_error"] is None

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("slow")))
    try:
        client.chat([])
    except httpx.ReadTimeout:
        pass
    assert client.usage_snapshot()["llm_error"]["type"] == "timeout"
