"""리스크 확률 캘리브레이션 (SIM-03). 설계: docs/03_FDT_설계.md §11.5"""
from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fdt.eval.backtest import _build_model, _date_key, _load_inputs, _seed_dir


def _date(value: str) -> date:
    """§11.5 YYYYMMDD 또는 YYYY-MM-DD를 date로 변환한다."""
    key = _date_key(value)
    return date.fromisoformat(f"{key[:4]}-{key[4:6]}-{key[6:8]}")


def _profile_dirs(seed_root: Path) -> list[Path]:
    """§11.5 평가 대상 시드 프로필 디렉터리를 나열한다."""
    root = Path(seed_root)
    if (root / "snapshot.json").exists():
        return [_seed_dir(root)]
    if not root.exists():
        raise FileNotFoundError(f"seed root not found: {root}")
    return sorted(path for path in root.iterdir() if path.is_dir() and (path / "snapshot.json").exists())


def _risk_probability(seed_dir: Path, as_of: date) -> tuple[float, set[date]]:
    """§11.5 한 기준일의 예측 확률과 실제 부족 일자를 읽는다."""
    from fdt.twin.simulate import risk

    snapshot, transactions, truth = _load_inputs(seed_dir)
    state, behavior = _build_model(transactions, snapshot, as_of)
    result = risk(state, behavior, horizon_days=30)
    probability = float(result["card_shortfall_prob"] if isinstance(result, dict) else result.card_shortfall_prob)
    actual = {_date(item["date"]) for item in truth.get("card_shortfalls", []) if "date" in item}
    return min(1.0, max(0.0, probability)), actual


def _as_ofs(truth: dict[str, Any], step_days: int) -> list[date]:
    """§11.5 데이터 시작+90일부터 종료-30일까지의 기준일을 만든다."""
    keys = sorted(_date_key(value) for value in truth.get("daily_balance", {}))
    if not keys:
        return []
    start, end = _date(keys[0]), _date(keys[-1])
    first = start + timedelta(days=90)
    last = end - timedelta(days=30)
    result: list[date] = []
    current = first
    while current <= last:
        result.append(current)
        current += timedelta(days=step_days)
    return result


def _collect_for_dir(seed_dir: Path, step_days: int) -> list[tuple[float, int]]:
    """§11.5 한 프로필의 롤링 (예측, 실제) 쌍을 수집한다."""
    _, _, truth = _load_inputs(seed_dir)
    pairs: list[tuple[float, int]] = []
    for as_of in _as_ofs(truth, step_days):
        probability, actual_dates = _risk_probability(seed_dir, as_of)
        observed = int(any(as_of < day <= as_of + timedelta(days=30) for day in actual_dates))
        pairs.append((probability, observed))
    return pairs


def collect_pairs(seed_root: Path, step_days: int = 7, extra_seeds: int = 20) -> list[tuple[float, int]]:
    """§11.5 (예측 card_shortfall_prob, 실제 30일 내 카드 부족 0/1) 쌍을 수집한다."""
    if step_days < 1:
        raise ValueError("step_days must be positive")
    if extra_seeds < 0:
        raise ValueError("extra_seeds must be non-negative")

    base_dirs = _profile_dirs(Path(seed_root))
    if not base_dirs:
        raise FileNotFoundError(f"no seed profiles found: {seed_root}")
    pairs: list[tuple[float, int]] = []
    for directory in base_dirs:
        pairs.extend(_collect_for_dir(directory, step_days))

    if extra_seeds == 0:
        return pairs
    from fdt.data.generator import generate

    with tempfile.TemporaryDirectory(prefix="fdt-calibration-") as temporary:
        output_root = Path(temporary)
        for index in range(extra_seeds):
            source = base_dirs[index % len(base_dirs)]
            _, _, truth = _load_inputs(source)
            keys = sorted(_date_key(value) for value in truth.get("daily_balance", {}))
            end = _date(keys[-1]) if keys else None
            generated, _ = generate(source.name, output_root, seed=10_000 + index, end=end)
            pairs.extend(_collect_for_dir(generated, step_days))
    return pairs


def calibration_report(pairs: list[tuple[float, int]], n_bins: int = 5) -> dict[str, Any]:
    """§11.5 구간별 예측 평균·실제 비율, ECE, Brier와 기준율 Brier를 계산한다."""
    if n_bins < 1:
        raise ValueError("n_bins must be positive")
    checked: list[tuple[float, int]] = []
    for probability, observed in pairs:
        probability = float(probability)
        observed = int(observed)
        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"probability out of range: {probability}")
        if observed not in (0, 1):
            raise ValueError(f"observed must be 0 or 1: {observed}")
        checked.append((probability, observed))

    bins: list[dict[str, Any]] = []
    total = len(checked)
    ece = 0.0
    for index in range(n_bins):
        lower, upper = index / n_bins, (index + 1) / n_bins
        values = [(probability, observed) for probability, observed in checked
                  if index == n_bins - 1 and lower <= probability <= upper
                  or index < n_bins - 1 and lower <= probability < upper]
        count = len(values)
        mean_probability = sum(item[0] for item in values) / count if count else None
        observed_rate = sum(item[1] for item in values) / count if count else None
        gap = abs(mean_probability - observed_rate) if count else None
        if gap is not None and total:
            ece += count / total * gap
        bins.append({"lower": lower, "upper": upper, "count": count,
                     "mean_predicted": mean_probability, "actual_rate": observed_rate,
                     "gap": gap, "status": "hold" if count < 15 else "ok"})

    brier = sum((probability - observed) ** 2 for probability, observed in checked) / total if total else None
    prevalence = sum(observed for _, observed in checked) / total if total else None
    baseline_brier = prevalence * (1.0 - prevalence) if prevalence is not None else None
    enough_data = (
        total >= 30
        and len({observed for _, observed in checked}) == 2
        and all(item["count"] >= 15 for item in bins if item["count"])
    )
    passed = bool(enough_data and ece <= 0.15 and brier is not None and baseline_brier is not None and brier < baseline_brier)
    return {"n": total, "bins": bins, "ece": ece if total else None, "brier": brier,
            "baseline_brier": baseline_brier, "prevalence": prevalence,
            "criteria": {"ece_max": 0.15, "brier_must_be_below_baseline": True,
                         "min_samples": 30, "min_samples_per_occupied_bin": 15,
                         "both_outcomes_required": True}, "passed": passed,
            "status": "blocked" if not total else "complete" if enough_data else "insufficient_data"}
