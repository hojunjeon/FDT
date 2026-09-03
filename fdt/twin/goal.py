"""목표 역산 (FDT-SIM-04). 설계: docs/03_FDT_설계.md §7.5"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from math import ceil

import numpy as np

from fdt.schemas.domain import Behavior, FixedCommitment, GoalPlan, State, WeeklyCap
from fdt.taxonomy.categories import ENVELOPES, ESSENTIAL_ENVELOPES, Envelope
try:
    from fdt.twin.simulate import simulate
except ModuleNotFoundError as error:  # T4 can be imported while T3 is still being assembled.
    if error.name != "fdt.twin.simulate":
        raise
    simulate = None


def plan_goal(state: State, behavior: Behavior, target_amount: int, target_date: date, seed: int = 42) -> GoalPlan:
    """§7.5 목표 잔액을 고정하고 주차별·봉투별 지출 상한을 계산한다."""
    if target_amount < 0:
        raise ValueError("target_amount must be non-negative")

    horizon = (target_date - state.as_of).days
    if horizon <= 0:
        return GoalPlan(
            target_amount=target_amount,
            target_date=target_date,
            feasible=False,
            required_total_discretionary=0,
            baseline_discretionary=0,
            reduction_ratio=0.0,
            weekly=[],
            note="목표일은 기준일 이후여야 합니다.",
        )

    if simulate is None:
        from fdt.twin.simulate import simulate as run_simulation
    else:
        run_simulation = simulate
    result = run_simulation(state, behavior, horizon_days=horizon, n_paths=1000, seed=seed)
    spend = np.asarray(result.envelope_spend, dtype=float)
    if spend.ndim != 2 or spend.shape[1] != len(ENVELOPES):
        raise ValueError("simulation envelope_spend must have shape (n_paths, 7)")

    envelope_baseline = dict(zip(ENVELOPES, np.median(spend, axis=0)))
    baseline = int(round(float(np.median(spend.sum(axis=1)))))
    if baseline == 0:
        baseline = int(round(sum(envelope_baseline.values())))

    expected_income = _expected_income(state, behavior, horizon)
    fixed_outflow = _fixed_outflow(state, target_date)
    available = state.liquidity + expected_income - fixed_outflow - target_amount
    reduction_ratio = max(0.0, 1.0 - available / baseline) if baseline else 0.0

    if available < 0:
        return GoalPlan(
            target_amount=target_amount,
            target_date=target_date,
            feasible=False,
            required_total_discretionary=0,
            baseline_discretionary=baseline,
            reduction_ratio=reduction_ratio,
            weekly=[],
            note=f"목표일까지 {-available:,}원 부족합니다.",
        )

    weekly, allocation_feasible = _weekly_caps(
        state.as_of, horizon, available, envelope_baseline, baseline
    )
    if baseline == 0:
        note = "기준선 소비가 없어 가용액을 균등 배분합니다."
    elif available >= baseline:
        note = "현재 소비 수준으로 달성 가능합니다."
    else:
        note = f"재량지출을 {reduction_ratio:.0%} 줄여야 합니다."
    if not allocation_feasible:
        note += " 필수 봉투 하한을 모두 보장할 수 없습니다."

    return GoalPlan(
        target_amount=target_amount,
        target_date=target_date,
        feasible=allocation_feasible,
        required_total_discretionary=available,
        baseline_discretionary=baseline,
        reduction_ratio=reduction_ratio,
        weekly=weekly,
        note=note,
    )


def _expected_income(state: State, behavior: Behavior, horizon: int) -> int:
    """기준일 이후 목표 기간의 예상 수입을 계산한다."""
    amount = behavior.income_amount_median or state.expected_income
    if amount <= 0:
        return 0

    dates = sorted(set(behavior.income_dates))
    gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
    gap = max(1, int(round(float(np.median(gaps))))) if gaps else horizon
    if behavior.irregular_income:
        return int(amount * horizon / gap * 0.8)

    next_date = state.next_income_date
    if next_date is None and dates:
        next_date = _add_month(dates[-1])
        while next_date <= state.as_of:
            next_date = _add_month(next_date)
    if next_date is None:
        return 0

    total = 0
    current = next_date
    while current <= state.as_of:
        current = _add_month(current)
    end = state.as_of.toordinal() + horizon
    while current.toordinal() <= end:
        total += amount
        current = _add_month(current)
    return total


def _fixed_outflow(state: State, target_date: date) -> int:
    """큐의 기간 내 항목과 월 반복 고정비를 합산한다."""
    selected = [c for c in state.committed if state.as_of < c.due <= target_date]
    total = sum(c.amount for c in selected)
    groups: dict[tuple[str, str, str], list[FixedCommitment]] = {}
    for commitment in selected:
        if commitment.kind != "카드대금":
            groups.setdefault((commitment.kind, commitment.name, commitment.account_no), []).append(commitment)
    for commitments in groups.values():
        latest = max(commitments, key=lambda item: item.due)
        due = _add_month(latest.due)
        while due <= target_date:
            total += latest.amount
            due = _add_month(due)
    return total


def _add_month(value: date) -> date:
    year = value.year + (value.month == 12)
    month = 1 if value.month == 12 else value.month + 1
    return value.replace(day=min(value.day, monthrange(year, month)[1]), year=year, month=month)


def _weekly_caps(
    as_of: date,
    horizon: int,
    available: int,
    baseline_by_envelope: dict[Envelope, float],
    baseline: int,
) -> tuple[list[WeeklyCap], bool]:
    """주차별 100원 단위 상한을 기준선 비율로 배분한다."""
    if baseline <= 0:
        weights = {env: 1.0 for env in ENVELOPES}
    else:
        weights = {env: max(0.0, baseline_by_envelope.get(env, 0.0)) for env in ENVELOPES}
        if not any(weights.values()):
            weights = {env: 1.0 for env in ENVELOPES}

    weeks: list[WeeklyCap] = []
    feasible = True
    start = as_of
    remaining = horizon
    while remaining:
        days = min(7, remaining)
        week_start = start.fromordinal(start.toordinal() + 1)
        week_end = week_start.fromordinal(week_start.toordinal() + days - 1)
        target = (available * days // horizon) // 100 * 100
        caps, ok = _allocate_week(target, days, horizon, weights, baseline_by_envelope)
        feasible = feasible and ok
        weeks.append(WeeklyCap(week_start=week_start, week_end=week_end, caps=caps, total=sum(caps.values())))
        start = week_end
        remaining -= days
    return weeks, feasible


def _allocate_week(
    target: int,
    days: int,
    horizon: int,
    weights: dict[Envelope, float],
    baseline_by_envelope: dict[Envelope, float],
) -> tuple[dict[str, int], bool]:
    target_units = max(0, target // 100)
    lower = {
        env: ceil(0.8 * max(0.0, baseline_by_envelope.get(env, 0.0)) * days / horizon / 100)
        if env in ESSENTIAL_ENVELOPES else 0
        for env in ENVELOPES
    }
    if sum(lower.values()) > target_units:
        return {env.value: lower[env] * 100 for env in ENVELOPES}, False

    weight_sum = sum(weights.values()) or 1.0
    units = {
        env: max(lower[env], int(target_units * weights[env] / weight_sum))
        for env in ENVELOPES
    }
    excess = sum(units.values()) - target_units
    for env in reversed(ENVELOPES):
        if excess <= 0:
            break
        removable = max(0, units[env] - lower[env])
        cut = min(removable, excess)
        units[env] -= cut
        excess -= cut
    if excess > 0:
        return {env.value: units[env] * 100 for env in ENVELOPES}, False

    remainder = target_units - sum(units.values())
    order = sorted(ENVELOPES, key=lambda env: (-weights[env], ENVELOPES.index(env)))
    for env in order[:remainder]:
        units[env] += 1
    return {env.value: units[env] * 100 for env in ENVELOPES}, True
