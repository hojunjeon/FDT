"""FDT 로컬 대시보드 HTTP 계약 테스트. 설계: docs/03_FDT_설계.md §11.3.1"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from fdt.web import app


class _ASGIClient:
    """Starlette TestClient의 httpx2 전환 경고를 피하는 작은 동기 어댑터."""

    def _request(self, method: str, path: str, **kwargs):
        async def request():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(request())

    def get(self, path: str, **kwargs):
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self._request("POST", path, **kwargs)


client = _ASGIClient()


def test_static_health_and_profiles() -> None:
    """정적 파일·상태·프로필 목록이 UTF-8 JSON으로 제공된다. §11.3.1"""
    root = client.get("/")
    assert root.status_code == 200
    assert "Finance Digital Twin" in root.text
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200

    health = client.get("/api/health")
    assert health.status_code == 200, health.text
    health_data = health.json()
    assert {"ok", "source", "engine_ready", "llm_ready", "llm_model", "fallback", "turn_log_dir"} <= health_data.keys()
    assert health_data["source"] == "DEMO"
    assert isinstance(health_data["engine_ready"], bool)

    profiles = client.get("/api/profiles")
    assert profiles.status_code == 200
    profile_data = profiles.json()
    assert {item["id"] for item in profile_data["profiles"]} >= {"A_steady", "B_card_crunch", "C_impulsive"}
    assert {item["id"] for item in profile_data["coach_personas"]} == {"도도냥", "온순냥", "지방냥"}
    assert all("coach_persona" not in item for item in profile_data["profiles"])


def test_dashboard_runtime_and_persona_contract() -> None:
    """runtime 상태와 코치 헤더 갱신 계약이 정적 JS에 남아 있다. §11.3.1"""
    script = (Path(__file__).parents[1] / "fdt" / "static" / "app.js").read_text(encoding="utf-8")
    assert "engine_ready:" in script
    assert "fallback:" in script
    assert "renderAgentHeader();" in script


def test_profile_bundle_has_core_results() -> None:
    """프로필 조회는 State·RiskResult·RoomProjection을 함께 반환한다. §11.3.1"""
    response = client.get("/api/profiles/A_steady")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source"] == "DEMO"
    assert payload["profile"]["id"] == "A_steady"
    assert payload["state"]["as_of"] == payload["profile"]["as_of"]
    assert {"liquidity", "envelopes", "next_income_date"} <= payload["state"].keys()
    assert {"risk_score", "shortfall_prob", "level"} <= payload["risk"].keys()
    assert {"weather", "avatar_mood", "board_progress"} <= payload["room"].keys()


def test_chat_start_message_end_and_separate_persona() -> None:
    """start → message → end가 동작하고 프로필·코치 선택이 분리된다. §11.3.1"""
    start = client.post("/api/chat/start", json={"profile_id": "A_steady", "coach_persona": "도도냥"})
    assert start.status_code == 200, start.text
    start_data = start.json()
    assert start_data["profile_id"] == "A_steady"
    assert start_data["coach_persona"] == "도도냥"
    session_id = start_data["session_id"]

    message = client.post(
        "/api/chat/message",
        json={"session_id": session_id, "message": "오늘 안심하고 쓸 수 있는 돈이 얼마야?"},
    )
    assert message.status_code == 200, message.text
    message_data = message.json()
    assert {"message", "route", "results", "faithful", "fallback"} <= message_data.keys()
    assert message_data["route"][-1] == "coach"
    assert message_data["results"]
    assert {"tool", "data", "visualization"} <= message_data["results"][0].keys()
    assert message_data["persona"] == "도도냥"

    end = client.post("/api/chat/end", json={"session_id": session_id})
    assert end.status_code == 200
    assert end.json()["active"] is False
    assert client.post("/api/chat/message", json={"session_id": session_id, "message": "다시"}).status_code == 404


def test_invalid_profile_persona_session_and_message() -> None:
    """잘못된 경계 입력은 404/422로 구분한다. §11.3.1"""
    assert client.get("/api/profiles/not-a-profile").status_code == 404
    assert client.post(
        "/api/chat/start", json={"profile_id": "A_steady", "coach_persona": "없는냥"}
    ).status_code == 422
    assert client.post("/api/chat/message", json={"session_id": "missing", "message": "x"}).status_code == 404
    assert client.post("/api/chat/message", json={"session_id": "missing", "message": ""}).status_code == 422


def test_chat_turn_logs_are_readable_and_filterable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FDT_TURN_LOG_DIR", str(tmp_path))
    start = client.post("/api/chat/start", json={"profile_id": "A_steady", "coach_persona": "온순냥"})
    assert start.status_code == 200
    session_id = start.json()["session_id"]
    message = client.post(
        "/api/chat/message",
        json={"session_id": session_id, "message": "오늘 얼마까지 써도 돼?"},
    )
    assert message.status_code == 200

    logs = client.get("/api/logs/turns", params={"session_id": session_id, "limit": 50})
    assert logs.status_code == 200
    payload = logs.json()
    assert len(payload["turns"]) == 2
    assert [row["turn"] for row in payload["turns"]] == [2, 1]
    assert all(row["session_id"] == session_id for row in payload["turns"])
    client.post("/api/chat/end", json={"session_id": session_id})


def test_turn_logs_limit_reads_latest_files_first(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FDT_TURN_LOG_DIR", str(tmp_path))
    older = {
        "ts": "2026-09-03T09:00:00+09:00",
        "session_id": "s-old",
        "turn": 1,
    }
    latest = [
        {"ts": "2026-09-04T09:00:00+09:00", "session_id": "s-new", "turn": 1},
        {"ts": "2026-09-04T10:00:00+09:00", "session_id": "s-new", "turn": 2},
    ]
    (tmp_path / "2026-09-03.jsonl").write_text(json.dumps(older) + "\n", encoding="utf-8")
    (tmp_path / "2026-09-04.jsonl").write_text("\n".join(json.dumps(row) for row in latest) + "\n", encoding="utf-8")

    response = client.get("/api/logs/turns", params={"limit": 2})

    assert response.status_code == 200
    assert [row["ts"] for row in response.json()["turns"]] == [
        "2026-09-04T10:00:00+09:00",
        "2026-09-04T09:00:00+09:00",
    ]


def test_turn_logs_reverse_blocks_filter_across_files_and_decode_korean(monkeypatch, tmp_path: Path) -> None:
    import fdt.web as web

    monkeypatch.setenv("FDT_TURN_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(web, "_LOG_READ_BLOCK_SIZE", 13)
    older = [
        {"ts": "2026-09-03T09:00:00+09:00", "session_id": "target", "reply": "오래된 한글"},
        {"ts": "2026-09-03T09:01:00+09:00", "session_id": "other", "reply": "이전 기록"},
        {"ts": "2026-09-03T09:02:00+09:00", "session_id": "target", "reply": "경계 이전"},
    ]
    latest = [
        {"ts": "2026-09-04T09:57:00+09:00", "session_id": "other", "reply": "무관한 기록"},
        {"ts": "2026-09-04T09:58:00+09:00", "session_id": "target", "reply": "최신 둘째"},
        {"ts": "2026-09-04T09:59:00+09:00", "session_id": "other", "reply": "최신 기록"},
        {"ts": "2026-09-04T10:00:00+09:00", "session_id": "target", "reply": "최신 한글"},
    ]
    (tmp_path / "2026-09-03.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in older) + "\n", encoding="utf-8"
    )
    (tmp_path / "2026-09-04.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in latest) + "\n", encoding="utf-8"
    )

    latest_response = client.get("/api/logs/turns", params={"limit": 3})
    assert [row["ts"] for row in latest_response.json()["turns"]] == [
        "2026-09-04T10:00:00+09:00",
        "2026-09-04T09:59:00+09:00",
        "2026-09-04T09:58:00+09:00",
    ]

    filtered_response = client.get(
        "/api/logs/turns", params={"limit": 3, "session_id": "target"}
    )
    filtered = filtered_response.json()["turns"]
    assert [row["ts"] for row in filtered] == [
        "2026-09-04T10:00:00+09:00",
        "2026-09-04T09:58:00+09:00",
        "2026-09-03T09:02:00+09:00",
    ]
    assert [row["reply"] for row in filtered] == ["최신 한글", "최신 둘째", "경계 이전"]
