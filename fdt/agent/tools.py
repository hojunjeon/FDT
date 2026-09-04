"""에이전트 툴 정의와 실행기. 설계: docs/03_FDT_설계.md §8.2

툴은 전부 트윈 코어의 결정론 함수를 감싼다. LLM 은 툴 이름과 파라미터만 고른다 (FDT-INP-02).
"""
from __future__ import annotations

import calendar
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from fdt.schemas.domain import Behavior, LedgerTx, State, VirtualSpend
from fdt.schemas.finapi import FinSnapshot
from fdt.taxonomy.categories import Envelope
from fdt.twin.analytics import detect_alerts, health, rebalance, safe_to_spend
from fdt.twin.goal import plan_goal
from fdt.twin.projection import project_room
from fdt.twin.simulate import forecast, risk, what_if


_ENVELOPE_ALIASES: dict[Envelope, tuple[str, ...]] = {
    Envelope.DINING: ("외식", "밥", "식비", "음식", "카페", "커피", "배달", "먹는 것"),
    Envelope.TRANSPORT: ("교통비", "교통", "택시", "지하철", "버스", "주유"),
    Envelope.HEALTH: ("의료·건강", "의료", "건강", "병원", "약", "운동", "헬스"),
    Envelope.LEISURE: ("취미·여가", "취미", "여가", "영화", "게임", "여행", "콘텐츠"),
    Envelope.SHOPPING: ("쇼핑", "옷", "신발", "화장품", "패션", "뷰티"),
    Envelope.GROCERY: ("편의점·마트·잡화", "편의점", "마트", "잡화", "생활용품", "장보기", "다이소"),
    Envelope.ETC: ("기타", "교육", "해외", "경조사"),
}
_AMOUNT_UNIT = {"억": 100_000_000, "만": 10_000, "천": 1_000, "백": 100}
_WEEKDAY = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}


def normalize_envelope(value: Envelope | str) -> Envelope:
    """자연어 봉투 이름을 일곱 개의 고정 봉투 중 하나로 정규화한다."""
    if isinstance(value, Envelope):
        return value
    text = str(value).strip().lower()
    for envelope, aliases in _ENVELOPE_ALIASES.items():
        if text == envelope.value.lower() or text == envelope.name.lower():
            return envelope
        if any(alias.lower() in text for alias in aliases):
            return envelope
    if not text:
        raise ValueError("envelope is required")
    return Envelope.ETC


def normalize_amount(value: int | float | str) -> int:
    """원화 표기를 정수 원으로 바꾼다. 음수와 불명확한 표기는 거부한다."""
    if isinstance(value, bool):
        raise ValueError("amount must be a number")
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or value < 0 or float(value) != int(value):
            raise ValueError("amount must be a non-negative integer")
        return int(value)
    text = str(value).strip().replace(",", "").replace("원", "").strip()
    if not text or text.startswith("-"):
        raise ValueError("amount must be a non-negative number")
    if any(unit in text for unit in _AMOUNT_UNIT):
        return _checked_amount(_parse_korean_amount(text))
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        raise ValueError(f"invalid amount: {value}")
    return _checked_amount(float(text))


def _checked_amount(value: float) -> int:
    if not math.isfinite(value) or value < 0 or value != int(value):
        raise ValueError("amount must resolve to a non-negative integer")
    return int(value)


def _parse_korean_amount(text: str) -> float:
    """억·만·천·백 복합 표기를 재귀적으로 계산한다."""
    text = text.replace(" ", "")
    if "억" in text:
        high, rest = text.split("억", 1)
        return _parse_amount_part(high) * _AMOUNT_UNIT["억"] + _parse_korean_amount(rest)
    return _parse_amount_part(text)


def _parse_amount_part(text: str) -> float:
    if not text:
        return 0.0
    for unit in ("만", "천", "백"):
        if unit in text:
            high, rest = text.split(unit, 1)
            return _parse_amount_part(high) * _AMOUNT_UNIT[unit] + _parse_amount_part(rest)
    return float(text)


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month = divmod(month_index, 12)
    return date(year, month + 1, min(value.day, calendar.monthrange(year, month + 1)[1]))


