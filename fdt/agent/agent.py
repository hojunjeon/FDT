"""대화 루프. 설계: docs/03_FDT_설계.md §8.6

사용자 발화 -> (LLM) 툴 선택·파라미터 추출 -> (엔진) 결정론 실행 -> (LLM) 페르소나 코칭 -> 충실도 검사 -> 응답.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from fdt.agent import coach as coach_module
from fdt.agent.llm import OllamaClient
from fdt.agent.tools import TOOL_SPECS, TwinContext, execute_tool, normalize_amount, normalize_date


_SYSTEM_PROMPT = """너는 KeyFin의 qwen2.5:7b-instruct-q4_K_M 금융 툴 라우터다.
숫자 계산·금융 판단·답변 작성은 하지 말고, 아래 함수 중 하나를 골라 JSON 인자와 함께 호출한다.
가장 최근 사용자 발화가 이전 대화보다 항상 우선이다. 상대 날짜는 TwinContext의 as_of 기준으로 days_from_now를 고르고, 봉투는 enum 이름을 사용한다.
라우팅 우선순위와 대표 표현:
- 현황/계좌 상태/재정 상태/금융 요약만 물으면 get_state
- 잔액 예측·전망·미래 현금 흐름이면 forecast_balance
- 금액과 써도/사도/구매/결제/지출 여부가 함께 있으면 what_if
- 모으기·저축·목표·달성·주간 한도면 goal_plan
- 안심 한도·남은 돈·편하게 써도 되는 금액·수입 전 하루 한도면 safe_to_spend
- 예산 조정·재배분·봉투 이동이면 rebalance_envelopes
- 소비 알림·우려 결제·소비 속도·가속이면 spending_alerts
- 방·날씨·고양이·기분·캐릭터 행동이면 room_status
- 정책·혜택·금융 추천이면 policy_tips
- 카드값·카드대금·결제일·부족 확률·리스크·마이너스 위험이면 payment_risk
금액이 있는 구매 질문은 반드시 what_if다. what_if의 via_card는 '계좌' 또는 '체크'가 있을 때만 false이고, 그 외에는 true다. '오늘'은 days_from_now=0이다.
도구를 고를 수 없으면 get_state를 호출한다. 존재하지 않는 인자나 숫자를 만들지 않는다.

