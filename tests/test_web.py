"""FDT 로컬 대시보드 HTTP 계약 테스트. 설계: docs/03_FDT_설계.md §11.3.1"""
from __future__ import annotations

import asyncio
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
    assert {"ok", "source", "engine_ready", "llm_ready", "llm_model", "fallback"} <= health_data.keys()
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
