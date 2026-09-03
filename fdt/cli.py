"""FDT 명령줄 도구. 설계: docs/03_FDT_설계.md §9.1"""
from __future__ import annotations

import importlib
import json
import os
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import typer

from fdt.schemas.domain import VirtualSpend
from fdt.taxonomy.categories import Envelope


app = typer.Typer(help="KeyFin 개인 금융 디지털 트윈", no_args_is_help=True)
eval_app = typer.Typer(help="FDT 평가 실행", no_args_is_help=True)
app.add_typer(eval_app, name="eval")
SEED_DIR = Path("data/seed")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@app.callback()
def _root() -> None:
    """§9.1 서브커맨드 강제용 콜백."""


@app.command()
def gen(
    profile: str = typer.Argument("all", help="프로필 id (A_steady 등) 또는 all"),
    out: Path = typer.Option(SEED_DIR, help="출력 디렉터리"),
    seed: int | None = typer.Option(None, help="시드 덮어쓰기"),
    end: str | None = typer.Option(None, help="생성 종료일 YYYY-MM-DD"),
) -> None:
    """§9.1 프로필로 금융망 형식 더미 데이터를 생성한다."""
    from fdt.data.generator import generate, list_profiles

    end_date = _parse_date(end, "end") if end else None
    names = list_profiles() if profile == "all" else [profile]
    for name in names:
        directory, summary = generate(name, out, seed=seed, end=end_date)
        typer.echo(f"[{name}] -> {directory}")
        typer.echo(json.dumps(summary, ensure_ascii=False, indent=1, default=str))


@app.command()
def ingest(
    seed_dir: Path = typer.Argument(..., help="snapshot.json 또는 시드 디렉터리"),
    out: Path | None = typer.Option(None, "--out", help="원장 JSONL 출력 경로"),
) -> None:
    """§9.1 금융망 스냅샷을 원장으로 만들고 대사 결과를 출력한다."""
    from fdt.ledger.ingest import ingest as ingest_snapshot, load_snapshot, reconcile, save_ledger

    snap = load_snapshot(_snapshot_path(seed_dir))
    txs = ingest_snapshot(snap)
    if out is not None:
        save_ledger(txs, out)
    result: dict[str, Any] = {"count": len(txs), "reconcile": reconcile(snap, txs)}
    if out is not None:
        result["ledger"] = str(out)
    _echo_json(result)


@app.command()
def state(
    seed_dir: Path = typer.Argument(..., help="snapshot.json 또는 시드 디렉터리"),
    as_of: str | None = typer.Option(None, "--as-of", help="기준일 YYYY-MM-DD"),
) -> None:
    """§9.1 State(t) JSON을 출력한다."""
    ctx = _load_context(seed_dir, as_of)
    _echo_json(ctx.state)


@app.command()
def forecast(
    seed_dir: Path = typer.Argument(..., help="snapshot.json 또는 시드 디렉터리"),
    as_of: str | None = typer.Option(None, "--as-of", help="기준일 YYYY-MM-DD"),
    days: int = typer.Option(30, "--days", min=1, max=60, help="예측 일수 (1~60)"),
) -> None:
    """§9.1 SIM-01 잔액 예측을 출력한다."""
    from fdt.twin.simulate import forecast as forecast_balance

    ctx = _load_context(seed_dir, as_of)
    _echo_json(forecast_balance(ctx.state, ctx.behavior, horizon_days=days, seed=ctx.seed))


