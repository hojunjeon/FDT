"""홀드아웃 백테스트 (SIM-01 정확도). 설계: docs/03_FDT_설계.md §11.4"""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


_OUTPUT_DIR = Path("data/out/eval")
_CSV_FIELDS = ("date", "p10", "median", "p90", "truth")


def _seed_dir(path: Path) -> Path:
    """§11.4 평가 입력 디렉터리의 표준 위치를 찾는다."""
    path = Path(path)
    if path.is_file():
        path = path.parent
    if (path / "snapshot.json").exists() and (path / "ground_truth.json").exists():
        return path
    raise FileNotFoundError(f"seed files not found: {path}")


def _load_inputs(seed_dir: Path) -> tuple[Any, list[Any], dict[str, Any]]:
    """§11.4 스냅샷·원장·정답을 평가 계층에서만 읽는다."""
    from fdt.ledger.ingest import ingest, load_snapshot

    directory = _seed_dir(seed_dir)
    snapshot = load_snapshot(directory / "snapshot.json")
    transactions = ingest(snapshot)
    truth = json.loads((directory / "ground_truth.json").read_text(encoding="utf-8"))
    return snapshot, transactions, truth


def _build_model(transactions: list[Any], snapshot: Any, as_of: date) -> tuple[Any, Any]:
    """§11.4 as_of 경계를 지키는 State·Behavior를 구성한다."""
    from fdt.twin.behavior import estimate_behavior
    from fdt.twin.state import build_state, propose_budgets

    budgets = propose_budgets(transactions, as_of)
    state = build_state(transactions, snapshot, as_of, budgets=budgets)
    behavior = estimate_behavior(transactions, as_of, budgets=budgets)
    return state, behavior


def _date_key(value: date | str) -> str:
    """§11.4 정답 JSON 날짜를 YYYYMMDD로 통일한다."""
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value)
    return text.replace("-", "")[:8]


def _number(value: Any) -> int:
    """§11.4 pydantic·dict·numpy 값을 정수로 읽는다."""
    return int(value)


def _thresholds(profile_id: str) -> dict[str, float]:
    """§11.4 프로필별 초기 합격 기준을 반환한다."""
    if profile_id.startswith("C"):
        return {"smape_max": 0.40, "min_balance_error_max": 500_000, "coverage_min": 0.50, "coverage_max": 0.95}
    return {"smape_max": 0.15 if profile_id.startswith("A") else 0.25,
            "min_balance_error_max": 300_000, "coverage_min": 0.60, "coverage_max": 0.95}


def _metric_pass(metrics: dict[str, float], thresholds: dict[str, float]) -> bool:
    """§11.4 지표를 설계서의 초기 기준과 비교한다."""
    return (
        metrics["smape"] <= thresholds["smape_max"]
        and metrics["min_balance_error"] <= thresholds["min_balance_error_max"]
        and thresholds["coverage_min"] <= metrics["coverage"] <= thresholds["coverage_max"]
    )


def _safe_filename(value: str) -> str:
    """§11.4 프로필 ID를 평가 산출물 파일명으로 제한한다."""
    name = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
    return name or "profile"


def _write_outputs(report: dict[str, Any], output_dir: Path = _OUTPUT_DIR) -> None:
    """§11.4 JSON 보고서와 프로필별 UTF-8 CSV를 기록한다."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for profile in report["profiles"]:
        csv_path = output_dir / f"backtest_{_safe_filename(str(profile['profile_id']))}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=_CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(profile["rows"])
    (output_dir / "backtest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def backtest_profile(seed_dir: Path, holdout_days: int = 30, n_paths: int = 1000, seed: int = 42) -> dict[str, Any]:
    """§11.4 as_of 이후 홀드아웃의 중앙값·밴드 정확도를 계산한다."""
    if holdout_days < 1:
        raise ValueError("holdout_days must be positive")
    if n_paths < 1:
        raise ValueError("n_paths must be positive")

    from fdt.twin.simulate import forecast

    snapshot, transactions, truth = _load_inputs(Path(seed_dir))
    balance_truth = truth.get("daily_balance", {})
    if not balance_truth:
        raise ValueError(f"daily_balance is empty: {_seed_dir(Path(seed_dir))}")
    truth_dates = sorted(_date_key(value) for value in balance_truth)
    end = date.fromisoformat(f"{truth_dates[-1][:4]}-{truth_dates[-1][4:6]}-{truth_dates[-1][6:8]}")
    as_of = end - timedelta(days=holdout_days)
    state, behavior = _build_model(transactions, snapshot, as_of)
    stats = forecast(state, behavior, horizon_days=holdout_days, n_paths=n_paths, seed=seed)

    predicted_dates = list(getattr(stats, "dates"))
    predicted = {
        _date_key(day): (stats.p10[index], stats.median[index], stats.p90[index])
        for index, day in enumerate(predicted_dates)
        if _date_key(day) != _date_key(as_of)
    }
    primary = getattr(state, "primary_account_no")
    rows: list[dict[str, Any]] = []
    for offset in range(1, holdout_days + 1):
        day = as_of + timedelta(days=offset)
        key = _date_key(day)
        if key not in predicted or key not in balance_truth:
            continue
        band = predicted[key]
        truth_balance = _number(balance_truth[key][primary])
        rows.append({"date": day.isoformat(), "p10": _number(band[0]), "median": _number(band[1]),
                     "p90": _number(band[2]), "truth": truth_balance})
    if not rows:
        raise ValueError(f"no holdout rows for {as_of}: {_seed_dir(Path(seed_dir))}")

    errors = [abs(row["median"] - row["truth"]) for row in rows]
    smape_terms = [error / ((abs(row["median"]) + abs(row["truth"])) / 2 + 100_000)
                   for row, error in zip(rows, errors)]
    model_min = min(rows, key=lambda row: row["median"])
    truth_min = min(rows, key=lambda row: row["truth"])
    metrics = {
        "mae": sum(errors) / len(errors),
        "smape": sum(smape_terms) / len(smape_terms),
        "min_balance_error": abs(model_min["median"] - truth_min["truth"]),
        "min_balance_date_error_days": abs((date.fromisoformat(model_min["date"]) - date.fromisoformat(truth_min["date"])).days),
        "coverage": sum(row["p10"] <= row["truth"] <= row["p90"] for row in rows) / len(rows),
    }
    profile_id = str(truth.get("profile_id") or _seed_dir(Path(seed_dir)).name)
    thresholds = _thresholds(profile_id)
    return {"profile": profile_id, "profile_id": profile_id, "as_of": as_of.isoformat(), "holdout_days": holdout_days,
            "n_paths": n_paths, "metrics": metrics, "thresholds": thresholds,
            "passed": _metric_pass(metrics, thresholds), "rows": rows}


def run_all(seed_root: Path) -> dict[str, Any]:
    """§11.4 세 프로필 백테스트를 실행하고 프로필별 판정을 묶는다."""
    root = Path(seed_root)
    directories = [_seed_dir(root)] if (root / "snapshot.json").exists() else sorted(
        path for path in root.iterdir() if path.is_dir() and (path / "snapshot.json").exists()
    )
    if not directories:
        raise FileNotFoundError(f"no seed profiles found: {root}")
    reports = [backtest_profile(directory) for directory in directories]
    report = {"profiles": reports, "count": len(reports), "passed": all(report["passed"] for report in reports)}
    _write_outputs(report)
    return report
