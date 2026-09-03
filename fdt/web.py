"""로컬 대시보드용 FastAPI 어댑터. 설계: docs/03_FDT_설계.md §9.2"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from fdt.agent.agent import FdtAgent
from fdt.agent.llm import DEFAULT_MODEL, DEFAULT_URL, OllamaClient
from fdt.agent.tools import TwinContext
from fdt.ledger.ingest import ingest, load_snapshot
from fdt.schemas.domain import LedgerTx, RiskResult, RoomProjection, State
from fdt.twin.analytics import detect_alerts, health
from fdt.twin.behavior import estimate_behavior
from fdt.twin.projection import project_room
from fdt.twin.simulate import risk
from fdt.twin.state import build_state


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
SEED_DIR = PROJECT_DIR / "data" / "seed"
STATIC_DIR = BASE_DIR / "static"
COACH_PERSONAS = (
    {"id": "도도냥", "name": "도도냥", "description": "짧고 직설적인 코치"},
    {"id": "온순냥", "name": "온순냥", "description": "부드럽고 격려하는 코치"},
    {"id": "지방냥", "name": "지방냥", "description": "구수한 사투리 코치"},
)
COACH_PERSONA_IDS = frozenset(item["id"] for item in COACH_PERSONAS)


class ChatStartRequest(BaseModel):
    """대화 시작 경계 입력. §9.2.2"""

    profile_id: str = Field(min_length=1, max_length=64)
    coach_persona: str = Field(min_length=1, max_length=20)
    as_of: date | None = None


class ChatMessageRequest(BaseModel):
    """대화 메시지 경계 입력. §9.2.2"""

    session_id: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=1000)

    @field_validator("message")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class ChatEndRequest(BaseModel):
    """대화 종료 경계 입력. §9.2.2"""

    session_id: str = Field(min_length=1, max_length=80)


class EngineLoadError(RuntimeError):
    """시드 또는 FDT 코어를 준비하지 못한 경우."""


@dataclass
class _Session:
    id: str
    profile_id: str
    coach_persona: str
    ctx: TwinContext
    agent: FdtAgent
    risk_result: RiskResult
    room: RoomProjection
    lock: threading.Lock = field(default_factory=threading.Lock)


_SESSIONS: dict[str, _Session] = {}
_SESSIONS_LOCK = threading.Lock()

app = FastAPI(
    title="FDT Local Dashboard",
    version="0.1.0",
    description="더미 금융 데이터 기반 개인 금융 디지털 트윈 대시보드",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _snapshot_path(profile_id: str) -> Path:
    """검증된 프로필 ID를 시드 스냅샷 경로로 변환한다. §9.2.3"""
    path = SEED_DIR / profile_id / "snapshot.json"
    if not path.is_file():
        raise KeyError(profile_id)
    return path


@lru_cache(maxsize=8)
def _load_seed(profile_id: str) -> tuple[Any, tuple[LedgerTx, ...]]:
    """프로필 스냅샷과 불변 원장을 한 번만 인입한다. §9.2.3"""
    try:
        snap = load_snapshot(_snapshot_path(profile_id))
        return snap, tuple(ingest(snap))
    except KeyError:
        raise
    except Exception as exc:  # pragma: no cover - concrete cause is environment-specific
        raise EngineLoadError(f"프로필 {profile_id} 엔진 입력을 읽지 못했습니다: {exc}") from exc


def _profile_ids() -> list[str]:
    """사용 가능한 DEMO 금융 사용자 프로필 ID를 반환한다. §9.2.2"""
    return sorted(
        path.name
        for path in SEED_DIR.iterdir()
        if path.is_dir() and (path / "snapshot.json").is_file()
    ) if SEED_DIR.is_dir() else []


def _profile_meta(profile_id: str) -> dict[str, Any]:
    """금융 사용자 메타데이터만 반환하고 코치 페르소나와 섞지 않는다. §9.2.1"""
    snap, txs = _load_seed(profile_id)
    profile_file = SEED_DIR / profile_id / "profile.yaml"
    config: dict[str, Any] = {}
    if profile_file.is_file():
        try:
            config = yaml.safe_load(profile_file.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            config = {}
    as_of = max((tx.day for tx in txs), default=date.fromisoformat(snap.generatedAt[:10]))
    return {
        "id": profile_id,
        "name": snap.userName,
        "description": str(config.get("description", "더미 금융 사용자")),
        "source": "DEMO",
        "as_of": as_of.isoformat(),
        "currency": "KRW",
    }


def _resolve_as_of(profile_id: str, requested: date | None) -> date:
    """기준일을 검증하고 데이터 범위 안에서 확정한다. §9.2.3"""
    _, txs = _load_seed(profile_id)
    days = [tx.day for tx in txs]
    if not days:
        return requested or date.today()
    first, last = min(days), max(days)
    cutoff = requested or last
    if cutoff < first or cutoff > last:
        raise HTTPException(
            status_code=422,
            detail=f"as_of는 {first.isoformat()}~{last.isoformat()} 범위여야 합니다.",
        )
    return cutoff


def _build_context(profile_id: str, requested_as_of: date | None = None) -> tuple[TwinContext, RiskResult, RoomProjection]:
    """원장부터 TwinContext·위험·방 상태를 조립한다. §9.2.3"""
    try:
        snap, source_txs = _load_seed(profile_id)
        txs = list(source_txs)
        as_of = _resolve_as_of(profile_id, requested_as_of)
        state = build_state(txs, snap, as_of)
        budgets = {item.envelope: item.budget for item in state.envelopes}
        behavior = estimate_behavior(txs, as_of, budgets=budgets)
        risk_result = risk(state, behavior, horizon_days=30, seed=42)
        score, level = health(state, risk_result)
        state = state.model_copy(update={"health_score": score, "health_level": level})
        today_txs = [tx for tx in txs if tx.day == as_of]
        room = project_room(state, detect_alerts(state, behavior, today_txs))
        ctx = TwinContext(snap=snap, txs=txs, state=state, behavior=behavior, seed=42)
        return ctx, risk_result, room
    except HTTPException:
        raise
    except KeyError as exc:
        raise exc
    except Exception as exc:
        raise EngineLoadError(f"프로필 {profile_id} 엔진을 준비하지 못했습니다: {exc}") from exc


def _dump(value: Any) -> Any:
    """코어 모델을 JSON 표현으로만 변환한다. §9.2.2"""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return jsonable_encoder(value)


def _client() -> OllamaClient:
    """환경변수 기반 로컬 LLM 클라이언트를 만든다. §8.1"""
    try:
        timeout = float(os.getenv("FDT_LLM_TIMEOUT", "20.0"))
    except ValueError:
        timeout = 1.0
    return OllamaClient(
        url=os.getenv("FDT_OLLAMA_URL", DEFAULT_URL),
        model=os.getenv("FDT_LLM_MODEL", DEFAULT_MODEL),
        timeout=max(0.1, timeout),
    )


def _initial_message(persona: str) -> str:
    """세션 시작용 고정 인사. 금융 숫자를 만들지 않는다. §9.2.2"""
    return {
        "도도냥": "상태 확인 끝났냥. 궁금한 걸 물어보라냥.",
        "지방냥": "상태 확인했시봉. 궁금한 건 편하게 물어보소.",
    }.get(persona, "상태 확인했어요. 궁금한 내용을 물어보세요, 냥.")


def _result_visualization(tool: str, raw_data: Any) -> dict[str, Any] | None:
    """코어 결과를 화면 명세로 감싼다. 수치·판정은 재계산하지 않는다. §9.2.2"""
    data = _dump(raw_data)

    if tool == "spending_alerts":
        items = data if isinstance(data, list) else []
        if not items:
            return None
        rows = [{"severity": item.get("severity"), "kind": item.get("kind"), "message": item.get("message")} for item in items]
        return {
            "type": "table",
            "title": "소비 알림",
            "columns": [
                {"key": "severity", "label": "등급"},
                {"key": "kind", "label": "종류"},
                {"key": "message", "label": "내용"},
            ],
            "rows": rows,
        }

    if not isinstance(data, dict):
        return None

    if tool == "get_state":
        return {
            "type": "comparison_bar",
            "title": "현재 금융 상태",
            "unit": "KRW",
            "series": [
                {"label": "유동성", "value": data.get("liquidity")},
                {"label": "비상금", "value": data.get("emergency_fund")},
            ],
        }

    if tool == "safe_to_spend":
        return {
            "type": "comparison_bar",
            "title": "오늘 안심 소비 한도",
            "unit": "KRW",
            "series": [
                {"label": "오늘 한도", "value": data.get("safe_today")},
                {"label": "현재 유동성", "value": data.get("liquidity")},
                {"label": "수입 전 약정", "value": data.get("committed_until_income")},
            ],
        }

    if tool == "forecast_balance":
        dates = data.get("dates", [])
        median = data.get("median", [])
        low = data.get("p10", [])
        high = data.get("p90", [])
        series = [
            {"label": str(day), "value": value, "low": low[index], "high": high[index]}
            for index, (day, value) in enumerate(zip(dates, median))
            if index < len(low) and index < len(high)
        ]
        return {"type": "forecast_line", "title": "30일 잔액 예측", "unit": "KRW", "series": series}

    if tool == "what_if":
        base, branch = data.get("base", {}), data.get("branch", {})
        return {
            "type": "comparison_bar",
            "title": "What-if 잔액 비교",
            "unit": "KRW",
            "series": [
                {"label": "기본 최저 잔액", "value": base.get("min_balance")},
                {"label": "구매 후 최저 잔액", "value": branch.get("min_balance")},
                {"label": "최저 잔액 변화", "value": data.get("delta_min_balance")},
            ],
            "status": data.get("verdict"),
        }

    if tool == "payment_risk":
        return {
            "type": "comparison_bar",
            "title": "결제 부족 위험",
            "unit": "",
            "series": [
                {"label": "위험 점수", "value": data.get("risk_score")},
                {"label": "전체 부족 확률", "value": data.get("shortfall_prob")},
                {"label": "카드 부족 확률", "value": data.get("card_shortfall_prob")},
            ],
            "status": data.get("level"),
        }

    if tool == "goal_plan":
        weekly = data.get("weekly", [])
        rows = [
            {"week_start": item.get("week_start"), "week_end": item.get("week_end"), "total": item.get("total")}
            for item in weekly
        ]
        return {
            "type": "table",
            "title": "주차별 목표 지출 상한",
            "status": "달성 가능" if data.get("feasible") else "조정 필요",
            "columns": [
                {"key": "week_start", "label": "시작일", "format": "date"},
                {"key": "week_end", "label": "종료일", "format": "date"},
                {"key": "total", "label": "주간 상한", "format": "money"},
            ],
            "rows": rows,
        }

    if tool == "rebalance_envelopes":
        items = data.get("moves", [])
        if not items:
            return None
        rows = [{"from": item.get("from_envelope"), "to": item.get("to_envelope"), "amount": item.get("amount")} for item in items]
        columns = [
            {"key": "from", "label": "출발 봉투"},
            {"key": "to", "label": "도착 봉투"},
            {"key": "amount", "label": "이동액", "format": "money"},
        ]
        return {"type": "table", "title": "알림·처방", "columns": columns, "rows": rows}

    if tool == "room_status":
        progress = data.get("board_progress", {})
        return {
            "type": "comparison_bar",
            "title": "방 상태",
            "unit": "ratio",
            "series": [{"label": label, "value": value} for label, value in progress.items()],
            "status": data.get("level"),
        }
    return None


def _chat_results(result: dict[str, Any]) -> list[dict[str, Any]]:
    """에이전트 툴 결과를 대시보드 최소 계약으로 변환한다. §9.2.2"""
    results: list[dict[str, Any]] = []
    for call in result.get("tool_calls", []):
        if not isinstance(call, dict):
            continue
        tool = str(call.get("name", "get_state"))
        data = _dump(call.get("result", {}))
        results.append({"tool": tool, "data": data, "visualization": _result_visualization(tool, data)})
    return results


def _http_engine_error(exc: Exception) -> HTTPException:
    """코어 실패를 503으로 표준화한다. §9.2.3"""
    return HTTPException(status_code=503, detail=str(exc))


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    """자체 포함된 대시보드 HTML을 제공한다. §9.2.2"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def api_health(response: Response) -> dict[str, Any]:
    """엔진과 LLM 준비 상태를 분리해 반환한다. §9.2.2"""
    engine_ready = False
    try:
        if _profile_ids():
            _build_context(_profile_ids()[0])
            engine_ready = True
    except Exception:
        engine_ready = False

    client = _client()
    try:
        llm_ready = bool(client.available())
    except Exception:
        llm_ready = False
    response.status_code = 200 if engine_ready else 503
    return {
        "ok": engine_ready,
        "source": "DEMO",
        "engine_ready": engine_ready,
        "llm_ready": llm_ready,
        "llm_model": client.model,
        "fallback": not llm_ready,
        "service": "fdt-local-dashboard",
        "version": app.version,
    }


