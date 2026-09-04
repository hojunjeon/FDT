import json
from pathlib import Path

from fdt.eval.report import render_markdown, run_report


def _row(
    surface: str,
    session: str,
    model: str | None,
    route: list[str],
    calls: list[str],
    *,
    fallback: bool = False,
    first_faithful: bool = True,
    attempt: int = 0,
    violations: list[object] | None = None,
    conflict: object = None,
    latency: tuple[int, int, int] = (100, 20, 70),
    tokens: tuple[int, int] | None = (10, 5),
    error: str | None = None,
) -> dict[str, object]:
    return {
        "ts": "2026-09-04T09:12:33.123+09:00",
        "schema_version": 1,
        "surface": surface,
        "session_id": session,
        "turn": 1,
        "profile_id": "B_card_crunch",
        "persona": "온순냥",
        "as_of": "2026-09-02",
        "llm_model": model,
        "user_message": "질문",
        "reply": "답변",
        "route": route,
        "tool_calls": [{"name": name, "args": {}, "result_summary": {}} for name in calls],
        "faithful": first_faithful,
        "first_faithful": first_faithful,
        "attempt": attempt,
        "fallback": fallback,
        "violations": violations or [],
        "verdict_conflict": conflict,
        "latency_ms": {"total": latency[0], "engine": latency[1], "llm": latency[2]},
        "llm_calls": len(calls),
        "tokens": None if tokens is None else {"prompt": tokens[0], "completion": tokens[1]},
        "llm_error": None if error is None else {"type": error, "message": error},
    }


def test_run_report_aggregates_all_metrics_and_skips_bad_lines(tmp_path: Path) -> None:
    rows = [
        _row("web", "s1", "qwen", ["what_if", "coach"], ["what_if", "coach"], latency=(100, 20, 70)),
        _row("web", "s1", "qwen", ["safe_to_spend", "coach"], ["safe_to_spend"], fallback=True,
             first_faithful=False, attempt=2, violations=["verdict_conflict"], conflict={"engine": "DANGER"},
             latency=(200, 30, 120), error="timeout", tokens=(20, 10)),
        _row("cli_chat", "s2", None, ["get_state"], ["get_state"], latency=(300, 40, 0), tokens=None),
        _row("cli_chat", "s2", None, ["what_if"], ["what_if"], fallback=True, first_faithful=False, attempt=3,
             violations=["date_mismatch"], latency=(400, 50, 130), error="connection", tokens=(40, 15)),
        _row("cli_brief", "s3", "qwen", [], [], violations=[{"type": "numeric_hallucination"}],
             latency=(500, 60, 60), error="parse", tokens=(50, 25)),
        _row("eval", "s4", "model2", ["policy_tips"], ["policy_tips"], first_faithful=False, attempt=1,
             latency=(600, 70, 0), tokens=(60, 30)),
        _row("web", "s5", "qwen", ["what_if", "coach"], ["what_if", "coach"], fallback=True,
             first_faithful=False, attempt=2, violations=["verdict_conflict", {"type": "date_mismatch"}],
             conflict={"engine": "WARNING"}, latency=(700, 80, 95), error="timeout", tokens=(70, 35)),
        _row("eval", "s4", "model2", ["get_state"], ["get_state"], latency=(800, 90, 0), tokens=(80, 40)),
    ]
    path = tmp_path / "2026-09-04.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n{broken}\n", encoding="utf-8")
    output = tmp_path / "out" / "report.json"

    report = run_report(tmp_path, output)

    assert report["turns"] == 8
    assert report["sessions"] == 5
    assert report["skipped_lines"] == 1
    assert report["surfaces"] == {"cli_brief": 1, "cli_chat": 2, "eval": 2, "web": 3}
    assert report["tool_calls"] == {
        "total": 9,
        "by_tool": {"coach": 2, "get_state": 2, "policy_tips": 1, "safe_to_spend": 1, "what_if": 3},
        "avg_per_turn": 9 / 8,
    }
    assert report["fallback"]["count"] == 3
    assert report["fallback"]["causes"] == {"connection": 1, "timeout": 2}
    assert report["first_faithful"]["count"] == 4
    assert report["attempts"]["distribution"] == {"0": 4, "1": 1, "2": 2, "3": 1}
    assert report["violations"]["by_type"] == {
        "date_mismatch": 2,
        "numeric_hallucination": 1,
        "verdict_conflict": 2,
    }
    assert report["verdict_conflict_count"] == 2
    assert report["latency_ms"] == {
        "total": {"p50": 450.0, "p95": 765.0},
        "engine": {"p50": 55.0, "p95": 86.5},
        "llm": {"p50": 65.0, "p95": 126.5},
    }
    assert report["tokens"] == {
        "prompt": 330.0,
        "completion": 160.0,
        "total": 490.0,
        "avg_per_turn": {"prompt": 41.25, "completion": 20.0, "total": 61.25},
    }
    assert report["llm_errors"] == {
        "count": 4,
        "rate": 0.5,
        "by_type": {"connection": 1, "parse": 1, "timeout": 2},
    }
    assert report["models"]["qwen"]["turns"] == 4
    assert report["models"]["null"]["turns"] == 2
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_render_markdown_contains_tables(tmp_path: Path) -> None:
    fixture = _row("eval", "s1", "qwen", ["get_state"], ["get_state"])
    (tmp_path / "2026-09-04.jsonl").write_text(json.dumps(fixture, ensure_ascii=False) + "\n", encoding="utf-8")

    markdown = render_markdown(run_report(tmp_path))
    assert "# FDT 턴 로그 운영 지표" in markdown
    assert "| 구간 | p50 | p95 |" in markdown
    assert "## 모델별" in markdown


def test_run_report_missing_directory_returns_empty_report(tmp_path: Path) -> None:
    report = run_report(tmp_path / "missing", tmp_path / "report.json")

    assert report["turns"] == 0
    assert report["skipped_lines"] == 0
    assert report["log_dir_missing"] is True
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8")) == report
