import inspect
import math
from datetime import date, datetime, time, timedelta

import pytest

from fdt.data.generator import Generator, load_profile
from fdt.ledger.ingest import ingest
from fdt.schemas.domain import Instrument, LedgerTx, Source
from fdt.taxonomy.categories import Envelope, Flow
from fdt.twin.behavior import detect_income_schedule, estimate_behavior


def _tx(
    day: date,
    amount: int,
    envelope: Envelope | None = Envelope.DINING,
    *,
    instrument: Instrument = Instrument.ACCOUNT,
    flow: Flow = Flow.SPEND,
    tx_id: str | None = None,
    confidence: float = 1.0,
) -> LedgerTx:
    return LedgerTx(
        tx_id=tx_id or f"{day.isoformat()}:{amount}:{len(str(day))}",
        source=Source.SEED,
        occurred_at=datetime.combine(day, time(12)),
        instrument=instrument,
        instrument_no="card-1" if instrument == Instrument.CARD else "account-1",
        amount=amount,
        flow=flow,
        envelope=envelope,
        confidence=confidence,
    )


def _income(day: date, amount: int = 100_000) -> LedgerTx:
    return _tx(day, amount, None, flow=Flow.INCOME)


def _env_behavior(behavior, env: Envelope):
    return next(item for item in behavior.envelopes if item.envelope == env)


def test_weekday_multipliers_are_normalized_and_sparse_data_is_flat():
    as_of = date(2026, 1, 28)
    txs = [_tx(date(2026, 1, 5) + timedelta(days=7 * i), -10_000) for i in range(4)]
    txs += [_tx(date(2026, 1, 6) + timedelta(days=i), -10_000) for i in range(6)]
    behavior = estimate_behavior(txs, as_of, window_days=28)
    multipliers = _env_behavior(behavior, Envelope.DINING).weekday_mult
    assert sum(multipliers) / 7 == pytest.approx(1.0, abs=1e-9)
    assert len([tx for tx in txs if tx.envelope == Envelope.DINING]) == 10

    sparse = estimate_behavior(txs[:9], as_of, window_days=28)
    assert _env_behavior(sparse, Envelope.DINING).weekday_mult == [1.0] * 7


def test_amount_sigma_is_clipped_and_pooled_or_default_when_sparse():
    as_of = date(2026, 1, 28)
    amounts = [100, 1_000, 10_000, 100_000, 1_000_000]
    behavior = estimate_behavior(
        [_tx(date(2026, 1, i + 1), -amount) for i, amount in enumerate(amounts)],
        as_of,
        window_days=28,
    )
    assert _env_behavior(behavior, Envelope.DINING).amount_sigma == 1.5

    pooled_txs = [
        _tx(date(2026, 1, i + 1), -(i + 1) * 10_000, env)
        for i, env in enumerate((Envelope.DINING, Envelope.DINING, Envelope.TRANSPORT,
                                  Envelope.TRANSPORT, Envelope.ETC, Envelope.ETC))
    ]
    pooled = estimate_behavior(pooled_txs, as_of, window_days=28)
    assert _env_behavior(pooled, Envelope.DINING).amount_mu == pytest.approx(
        _env_behavior(pooled, Envelope.TRANSPORT).amount_mu
    )
    empty = estimate_behavior([], as_of)
    assert _env_behavior(empty, Envelope.DINING).amount_mu == pytest.approx(math.log(10_000))
    assert _env_behavior(empty, Envelope.DINING).amount_sigma == pytest.approx(0.6)


def test_income_schedule_regular_irregular_and_single_observation():
    regular = [_income(date(2026, month, 25), 3_150_000) for month in (1, 2, 3)]
    dates, amount, irregular, next_date = detect_income_schedule(regular, date(2026, 3, 26))
    assert dates == [date(2026, 1, 25), date(2026, 2, 25), date(2026, 3, 25)]
    assert amount == 3_150_000
    assert irregular is False
    assert next_date == date(2026, 4, 25)

    irregular_txs = [_income(date(2026, 1, 5)), _income(date(2026, 1, 15)), _income(date(2026, 2, 2))]
    _, _, irregular, next_date = detect_income_schedule(irregular_txs, date(2026, 2, 3))
    assert irregular is True
    assert next_date == date(2026, 2, 16)

    dates, amount, irregular, next_date = detect_income_schedule([_income(date(2026, 2, 1))], date(2026, 2, 3))
    assert dates == [date(2026, 2, 1)]
    assert amount == 0
    assert irregular is True
    assert next_date is None


@pytest.mark.parametrize(("profile_id", "irregular"), (("A_steady", False), ("C_impulsive", True)))
def test_seed_profiles_income_schedule(profile_id: str, irregular: bool):
    profile = load_profile(profile_id)
    profile["period"]["end"] = date(2026, 5, 31)
    snapshot, _ = Generator(profile).run()
    txs = ingest(snapshot)
    _, _, got_irregular, next_date = detect_income_schedule(txs, date(2026, 5, 31))
    assert got_irregular is irregular
    assert next_date is not None


def test_low_residual_days_fewer_than_five_keep_neutral_elasticity():
    as_of = date(2026, 1, 28)
    txs = [_tx(date(2026, 1, i), -30_000) for i in range(25, 29)]
    budgets = {env: 100_000 for env in Envelope}
    behavior = estimate_behavior(txs, as_of, window_days=28, budgets=budgets)
    assert _env_behavior(behavior, Envelope.DINING).elasticity == 1.0


def test_as_of_and_cancelled_card_spend_do_not_leak_into_behavior():
    as_of = date(2026, 1, 10)
    txs = [
        _tx(date(2026, 1, 3), -20_000, instrument=Instrument.CARD, tx_id="approval"),
        _tx(date(2026, 1, 3), 20_000, instrument=Instrument.CARD, flow=Flow.REFUND, tx_id="approval:cancel"),
        _tx(date(2026, 1, 5), -30_000, tx_id="kept"),
        _tx(date(2026, 1, 11), -90_000, tx_id="future"),
    ]
    behavior = estimate_behavior(txs, as_of, window_days=28, budgets={env: 100_000 for env in Envelope})
    dining = _env_behavior(behavior, Envelope.DINING)
    assert behavior.estimated_to == as_of
    assert dining.daily_rate == pytest.approx(1 / behavior.n_days)
    assert behavior.n_days == 8


def test_behavior_source_has_no_hidden_data_dependencies():
    from fdt.twin import behavior

    source = inspect.getsource(behavior)
    for forbidden in ("ground_truth", "hidden_params", "yaml"):
        assert forbidden not in source