@app.command("whatif")
def what_if(
    seed_dir: Path = typer.Argument(..., help="snapshot.json 또는 시드 디렉터리"),
    amount: int = typer.Option(..., "--amount", min=0, help="가상 지출 금액(원)"),
    envelope: str = typer.Option(..., "--envelope", help="소비 봉투"),
    days_from_now: int = typer.Option(..., "--days-from-now", min=0, max=60, help="오늘부터 경과 일수"),
    card: bool = typer.Option(False, "--card", help="카드 결제로 주입"),
    as_of: str | None = typer.Option(None, "--as-of", help="기준일 YYYY-MM-DD"),
) -> None:
    """§9.1 SIM-02 가상 지출 분기 결과를 출력한다."""
    from fdt.twin.simulate import what_if as run_what_if

    ctx = _load_context(seed_dir, as_of)
    on = ctx.state.as_of + timedelta(days=days_from_now)
    injection = VirtualSpend(amount=amount, envelope=_parse_envelope(envelope), on=on, via_card=card)
    _echo_json(run_what_if(ctx.state, ctx.behavior, [injection], seed=ctx.seed))


@app.command()
def risk(
    seed_dir: Path = typer.Argument(..., help="snapshot.json 또는 시드 디렉터리"),
    as_of: str | None = typer.Option(None, "--as-of", help="기준일 YYYY-MM-DD"),
    days: int = typer.Option(30, "--days", min=1, max=60, help="위험 예측 일수 (1~60)"),
) -> None:
    """§9.1 SIM-03 결제 부족 위험을 출력한다."""
    from fdt.twin.simulate import risk as calculate_risk

    ctx = _load_context(seed_dir, as_of)
    _echo_json(calculate_risk(ctx.state, ctx.behavior, horizon_days=days, seed=ctx.seed))


@app.command()
def goal(
    seed_dir: Path = typer.Argument(..., help="snapshot.json 또는 시드 디렉터리"),
    target: int = typer.Option(..., "--target", min=0, help="목표 잔액(원)"),
    target_date: str = typer.Option(..., "--date", help="목표일 YYYY-MM-DD"),
    as_of: str | None = typer.Option(None, "--as-of", help="기준일 YYYY-MM-DD"),
) -> None:
    """§9.1 SIM-04 목표 역산 결과를 출력한다."""
    from fdt.twin.goal import plan_goal

    ctx = _load_context(seed_dir, as_of)
    _echo_json(plan_goal(ctx.state, ctx.behavior, target, _parse_date(target_date, "date"), seed=ctx.seed))


@app.command()
def analyze(
    seed_dir: Path = typer.Argument(..., help="snapshot.json 또는 시드 디렉터리"),
    as_of: str | None = typer.Option(None, "--as-of", help="기준일 YYYY-MM-DD"),
) -> None:
    """§9.1 ANL-01~03, 건전성, 방 상태를 한 번에 출력한다."""
    from fdt.twin.analytics import detect_alerts, health, rebalance, safe_to_spend
    from fdt.twin.projection import project_room
    from fdt.twin.simulate import risk as calculate_risk

    ctx = _load_context(seed_dir, as_of)
    today = [tx for tx in ctx.txs if tx.day == ctx.state.as_of]
    risk_result = calculate_risk(ctx.state, ctx.behavior, seed=ctx.seed)
    alerts = detect_alerts(ctx.state, ctx.behavior, today)
    score, level = health(ctx.state, risk_result)
    display_state = ctx.state.model_copy(update={"health_score": score, "health_level": level})
    _echo_json({
        "safe_to_spend": safe_to_spend(display_state, today),
        "rebalance": rebalance(display_state, ctx.behavior),
        "alerts": alerts,
        "risk": risk_result,
        "health": {"score": score, "level": level},
        "room": project_room(display_state, alerts),
    })


@app.command()
def brief(
    seed_dir: Path = typer.Argument(..., help="snapshot.json 또는 시드 디렉터리"),
    persona: str = typer.Option("온순냥", "--persona", help="코치 페르소나"),
    as_of: str | None = typer.Option(None, "--as-of", help="기준일 YYYY-MM-DD"),
) -> None:
    """§9.1 FDT 에이전트 상태 브리핑을 출력한다."""
    ctx = _load_context(seed_dir, as_of)
    _echo_json(_make_agent(ctx, persona).briefing())