def _date_in_month(base: date, months: int, day: int) -> date:
    target = _add_months(base.replace(day=1), months)
    last_day = calendar.monthrange(target.year, target.month)[1]
    if day < 1 or day > last_day:
        raise ValueError(f"invalid day: {day}")
    return target.replace(day=day)


def _weekend_date(base: date, following: bool = False) -> date:
    """기준일의 이번 주말 또는 다음 주말 토요일을 반환한다."""
    if not following and base.weekday() >= 5:
        return base
    saturday = base + timedelta(days=(5 - base.weekday()) % 7)
    return saturday + timedelta(days=7 if following and base.weekday() != 6 else 0)


def normalize_date(value: date | datetime | str, as_of: date | None = None) -> date:
    """ISO 날짜와 한국어 상대 날짜를 기준일에 대해 결정론적으로 해석한다."""
    base = as_of or date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = re.sub(r"\s+", "", str(value).strip())
    if not text:
        raise ValueError("date is required")
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    explicit = re.fullmatch(r"(\d{4})년?(\d{1,2})월(\d{1,2})일?", text)
    if explicit:
        return date(int(explicit.group(1)), int(explicit.group(2)), int(explicit.group(3)))
    explicit = re.fullmatch(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", text)
    if explicit:
        return date(int(explicit.group(1)), int(explicit.group(2)), int(explicit.group(3)))
    relative_month_day = re.fullmatch(r"(다음달|이번달)(\d{1,2})일(?:까지|에)?", text)
    if relative_month_day:
        month_offset = 1 if relative_month_day.group(1) == "다음달" else 0
        return _date_in_month(base, month_offset, int(relative_month_day.group(2)))
    relative_month_end = re.fullmatch(r"(다음달|이번달)말(?:일까지|까지|일)?", text)
    if relative_month_end:
        target = _add_months(base.replace(day=1), 1 if relative_month_end.group(1) == "다음달" else 0)
        return target.replace(day=calendar.monthrange(target.year, target.month)[1])
    month_day = re.fullmatch(r"(\d{1,2})월(\d{1,2})일?", text)
    if month_day:
        month, day = int(month_day.group(1)), int(month_day.group(2))
        year = base.year + (month < base.month)
        return date(year, month, day)
    month_only = re.fullmatch(r"(\d{1,2})월(?:말까지|까지|말)?", text)
    if month_only:
        month = int(month_only.group(1))
        year = base.year + (month < base.month)
        return date(year, month, calendar.monthrange(year, month)[1])
    if text in {"오늘", "당일"}:
        return base
    if text in {"내일", "익일"}:
        return base + timedelta(days=1)
    if text == "모레":
        return base + timedelta(days=2)
    if text in {"이번달말", "이번달말일", "말일"}:
        return date(base.year, base.month, calendar.monthrange(base.year, base.month)[1])
    if re.fullmatch(r"(?:이번)?주말(?:까지|에)?", text):
        return _weekend_date(base)
    if re.fullmatch(r"다음주말(?:까지|에)?", text):
        return _weekend_date(base, following=True)
    relative = re.fullmatch(r"(\d+)일(?:뒤|후)", text)
    if relative:
        return base + timedelta(days=int(relative.group(1)))
    relative = re.fullmatch(r"(\d+)개월(?:뒤|후)", text)
    if relative:
        return _add_months(base, int(relative.group(1)))
    relative = re.fullmatch(r"(\d+)주(?:뒤|후)", text)
    if relative:
        return base + timedelta(weeks=int(relative.group(1)))
    weekday = re.fullmatch(r"(이번|다음)주([월화수목금토일])(?:요일)?", text)
    if weekday:
        offset = _WEEKDAY[weekday.group(2)] - base.weekday()
        if weekday.group(1) == "다음":
            offset += 7
        return base + timedelta(days=offset)
    if text in {"이번주", "이번주내"}:
        return base
    if text in {"다음주", "다음주초"}:
        return base + timedelta(days=7)
    day_range = re.fullmatch(r"(\d{1,2})[~〜\-](\d{1,2})일(?:에|까지)?", text)
    if day_range:
        # ponytail: the one-date tool schema uses a range's first day; add interval support when needed.
        day_only = day_range.group(1)
    else:
        day_only = re.fullmatch(r"(\d{1,2})일(?:에|까지)?", text)
    if day_only:
        day = int(day_only if isinstance(day_only, str) else day_only.group(1))
        if day < 1 or day > 31:
            raise ValueError(f"invalid day: {day}")
        month_offset = 1 if day < base.day else 0
        while month_offset <= 12:
            candidate = _add_months(base.replace(day=1), month_offset)
            if day <= calendar.monthrange(candidate.year, candidate.month)[1]:
                return candidate.replace(day=day)
            month_offset += 1
        raise ValueError(f"invalid day: {day}")
    raise ValueError(f"invalid date: {value}")


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes", "y", "카드"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "0", "no", "n", "현금"}:
        return False
    raise ValueError("boolean value expected")


def _bounded_int(value: Any, name: str, lower: int, upper: int, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < lower or parsed > upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return parsed


def normalize_args(name: str, args: dict[str, Any] | None, ctx: TwinContext) -> dict[str, Any]:
    """툴별 금액·봉투·날짜를 검증하고 코어 함수가 받는 타입으로 정규화한다."""
    args = dict(args or {})
    if name in {"get_state", "safe_to_spend", "rebalance_envelopes", "room_status", "policy_tips"}:
        return {}
    if name in {"forecast_balance", "payment_risk"}:
        return {"horizon_days": _bounded_int(args.get("horizon_days"), "horizon_days", 7, 60, 30)}
    if name == "spending_alerts":
        return {"days": _bounded_int(args.get("days"), "days", 1, 7, 1)}
    if name == "what_if":
        raw_days = args.get("days_from_now", 0)
        try:
            days = int(raw_days)
        except (TypeError, ValueError):
            days = (normalize_date(raw_days, ctx.state.as_of) - ctx.state.as_of).days
        if days < 0 or days > 60:
            raise ValueError("days_from_now must be between 0 and 60")
        return {
            "amount": normalize_amount(args.get("amount")),
            "envelope": normalize_envelope(args.get("envelope")),
            "days_from_now": days,
            "via_card": _as_bool(args.get("via_card"), True),
            "label": str(args.get("label", "")),
        }
    if name == "goal_plan":
        return {
            "target_amount": normalize_amount(args.get("target_amount")),
            "target_date": normalize_date(args.get("target_date"), ctx.state.as_of),
        }
    raise ValueError(f"unknown tool: {name}")


@dataclass
class TwinContext:
    snap: FinSnapshot
    txs: list[LedgerTx]
    state: State
    behavior: Behavior
    seed: int = 42


def _tool_spec(name: str, description: str, properties: dict[str, Any] | None = None,
               required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


_ENVELOPE_SCHEMA = {"type": "string", "enum": [str(item) for item in Envelope]}
TOOL_SPECS: list[dict[str, Any]] = [
    _tool_spec("get_state", "현재 잔액과 약정 지출 상태를 조회한다. 단순 현황 질문의 기본 도구다."),
    _tool_spec("forecast_balance", "앞으로·미래 잔액과 현금 흐름 범위를 예측한다. 단순 잔액 조회에는 쓰지 않는다.", {
        "horizon_days": {"type": "integer", "minimum": 7, "maximum": 60, "default": 30},
    }),
    _tool_spec("what_if", "'써도 돼', '사도 돼', 구매·결제·지출처럼 금액이 있는 가상 지출을 넣고 잔액 변화를 비교한다. 실제 결제는 하지 않는다.", {
        "amount": {"type": "integer", "minimum": 0},
        "envelope": _ENVELOPE_SCHEMA,
        "days_from_now": {"type": "integer", "minimum": 0, "maximum": 60},
        "via_card": {"type": "boolean", "default": True},
        "label": {"type": "string", "default": ""},
    }, ["amount", "envelope", "days_from_now"]),
    _tool_spec("payment_risk", "카드대금·카드값·결제일의 잔액 부족 위험(리스크)을 계산한다.", {
        "horizon_days": {"type": "integer", "minimum": 7, "maximum": 60, "default": 30},
    }),
    _tool_spec("goal_plan", "모으기·모을 돈·저축·목표 달성의 가능성과 주간 한도를 계산한다.", {
        "target_amount": {"type": "integer", "minimum": 0},
        "target_date": {"type": "string", "format": "date"},
    }, ["target_amount", "target_date"]),
    _tool_spec("safe_to_spend", "오늘·이번 달 남은 돈처럼 가상 지출 금액이 없는 안심 소비 한도를 계산한다."),
    _tool_spec("rebalance_envelopes", "봉투 예산 재배분 가능성을 계산한다."),
    _tool_spec("spending_alerts", "소비가 빨라졌는지, 최근 가속·우려·알림 대상 결제가 있는지 찾는다.", {
        "days": {"type": "integer", "minimum": 1, "maximum": 7, "default": 1},
    }),
    _tool_spec("room_status", "금융 상태를 방과 캐릭터 상태로 매핑한다."),
    _tool_spec("policy_tips", "정책 팁을 조회한다."),
]

_TOOL_NAMES = {spec["function"]["name"] for spec in TOOL_SPECS}


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _run_tool(name: str, args: dict[str, Any], ctx: TwinContext) -> Any:
    if name == "get_state":
        result = ctx.state.model_dump(mode="json")
        result["committed"] = result.get("committed", [])[:5]
        try:
            score, level = health(ctx.state, risk(ctx.state, ctx.behavior, seed=ctx.seed))
        except (AttributeError, TypeError, ValueError):
            # 테스트용 경량 컨텍스트처럼 건강도 계산에 필요한 코어 필드가 없으면 기존 값을 유지한다.
            if isinstance(ctx.state, State):
                raise
        else:
            result["health_score"] = score
            result["health_level"] = level
        return result
    if name == "forecast_balance":
        return forecast(ctx.state, ctx.behavior, horizon_days=args["horizon_days"], seed=ctx.seed)
    if name == "what_if":
        injection = VirtualSpend(
            amount=args["amount"],
            envelope=args["envelope"],
            on=ctx.state.as_of + timedelta(days=args["days_from_now"]),
            via_card=args["via_card"],
            label=args["label"],
        )
        return what_if(ctx.state, ctx.behavior, [injection], seed=ctx.seed)
    if name == "payment_risk":
        return risk(ctx.state, ctx.behavior, horizon_days=args["horizon_days"], seed=ctx.seed)
    if name == "goal_plan":
        return plan_goal(ctx.state, ctx.behavior, args["target_amount"], args["target_date"], seed=ctx.seed)
    if name == "safe_to_spend":
        txs_today = [tx for tx in ctx.txs if tx.day == ctx.state.as_of]
        return safe_to_spend(ctx.state, txs_today)
    if name == "rebalance_envelopes":
        return rebalance(ctx.state, ctx.behavior)
    if name == "spending_alerts":
        start = ctx.state.as_of - timedelta(days=args["days"] - 1)
        recent = [tx for tx in ctx.txs if start <= tx.day <= ctx.state.as_of]
        return detect_alerts(ctx.state, ctx.behavior, recent)
    if name == "room_status":
        recent = [tx for tx in ctx.txs if ctx.state.as_of - timedelta(days=6) <= tx.day <= ctx.state.as_of]
        return project_room(ctx.state, detect_alerts(ctx.state, ctx.behavior, recent))
    if name == "policy_tips":
        return {"status": "not_available"}
    raise ValueError(f"unknown tool: {name}")


def execute_tool(name: str, args: dict[str, Any], ctx: TwinContext) -> dict[str, Any]:
    """툴 이름 -> 트윈 함수 호출 -> 결과를 JSON 직렬화 가능한 dict 로. 알 수 없는 툴은 ValueError."""
    try:
        if name not in _TOOL_NAMES:
            raise ValueError(f"unknown tool: {name}")
        normalized = normalize_args(name, args, ctx)
        return _jsonable(_run_tool(name, normalized, ctx))
    except Exception as exc:
        return {"error": str(exc)}
