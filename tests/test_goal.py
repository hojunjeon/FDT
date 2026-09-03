from __future__ import annotations

from datetime import date

import numpy as np

from fdt.schemas.domain import Behavior, EnvelopeBehavior, EnvelopeState, State
from fdt.taxonomy.categories import ENVELOPES, Envelope
from fdt.twin import goal


def _state(*, liquidity: int, next_income: date | None = None, target_spent: int = 0) -> State:
    cycle_end = date(2026, 1, 31)
    envelopes = [
        EnvelopeState(
            envelope=env,
            budget=100_000,
            spent=target_spent if env == Envelope.DINING else 0,
            remaining=100_000 - (target_spent if env == Envelope.DINING else 0),
            cycle_start=date(2026, 1, 1),
            cycle_end=cycle_end,
        )
        for env in ENVELOPES
    ]
    return State(
        as_of=date(2026, 1, 10),
        user_name="테스트",
        liquidity=liquidity,
        emergency_fund=0,
        account_balances={"p": liquidity},
        primary_account_no="p",
        committed=[],
        envelopes=envelopes,
        cards=[],
        next_income_date=next_income,
        expected_income=0,
        spend_7d_avg=10_000,
        spend_90d_avg=10_000,
        acceleration=1.0,
        unconfirmed_count=0,
    )


def _behavior() -> Behavior:
    return Behavior(
        estimated_from=date(2025, 10, 1),
        estimated_to=date(2026, 1, 10),
        n_days=102,
        envelopes=[
            EnvelopeBehavior(
                envelope=env,
                daily_rate=0.1,
                weekday_mult=[1.0] * 7,
                amount_mu=9.0,
                amount_sigma=0.6,
                card_share=0.5,
                payday_boost=1.0,
                elasticity=1.0,
            )
            for env in ENVELOPES
        ],
        income_dates=[date(2025, 12, 25), date(2026, 1, 25)],
        income_amount_median=1_000_000,
        irregular_income=False,
        shock_daily_prob=0.0,
        shock_amount_mu=11.0,
        shock_amount_sigma=0.6,
    )


class _Simulation:
    envelope_spend = np.tile(
        np.array([[100_000, 80_000, 70_000, 50_000, 40_000, 60_000, 20_000]]),
        (8, 1),
    )


def test_goal_feasible_without_reduction(monkeypatch):
    monkeypatch.setattr(goal, "simulate", lambda *args, **kwargs: _Simulation())
    plan = goal.plan_goal(_state(liquidity=1_500_000, next_income=date(2026, 1, 25)), _behavior(), 1_000_000, date(2026, 2, 10))

    assert plan.feasible
    assert plan.reduction_ratio == 0
    assert plan.required_total_discretionary > plan.baseline_discretionary


def test_goal_impossible_reports_shortfall(monkeypatch):
    monkeypatch.setattr(goal, "simulate", lambda *args, **kwargs: _Simulation())
    plan = goal.plan_goal(_state(liquidity=500_000), _behavior(), 2_000_000, date(2026, 2, 10))

    assert not plan.feasible
    assert "1,500,000원" in plan.note
    assert plan.weekly == []


def test_goal_preserves_essential_floor_and_weekly_total(monkeypatch):
    monkeypatch.setattr(goal, "simulate", lambda *args, **kwargs: _Simulation())
    plan = goal.plan_goal(_state(liquidity=1_500_000), _behavior(), 900_000, date(2026, 2, 10))

    assert plan.feasible
    assert sum(week.total for week in plan.weekly) <= plan.required_total_discretionary
    assert sum(week.total for week in plan.weekly) >= plan.required_total_discretionary - 100 * len(plan.weekly)
    for week in plan.weekly:
        days = (week.week_end - week.week_start).days + 1
        for env in (Envelope.TRANSPORT, Envelope.HEALTH, Envelope.GROCERY):
            floor_amount = 0.8 * _Simulation.envelope_spend[0, ENVELOPES.index(env)] * days / 31
            assert week.caps[env.value] >= floor_amount
