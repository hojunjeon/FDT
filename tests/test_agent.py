from datetime import date
from types import SimpleNamespace

import pytest

import fdt.agent.agent as agent_module


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