@app.command()
def chat(
    seed_dir: Path = typer.Argument(..., help="snapshot.json 또는 시드 디렉터리"),
    persona: str = typer.Option("온순냥", "--persona", help="코치 페르소나"),
    as_of: str | None = typer.Option(None, "--as-of", help="기준일 YYYY-MM-DD"),
) -> None:
    """§9.1 FDT 에이전트 대화 REPL을 실행한다."""
    agent = _make_agent(_load_context(seed_dir, as_of), persona)
    typer.echo("대화를 시작합니다. 종료하려면 '종료'를 입력하세요.")
    while True:
        try:
            text = typer.prompt("사용자", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt, typer.Abort):
            typer.echo()
            break
        if text.strip().lower() in {"종료", "끝", "quit", "exit", ":q"}:
            break
        if not text.strip():
            continue
        result = agent.ask(text)
        typer.echo(result["reply"])


@eval_app.command("backtest")
def eval_backtest(
    seed_root: Path = typer.Option(SEED_DIR, "--seed-root", help="시드 루트"),
    out: Path = typer.Option(Path("data/out/eval/backtest.json"), "--out", help="보고서 경로"),
) -> None:
    """§9.1 백테스트 평가를 실행한다."""
    _run_eval("backtest", seed_root, out)


@eval_app.command("calibration")
def eval_calibration(
    seed_root: Path = typer.Option(SEED_DIR, "--seed-root", help="시드 루트"),
    out: Path = typer.Option(Path("data/out/eval/calibration.json"), "--out", help="보고서 경로"),
) -> None:
    """§9.1 리스크 캘리브레이션을 실행한다."""
    _run_eval("calibration", seed_root, out)


@eval_app.command("faithfulness")
def eval_faithfulness(
    seed_root: Path = typer.Option(SEED_DIR, "--seed-root", help="시드 루트"),
    scenarios: Path = typer.Option(Path("data/eval/scenarios.yaml"), "--scenarios", help="시나리오 YAML"),
    out: Path = typer.Option(Path("data/out/eval/faithfulness.json"), "--out", help="보고서 경로"),
) -> None:
    """§9.1 코칭 충실도 평가를 실행한다."""
    _run_eval("faithfulness", seed_root, out, scenarios=scenarios)


@eval_app.command("routing")
def eval_routing(
    seed_root: Path = typer.Option(SEED_DIR, "--seed-root", help="시드 루트"),
    utterances: Path = typer.Option(Path("data/eval/utterances.yaml"), "--utterances", help="발화 YAML"),
    out: Path = typer.Option(Path("data/out/eval/routing.json"), "--out", help="보고서 경로"),
) -> None:
    """§9.1 툴 라우팅 평가를 실행한다."""
    _run_eval("routing", seed_root, out, utterances=utterances)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="바인딩 주소"),
    port: int = typer.Option(8787, "--port", min=1, max=65535, help="포트"),
) -> None:
    """§9.1 fdt.web:app 로컬 대시보드를 실행한다."""
    import uvicorn

    host = host.strip().lower()
    if host not in _LOOPBACK_HOSTS:
        raise typer.BadParameter(
            "인증 없는 대시보드는 127.0.0.1, localhost, ::1에서만 실행할 수 있습니다.",
            param_hint="--host",
        )
    uvicorn.run("fdt.web:app", host=host, port=port)


