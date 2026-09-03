from __future__ import annotations

from datetime import date, datetime, timedelta

from fdt.schemas.domain import Alert, Behavior, EnvelopeState, FixedCommitment, LedgerTx, RiskResult, State
from fdt.schemas.domain import Instrument, Source
from fdt.taxonomy.categories import ENVELOPES, Flow, Envelope
from fdt.twin.analytics import detect_alerts, health, rebalance, safe_to_spend


def _state(*, as_of: date = date(2026, 1, 15), liquidity: int = 1_000_000, spent: dict[Envelope, int] | None = None, budget: int = 100_000, **kwargs) -> State:
    spent = spent or {}
    envelopes = [
        EnvelopeState(
            envelope=env,
            budget=budget,
            spent=spent.get(env, 0),
            remaining=budget - spent.get(env, 0),
            cycle_start=as_of.replace(day=1),
            cycle_end=as_of.replace(day=31),
        )
        for env in ENVELOPES
    ]
    defaults = dict(
        next_income_date=None,
        expected_income=0,
        spend_7d_avg=1_000,
        spend_90d_avg=10_000,
        acceleration=1.0,
        unconfirmed_count=0,
    )
    defaults.update(kwargs)
    return State(
        as_of=as_of,
        user_name="테스트",
        liquidity=liquidity,
        emergency_fund=200_000,
        account_balances={"p": liquidity},
        primary_account_no="p",
        committed=[],
        envelopes=envelopes,
        cards=[],
        **defaults,
    )


def _behavior() -> Behavior:
    return Behavior(
        estimated_from=date(2025, 1, 1),
        estimated_to=date(2026, 1, 15),
        n_days=380,
        envelopes=[],
        income_dates=[],
        income_amount_median=0,
        irregular_income=True,
        shock_daily_prob=0.01,
        shock_amount_mu=11.0,
        shock_amount_sigma=0.6,
    )


def _tx(amount: int, env: Envelope, tx_id: str = "tx") -> LedgerTx:
    return LedgerTx(
        tx_id=tx_id,
        source=Source.SEED,
        occurred_at=datetime(2026, 1, 15, 12),
        instrument=Instrument.ACCOUNT,
        instrument_no="p",
        amount=amount,
        merchant="테스트",
        flow=Flow.SPEND,
        envelope=env,
    )


def _card_tx(
    amount: int,
    day: date,
    *,
    card_no: str = "card-1",
    flow: Flow = Flow.SPEND,
    tx_id: str = "card-tx",
) -> LedgerTx:
    return LedgerTx(
        tx_id=tx_id,
        source=Source.SEED,
        occurred_at=datetime.combine(day, datetime.min.time()),
        instrument=Instrument.CARD,
        instrument_no=card_no,
        amount=amount,
        merchant="테스트",
        flow=flow,
        envelope=Envelope.DINING,
    )


def test_safe_to_spend_never_negative_and_reports_fixed_cost_pressure():
    state = _state(liquidity=50_000, next_income_date=date(2026, 1, 20))
    state.committed.append(FixedCommitment(kind="월세", name="월세", amount=80_000, due=date(2026, 1, 19), account_no="p"))
    result = safe_to_spend(state, [])

    assert result.safe_today == 0
    assert "부족 30,000원" in result.note
    assert "비상금 200,000원 별도" in result.note


def test_rebalance_never_uses_essential_envelopes():
    spent = {Envelope.DINING: 90_000, Envelope.LEISURE: 10_000}
    state = _state(spent=spent, budget=100_000)
    result = rebalance(state, _behavior())

    assert result.trigger == Envelope.DINING
    assert result.moves
    assert all(move.from_envelope not in {Envelope.TRANSPORT, Envelope.HEALTH, Envelope.GROCERY} for move in result.moves)
    assert sum(move.amount for move in result.moves) <= result.shortfall


def test_detect_alerts_applies_pace_floor_before_month_end_noise():
    state = _state(as_of=date(2026, 1, 31), spent={Envelope.DINING: 595_000}, budget=600_000)
    no_alert = detect_alerts(state, _behavior(), [_tx(-15_000, Envelope.DINING)])
    assert not [a for a in no_alert if a.kind == "CONCERNING_PAYMENT"]

    state = _state(spent={Envelope.DINING: 520_000}, budget=600_000)
    warning = detect_alerts(state, _behavior(), [_tx(-120_000, Envelope.DINING, "warning")])
    assert warning[-1].severity == "WARNING"
    assert warning[-1].threshold == 100_000

    state = _state(spent={Envelope.DINING: 650_000}, budget=600_000)
    danger = detect_alerts(state, _behavior(), [_tx(-250_000, Envelope.DINING, "danger")])
    assert danger[-1].severity == "DANGER"


def test_detect_alerts_ignores_a_card_approval_cancelled_on_the_same_day():
    day = date(2026, 1, 15)
    state = _state(as_of=day)
    approval = _card_tx(-120_000, day, tx_id="approval")
    cancel = _card_tx(120_000, day, flow=Flow.REFUND, tx_id="approval:cancel")

    alerts = detect_alerts(state, _behavior(), [approval, cancel])

    assert not [a for a in alerts if a.kind == "CONCERNING_PAYMENT"]


def test_detect_alerts_requires_the_behavior_cancel_match_key():
    approval_day = date(2026, 1, 15)
    approval = _card_tx(-120_000, approval_day, tx_id="approval")
    near_cancels = [
        _card_tx(120_000, approval_day, card_no="card-2", flow=Flow.REFUND, tx_id="wrong-card"),
        _card_tx(110_000, approval_day, flow=Flow.REFUND, tx_id="wrong-amount"),
        _card_tx(120_000, approval_day + timedelta(days=1), flow=Flow.REFUND, tx_id="adjacent-day"),
    ]

    for cancel in near_cancels:
        state = _state(as_of=cancel.day)
        alerts = detect_alerts(state, _behavior(), [approval, cancel])
        concerning = [a for a in alerts if a.kind == "CONCERNING_PAYMENT"]
        assert concerning and concerning[0].tx_id == "approval"


def test_acceleration_alert_has_noise_floor():
    quiet = _state(spend_7d_avg=9_999, acceleration=2.0)
    assert not detect_alerts(quiet, _behavior(), [])
    loud = _state(spend_7d_avg=10_000, acceleration=1.3)
    assert detect_alerts(loud, _behavior(), [])[0].kind == "ACCELERATION"


def test_health_thresholds_are_safe_warning_danger():
    risk = RiskResult(
        horizon_days=30,
        n_paths=10,
        shortfall_prob=0.0,
        card_shortfall_prob=0.0,
        risk_score=0,
        level="SAFE",
        worst_day=None,
        expected_shortfall=0,
    )
    safe = _state(liquidity=1_000_000, spend_90d_avg=10_000)
    assert health(safe, risk)[1] == "SAFE"
    danger = _state(liquidity=0, spend_90d_avg=100_000, acceleration=1.0)
    assert health(danger, risk)[1] == "WARNING"
    assert health(danger, risk.model_copy(update={"card_shortfall_prob": 1.0}))[1] == "DANGER"