예시:
사용자: 오늘 커피 3만원 써도 돼? → what_if({"amount":30000,"envelope":"외식","days_from_now":0,"via_card":true})
사용자: 다음 주 신발 15만원 사도 돼? → what_if({"amount":150000,"envelope":"쇼핑","days_from_now":7,"via_card":true})
사용자: 12월까지 200만원 모을래 → goal_plan({"target_amount":2000000,"target_date":"2026-12-31"})
사용자: 카드대금 리스크 알려줘 → payment_risk({})
사용자: 소비가 빨라졌는지 봐줘 → spending_alerts({})
사용자: 오늘 얼마까지 써도 돼? → safe_to_spend({})
사용자: 이번 달 남은 돈이 얼마지? → safe_to_spend({})
사용자: 다음 수입 전까지 하루에 얼마 쓸 수 있어? → safe_to_spend({})
사용자: 예산 봉투 재배분안을 보여줘 → rebalance_envelopes({})
사용자: 이번 달 예산 조정이 필요할까? → rebalance_envelopes({})
사용자: 7일간 우려되는 결제가 있어? → spending_alerts({"days":7})
사용자: 오늘 방 상태는 어때? → room_status({})
사용자: 캐릭터가 지금 무엇을 하고 있어? → room_status({})
사용자: 받을 수 있는 정책 혜택이 있어? → policy_tips({})"""


class FdtAgent:
    """FDT 코어 결과를 도구 호출과 코칭으로 연결한다. §8.6"""

    def __init__(self, client: OllamaClient, ctx: TwinContext, persona: str = "온순냥"):
        """§8.6 Ollama 클라이언트와 불변 트윈 컨텍스트를 연결한다."""
        self.client, self.ctx, self.persona = client, ctx, persona
        self.history: list[dict[str, Any]] = []
        self._available_cache: bool | None = None

    def ask(self, user_text: str) -> dict[str, Any]:
        """§8.6 사용자 발화를 라우팅하고 엔진 결과 기반 코칭을 반환한다."""
        if not isinstance(user_text, str) or not user_text.strip():
            raise ValueError("사용자 발화는 비어 있지 않은 문자열이어야 합니다")

        routed_by_llm = self._client_available()
        if routed_by_llm:
            calls = self._llm_calls(user_text)
            if not calls:
                calls = self._fallback_calls(user_text)
        else:
            calls = self._fallback_calls(user_text)
        self._correct_relative_what_if_dates(calls, user_text)

        tool_calls: list[dict[str, Any]] = []
        engine_json: dict[str, Any] = {}
        for call in calls:
            name = str(call.get("name", "get_state"))
            args = call.get("args", {})
            if not isinstance(args, dict):
                args = {}
            result = self._execute(name, args)
            tool_calls.append({"name": name, "args": args, "result": result})
            self._add_engine_result(engine_json, name, result)

        intent = tool_calls[0]["name"] if tool_calls else "get_state"
        coached = self._coach(intent, engine_json, user_text)
        reply = str(coached.get("reply") or coached.get("text") or "")
        if not reply:
            reply = str(coach_module.template_fallback(intent, engine_json, self.persona))
            coached = {
                **coached,
                "text": reply,
                "faithful": True,
                "fallback": True,
                "violations": [],
                "first_faithful": False,
                "attempt": 0,
            }

        self._remember(user_text, reply)
        return {
            "reply": reply,
            "tool_calls": tool_calls,
            "faithful": bool(coached.get("faithful", False)),
            "fallback": bool(coached.get("fallback", False) or not routed_by_llm),
            "first_faithful": bool(coached.get("first_faithful", False)),
            "attempt": coached.get("attempt", 0),
            "violations": coached.get("violations", []),
            "verdict_conflict": coached.get("verdict_conflict"),
            "persona": self.persona,
            "engine_json": engine_json,
        }

    def briefing(self) -> dict[str, Any]:
        """§8.6 상태·안심한도·알림·리스크를 한 번에 코칭한다."""
        calls = [
            ("get_state", {}),
            ("safe_to_spend", {}),
            ("spending_alerts", {}),
            ("payment_risk", {}),
        ]
        tool_calls: list[dict[str, Any]] = []
        engine_json: dict[str, Any] = {}
        for name, args in calls:
            result = self._execute(name, args)
            tool_calls.append({"name": name, "args": args, "result": result})
            self._add_engine_result(engine_json, name, result)

        coached = self._coach("briefing", engine_json, "현재 금융 상태를 간단히 브리핑해줘")
        reply = str(coached.get("reply") or coached.get("text") or "")
        if not reply:
            reply = str(coach_module.template_fallback("briefing", engine_json, self.persona))
            coached = {
                **coached,
                "text": reply,
                "faithful": True,
                "fallback": True,
                "violations": [],
                "first_faithful": False,
                "attempt": 0,
            }
        return {
            "reply": reply,
            "tool_calls": tool_calls,
            "faithful": bool(coached.get("faithful", False)),
            "fallback": bool(coached.get("fallback", True)),
            "first_faithful": bool(coached.get("first_faithful", False)),
            "attempt": coached.get("attempt", 0),
            "violations": coached.get("violations", []),
            "verdict_conflict": coached.get("verdict_conflict"),
            "persona": self.persona,
            "engine_json": engine_json,
        }

    def _client_available(self) -> bool:
        if self._available_cache is not None:
            return self._available_cache
        available = getattr(self.client, "available", None)
        if available is None:
            self._available_cache = True
        elif not callable(available):
            self._available_cache = bool(available)
        else:
            try:
                self._available_cache = bool(available())
            except Exception:
                self._available_cache = False
        return self._available_cache

    def _llm_calls(self, user_text: str) -> list[dict[str, Any]]:
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}, *self.history[-12:], {"role": "user", "content": user_text}]
        try:
            response = self.client.chat(messages, tools=TOOL_SPECS, temperature=0.0)
        except Exception:
            return []
        raw_calls: Any = response
        if isinstance(response, Mapping) and isinstance(response.get("message"), Mapping):
            raw_calls = response["message"]
        if isinstance(raw_calls, Mapping):
            raw_calls = raw_calls.get("tool_calls", [])
        if not isinstance(raw_calls, list):
            return []

        calls: list[dict[str, Any]] = []
        for raw in raw_calls:
            if not isinstance(raw, Mapping):
                continue
            function = raw.get("function") if isinstance(raw.get("function"), Mapping) else raw
            name = function.get("name") if isinstance(function, Mapping) else None
            if not name:
                continue
            raw_args = function.get("arguments", {}) if isinstance(function, Mapping) else {}
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}
            calls.append({"name": str(name), "args": args if isinstance(args, dict) else {}})
        return calls

    def _execute(self, name: str, args: dict[str, Any]) -> Any:
        try:
            result = execute_tool(name, args, self.ctx)
            if isinstance(result, Mapping):
                return dict(result)
            if hasattr(result, "model_dump"):
                return result.model_dump(mode="json")
            return result
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    def _add_engine_result(engine_json: dict[str, Any], name: str, result: Any) -> None:
        if name not in engine_json:
            engine_json[name] = result
        elif isinstance(engine_json[name], list):
            engine_json[name].append(result)
        else:
            engine_json[name] = [engine_json[name], result]

    def _coach(self, intent: str, engine_json: dict[str, Any], user_text: str) -> dict[str, Any]:
        try:
            result = coach_module.coach(self.client, self.persona, intent, engine_json, user_text)
            if isinstance(result, Mapping):
                return dict(result)
            return {
                "text": str(result), "faithful": True, "fallback": True, "violations": [],
                "verdict_conflict": None, "first_faithful": False, "attempt": 0,
            }
        except Exception:
            try:
                text = coach_module.template_fallback(intent, engine_json, self.persona)
            except Exception as exc:
                text = f"현재 상태를 계산하지 못했어요. ({exc})"
            return {
                "text": text, "faithful": True, "fallback": True, "violations": [],
                "verdict_conflict": None, "first_faithful": False, "attempt": 0,
            }

    def _remember(self, user_text: str, reply: str) -> None:
        self.history.extend(({"role": "user", "content": user_text}, {"role": "assistant", "content": reply}))
        del self.history[:-12]

    def _fallback_calls(self, text: str) -> list[dict[str, Any]]:
        """§8.1 LLM 미가동 시 사용하는 최소 결정론 라우터."""
        lowered = text.lower()
        amount = _parse_amount(text)
        what_if_words = ("써도", "쓰면", "사도", "구매", "결제", "지출", "살까", "사용해도")
        if amount is not None and any(word in text for word in what_if_words):
            target = _parse_target_date(text, self.ctx.state.as_of)
            days = max(0, min(60, (target - self.ctx.state.as_of).days)) if target else _parse_days(text, self.ctx.state.as_of)
            return [{
                "name": "what_if",
                "args": {
                    "amount": amount,
                    "envelope": _parse_envelope(text),
                    "days_from_now": days,
                    "via_card": "체크" not in text and "계좌" not in text,
                    "label": text[:80],
                },
            }]
        if any(word in text for word in ("모으", "모을", "저축", "저금", "목표", "달성")):
            args: dict[str, Any] = {"target_amount": amount or 0}
            target_date = _parse_target_date(text, self.ctx.state.as_of)
            if target_date:
                args["target_date"] = target_date.isoformat()
            return [{"name": "goal_plan", "args": args}]
        if any(word in text for word in ("재배분", "옮겨", "예산", "봉투")):
            return [{"name": "rebalance_envelopes", "args": {}}]
        if any(word in text for word in ("위험", "부족", "카드값", "카드대금", "결제일", "리스크")):
            return [{"name": "payment_risk", "args": {"horizon_days": _parse_horizon(text)}}]
        if any(word in text for word in ("예측", "전망", "미래", "궤적")):
            return [{"name": "forecast_balance", "args": {"horizon_days": _parse_horizon(text)}}]
        if any(word in text for word in ("알림", "우려", "가속", "걱정", "소비가 빨라", "소비 속도")):
            return [{"name": "spending_alerts", "args": {"days": min(7, max(1, _parse_horizon(text)))}}]
        if any(word in text for word in ("방", "고양이", "날씨", "캐릭터", "기분", "하고 있어")):
            return [{"name": "room_status", "args": {}}]
        if any(word in text for word in ("정책", "혜택", "추천")):
            return [{"name": "policy_tips", "args": {}}]
        if any(word in text for word in ("오늘", "안심", "남은 돈", "얼마까지", "편하게 써도")):
            return [{"name": "safe_to_spend", "args": {}}]
        if "잔액" in lowered:
            return [{"name": "get_state", "args": {}}]
        return [{"name": "get_state", "args": {}}]

    def _correct_relative_what_if_dates(self, calls: list[dict[str, Any]], text: str) -> None:
        """상대 날짜가 있는 가상 지출은 기준일 기준 days_from_now로 고정한다."""
        target = _parse_target_date(text, self.ctx.state.as_of)
        if target is None:
            return
        days = max(0, min(60, (target - self.ctx.state.as_of).days))
        for call in calls:
            if call.get("name") != "what_if":
                continue
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            call["args"] = {**args, "days_from_now": days}


def _parse_amount(text: str) -> int | None:
    compact = text.replace(" ", "")
    matches = list(re.finditer(
        r"(?<!\d)[\d,.]+\s*(?:억|만|천|백|원)"
        r"(?:(?:[\d,.]+\s*)?(?:억|만|천|백|원))*",
        compact,
    ))
    if matches:
        raw = matches[-1].group()
        try:
            return normalize_amount(raw)
        except ValueError:
            return None
    match = re.search(
        r"(?<![\d./-])(\d[\d,]*(?:\.\d+)?)(?![\d./-]|\s*(?:일|월|년|주|%|배|점))",
        compact,
    )
    if match:
        return int(match.group(1).replace(",", ""))
    return None


def _parse_days(text: str, as_of: date | None = None) -> int:
    base = as_of or date.today()
    candidates = (
        r"\d+\s*일\s*(?:뒤|후)",
        r"(?:다음|이번)\s*달\s*\d{1,2}\s*일(?:까지|에)?",
        r"(?:다음|이번)\s*달\s*말(?:일까지|까지|일)?",
        r"(?:이번|다음)\s*주말|주말",
        r"\d+\s*개월\s*(?:뒤|후)",
        r"(?:다음|이번)\s*주\s*[월화수목금토일]요일?",
        r"(?:오늘|당일|내일|익일|모레)",
        r"이번\s*달\s*말(?:일)?",
        r"다음\s*주(?:초)?",
        r"\d{1,2}\s*(?:~|〜|-)\s*\d{1,2}\s*일(?:에|까지)?",
        r"\d{1,2}\s*일(?:에|까지)?",
    )
    for pattern in candidates:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            target = normalize_date(match.group(), base)
        except ValueError:
            continue
        return max(0, min(60, (target - base).days))
    return 0


def _parse_horizon(text: str) -> int:
    match = re.search(r"(\d+)\s*일", text)
    return min(60, max(1, int(match.group(1)))) if match else 30


def _parse_target_date(text: str, as_of: date) -> date | None:
    patterns = (
        r"20\d{2}[-./년]\s*\d{1,2}[-./월]\s*\d{1,2}일?",
        r"(?:다음|이번)\s*달\s*\d{1,2}\s*일(?:까지|에)?",
        r"(?:다음|이번)\s*달\s*말(?:일까지|까지|일)?",
        r"\d{1,2}월\s*\d{1,2}일",
        r"\d{1,2}월(?:말까지|까지|말)?",
        r"(?:이번|다음)\s*주말",
        r"주말",
        r"\d+\s*개월\s*(?:뒤|후)",
        r"이번\s*달\s*말(?:일)?",
        r"\d{1,2}\s*(?:~|〜|-)\s*\d{1,2}\s*일(?:까지|에)?",
        r"\d{1,2}\s*일(?:까지|에)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            return normalize_date(match.group(), as_of)
        except ValueError:
            return None
    return None


def _parse_envelope(text: str) -> str:
    groups = {
        "외식": ("외식", "밥", "식비", "커피", "카페", "음식", "배달"),
        "교통비": ("교통", "택시", "지하철", "버스", "주유"),
        "의료·건강": ("의료", "건강", "병원", "약", "헬스", "운동"),
        "취미·여가": ("취미", "여가", "영화", "게임", "여행"),
        "쇼핑": ("쇼핑", "옷", "화장품", "신발", "패션", "뷰티"),
        "편의점·마트·잡화": ("편의점", "마트", "다이소", "잡화", "생활용품", "장보기"),
    }
    for envelope, words in groups.items():
        if any(word in text for word in words):
            return envelope
    return "기타"
