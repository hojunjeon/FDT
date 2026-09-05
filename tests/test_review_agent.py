"""실행 결과, 필수 입력, 일반 대화, 라우터 복구에 대한 회귀 테스트."""
from datetime import date
from types import SimpleNamespace

import pytest

import fdt.agent.agent as agent_module
from fdt.agent.agent import FdtAgent
from fdt.agent.tools import ACTIVE_TOOL_SPECS, execute_tool, normalize_amount, normalize_args


class Offline:
    def available(self):
        return False


@pytest.fixture
def ctx():
    return SimpleNamespace(state=SimpleNamespace(as_of=date(2026, 9, 2)))


def test_failed_engine_is_not_coached_as_a_success(monkeypatch, ctx):
    monkeypatch.setattr(agent_module, "execute_tool", lambda *a: {"error": "secret path", "status": "error"})
    monkeypatch.setattr(agent_module.coach_module, "coach", lambda *a: pytest.fail("must not coach an error"))
    result = FdtAgent(Offline(), ctx).ask("잔액 예측해줘")
    assert result["status"] == "error"
    assert result["faithful"] is False
    assert "완료하지 못" in result["reply"]
    assert "secret" not in result["reply"]


@pytest.mark.parametrize("text", ["저축하고 싶어", "신발 사도 돼?", "-3만원 신발 사도 돼?", "61일 뒤 신발 3만원 사도 돼?"])
def test_invalid_or_missing_purchase_and_goal_inputs_are_reported(text, ctx):
    result = FdtAgent(Offline(), ctx).ask(text)
    assert result["status"] == "needs_input"
    assert result["faithful"] is False
    assert "계산하지 않았" in result["reply"]


def test_missing_amount_is_not_invented_by_llm(ctx):
    class Online:
        def available(self):
            pytest.fail("routing LLM must not fill missing user amounts")
    assert FdtAgent(Online(), ctx).ask("신발 사도 돼?")["status"] == "needs_input"


@pytest.mark.parametrize("text", ["안녕", "고마워", "아무거나", "오늘 기분이 안 좋아", "오늘 뭐해?"])
def test_smalltalk_has_no_financial_tool_calls(text, monkeypatch, ctx):
    monkeypatch.setattr(agent_module, "execute_tool", lambda *a: pytest.fail("not a financial request"))
    result = FdtAgent(Offline(), ctx).ask(text)
    assert result["status"] == "chat"
    assert result["tool_calls"] == []


def test_cash_is_cash_in_rule_and_llm_routes(ctx):
    agent = FdtAgent(Offline(), ctx)
    assert not agent._fallback_calls("현금으로 신발 3만원 사도 돼?")[0]["args"]["via_card"]
    calls = [{"name": "what_if", "args": {"via_card": True}}]
    agent._correct_relative_what_if_dates(calls, "현금으로 신발 3만원 사도 돼?")
    assert calls[0]["args"]["via_card"] is False


@pytest.mark.parametrize("raw", [True, 1.5, -1, float("inf"), 1_000_000_000_001])
def test_amount_bounds(raw):
    with pytest.raises(ValueError):
        normalize_amount(raw)


@pytest.mark.parametrize("raw", [True, 1.5, -1, 61])
def test_what_if_days_are_not_silently_coerced(raw, ctx):
    with pytest.raises(ValueError):
        normalize_args("what_if", {"amount": 100, "envelope": "쇼핑", "days_from_now": raw}, ctx)


def test_goal_date_limit_is_checked_before_engine(ctx):
    result = execute_tool("goal_plan", {"target_amount": 100, "target_date": "9999-12-31"}, ctx)
    assert result["status"] == "needs_input"


def test_unimplemented_policy_tool_is_not_advertised():
    assert "policy_tips" not in {item["function"]["name"] for item in ACTIVE_TOOL_SPECS}


def test_availability_cache_expires(monkeypatch, ctx):
    clock = [100.0]
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: clock[0])
    client = SimpleNamespace(available=lambda: False)
    agent = FdtAgent(client, ctx)
    assert agent._client_available() is False
    client.available = lambda: True
    assert agent._client_available() is False
    clock[0] += 31
    assert agent._client_available() is True
