"""코칭 숫자 충실도 + 툴 라우팅 평가. 설계: docs/03_FDT_설계.md §11.6, §11.7"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from fdt.eval.backtest import _build_model, _date_key, _load_inputs, _seed_dir
from fdt.agent.tools import normalize_date

PERSONAS = ("도도냥", "온순냥", "지방냥")
TOOLS = {
    "get_state", "forecast_balance", "what_if", "payment_risk", "goal_plan",
    "safe_to_spend", "rebalance_envelopes", "spending_alerts", "room_status", "policy_tips",
}
_ENVELOPE_ALIASES = {
    "밥": "외식", "식비": "외식", "커피": "외식", "음식": "외식", "외식": "외식",
    "옷": "쇼핑", "신발": "쇼핑", "화장품": "쇼핑", "쇼핑": "쇼핑",
    "택시": "교통비", "지하철": "교통비", "버스": "교통비", "교통": "교통비", "교통비": "교통비",
    "병원": "의료·건강", "약": "의료·건강", "건강": "의료·건강", "의료": "의료·건강", "의료·건강": "의료·건강",
    "영화": "취미·여가", "게임": "취미·여가", "여행": "취미·여가", "취미": "취미·여가", "취미·여가": "취미·여가",
    "편의점": "편의점·마트·잡화", "마트": "편의점·마트·잡화", "잡화": "편의점·마트·잡화", "편의점·마트·잡화": "편의점·마트·잡화",
    "기타": "기타",
}


def _items(path: Path, key: str) -> list[dict[str, Any]]:
    """§11.6/§11.7 YAML의 list·wrapper 형식을 모두 읽는다."""
    loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if isinstance(loaded, list):
        return [item for item in loaded if isinstance(item, dict)]
    if isinstance(loaded, dict):
        value = loaded.get(key, loaded.get("items", loaded.get("cases", [])))
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    raise ValueError(f"{path} must contain a list of {key}")


def _date(value: str) -> date:
    """§11.7 YYYYMMDD 또는 YYYY-MM-DD를 date로 변환한다."""
    key = _date_key(value)
    return date.fromisoformat(f"{key[:4]}-{key[4:6]}-{key[6:8]}")


def _field(item: dict[str, Any], *names: str, default: Any = None) -> Any:
    """§11.6/§11.7 입력 별칭을 단일 필드로 읽는다."""
    for name in names:
        if name in item:
            return item[name]
    return default


def _as_of(seed_dir: Path) -> date:
    """§11.6/§11.7 최신 정답 날짜를 에이전트 기준일로 사용한다."""
    _, _, truth = _load_inputs(seed_dir)
    keys = sorted(_date_key(value) for value in truth.get("daily_balance", {}))
    if not keys:
        raise ValueError(f"daily_balance is empty: {seed_dir}")
    return _date(keys[-1])


def _agent(seed_dir: Path, persona: str) -> Any:
    """§11.6/§11.7 한 프로필·코치 페르소나의 에이전트를 만든다."""
    from fdt.agent.agent import FdtAgent
    from fdt.agent.llm import OllamaClient
    from fdt.agent.tools import TwinContext

    snapshot, transactions, _ = _load_inputs(seed_dir)
    as_of = _as_of(seed_dir)
    state, behavior = _build_model(transactions, snapshot, as_of)
    try:
        client = OllamaClient(timeout=5.0)
    except TypeError:
        client = OllamaClient()
    return FdtAgent(client, TwinContext(snapshot, transactions, state, behavior, seed=42), persona=persona)


def _response_value(response: Any, key: str, default: Any = None) -> Any:
    """§11.6 에이전트 dict 또는 모델 결과에서 값을 꺼낸다."""
    if isinstance(response, dict):
        return response.get(key, default)
    return getattr(response, key, default)


def _args(value: Any) -> dict[str, Any]:
    """§11.7 툴 인자 dict·JSON 문자열·pydantic 결과를 dict로 통일한다."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        parsed = dump()
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _first_pass(response: Any, faithful: bool, fallback: bool) -> bool:
    """§11.6 명시된 초기 검사값을 우선하고, 구버전 결과는 보수적으로 추정한다."""
    for key in ("first_faithful", "initial_faithful", "first_pass"):
        value = _response_value(response, key)
        if value is not None:
            return bool(value)
    return bool(faithful and not fallback)


def _attempt(response: Any, first_pass: bool, fallback: bool) -> int:
    """코치의 1차/재생성 상태를 정수 시도 횟수로 통일한다."""
    value = _response_value(response, "attempt")
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if isinstance(value, str):
        labels = {"first": 1, "initial": 1, "retry": 2, "regenerated": 2, "fallback": 0}
        if value.lower() in labels:
            return labels[value.lower()]
        try:
            return max(0, int(value))
        except ValueError:
            pass
    if fallback:
        return 0
    return 1 if first_pass else 2


