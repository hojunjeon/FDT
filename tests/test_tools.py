import json
from datetime import date

import pytest

from fdt.agent import tools
from fdt.agent.tools import TwinContext, execute_tool, normalize_amount, normalize_date, normalize_envelope


class _State:
    as_of = date(2026, 9, 2)

    def model_dump(self, mode="json"):
        return {"as_of": self.as_of.isoformat(), "liquidity": 100_000, "committed": list(range(6))}


@pytest.fixture
def context():
    return TwinContext(snap=None, txs=[], state=_State(), behavior=None)


def test_tool_specs_are_unique_json_schemas():
    names = [spec["function"]["name"] for spec in tools.TOOL_SPECS]
    assert len(names) == len(set(names)) == 10
    for spec in tools.TOOL_SPECS:
        parameters = spec["function"]["parameters"]
        assert spec["type"] == "function"
        assert parameters["type"] == "object"
        assert set(parameters) >= {"properties", "required", "additionalProperties"}
        json.dumps(spec, ensure_ascii=False)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3만원", 30_000), ("30,000원", 30_000), ("3만", 30_000),
        ("1만 8천원", 18_000), ("21만원", 210_000), ("1,250,000원", 1_250_000),
        ("1.5만원", 15_000), ("30천원", 30_000), ("5백원", 500),
        ("1억", 100_000_000), ("1억 2천만", 120_000_000), ("30000", 30_000), ("0원", 0),
    ],
)
def test_amount_normalization(raw, expected):
    assert normalize_amount(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("오늘", date(2026, 9, 2)), ("내일", date(2026, 9, 3)),
        ("모레", date(2026, 9, 4)), ("3일 뒤", date(2026, 9, 5)),
        ("2주 후", date(2026, 9, 16)), ("다음 주 금요일", date(2026, 9, 11)),
        ("이번 달 말", date(2026, 9, 30)), ("25일", date(2026, 9, 25)),
        ("다음달 15일", date(2026, 10, 15)), ("다음  달 15일까지", date(2026, 10, 15)),
        ("이번달 15일", date(2026, 9, 15)), ("다음달 말", date(2026, 10, 31)),
        ("이번 주말", date(2026, 9, 5)), ("다음 주말", date(2026, 9, 12)),
        ("주말", date(2026, 9, 5)), ("2개월 후", date(2026, 11, 2)),
    ],
)
def test_relative_date_normalization(raw, expected):
    assert normalize_date(raw, date(2026, 9, 2)) == expected


def test_weekend_on_weekend_uses_today_for_bare_weekend():
    saturday = date(2026, 9, 5)
    sunday = date(2026, 9, 6)
    assert normalize_date("주말", saturday) == saturday
    assert normalize_date("주말", sunday) == sunday
    assert normalize_date("다음 주말", sunday) == date(2026, 9, 12)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("밥", "외식"), ("화장품", "쇼핑"), ("택시", "교통비"),
        ("병원", "의료·건강"), ("영화", "취미·여가"),
        ("편의점", "편의점·마트·잡화"), ("기타", "기타"),
    ],
)
def test_envelope_synonyms(raw, expected):
    assert normalize_envelope(raw).value == expected


def test_unknown_envelope_defaults_to_etc():
    assert normalize_envelope("분류되지 않은 지출").value == "기타"


def test_execute_tool_serializes_every_tool(monkeypatch, context):
    monkeypatch.setattr(tools, "forecast", lambda *args, **kwargs: {"value": 1})
    monkeypatch.setattr(tools, "what_if", lambda *args, **kwargs: {"value": 2})
    monkeypatch.setattr(tools, "risk", lambda *args, **kwargs: {"value": 3})
    monkeypatch.setattr(tools, "plan_goal", lambda *args, **kwargs: {"value": 4})
    monkeypatch.setattr(tools, "safe_to_spend", lambda *args, **kwargs: {"value": 5})
    monkeypatch.setattr(tools, "rebalance", lambda *args, **kwargs: {"value": 6})
    monkeypatch.setattr(tools, "detect_alerts", lambda *args, **kwargs: [{"value": 7}])
    monkeypatch.setattr(tools, "project_room", lambda *args, **kwargs: {"value": 8})
    calls = {
        "get_state": {}, "forecast_balance": {}, "what_if": {"amount": "3만원", "envelope": "밥", "days_from_now": 2},
        "payment_risk": {}, "goal_plan": {"target_amount": "120만원", "target_date": "2026-09-25"},
        "safe_to_spend": {}, "rebalance_envelopes": {}, "spending_alerts": {}, "room_status": {}, "policy_tips": {},
    }
    for name, args in calls.items():
        result = execute_tool(name, args, context)
        json.dumps(result, ensure_ascii=False)
        assert "error" not in result, (name, result)


def test_execute_tool_wraps_validation_errors(context):
    assert "error" in execute_tool("forecast_balance", {"horizon_days": 6}, context)
    assert "error" in execute_tool("not_a_tool", {}, context)


def test_get_state_recomputes_health_from_twin(monkeypatch, context):
    monkeypatch.setattr(tools, "risk", lambda state, behavior, seed: {"seed": seed})
    monkeypatch.setattr(tools, "health", lambda state, risk_result: (61.5, "WARNING"))

    result = execute_tool("get_state", {}, context)

    assert result["health_score"] == 61.5
    assert result["health_level"] == "WARNING"
