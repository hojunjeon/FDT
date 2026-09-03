from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from fdt.schemas.domain import (
    Behavior,
    CardState,
    EnvelopeBehavior,
    EnvelopeState,
    FixedCommitment,
    State,
    VirtualSpend,
)
from fdt.taxonomy.categories import ENVELOPES, Envelope
from fdt.twin.simulate import _irregular_income_schedule, forecast, risk, simulate, what_if


def _state(
    *,
    as_of: date = date(2026, 3, 1),
    liquidity: int = 1000,
    committed: list[FixedCommitment] | None = None,
    cards: list[CardState] | None = None,
    next_income_date: date | None = None,
    expected_income: int = 0,
) -> State:
    envelopes = [
        EnvelopeState(
            envelope=env, budget=100000, spent=0, remaining=100000,
            cycle_start=as_of.replace(day=1), cycle_end=as_of.replace(day=28),
        )
        for env in ENVELOPES
    ]
    return State(
        as_of=as_of, user_name="테스트", liquidity=liquidity, emergency_fund=0,
        account_balances={"primary": liquidity}, primary_account_no="primary",
        committed=committed or [], envelopes=envelopes, cards=cards or [],
        next_income_date=next_income_date, expected_income=expected_income,
        spend_7d_avg=0, spend_90d_avg=0, acceleration=1, unconfirmed_count=0,
    )


def _behavior(*, income_dates: list[date] | None = None, irregular: bool = False, rates: float = 0) -> Behavior:
    return Behavior(
        estimated_from=date(2026, 1, 1), estimated_to=date(2026, 3, 1), n_days=60,
        envelopes=[
            EnvelopeBehavior(
                envelope=env, daily_rate=rates, weekday_mult=[1] * 7,
                amount_mu=float(np.log(10000)), amount_sigma=0.6,
                card_share=0.0, payday_boost=1.0, elasticity=1.0,
            )
            for env in ENVELOPES
        ],
        income_dates=income_dates or [], income_amount_median=500,
        irregular_income=irregular, shock_daily_prob=0,
        shock_amount_mu=float(np.log(100000)), shock_amount_sigma=0.6,
    )


def _deterministic_cash_behavior() -> Behavior:
    return Behavior(
        estimated_from=date(2026, 1, 1), estimated_to=date(2026, 3, 1), n_days=60,
        envelopes=[
            EnvelopeBehavior(
                envelope=env, daily_rate=0.5 if env == Envelope.DINING else 0,
                weekday_mult=[1] * 7, amount_mu=float(np.log(100)), amount_sigma=0,
                card_share=0, payday_boost=1, elasticity=1,
            )
            for env in ENVELOPES
        ],
        income_dates=[], income_amount_median=0, irregular_income=True,
        shock_daily_prob=0, shock_amount_mu=float(np.log(100)), shock_amount_sigma=0,
    )


def test_seed_reproducibility_and_stats_shape() -> None:
    state = _state(liquidity=100000)
    behavior = _behavior(rates=0.5)
    first = simulate(state, behavior, horizon_days=30, n_paths=1000, seed=7)
    second = simulate(state, behavior, horizon_days=30, n_paths=1000, seed=7)
    assert first.balances.tobytes() == second.balances.tobytes()
    stats = forecast(state, behavior, n_paths=1000, seed=7)
    assert len(stats.dates) == len(stats.median) == 31
    assert stats.p10[0] == stats.median[0] == stats.p90[0] == 100000


def test_irregular_income_projects_recent_month_cluster() -> None:
    state = _state(
        as_of=date(2026, 8, 3),
        next_income_date=date(2026, 8, 5),
    )
    behavior = _behavior(
        income_dates=[date(2026, 7, 4), date(2026, 7, 7)],
        irregular=True,
    )
    assert _irregular_income_schedule(state, behavior, 30) == {
        date(2026, 8, 5), date(2026, 8, 8),
    }


def test_transition_order_income_fixed_bill_and_withdrawal() -> None:
    card = CardState(
        card_no="card", withdrawal_account_no="primary", withdrawal_weekday=1,
        unbilled=100, issued_unpaid=[],
    )
    state = _state(
        liquidity=1000,
        cards=[card],
        committed=[FixedCommitment(kind="월세", name="월세", amount=200, due=date(2026, 3, 2), account_no="primary")],
        next_income_date=date(2026, 3, 3), expected_income=500,
    )
    behavior = _behavior(income_dates=[date(2026, 2, 3), date(2026, 1, 3)])
    result = simulate(state, behavior, horizon_days=2, n_paths=1, seed=1)
    assert result.balances[0].tolist() == [1000, 800, 1200]


