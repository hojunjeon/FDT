"""턴 로그 JSONL 운영 지표 보고서 (설계: PLAN.md Task D)."""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


_LATENCY_FIELDS = ("total", "engine", "llm")
_ERROR_TYPES = frozenset({"timeout", "connection", "parse", "other"})


def _number(value: Any) -> float | None:
    """불리언이 아닌 유한 숫자를 float로 통일한다."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nonnegative_int(value: Any) -> int:
    number = _number(value)
    return max(0, int(number)) if number is not None else 0


def _label(value: Any, default: str = "unknown") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    """정렬된 값 사이를 선형 보간하는 p50/p95를 계산한다."""
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _tool_calls(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _tool_name(call: Any) -> str:
    if isinstance(call, dict):
        name = call.get("name")
        if name is None and isinstance(call.get("function"), dict):
            name = call["function"].get("name")
    else:
        name = getattr(call, "name", None)
    return _label(name)


def _route_path(value: Any) -> str:
    if isinstance(value, str):
        parts = [value.strip()] if value.strip() else []
    elif isinstance(value, (list, tuple)):
        parts = [_label(part) for part in value if str(part).strip()]
    else:
        parts = []
    return " -> ".join(parts) or "(none)"


def _violation_types(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        if isinstance(item, dict):
            kind = item.get("type", item.get("code", item.get("name", item.get("kind"))))
        else:
            kind = item
        result.append(_label(kind))
    return result


def _error_type(value: Any) -> str | None:
    if value is None or value is False or value == "":
        return None
    if not isinstance(value, dict) or not value:
        return "other"
    kind = _label(value.get("type"), "other")
    return kind if kind in _ERROR_TYPES else "other"


def _model_key(value: Any) -> str:
    return "null" if value is None else _label(value)


def _aggregate(records: list[dict[str, Any]], *, include_models: bool = True) -> dict[str, Any]:
    turns = len(records)
    sessions: set[str] = set()
    surfaces: Counter[str] = Counter()
    routes: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    attempts: Counter[str] = Counter()
    violations: Counter[str] = Counter()
    latencies: dict[str, list[float]] = {field: [] for field in _LATENCY_FIELDS}
    error_types: Counter[str] = Counter()
    fallback_causes: Counter[str] = Counter()
    token_prompt = 0.0
    token_completion = 0.0
    fallback_count = 0
    first_faithful_count = 0
    verdict_conflict_count = 0

    model_records: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        sessions.add(_label(record.get("session_id")))
        surfaces[_label(record.get("surface"))] += 1
        routes[_route_path(record.get("route"))] += 1

        calls = _tool_calls(record.get("tool_calls"))
        for call in calls:
            tools[_tool_name(call)] += 1

        attempt = _nonnegative_int(record.get("attempt"))
        attempts[str(attempt)] += 1
        violation_names = _violation_types(record.get("violations"))
        violations.update(violation_names)

        if bool(record.get("fallback")):
            fallback_count += 1
        if bool(record.get("first_faithful")):
            first_faithful_count += 1
        if record.get("verdict_conflict") not in (None, False, "") or "verdict_conflict" in violation_names:
            verdict_conflict_count += 1

        error_kind = _error_type(record.get("llm_error"))
        if error_kind is not None:
            error_types[error_kind] += 1
        if bool(record.get("fallback")):
            fallback_causes[error_kind or "unknown"] += 1

        latency = record.get("latency_ms")
        if isinstance(latency, dict):
            for field in _LATENCY_FIELDS:
                value = _number(latency.get(field))
                if value is not None:
                    latencies[field].append(value)

        tokens = record.get("tokens")
        if isinstance(tokens, dict):
            token_prompt += _number(tokens.get("prompt")) or 0.0
            token_completion += _number(tokens.get("completion")) or 0.0

        if include_models:
            model_records.setdefault(_model_key(record.get("llm_model")), []).append(record)

    total_calls = sum(tools.values())
    error_count = sum(error_types.values())
    fallback_rate = fallback_count / turns if turns else 0.0
    first_faithful_rate = first_faithful_count / turns if turns else 0.0
    llm_error_rate = error_count / turns if turns else 0.0

    report: dict[str, Any] = {
        "turns": turns,
        "sessions": len(sessions),
        "surfaces": dict(sorted(surfaces.items())),
        "tool_calls": {
            "total": total_calls,
            "by_tool": dict(sorted(tools.items())),
            "avg_per_turn": total_calls / turns if turns else 0.0,
        },
        "routes": dict(sorted(routes.items())),
        "fallback": {
            "count": fallback_count,
            "rate": fallback_rate,
            "causes": dict(sorted(fallback_causes.items())),
        },
        "fallback_rate": fallback_rate,
        "first_faithful": {
            "count": first_faithful_count,
            "rate": first_faithful_rate,
        },
        "first_faithful_rate": first_faithful_rate,
        "attempts": {
            "distribution": {key: attempts[key] for key in sorted(attempts, key=lambda item: int(item))},
            "avg": sum(int(key) * count for key, count in attempts.items()) / turns if turns else 0.0,
        },
        "violations": {
            "total": sum(violations.values()),
            "by_type": dict(sorted(violations.items())),
        },
        "verdict_conflict_count": verdict_conflict_count,
        "latency_ms": {
            field: {
                "p50": _percentile(latencies[field], 50),
                "p95": _percentile(latencies[field], 95),
            }
            for field in _LATENCY_FIELDS
        },
        "tokens": {
            "prompt": token_prompt,
            "completion": token_completion,
            "total": token_prompt + token_completion,
            "avg_per_turn": {
                "prompt": token_prompt / turns if turns else 0.0,
                "completion": token_completion / turns if turns else 0.0,
                "total": (token_prompt + token_completion) / turns if turns else 0.0,
            },
        },
        "llm_errors": {
            "count": error_count,
            "rate": llm_error_rate,
            "by_type": dict(sorted(error_types.items())),
        },
        "llm_error_rate": llm_error_rate,
    }
    if include_models:
        report["models"] = {
            model: _aggregate(model_rows, include_models=False)
            for model, model_rows in sorted(model_records.items())
        }
    return report


def _records(log_dir: Path) -> tuple[list[dict[str, Any]], int]:
    root = Path(log_dir)
    if not root.exists():
        raise FileNotFoundError(f"turn log directory not found: {root}")
    paths = [root] if root.is_file() else sorted(root.rglob("*.jsonl"))
    records: list[dict[str, Any]] = []
    skipped = 0
    for path in paths:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except (TypeError, json.JSONDecodeError):
                    skipped += 1
                    continue
                if not isinstance(value, dict):
                    skipped += 1
                    continue
                records.append(value)
    return records, skipped


def run_report(log_dir: Path, out: Path | None = None) -> dict[str, Any]:
    """모든 JSONL 턴 로그를 집계하고 선택적으로 JSON 파일에 저장한다."""
    root = Path(log_dir)
    missing = not root.exists()
    records, skipped = ([], 0) if missing else _records(root)
    report = _aggregate(records)
    report["skipped_lines"] = skipped
    report["log_dir_missing"] = missing
    if out is not None:
        output = Path(out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _table(rows: Iterable[tuple[str, Any]]) -> list[str]:
    lines = ["| 항목 | 값 |", "| --- | ---: |"]
    lines.extend(f"| {name} | {value} |" for name, value in rows)
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    """운영 지표를 사람이 읽는 Markdown 표로 렌더링한다."""
    fallback = report.get("fallback") or {}
    faithful = report.get("first_faithful") or {}
    errors = report.get("llm_errors") or {}
    tools = report.get("tool_calls") or {}
    latency = report.get("latency_ms") or {}
    tokens = report.get("tokens") or {}
    attempts = report.get("attempts", {}) or {}
    violation_report = report.get("violations", {}) or {}
    lines = [
        "# FDT 턴 로그 운영 지표",
        "",
        *_table((
            ("턴 수", report.get("turns", 0)),
            ("세션 수", report.get("sessions", 0)),
            ("fallback 비율", f"{float(fallback.get('rate', report.get('fallback_rate', 0))):.2%}"),
            ("1차 faithful 비율", f"{float(faithful.get('rate', report.get('first_faithful_rate', 0))):.2%}"),
            ("LLM 오류 비율", f"{float(errors.get('rate', report.get('llm_error_rate', 0))):.2%}"),
            ("verdict_conflict 건수", report.get("verdict_conflict_count", 0)),
            ("건너뛴 줄", report.get("skipped_lines", 0)),
        )),
        "",
        "## Surface 분포",
        "",
        *_table(sorted((str(key), value) for key, value in (report.get("surfaces", {}) or {}).items())),
        "",
        "## 도구 호출",
        "",
        *_table([
            ("전체 호출", tools.get("total", 0)),
            ("턴당 평균", tools.get("avg_per_turn", 0)),
            *[(f"도구: {key}", value) for key, value in sorted((tools.get("by_tool", {}) or {}).items())],
        ]),
        "",
        "## Route 경로",
        "",
        *_table(sorted((str(key), value) for key, value in (report.get("routes", {}) or {}).items())),
        "",
        "## 지연 시간 (ms)",
        "",
        "| 구간 | p50 | p95 |",
        "| --- | ---: | ---: |",
    ]
    for field in _LATENCY_FIELDS:
        values = latency.get(field, {}) or {}
        lines.append(f"| {field} | {values.get('p50')} | {values.get('p95')} |")
    lines.extend([
        "",
        "## 토큰",
        "",
        "| 구분 | 합계 | 턴당 평균 |",
        "| --- | ---: | ---: |",
    ])
    averages = tokens.get("avg_per_turn", {}) or {}
    for field in ("prompt", "completion", "total"):
        lines.append(f"| {field} | {tokens.get(field, 0)} | {averages.get(field, 0)} |")
    lines.extend(["", "## 시도·위반·오류", "", *_table([
        ("시도 분포", json.dumps(attempts.get("distribution", {}), ensure_ascii=False)),
        ("위반 유형", json.dumps(violation_report.get("by_type", {}), ensure_ascii=False)),
        ("fallback 원인", json.dumps(fallback.get("causes", {}), ensure_ascii=False)),
        ("LLM 오류 유형", json.dumps(errors.get("by_type", {}), ensure_ascii=False)),
    ]), "", "## 모델별", ""])
    model_rows = report.get("models", {}) or {}
    if model_rows:
        lines.extend(("| 모델 | 턴 수 | fallback 비율 | 1차 faithful 비율 | LLM 오류 비율 |",
                      "| --- | ---: | ---: | ---: | ---: |"))
        for model, values in sorted(model_rows.items()):
            lines.append(
                f"| {model} | {values.get('turns', 0)} | "
                f"{float((values.get('fallback', {}) or {}).get('rate', 0)):.2%} | "
                f"{float((values.get('first_faithful', {}) or {}).get('rate', 0)):.2%} | "
                f"{float((values.get('llm_errors', {}) or {}).get('rate', 0)):.2%} |"
            )
    else:
        lines.append("기록 없음")
    return "\n".join(lines) + "\n"


__all__ = ["render_markdown", "run_report"]
