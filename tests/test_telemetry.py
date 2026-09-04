import json
from pathlib import Path

import httpx

from fdt.agent.llm import OllamaClient
from fdt.agent.telemetry import TurnLogger, _safe_name


def _record(**overrides) -> dict:
    base = {
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
    base.update(overrides)
    return base


def test_turn_logger_appends_utf8_jsonl(tmp_path: Path) -> None:
    logger = TurnLogger(tmp_path)
    path = logger.log_turn(_record())
    logger.log_turn({**_record(), "turn": 2})

    assert path == tmp_path / "2026-09-04" / "cli_chat-session-1.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["persona"] == "온순냥"


def test_turn_logger_swallow_failures(caplog, tmp_path: Path) -> None:
    logger = TurnLogger(tmp_path)
    path = logger.log_turn({})

    assert not path.exists()
    assert "턴 로그 기록 실패" in caplog.text


def test_different_session_ids_go_to_different_files(tmp_path: Path) -> None:
    logger = TurnLogger(tmp_path)
    path_a = logger.log_turn(_record(session_id="session-a"))
    path_b = logger.log_turn(_record(session_id="session-b"))

    assert path_a != path_b
    assert path_a.name == "cli_chat-session-a.jsonl"
    assert path_b.name == "cli_chat-session-b.jsonl"
    assert path_a.exists() and path_b.exists()


def test_same_session_id_appends_to_one_file(tmp_path: Path) -> None:
    logger = TurnLogger(tmp_path)
    path1 = logger.log_turn(_record(session_id="session-x", turn=1))
    path2 = logger.log_turn(_record(session_id="session-x", turn=2))

    assert path1 == path2
    rows = [json.loads(line) for line in path1.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert [row["turn"] for row in rows] == [1, 2]


def test_surface_splits_files(tmp_path: Path) -> None:
    logger = TurnLogger(tmp_path)
    path_web = logger.log_turn(_record(surface="web", session_id="s1"))
    path_cli = logger.log_turn(_record(surface="cli_brief", session_id="s1"))

    assert path_web != path_cli
    assert path_web.name == "web-s1.jsonl"
    assert path_cli.name == "cli_brief-s1.jsonl"


def test_dangerous_session_id_is_sanitized_and_stays_inside_log_root(tmp_path: Path) -> None:
    logger = TurnLogger(tmp_path)
    dangerous = "../../etc/passwd 세션 이름"
    path = logger.log_turn(_record(session_id=dangerous))

    # 로그 루트 밖으로 나가지 않는다: 항상 <root>/<날짜>/<파일명> 형태여야 한다.
    assert path.parent.parent.resolve() == tmp_path.resolve()
    # 위험 문자는 전부 치환되어 실제 슬래시나 상위 디렉터리 이동이 없다.
    assert ".." not in path.name
    assert "/" not in path.name and "\\" not in path.name
    assert path.exists()


def test_safe_name_helper_handles_slashes_and_empty_values() -> None:
    assert _safe_name("../../secret") == "______secret"
    assert _safe_name("") == "unknown"
    assert _safe_name(None) == "unknown"
    assert _safe_name("a b/c") == "a_b_c"
    assert _safe_name("x" * 200) == "x" * 80


def test_different_ts_dates_go_to_different_date_directories(tmp_path: Path) -> None:
    logger = TurnLogger(tmp_path)
    path_day1 = logger.log_turn(_record(ts="2026-09-04T23:59:59+09:00", session_id="s"))
    path_day2 = logger.log_turn(_record(ts="2026-09-05T00:00:01+09:00", session_id="s"))

    assert path_day1.parent != path_day2.parent
    assert path_day1.parent.name == "2026-09-04"
    assert path_day2.parent.name == "2026-09-05"


def test_path_for_is_reusable_and_pure(tmp_path: Path) -> None:
    logger = TurnLogger(tmp_path)
    record = _record(surface="eval", session_id="abc")
    expected = tmp_path / "2026-09-04" / "eval-abc.jsonl"

    assert logger.path_for(record) == expected
    # 여러 번 호출해도 부작용(파일 생성 등)이 없다.
    assert not expected.exists()


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
