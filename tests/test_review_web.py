"""웹 경계: 로그 접근·시간 정렬·세션 만료·전역 잠금·오류 상태."""
import asyncio
import json
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

import fdt.web as web


def request(method, path, *, peer="127.0.0.1", **kwargs):
    async def run():
        transport = httpx.ASGITransport(app=web.app, client=(peer, 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(run())


def test_logs_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FDT_ENABLE_LOG_API", raising=False)
    assert request("GET", "/api/logs/turns").status_code == 404


def test_logs_reject_remote_clients_even_when_enabled(monkeypatch):
    monkeypatch.setenv("FDT_ENABLE_LOG_API", "1")
    assert request("GET", "/api/logs/turns", peer="198.51.100.1").status_code == 403


def test_log_limit_merges_interleaved_sessions_by_timestamp(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text('\n'.join(json.dumps({"ts": f"2026-09-05T{hour}:00:00+09:00"}) for hour in ("09", "12")) + '\n')
    b.write_text(json.dumps({"ts": "2026-09-05T11:00:00+09:00"}) + '\n')
    result = web._read_turn_records([a, b], 2, None)
    assert [row["ts"][11:13] for row in result] == ["12", "11"]


def test_log_sort_normalizes_timezones_and_puts_invalid_dates_last(tmp_path):
    path = tmp_path / "a.jsonl"
    rows = [{"ts": "2026-09-05T01:00:00Z"}, {"ts": "invalid"}, {"ts": "2026-09-05T09:00:00+09:00"}]
    path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
    assert [r["ts"] for r in web._read_turn_records([path], 3, None)] == [rows[0]["ts"], rows[2]["ts"], "invalid"]


def test_session_filter_keeps_legacy_and_new_logs(monkeypatch, tmp_path):
    monkeypatch.setenv("FDT_ENABLE_LOG_API", "1")
    monkeypatch.setenv("FDT_TURN_LOG_DIR", str(tmp_path))
    (tmp_path / "2026-09-05").mkdir()
    rows = [{"ts": f"2026-09-05T{h}:00:00+09:00", "session_id": "same"} for h in ("09", "10")]
    (tmp_path / "2026-09-05.jsonl").write_text(json.dumps(rows[0]) + '\n')
    (tmp_path / "2026-09-05/web-same.jsonl").write_text(json.dumps(rows[1]) + '\n')
    assert len(request("GET", "/api/logs/turns?session_id=same").json()["turns"]) == 2


def test_expired_session_cannot_call_agent(monkeypatch):
    session = SimpleNamespace(lock=threading.Lock(), active=True, last_used=0)
    monkeypatch.setattr(web, "_SESSIONS", {"expired": session})
    monkeypatch.setattr(web.time, "monotonic", lambda: 1801.0)
    response = request("POST", "/api/chat/message", json={"session_id": "expired", "message": "잔액"})
    assert response.status_code == 404
    assert not session.active


def test_pending_starts_count_toward_session_limit(monkeypatch):
    monkeypatch.setattr(web, "_SESSIONS", {})
    monkeypatch.setattr(web, "_MAX_SESSIONS", 1)
    monkeypatch.setattr(web, "_PENDING_STARTS", 1)
    monkeypatch.setattr(web, "_build_context", lambda *a: pytest.fail("must reject before computation"))
    response = request("POST", "/api/chat/start", json={"profile_id": "A_steady", "coach_persona": "온순냥"})
    assert response.status_code == 429


def test_end_waiting_for_session_does_not_hold_registry_lock(monkeypatch):
    entered = threading.Event()
    held = threading.Lock()
    held.acquire()
    class ObservedLock:
        def __enter__(self):
            entered.set()
            held.acquire()
        def __exit__(self, *args):
            held.release()
    session = SimpleNamespace(lock=ObservedLock(), active=True)
    monkeypatch.setattr(web, "_SESSIONS", {"busy": session})
    completed = []
    worker = threading.Thread(target=lambda: completed.append(web.end_chat(web.ChatEndRequest(session_id="busy"))))
    worker.start()
    try:
        assert entered.wait(timeout=2)
        acquired = web._SESSIONS_LOCK.acquire(timeout=1)
        if acquired:
            web._SESSIONS_LOCK.release()
        assert acquired, "end_chat must not hold the global lock while waiting"
    finally:
        held.release()
        worker.join(timeout=2)
    assert not worker.is_alive()
    assert completed[0]["active"] is False


def test_health_and_liveness_do_not_run_simulations(monkeypatch):
    monkeypatch.setattr(web, "_build_context", lambda *a: pytest.fail("health must not simulate"))
    assert request("GET", "/api/live").json() == {"ok": True}
    assert request("GET", "/api/health").status_code == 200


def test_failed_tool_has_no_success_visualization():
    result = web._chat_results({"tool_calls": [{"name": "get_state", "result": {"error": "failure", "status": "error"}}]})
    assert result[0]["visualization"] is None


def test_risk_visualization_keeps_score_and_probability_units_separate():
    result = web._result_visualization("payment_risk", {"risk_score": 50, "shortfall_prob": 0.2, "card_shortfall_prob": 0.5})
    assert result["type"] == "table"
    assert result["columns"][1]["format"] == "percent"
    assert result["rows"][0]["card_shortfall_prob"] == 0.5


def test_web_exposes_execution_status(monkeypatch):
    session = SimpleNamespace(lock=threading.Lock(), active=True, last_used=web.time.monotonic(), turn=0,
                             id="s", coach_persona="온순냥", agent=SimpleNamespace(ask=lambda _: {
                                 "reply": "계산 실패", "status": "error", "faithful": False, "tool_calls": []}))
    monkeypatch.setattr(web, "_SESSIONS", {"s": session})
    monkeypatch.setattr(web, "_log_web_turn", lambda **kwargs: None)
    result = request("POST", "/api/chat/message", json={"session_id": "s", "message": "잔액"}).json()
    assert result["status"] == "error"
    assert result["faithful"] is False
