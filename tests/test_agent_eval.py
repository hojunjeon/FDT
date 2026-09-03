from datetime import date
from pathlib import Path

from fdt.agent.coach import coach
from fdt.agent.tools import normalize_date
from fdt.eval.faithfulness import _field, _items, _params_match, _rule_route


def test_bare_day_and_range_dates_roll_forward_without_value_error():
    as_of = date(2026, 9, 2)
    assert normalize_date("30일에", as_of) == date(2026, 9, 30)
    assert normalize_date("29~31일", as_of) == date(2026, 9, 29)
    assert normalize_date("31일", as_of) == date(2026, 10, 31)


def test_rule_routing_eval_meets_design_thresholds():
    cases = _items(Path("data/eval/utterances.yaml"), "utterances")
    tool_correct = parameter_correct = 0
    for case in cases:
        text = str(_field(case, "utterance", "message", "text", default=""))
        expected_tool = str(_field(case, "tool", "intent", "expected_tool", default=""))
        expected_args = _field(case, "args", "parameters", default={}) or {}
        actual_tool, actual_args = _rule_route(text, date(2026, 9, 2))
        tool_ok = actual_tool == expected_tool
        tool_correct += tool_ok
        parameter_correct += tool_ok and _params_match(expected_args, actual_args)
    assert tool_correct / len(cases) >= 0.85
    assert parameter_correct / len(cases) >= 0.75


class _Replies:
    def __init__(self, replies):
        self.replies = iter(replies)

    def available(self):
        return True

    def chat(self, *args, **kwargs):
        return {"message": {"content": next(self.replies)}}


def test_coach_exposes_first_pass_and_attempt_state():
    result = coach(
        _Replies(["999만원은 괜찮아요.", "1만 9천원 안에서 써요."]),
        "온순냥",
        "safe_to_spend",
        {"safe_today": 19_000},
        "얼마까지 써?",
    )
    assert result["first_faithful"] is False
    assert result["attempt"] == 2
    assert result["attempt_status"] == "retry"