def test_card_shortfall_keeps_failed_withdrawal_out_of_account_balance() -> None:
    bill = FixedCommitment(kind="카드대금", name="카드대금", amount=100, due=date(2026, 3, 3), account_no="card")
    card = CardState(
        card_no="card", withdrawal_account_no="primary", withdrawal_weekday=1,
        unbilled=0, issued_unpaid=[bill],
    )
    result = simulate(_state(liquidity=50, cards=[card]), _behavior(), horizon_days=3, n_paths=1, seed=1)
    assert result.card_shortfall.tolist() == [True]
    assert result.balances[0].tolist() == [50, 50, 50, 50]
    assert result.economic_balances[0].tolist() == [-50, -50, -50, -50]
    assert result.first_shortfall_idx.tolist() == [-1]


def test_card_commitment_uses_its_card_when_accounts_are_shared() -> None:
    as_of = date(2026, 3, 1)
    cards = [
        CardState(card_no="card-1", withdrawal_account_no="primary", withdrawal_weekday=1, unbilled=0, issued_unpaid=[]),
        CardState(card_no="card-2", withdrawal_account_no="primary", withdrawal_weekday=0, unbilled=0, issued_unpaid=[]),
    ]
    state = _state(
        as_of=as_of,
        liquidity=1000,
        cards=cards,
        committed=[FixedCommitment(
            kind="통신", name="통신", amount=100, due=date(2026, 3, 2),
            account_no="primary", card_no="card-2",
        )],
    )
    result = simulate(state, _behavior(), horizon_days=1, n_paths=1, seed=1)
    assert result.balances[0].tolist() == [1000, 900]


def test_repeated_internal_transfer_commitment_reduces_primary_liquidity() -> None:
    as_of = date(2026, 3, 1)
    state = _state(
        as_of=as_of,
        liquidity=1000,
        committed=[FixedCommitment(
            kind="비상금이체", name="비상금이체 세이프박스", amount=300,
            due=as_of + timedelta(days=1), account_no="primary",
        )],
    )
    result = simulate(state, _behavior(), horizon_days=1, n_paths=1, seed=1)
    assert result.balances[0].tolist() == [1000, 700]


def test_what_if_zero_is_identical_and_card_injection_is_not_cash() -> None:
    state = _state(liquidity=1000)
    behavior = _behavior()
    zero = VirtualSpend(amount=0, envelope=Envelope.DINING, on=state.as_of + timedelta(days=1))
    result = what_if(state, behavior, [zero], horizon_days=3, n_paths=100, seed=2)
    assert result.delta_min_balance == result.delta_end_balance == 0
    assert result.delta_shortfall_prob == 0
    card = CardState(card_no="card", withdrawal_account_no="primary", withdrawal_weekday=3, unbilled=0, issued_unpaid=[])
    result = what_if(
        _state(liquidity=1000, cards=[card]), behavior,
        [VirtualSpend(amount=500, envelope=Envelope.DINING, on=state.as_of + timedelta(days=1))],
        horizon_days=1, n_paths=10, seed=2,
    )
    assert result.branch.median[-1] == 500
    raw = simulate(
        _state(liquidity=1000, cards=[card]), behavior, horizon_days=1, n_paths=1, seed=2,
        injections=[VirtualSpend(amount=500, envelope=Envelope.DINING, on=state.as_of + timedelta(days=1))],
    )
    assert raw.balances[0, -1] == 1000


def test_what_if_applies_day_zero_and_extends_to_injection_date() -> None:
    state = _state(liquidity=1000)
    behavior = _behavior()
    immediate = what_if(
        state, behavior,
        [VirtualSpend(amount=200, envelope=Envelope.DINING, on=state.as_of, via_card=False)],
        horizon_days=0, n_paths=1, seed=2,
    )
    assert immediate.base.median == [1000]
    assert immediate.branch.median == [800]
    assert immediate.delta_end_balance == -200

    distant = what_if(
        state, behavior,
        [VirtualSpend(
            amount=100, envelope=Envelope.DINING,
            on=state.as_of + timedelta(days=60), via_card=False,
        )],
        horizon_days=30, n_paths=1, seed=2,
    )
    assert distant.branch.dates[-1] == state.as_of + timedelta(days=60)
    assert distant.branch.median[-1] == distant.base.median[-1] - 100


def test_rejected_cash_demand_is_kept_in_economic_balance_for_crn() -> None:
    state = _state(liquidity=100)
    behavior = _deterministic_cash_behavior()
    injection = VirtualSpend(amount=50, envelope=Envelope.DINING, on=state.as_of, via_card=False)
    base = simulate(state, behavior, horizon_days=1, n_paths=1, seed=0)
    branch = simulate(state, behavior, horizon_days=1, n_paths=1, seed=0, injections=[injection])
    result = what_if(state, behavior, [injection], horizon_days=1, n_paths=1, seed=0)

    assert base.balances[0].tolist() == [100, 0]
    assert branch.balances[0].tolist() == [50, 50]
    assert base.economic_balances[0].tolist() == [100, 0]
    assert branch.economic_balances[0].tolist() == [50, -50]
    assert result.branch.min_balance <= result.base.min_balance
    assert result.delta_min_balance == -50


