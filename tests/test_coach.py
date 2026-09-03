import json

import pytest

from fdt.agent.coach import (
    PERSONAS,
    allowed_numbers,
    check_faithful,
    coach,
    extract_numbers,
    template_fallback,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1만 8천원", [18_000]), ("21만원", [210_000]), ("35%", [35]), ("3일 뒤", [3]),
        ("2026-09-25", [2026, 9, 25]), ("1,250,000원", [1_250_000]),
        ("3만원 2천원", [32_000]), ("5천원", [5_000]), ("1억 2만원", [100_020_000]),
        ("0원", [0]), ("7일", [7]), ("2주", [2]), ("1.12배", [1.12]),
        ("100,000", [100_000]), ("12%", [12]), ("25일", [25]),
        ("내일 3만원", [30_000]), ("-5,000원", [-5_000]), ("1만5천원", [15_000]),
        ("2027-01-03에 2만원", [2027, 1, 3, 20_000]),
    ],
)
def test_extract_numbers(text, expected):
    assert extract_numbers(text) == expected


def test_allowed_numbers_contains_documented_derivations():
    allowed = allowed_numbers({
        "liquidity": 783_360,
        "safe_today": 19_100,
        "acceleration": 1.12,
        "card_shortfall_prob": 0.35,
        "as_of": "2026-09-02",
    })
    assert {783_360, 780_000, 783_000, 78, 19_100, 19_000, 12, 35, 2026, 9, 2} <= allowed


def test_check_faithful_uses_amount_tolerance_and_reports_violations():
    engine = {"safe_today": 215_000, "card_shortfall_prob": 0.35, "as_of": "2026-09-02"}
    assert check_faithful("오늘은 21만원 안에서 쓰고 부족 확률은 35%야.", engine) == (True, [])
    faithful, violations = check_faithful("오늘은 99만원 안에서 써.", engine)
    assert not faithful and violations == [990_000]


def test_template_fallback_is_faithful_for_all_intents_and_personas():
    engine = {
        "liquidity": 783_360, "safe_today": 19_100, "median": [780_000, 760_000],
        "delta_min_balance": -10_000, "verdict": "OK", "card_shortfall_prob": 0.35,
        "risk_score": 20, "target_amount": 1_200_000, "target_date": "2026-09-25",
        "shortfall": 10_000, "amount": 12_000, "weather": "맑음", "level": "SAFE",
    }
    intents = [
        "get_state", "forecast_balance", "what_if", "payment_risk", "goal_plan",
        "safe_to_spend", "rebalance_envelopes", "spending_alerts", "room_status", "policy_tips", "briefing",
    ]
    for intent in intents:
        for persona in PERSONAS:
            reply = template_fallback(intent, engine, persona)
            assert check_faithful(reply, engine) == (True, []), (intent, persona, reply)


class _FakeClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = 0
        self.messages = []
        self.kwargs = []

    def available(self):
        return True

    def chat(self, *args, **kwargs):
        self.calls += 1
        self.messages.append(args[0])
        self.kwargs.append(kwargs)
        return {"message": {"content": next(self.replies)}}


def test_coach_prompt_lists_engine_numbers_and_forbids_new_values():
    client = _FakeClient(["오늘은 1만 9천원 안에서 써요."])
    coach(client, "온순냥", "safe_to_spend", {"safe_today": 19_000}, "얼마까지 써?")
    prompt = client.messages[0][0]["content"]
    assert "[허용 숫자 집합]" in prompt and "19000" in prompt
    assert "집합에 없는 숫자·날짜·기간·확률을 만들거나" in prompt
    assert client.kwargs[0]["temperature"] == 0.0


def test_coach_retries_once_then_accepts_faithful_response():
    client = _FakeClient(["999만원은 괜찮아요.", "1만 9천원 안에서 써요."])
    result = coach(client, "온순냥", "safe_to_spend", {"safe_today": 19_000}, "얼마까지 써?")
    assert result["faithful"] is True and result["fallback"] is False
    assert result["reply"] == "1만 9천원 안에서 써요."
    assert client.calls == 2


def test_coach_falls_back_when_llm_is_unavailable():
    class Unavailable:
        def available(self):
            return False

    result = coach(Unavailable(), "도도냥", "safe_to_spend", {"safe_today": 19_000}, "얼마까지 써?")
    assert result["faithful"] is True and result["fallback"] is True
    json.dumps(result, ensure_ascii=False)
