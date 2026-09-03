"""페르소나 코칭 문장 생성 + 숫자 충실도 검사 (FDT-INT-01). 설계: docs/03_FDT_설계.md §8.3, §8.4"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from fdt.agent.llm import OllamaClient

PERSONAS: dict[str, str] = {
    "도도냥": "짧고 새침하게 말하며 문장 끝을 ~냥으로 한다. 칭찬은 인색하게, 경고는 직설적으로 한다.",
    "온순냥": "부드럽고 격려하는 말투를 쓴다. ~해요와 ~냥을 섞되 이모지는 쓰지 않는다.",
    "지방냥": "구수한 사투리를 쓴다. 문장 끝에 ~했시봉, ~겨, ~해야제를 자연스럽게 사용한다.",
}
PERSONA_ENDINGS = {"도도냥": "냥.", "온순냥": "요, 냥.", "지방냥": "겨."}
SYSTEM_PROMPT = """너는 KeyFin의 고양이 코치다. 아래 [엔진 결과]의 숫자만 사용해 한국어로 2~4문장 답한다.
금액·비율·확률·날짜·기간은 [허용 숫자 집합]에 있는 값만 사용한다. 금액은 만원 단위로 반올림해 말할 수 있다.
[허용 숫자 집합]
{allowed_numbers}
[금지 규칙]
- 집합에 없는 숫자·날짜·기간·확률을 만들거나 계산하거나 추정하지 않는다.
- 사용자 질문에만 있고 집합에 없는 숫자도 답변에 쓰지 않는다.
- 금액을 임의로 근사하거나 다시 반올림하지 않는다.
- 필요한 숫자가 집합에 없으면 숫자를 생략하고 정성적으로만 답한다.
말투: {persona}
[엔진 결과]
{engine_json}
사용자 질문: {user_text}
가장 중요한 최종 점검: 답변의 모든 숫자를 [허용 숫자 집합]과 대조하고, 하나라도 없으면 그 숫자를 삭제한다. 숫자를 쓰지 않아도 된다."""

_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.])-?\d[\d,]*(?:\.\d+)?")
_UNIT_RE = re.compile(r"\s*(억|만|천|백)")
_AMOUNT_FACTORS = {"억": 100_000_000, "만": 10_000, "천": 1_000, "백": 100}


def _number(value: str) -> int | float:
    value = value.replace(",", "")
    parsed = float(value) if "." in value else int(value)
    return int(parsed) if isinstance(parsed, float) and parsed.is_integer() else parsed


def _extract_tokens(text: str) -> list[tuple[int | float, str]]:
    """숫자와 표기 단위를 함께 추출한다. 단위는 충실도 허용오차에 사용한다."""
    tokens: list[tuple[int | float, str]] = []
    date_spans: list[tuple[int, int]] = []
    for match in _DATE_RE.finditer(text):
        date_spans.append(match.span())
        tokens.extend((int(part), "date") for part in match.groups())

    def in_date_span(position: int) -> bool:
        return any(start <= position < end for start, end in date_spans)

    matches = list(_NUMBER_RE.finditer(text))
    index = 0
    while index < len(matches):
        match = matches[index]
        if in_date_span(match.start()):
            index += 1
            continue
        value = _number(match.group())
        cursor = match.end()
        unit_match = _UNIT_RE.match(text, cursor)
        if unit_match:
            unit = unit_match.group(1)
            total = float(value) * _AMOUNT_FACTORS[unit]
            precision = unit
            cursor = unit_match.end()
            while index + 1 < len(matches):
                next_match = matches[index + 1]
                if next_match.start() < cursor:
                    index += 1
                    continue
                next_unit = _UNIT_RE.match(text, next_match.end())
                if not next_unit or next_match.start() - cursor > 3:
                    break
                total += float(_number(next_match.group())) * _AMOUNT_FACTORS[next_unit.group(1)]
                precision = "만" if "만" in {precision, next_unit.group(1)} else precision
                cursor = next_unit.end()
                index += 1
            if text[cursor:cursor + 1] == "원":
                cursor += 1
            parsed: int | float = int(total) if total.is_integer() else total
            tokens.append((parsed, precision))
        else:
            suffix = text[cursor:cursor + 1]
            tokens.append((value, suffix if suffix in {"원", "%", "일", "주", "배", "점"} else ""))
        index += 1
    return tokens


def allowed_numbers(engine_json: dict[str, Any]) -> set[int | float]:
    """엔진 결과의 모든 숫자 리프와 파생값(만원 반올림, 퍼센트) 집합. §8.4"""
    allowed: set[int | float] = {0, 1, 2, 3, 7, 30}

    def visit(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, date):
            allowed.update((value.year, value.month, value.day))
            return
        if isinstance(value, (int, float)):
            numeric: int | float = value
            allowed.add(numeric)
            rounded_10k = round(float(value), -4)
            rounded_1k = round(float(value), -3)
            allowed.add(int(rounded_10k) if rounded_10k.is_integer() else rounded_10k)
            allowed.add(int(rounded_1k) if rounded_1k.is_integer() else rounded_1k)
            allowed.add(int(value // 10_000))
            rounded_man = round(float(value) / 10_000)
            allowed.add(int(rounded_man))
            if 0 <= float(value) <= 1:
                percent = round(float(value) * 100)
                allowed.add(int(percent) if float(percent).is_integer() else percent)
                allowed.add(round(float(value) * 100, 1))
            allowed.add(round(float(value), 1))
            allowed.add(round(100 * (float(value) - 1)))
            return
        if isinstance(value, str):
            for match in _DATE_RE.finditer(value):
                allowed.update(int(part) for part in match.groups())
            return
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                visit(item)

    visit(engine_json)
    return allowed


def extract_numbers(text: str) -> list[int | float]:
    """한국어 금액 표기(3만 5천원, 35,000원, 12%) 를 정수로. §8.4"""
    return [value for value, _ in _extract_tokens(text)]


def check_faithful(text: str, engine_json: dict[str, Any]) -> tuple[bool, list[int | float]]:
    """텍스트의 모든 숫자가 허용 집합에 있으면 True. 위반 숫자 목록 반환."""
    allowed = allowed_numbers(engine_json)
    violations: list[int | float] = []
    for value, unit in _extract_tokens(text):
        if _is_allowed(value, allowed, unit):
            continue
        if value not in violations:
            violations.append(value)
    return not violations, violations


def _is_allowed(value: int | float, allowed: set[int | float], unit: str) -> bool:
    if any(_same_number(value, candidate) for candidate in allowed):
        return True
    tolerance = {"만": 5_000, "억": 5_000, "천": 500, "백": 100}.get(unit)
    if tolerance is None:
        return False
    return any(abs(float(value) - float(candidate)) <= tolerance for candidate in allowed if isinstance(candidate, (int, float)))


def _same_number(left: int | float, right: int | float) -> bool:
    return abs(float(left) - float(right)) < 1e-9


def coach(client: OllamaClient, persona: str, intent: str, engine_json: dict[str, Any], user_text: str) -> dict[str, Any]:
    """생성 -> 검사 -> 실패 시 1회 재생성 -> 실패 시 템플릿 폴백. 반환에 faithful/fallback 플래그 포함."""
    persona = persona if persona in PERSONAS else "온순냥"
    fallback = template_fallback(intent, engine_json, persona)
    if client is None:
        return {
            "reply": fallback, "faithful": True, "fallback": True, "violations": [],
            "first_faithful": False, "attempt": 0, "attempt_status": "fallback",
        }
    available = getattr(client, "available", None)
    if not callable(available):
        ready = True
    else:
        try:
            ready = bool(available())
        except Exception:
            ready = False
    if not ready:
        return {
            "reply": fallback, "faithful": True, "fallback": True, "violations": [],
            "first_faithful": False, "attempt": 0, "attempt_status": "fallback",
        }

    base_messages = [{
        "role": "system",
        "content": SYSTEM_PROMPT.format(
            persona=PERSONAS[persona],
            allowed_numbers=json.dumps(
                sorted(allowed_numbers(engine_json), key=lambda value: (float(value), str(value))),
                ensure_ascii=False,
            ),
            engine_json=json.dumps(engine_json, ensure_ascii=False, sort_keys=True),
            user_text=user_text,
        ),
    }]
    violations: list[int | float] = []
    first_faithful = False
    attempts = 0
    for attempt in range(2):
        attempts = attempt + 1
        messages = base_messages
        if attempt:
            messages = base_messages + [{
                "role": "user",
                "content": f"이전 답변의 금지 숫자 {violations}를 제거하고 엔진 결과만 사용해 다시 답해.",
            }]
        try:
            response = client.chat(messages, temperature=0.0)
            content = _response_content(response)
        except Exception:
            content = ""
        faithful, violations = check_faithful(content, engine_json)
        if attempt == 0:
            first_faithful = bool(content and faithful)
        if content and faithful:
            return {
                "reply": content,
                "faithful": True,
                "fallback": False,
                "violations": [],
                "first_faithful": first_faithful,
                "attempt": attempts,
                "attempt_status": "first" if attempts == 1 else "retry",
            }
    return {
        "reply": fallback,
        "faithful": True,
        "fallback": True,
        "violations": [],
        "first_faithful": first_faithful,
        "attempt": attempts,
        "attempt_status": "fallback",
    }


def template_fallback(intent: str, engine_json: dict[str, Any], persona: str) -> str:
    """LLM 없이 숫자만 끼워 넣는 결정론 문장. §8.5"""
    persona = persona if persona in PERSONA_ENDINGS else "온순냥"
    ending = PERSONA_ENDINGS[persona]
    level = _first_value(engine_json, "level", "health_level")
    prefix = "위험 신호가 있어요. " if str(level).upper() == "DANGER" else ""
    body = "엔진 결과를 확인했어요. 현재 상태를 기준으로 안내할게"
    if intent == "safe_to_spend":
        safe = _first_value(engine_json, "safe_today")
        body = f"오늘은 {_money(safe)}원까지 써도 돼" if safe is not None else "오늘 안심 소비 한도를 확인했어"
    elif intent == "get_state":
        liquidity = _first_value(engine_json, "liquidity")
        body = f"현재 유동성은 {_money(liquidity)}원이야" if liquidity is not None else "현재 상태를 확인했어"
    elif intent == "forecast_balance":
        balance = _last_value(engine_json, "median", "mean")
        body = f"예상 기간 끝 잔액은 {_money(balance)}원 정도야" if balance is not None else "잔액 예측을 확인했어"
    elif intent == "what_if":
        minimum = _first_value(engine_json, "delta_min_balance", "min_balance")
        verdict = _first_value(engine_json, "verdict")
        body = f"가상 지출 뒤 최저 잔액 변화는 {_money(minimum)}원이야" if minimum is not None else "가상 지출 결과를 확인했어"
        if verdict:
            body += f". 판단은 {verdict}"
    elif intent == "payment_risk":
        probability = _first_value(engine_json, "card_shortfall_prob", "shortfall_prob")
        score = _first_value(engine_json, "risk_score")
        parts = []
        if probability is not None:
            parts.append(f"카드 부족 가능성은 {_percent(probability)}%")
        if score is not None:
            parts.append(f"위험 점수는 {score}점")
        body = "이고 ".join(parts) if parts else "결제 위험을 확인했어"
    elif intent == "goal_plan":
        target = _first_value(engine_json, "target_amount")
        target_date = _first_value(engine_json, "target_date")
        body = f"{_money(target)}원 목표" if target is not None else "목표 계획"
        if target_date:
            body += f"을 {target_date}까지 살펴봤어"
        else:
            body += "을 살펴봤어"
    elif intent == "rebalance_envelopes":
        shortfall = _first_value(engine_json, "shortfall")
        body = f"봉투 재배분 필요액은 {_money(shortfall)}원이야" if shortfall is not None else "봉투 재배분 결과를 확인했어"
    elif intent == "spending_alerts":
        amount = _first_value(engine_json, "amount")
        body = f"최근 소비 중 {_money(amount)}원 규모의 주의 신호가 있어" if amount is not None else "최근 소비 주의 신호를 확인했어"
    elif intent == "room_status":
        weather = _first_value(engine_json, "weather")
        body = f"지금 방 날씨는 {weather}야" if weather else "지금 방 상태를 확인했어"
    elif intent == "policy_tips":
        body = "정책 팁은 아직 준비되지 않았어"
    return prefix + body + ending


def _response_content(response: Any) -> str:
    if not isinstance(response, dict):
        return ""
    message = response.get("message", response)
    if isinstance(message, dict):
        content = message.get("content", "")
        return content if isinstance(content, str) else str(content)
    return ""


def _first_value(value: Any, *keys: str) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value and value[key] is not None:
                return value[key]
        for item in value.values():
            found = _first_value(item, *keys)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _first_value(item, *keys)
            if found is not None:
                return found
    return None


def _last_value(value: Any, *keys: str) -> Any:
    found = _first_value(value, *keys)
    if isinstance(found, (list, tuple)):
        return found[-1] if found else None
    return found


def _money(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value:,}"


def _percent(value: Any) -> str:
    try:
        number = float(value)
        if 0 <= number <= 1:
            number *= 100
        return str(int(number)) if number.is_integer() else f"{number:.1f}"
    except (TypeError, ValueError):
        return str(value)