def test_rejected_fixed_debit_is_an_economic_obligation_only() -> None:
    as_of = date(2026, 3, 1)
    state = _state(
        as_of=as_of, liquidity=1000,
        committed=[FixedCommitment(kind="월세", name="월세", amount=950, due=as_of + timedelta(days=1), account_no="primary")],
    )
    injection = VirtualSpend(amount=100, envelope=Envelope.DINING, on=as_of, via_card=False)
    result = what_if(state, _behavior(), [injection], horizon_days=1, n_paths=1, seed=0)

    assert result.base.median == [1000, 50]
    assert result.branch.median == [900, -50]
    assert result.base.median == result.base.p10 == result.base.p90
    assert result.base.min_balance == 50
    assert result.branch.min_balance == -50
    assert result.branch.min_balance <= result.base.min_balance
    assert result.delta_min_balance == -100


def test_cash_and_card_injections_at_boundary_days_do_not_reduce_risk() -> None:
    as_of = date(2026, 3, 1)
    behavior = _behavior()
    for via_card in (False, True):
        cards = [CardState(
            card_no="card", withdrawal_account_no="primary", withdrawal_weekday=3,
            unbilled=0, issued_unpaid=[],
        )] if via_card else []
        state = _state(liquidity=1000, cards=cards)
        for offset in (0, 1, 60):
            result = what_if(
                state, behavior,
                [VirtualSpend(
                    amount=100, envelope=Envelope.DINING,
                    on=as_of + timedelta(days=offset), via_card=via_card,
                )],
                horizon_days=1, n_paths=25, seed=0,
            )
            assert result.branch.min_balance <= result.base.min_balance
            assert result.branch.shortfall_prob >= result.base.shortfall_prob
            assert result.branch.card_shortfall_prob >= result.base.card_shortfall_prob


def test_card_failure_does_not_reduce_balance_before_retry() -> None:
    as_of = date(2026, 3, 3)  # Tuesday; the next card withdrawal is Monday.
    card = CardState(
        card_no="card", withdrawal_account_no="primary", withdrawal_weekday=0,
        unbilled=100, issued_unpaid=[],
    )
    state = _state(as_of=as_of, liquidity=150, cards=[card])
    result = what_if(
        state, _behavior(),
        [VirtualSpend(
            amount=100, envelope=Envelope.DINING,
            on=as_of + timedelta(days=3), via_card=True,
        )],
        horizon_days=7, n_paths=1, seed=1,
    )
    assert result.base.min_balance == 50
    assert result.branch.min_balance == -50
    assert result.branch.min_balance <= result.base.min_balance
    assert result.delta_min_balance == -100
    assert result.delta_end_balance == -100
    assert result.delta_shortfall_prob >= 0
    assert result.branch.card_shortfall_prob == 1


def test_card_liability_clears_after_later_retry_without_cash_gain() -> None:
    as_of = date(2026, 3, 3)
    card = CardState(
        card_no="card", withdrawal_account_no="primary", withdrawal_weekday=0,
        unbilled=100, issued_unpaid=[],
    )
    state = _state(
        as_of=as_of, liquidity=150, cards=[card],
        next_income_date=date(2026, 3, 10), expected_income=100,
    )
    result = what_if(
        state, _behavior(),
        [VirtualSpend(amount=100, envelope=Envelope.DINING, on=date(2026, 3, 6), via_card=True)],
        horizon_days=13, n_paths=1, seed=1,
    )
    assert result.branch.card_shortfall_prob == 1
    assert result.branch.min_balance == -50
    assert result.branch.median[-1] == 50
    assert result.base.median[-1] == 150
    assert result.delta_end_balance == -100


def test_insufficient_fixed_debit_is_not_posted() -> None:
    state = _state(
        liquidity=100,
        committed=[FixedCommitment(kind="월세", name="월세", amount=200, due=date(2026, 3, 2), account_no="primary")],
    )
    result = risk(state, _behavior(), horizon_days=1, n_paths=5, seed=3)
    raw = simulate(state, _behavior(), horizon_days=1, n_paths=1, seed=3)
    assert raw.balances[0].tolist() == [100, 100]
    assert raw.economic_balances[0].tolist() == [100, -100]
    assert result.shortfall_prob == 1
    assert result.card_shortfall_prob == 0
    assert result.risk_score == 60
    assert result.level == "DANGER"
    assert result.expected_shortfall == 100