def run_faithfulness(seed_root: Path, scenarios_path: Path) -> dict[str, Any]:
    """§11.6 시나리오×페르소나를 실행해 충실도·재생성·폴백 지표를 낸다."""
    scenarios = _items(Path(scenarios_path), "scenarios")
    profile_dirs = {path.name: path for path in _profile_dirs(Path(seed_root))}
    results: list[dict[str, Any]] = []
    agents: dict[tuple[str, str], Any] = {}
    for scenario_index, scenario in enumerate(scenarios):
        profile_id = str(_field(scenario, "profile_id", "profile", default=""))
        text = str(_field(scenario, "utterance", "message", "text", default=""))
        scenario_id = str(_field(scenario, "id", "scenario_id", default=f"scenario-{scenario_index + 1}"))
        for persona in PERSONAS:
            item = {"scenario": scenario_id, "profile": profile_id, "persona": persona,
                    "faithful": False, "fallback": False, "first_faithful": False,
                    "first_pass": False, "attempt": 0, "retry_pass": False,
                    "violations": [], "verdict_conflict": None}
            try:
                directory = profile_dirs[profile_id]
                key = (profile_id, persona)
                if key not in agents:
                    agents[key] = _agent(directory, persona)
                response = agents[key].ask(text)
                faithful = bool(_response_value(response, "faithful", False))
                fallback = bool(_response_value(response, "fallback", False))
                first_pass = _first_pass(response, faithful, fallback)
                attempt = _attempt(response, first_pass, fallback)
                retry_pass = bool(attempt >= 2 and not first_pass and faithful and not fallback)
                violations = _response_value(response, "violations", []) or []
                if not isinstance(violations, list):
                    violations = [violations]
                item.update(
                    faithful=faithful,
                    fallback=fallback,
                    first_faithful=first_pass,
                    first_pass=first_pass,
                    attempt=attempt,
                    retry_pass=retry_pass,
                    violations=violations,
                    verdict_conflict=_response_value(response, "verdict_conflict"),
                )
            except Exception as exc:  # evaluation report keeps the remaining cases observable
                item["error"] = f"{type(exc).__name__}: {exc}"
            results.append(item)

    total = len(results)
    first_count = sum(bool(item["first_pass"]) for item in results)
    final_count = sum(bool(item["faithful"]) for item in results)
    fallback_count = sum(bool(item["fallback"]) for item in results)
    retry_count = sum(bool(item["attempt"] >= 2 and not item["first_pass"]) for item in results)
    retry_pass_count = sum(bool(item["retry_pass"]) for item in results)
    verdict_conflict_count = sum(
        bool(item.get("verdict_conflict")) or _has_violation(item.get("violations", []), "verdict_conflict")
        for item in results
    )
    date_mismatch_count = sum(
        _has_violation(item.get("violations", []), "date_mismatch") for item in results
    )
    unfaithful = total - final_count
    first_rate = first_count / total if total else 0.0
    final_rate = final_count / total if total else 0.0
    fallback_rate = fallback_count / total if total else 0.0
    retry_pass_rate = retry_pass_count / retry_count if retry_count else 0.0
    criteria = {
        "first_pass_min": 0.80,
        "fallback_max": 0.20,
        "unfaithful_max": 0,
        "verdict_conflict_max": 0,
    }
    passed = bool(
        total
        and first_rate >= criteria["first_pass_min"]
        and fallback_rate <= criteria["fallback_max"]
        and unfaithful <= criteria["unfaithful_max"]
        and verdict_conflict_count <= criteria["verdict_conflict_max"]
    )
    return {"scenarios": len(scenarios), "personas": len(PERSONAS), "total": total,
            "first_pass_rate": first_rate, "retry_pass_rate": retry_pass_rate,
            "final_pass_rate": final_rate, "fallback_rate": fallback_rate,
            "fallback_count": fallback_count, "retry_count": retry_count,
            "retry_pass_count": retry_pass_count,
            "unfaithful_count": unfaithful,
            "verdict_conflict_count": verdict_conflict_count,
            "date_mismatch_count": date_mismatch_count,
            "criteria": criteria,
            "passed": passed, "status": "complete" if total and not any("error" in item for item in results) else "blocked",
            "results": results}


def _has_violation(violations: Any, code: str) -> bool:
    if not isinstance(violations, list):
        return violations == code
    return any(
        item == code or (isinstance(item, dict) and item.get("type") == code)
        for item in violations
    )


def _profile_dirs(seed_root: Path) -> list[Path]:
    """§11.7 평가 프로필을 찾는다."""
    root = Path(seed_root)
    if (root / "snapshot.json").exists():
        return [_seed_dir(root)]
    if not root.exists():
        raise FileNotFoundError(f"seed root not found: {root}")
    return sorted(path for path in root.iterdir() if path.is_dir() and (path / "snapshot.json").exists())


