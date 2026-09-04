from datetime import date
from types import SimpleNamespace

import pytest

import fdt.agent.agent as agent_module
from fdt.agent.agent import _parse_target_date


class _Client:
    def __init__(self, response=None, available=True):
        self.response = response or {"message": {"tool_calls": []}}
        self.available_value = available
        self.messages = []

    def available(self):
        return self.available_value

    def chat(self, messages, **kwargs):
        self.messages.append((messages, kwargs))
        return self.response


@pytest.fixture
def context():
    return SimpleNamespace(state=SimpleNamespace(as_of=date(2026, 9, 2)))


def test_ask_executes_llm_tool_and_remembers_text(monkeypatch, context):
    client = _Client({"message": {"tool_calls": [{"function": {"name": "safe_to_spend", "arguments": {}}}]}})
    monkeypatch.setattr(agent_module, "execute_tool", lambda name, args, ctx: {"safe_today": 19_000})
    monkeypatch.setattr(agent_module.coach_module, "coach", lambda *args: {
        "reply": "오늘은 1만 9천원까지 써도 돼냥.", "faithful": True, "fallback": False,
    })

    result = agent_module.FdtAgent(client, context).ask("오늘 얼마 써도 돼?")

    assert result["reply"].startswith("오늘은")
    assert result["tool_calls"][0]["name"] == "safe_to_spend"
    assert result["engine_json"]["safe_to_spend"]["safe_today"] == 19_000
    assert len(client.messages) == 1


def test_ask_without_tool_call_defaults_to_get_state(monkeypatch, context):
    client = _Client({"message": {"content": "상태를 확인했어요."}})
    calls = []
    monkeypatch.setattr(agent_module, "execute_tool", lambda name, args, ctx: calls.append(name) or {"liquidity": 1})
    monkeypatch.setattr(agent_module.coach_module, "coach", lambda *args: {
        "reply": "현재 상태를 확인했어요.", "faithful": True, "fallback": True,
    })

    result = agent_module.FdtAgent(client, context).ask("아무거나")

    assert calls == ["get_state"]
    assert result["fallback"] is True


def test_unavailable_llm_uses_rule_route(monkeypatch, context):
    client = _Client(available=False)
    calls = []
    monkeypatch.setattr(agent_module, "execute_tool", lambda name, args, ctx: calls.append(name) or {"safe_today": 10_000})
    monkeypatch.setattr(agent_module.coach_module, "coach", lambda *args: {
        "reply": "오늘은 1만원까지 써도 돼냥.", "faithful": True, "fallback": True,
    })

    result = agent_module.FdtAgent(client, context).ask("오늘 얼마 써도 돼?")

    assert calls == ["safe_to_spend"]
    assert result["fallback"] is True
    assert not client.messages


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("다음달 15일까지 30만원 모으고 싶어", date(2026, 10, 15)),
        ("다음 달 말까지 20만원 모아줘", date(2026, 10, 31)),
        ("이번 주말에 외식으로 15만원", date(2026, 9, 5)),
        ("다음 주말에 10만원 써도 돼?", date(2026, 9, 12)),
        ("3개월 뒤까지 50만원 모으려면", date(2026, 12, 2)),
    ],
)
def test_parse_target_date_uses_relative_date_rules(text, expected):
    assert _parse_target_date(text, date(2026, 9, 2)) == expected


def test_fallback_what_if_uses_weekend_offset(context):
    agent = agent_module.FdtAgent(_Client(available=False), context)

    calls = agent._fallback_calls("이번 주말에 외식으로 15만원 써도 돼?")

    assert calls[0]["name"] == "what_if"
    assert calls[0]["args"]["days_from_now"] == 3


def test_llm_what_if_relative_date_is_corrected(monkeypatch, context):
    client = _Client({"message": {"tool_calls": [{
        "function": {"name": "what_if", "arguments": {"amount": 150000, "envelope": "외식", "days_from_now": 0}},
    }]}})
    captured = []
    monkeypatch.setattr(agent_module, "execute_tool", lambda name, args, ctx: captured.append(args) or {"ok": True})
    monkeypatch.setattr(agent_module.coach_module, "coach", lambda *args: {
        "reply": "확인했어요.", "faithful": True, "fallback": False,
    })

    agent_module.FdtAgent(client, context).ask("이번 주말에 외식으로 15만원 써도 돼?")

    assert captured[0]["days_from_now"] == 3


def test_ask_preserves_verdict_conflict_from_coach(monkeypatch, context):
    class PositiveClient:
        def available(self):
            return True

        def chat(self, messages, **kwargs):
            if "tools" in kwargs:
                return {"message": {"tool_calls": [{
                    "function": {"name": "what_if", "arguments": {"amount": 150000, "envelope": "외식", "days_from_now": 0}},
                }]}}
            return {"message": {"content": "괜찮아요."}}

    client = PositiveClient()
    monkeypatch.setattr(agent_module, "execute_tool", lambda name, args, ctx: {"verdict": "DANGER"})

    result = agent_module.FdtAgent(client, context).ask("외식으로 15만원 써도 돼?")

    assert result["verdict_conflict"] is not None
    assert result["verdict_conflict"]["engine"] == "DANGER"