def _load_context(seed_dir: Path, as_of: str | None, seed: int = 42) -> Any:
    """§9.1 시드 스냅샷에서 TwinContext를 조립한다."""
    from fdt.agent.tools import TwinContext
    from fdt.ledger.ingest import ingest as ingest_snapshot, load_snapshot
    from fdt.twin.behavior import estimate_behavior
    from fdt.twin.state import build_state

    snap = load_snapshot(_snapshot_path(seed_dir))
    txs = ingest_snapshot(snap)
    days = [tx.day for tx in txs]
    earliest = min(days, default=date.fromisoformat(snap.generatedAt[:10]))
    latest = max(days, default=earliest)
    cutoff = _parse_date(as_of, "as_of") if as_of else latest
    if cutoff < earliest or cutoff > latest:
        raise typer.BadParameter(
            f"as_of는 {earliest.isoformat()}~{latest.isoformat()} 범위여야 합니다.",
            param_hint="--as-of",
        )
    state_result = build_state(txs, snap, cutoff)
    budgets = {item.envelope: item.budget for item in state_result.envelopes}
    behavior_result = estimate_behavior(txs, cutoff, budgets=budgets)
    return TwinContext(snap=snap, txs=txs, state=state_result, behavior=behavior_result, seed=seed)


def _make_agent(ctx: Any, persona: str) -> Any:
    """§9.1 환경변수 기반 Ollama 클라이언트를 붙인다."""
    from fdt.agent.agent import FdtAgent
    from fdt.agent.llm import DEFAULT_MODEL, DEFAULT_URL, OllamaClient

    client = OllamaClient(
        url=os.getenv("FDT_OLLAMA_URL", DEFAULT_URL),
        model=os.getenv("FDT_LLM_MODEL", DEFAULT_MODEL),
    )
    return FdtAgent(client, ctx, persona=persona)


def _snapshot_path(seed_dir: Path) -> Path:
    path = Path(seed_dir)
    return path / "snapshot.json" if path.is_dir() else path


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter("YYYY-MM-DD 형식이어야 합니다", param_hint=f"--{name}") from exc


def _parse_envelope(value: str) -> Envelope:
    aliases = {
        "밥": Envelope.DINING, "식비": Envelope.DINING, "커피": Envelope.DINING,
        "택시": Envelope.TRANSPORT, "지하철": Envelope.TRANSPORT, "버스": Envelope.TRANSPORT,
        "병원": Envelope.HEALTH, "약": Envelope.HEALTH, "헬스": Envelope.HEALTH,
        "영화": Envelope.LEISURE, "게임": Envelope.LEISURE, "여행": Envelope.LEISURE,
        "옷": Envelope.SHOPPING, "화장품": Envelope.SHOPPING,
        "편의점": Envelope.GROCERY, "마트": Envelope.GROCERY, "잡화": Envelope.GROCERY,
    }
    if value in aliases:
        return aliases[value]
    try:
        return Envelope(value)
    except ValueError:
        try:
            return Envelope[value.upper()]
        except KeyError as exc:
            raise typer.BadParameter(f"지원하지 않는 봉투: {value}", param_hint="--envelope") from exc


def _run_eval(kind: str, seed_root: Path, out: Path, **paths: Path) -> None:
    """§9.1 평가 모듈의 공개 실행 함수를 호출한다."""
    if kind == "backtest":
        from fdt.eval.backtest import run_all

        report = run_all(seed_root)
    elif kind == "calibration":
        from fdt.eval.calibration import calibration_report, collect_pairs

        report = calibration_report(collect_pairs(seed_root))
    elif kind == "faithfulness":
        from fdt.eval.faithfulness import run_faithfulness

        report = run_faithfulness(seed_root, paths["scenarios"])
    elif kind == "routing":
        from fdt.eval.faithfulness import run_routing

        report = run_routing(seed_root, paths["utterances"])
    else:
        raise typer.ClickException(f"지원하지 않는 평가: {kind}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=1), encoding="utf-8")
    _echo_json(report)


def _echo_json(value: Any) -> None:
    """§9.1 CLI 경계에서 결과를 UTF-8 JSON으로 출력한다."""
    typer.echo(json.dumps(_jsonable(value), ensure_ascii=False, indent=1, default=str))


def _jsonable(value: Any) -> Any:
    """§9.1 중첩된 Pydantic 결과까지 JSON으로 변환한다."""
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


if __name__ == "__main__":
    app()