def _normalize_envelope(value: Any) -> str:
    """§11.7 봉투 동의어를 설계서의 표준명으로 바꾼다."""
    text = str(value).strip()
    return _ENVELOPE_ALIASES.get(text, text)


def _amount(text: str) -> int | None:
    """§11.7 한국어 금액 표현을 정수 원으로 읽는다."""
    matches = re.finditer(r"(\d[\d,]*)\s*(억|만|천)?\s*(\d[\d,]*)?\s*(만|천)?\s*(원)?", text)
    candidates: list[re.Match[str]] = []
    for match in matches:
        if match.group(2) or match.group(4) or match.group(5):
            candidates.append(match)
    if not candidates:
        return None
    match = candidates[-1]
    first = int(match.group(1).replace(",", ""))
    unit, tail, tail_unit = match.group(2), match.group(3), match.group(4)
    value = first * (100_000_000 if unit == "억" else 10_000 if unit == "만" else 1_000 if unit == "천" else 1)
    if tail:
        extra = int(tail.replace(",", ""))
        value += extra * (10_000 if tail_unit == "만" else 1_000 if tail_unit == "천" else 1)
    return value


def _days(text: str, as_of: date | None = None) -> int | None:
    """§11.7 기존 날짜 정규화기로 상대·bare-day 표현을 읽는다."""
    base = as_of or date.today()
    patterns = (
        r"\d+\s*일\s*(?:뒤|후)",
        r"(?:다음|이번)\s*주\s*[월화수목금토일]요일?",
        r"(?:오늘|당일|내일|익일|모레)",
        r"이번\s*달\s*말(?:일)?",
        r"다음\s*주(?:초)?",
        r"\d{1,2}\s*(?:~|〜|-)\s*\d{1,2}\s*일(?:에|까지)?",
        r"\d{1,2}\s*일(?:에|까지)?",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            target = normalize_date(match.group(), base)
        except ValueError:
            continue
        return max(0, min(60, (target - base).days))
    return None


def _rule_route(text: str, as_of: date | None = None) -> tuple[str, dict[str, Any]]:
    """§11.7 LLM 미가동 기준선용 최소 결정론 라우터."""
    value = _amount(text)
    if value is not None and any(word in text for word in ("사도", "써도", "구매", "쓰면", "결제해도", "결제해", "사용해도")):
        tool = "what_if"
    elif any(word in text for word in ("모으", "모을", "저축", "저금", "목표", "달성")):
        tool = "goal_plan"
    elif any(word in text for word in ("재배분", "옮겨", "예산 조정", "다시 나눠", "봉투별 예산", "봉투")):
        tool = "rebalance_envelopes"
    elif any(word in text for word in ("위험", "부족", "카드값", "카드대금", "결제일", "리스크")):
        tool = "payment_risk"
    elif any(word in text for word in ("알림", "우려", "소비가 빨라", "소비 속도", "가속", "걱정")):
        tool = "spending_alerts"
    elif any(word in text for word in ("방", "날씨", "고양이", "기분", "캐릭터", "하고 있어")):
        tool = "room_status"
    elif any(word in text for word in ("정책", "혜택", "추천")):
        tool = "policy_tips"
    elif any(word in text for word in ("예측", "앞으로", "잔액", "현금 흐름", "미래")) and "남은" not in text:
        tool = "forecast_balance"
    elif any(word in text for word in ("남은 돈", "안심", "오늘 쓸", "얼마", "편하게 써도", "되는 금액")):
        tool = "safe_to_spend"
    else:
        tool = "get_state"
    args: dict[str, Any] = {}
    if tool == "what_if":
        if value is not None:
            args["amount"] = value
        offset = _days(text, as_of)
        if offset is not None:
            args["days_from_now"] = offset
        args["via_card"] = "카드" in text or ("계좌" not in text and "체크" not in text)
        for alias in _ENVELOPE_ALIASES:
            if alias in text:
                args["envelope"] = _ENVELOPE_ALIASES[alias]
                break
    elif tool == "goal_plan":
        if value is not None:
            args["target_amount"] = value
        patterns = (
            r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}",
            r"\d{1,2}월\s*\d{1,2}일",
            r"\d{1,2}월(?:말까지|까지|말)?",
            r"이번\s*달\s*말(?:일)?",
            r"\d{1,2}\s*(?:~|〜|-)\s*\d{1,2}\s*일(?:까지|에)?",
            r"\d{1,2}\s*일(?:까지|에)",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            try:
                args["target_date"] = normalize_date(match.group(), as_of).isoformat()
            except ValueError:
                pass
            break
    elif tool == "forecast_balance":
        match = re.search(r"(\d+)\s*일", text)
        if match:
            args["horizon_days"] = int(match.group(1))
    elif tool == "payment_risk":
        match = re.search(r"(\d+)\s*일", text)
        if match:
            args["horizon_days"] = int(match.group(1))
    elif tool == "spending_alerts":
        match = re.search(r"(\d+)\s*일", text)
        args["days"] = int(match.group(1)) if match else 1
    return tool, args


def _route(response: Any, text: str, as_of: date | None = None) -> tuple[str | None, dict[str, Any]]:
    """§11.7 에이전트 응답에서 첫 툴과 파라미터를 추출한다."""
    calls = _response_value(response, "tool_calls", []) or []
    if calls:
        call = calls[0]
        if isinstance(call, dict):
            return call.get("name"), _args(call.get("args", {}))
        return getattr(call, "name", None), _args(getattr(call, "args", {}))
    route = _response_value(response, "route", []) or []
    if isinstance(route, list):
        names = [name for name in route if name in TOOLS]
        if names:
            return names[0], _args(_response_value(response, "args", {}))
    name = _response_value(response, "tool")
    return (name, _args(_response_value(response, "args", {}))) if name else _rule_route(text, as_of)


def _same_value(expected: Any, actual: Any, key: str) -> bool:
    """§11.7 정규화 후 금액·날짜·봉투 파라미터를 비교한다."""
    if key == "envelope":
        return _normalize_envelope(expected) == _normalize_envelope(actual)
    if key in {"amount", "target_amount"}:
        try:
            return int(expected) == int(actual)
        except (TypeError, ValueError):
            return False
    if key in {"days_from_now", "horizon_days", "days"}:
        try:
            return abs(int(expected) - int(actual)) <= (1 if key == "days_from_now" else 0)
        except (TypeError, ValueError):
            return False
    if key == "target_date":
        try:
            return abs((_date(str(expected)) - _date(str(actual))).days) <= 1
        except (TypeError, ValueError):
            return False
    return expected == actual


def _params_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """§11.7 예상 파라미터가 모두 존재하고 값이 일치하는지 확인한다."""
    return all(key in actual and _same_value(value, actual[key], key) for key, value in expected.items())


def run_routing(seed_root: Path, utterances_path: Path) -> dict[str, Any]:
    """§11.7 라벨 발화의 툴 정확도와 파라미터 완전 일치율을 계산한다."""
    utterances = _items(Path(utterances_path), "utterances")
    directories = _profile_dirs(Path(seed_root))
    if not directories:
        raise FileNotFoundError(f"no seed profiles found: {seed_root}")
    agents: dict[str, Any] = {}
    cases: list[dict[str, Any]] = []
    for index, utterance in enumerate(utterances):
        text = str(_field(utterance, "utterance", "message", "text", default=""))
        expected_tool = str(_field(utterance, "tool", "intent", "expected_tool", default=""))
        expected_args = _field(utterance, "args", "parameters", default={}) or {}
        profile_id = str(_field(utterance, "profile_id", "profile", default=directories[index % len(directories)].name))
        item = {"id": str(_field(utterance, "id", default=f"utterance-{index + 1}")),
                "profile": profile_id, "utterance": text, "expected_tool": expected_tool,
                "expected_args": expected_args, "predicted_tool": None, "predicted_args": {},
                "tool_correct": False, "parameters_correct": False}
        directory = next((path for path in directories if path.name == profile_id), None)
        as_of = _as_of(directory) if directory is not None else None
        try:
            if directory is None:
                raise KeyError(profile_id)
            if profile_id not in agents:
                agents[profile_id] = _agent(directory, "온순냥")
            response = agents[profile_id].ask(text)
            predicted_tool, predicted_args = _route(response, text, as_of)
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
            predicted_tool, predicted_args = _rule_route(text, as_of)
            item["mode"] = "rules"
        item.update(predicted_tool=predicted_tool, predicted_args=predicted_args,
                    tool_correct=predicted_tool == expected_tool,
                    parameters_correct=predicted_tool == expected_tool and _params_match(expected_args, predicted_args))
        cases.append(item)

    total = len(cases)
    tool_correct = sum(item["tool_correct"] for item in cases)
    parameter_correct = sum(item["parameters_correct"] for item in cases)
    tool_accuracy = tool_correct / total if total else 0.0
    parameter_accuracy = parameter_correct / total if total else 0.0
    errors = any("error" in item for item in cases)
    return {"total": total, "tool_correct": tool_correct, "parameter_correct": parameter_correct,
            "tool_accuracy": tool_accuracy, "parameter_accuracy": parameter_accuracy,
            "criteria": {"tool_accuracy_min": 0.85, "parameter_accuracy_min": 0.75, "rules_baseline_min": 0.60},
            "passed": bool(total and tool_accuracy >= 0.85 and parameter_accuracy >= 0.75),
            "status": "complete" if total and not errors else "blocked", "cases": cases}