@app.get("/api/profiles")
def list_profiles() -> dict[str, Any]:
    """금융 사용자 프로필 목록과 별도 코치 선택지를 반환한다. §9.2.2"""
    profiles = []
    for profile_id in _profile_ids():
        try:
            profiles.append(_profile_meta(profile_id))
        except Exception as exc:
            raise _http_engine_error(exc) from exc
    return {"profiles": profiles, "coach_personas": list(COACH_PERSONAS)}


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: str, as_of: date | None = Query(default=None)) -> dict[str, Any]:
    """프로필의 State·RiskResult·RoomProjection을 반환한다. §9.2.2"""
    if profile_id not in _profile_ids():
        raise HTTPException(status_code=404, detail=f"프로필을 찾을 수 없습니다: {profile_id}")
    try:
        ctx, risk_result, room = _build_context(profile_id, as_of)
        return {
            "profile": _profile_meta(profile_id),
            "profile_id": profile_id,
            "source": "DEMO",
            "state": _dump(ctx.state),
            "risk": _dump(risk_result),
            "room": _dump(room),
            "engine_ready": True,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_engine_error(exc) from exc


@app.post("/api/chat/start")
def start_chat(request: ChatStartRequest) -> dict[str, Any]:
    """금융 프로필과 코치 페르소나를 분리한 메모리 세션을 만든다. §9.2.3"""
    if request.profile_id not in _profile_ids():
        raise HTTPException(status_code=404, detail=f"프로필을 찾을 수 없습니다: {request.profile_id}")
    if request.coach_persona not in COACH_PERSONA_IDS:
        raise HTTPException(status_code=422, detail="coach_persona가 올바르지 않습니다.")
    try:
        ctx, risk_result, room = _build_context(request.profile_id, request.as_of)
        session_id = uuid4().hex
        agent = FdtAgent(_client(), ctx, persona=request.coach_persona)
        session = _Session(session_id, request.profile_id, request.coach_persona, ctx, agent, risk_result, room)
        with _SESSIONS_LOCK:
            _SESSIONS[session_id] = session
        return {
            "session_id": session_id,
            "active": True,
            "profile_id": request.profile_id,
            "coach_persona": request.coach_persona,
            "as_of": ctx.state.as_of.isoformat(),
            "message": _initial_message(request.coach_persona),
            "route": ["session_start"],
            "faithful": True,
            "fallback": True,
            "state": _dump(ctx.state),
            "risk": _dump(risk_result),
            "room": _dump(room),
        }
    except HTTPException:
        raise
    except EngineLoadError as exc:
        raise _http_engine_error(exc) from exc
    except Exception as exc:
        raise _http_engine_error(exc) from exc


@app.post("/api/chat/message")
def chat_message(request: ChatMessageRequest) -> dict[str, Any]:
    """세션의 메시지를 직렬 처리하고 코어 결과를 그대로 반환한다. §9.2.3"""
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    with session.lock:
        try:
            agent_result = session.agent.ask(request.message.strip())
        except Exception as exc:
            raise _http_engine_error(exc) from exc
        results = _chat_results(agent_result)
        route = [item["tool"] for item in results] or ["get_state"]
        route.append("coach")
        return {
            "session_id": session.id,
            "active": True,
            "message": str(agent_result.get("reply", "")),
            "route": route,
            "results": results,
            "faithful": bool(agent_result.get("faithful", False)),
            "fallback": bool(agent_result.get("fallback", True)),
            "persona": session.coach_persona,
            "engine_json": _dump(agent_result.get("engine_json", {})),
            "tool_calls": _dump(agent_result.get("tool_calls", [])),
        }


@app.post("/api/chat/end")
def end_chat(request: ChatEndRequest) -> dict[str, Any]:
    """메모리 세션을 종료하고 삭제한다. §9.2.3"""
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(request.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
        with session.lock:
            _SESSIONS.pop(request.session_id, None)
    return {
        "session_id": request.session_id,
        "active": False,
        "message": "대화를 종료했어요.",
        "route": ["session_end"],
        "faithful": True,
        "fallback": True,
    }
