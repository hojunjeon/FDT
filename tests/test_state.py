from __future__ import annotations

from datetime import date, timedelta
from statistics import median

import pytest

import fdt.twin.behavior as behavior
from fdt.data.generator import Generator, load_profile
from fdt.ledger.ingest import ingest
from fdt.schemas.domain import Flow
from fdt.twin.state import build_state, build_committed_queue, envelope_states, propose_budgets
from fdt.taxonomy.categories import ENVELOPES


@pytest.fixture(scope="module")
def snapshots():
    result = {}
    for profile_id in ("A_steady", "B_card_crunch", "C_impulsive"):
        profile = load_profile(profile_id)
        snapshot, truth = Generator(profile).run()
        result[profile_id] = (snapshot, ingest(snapshot), truth)
    return result


@pytest.fixture(autouse=True)
def income_schedule_stub(monkeypatch):
    monkeypatch.setattr(behavior, "detect_income_schedule", lambda txs, as_of: ([], 0, True, None))


def test_primary_balance_matches_generated_truth(snapshots):
    for profile_id, (snapshot, txs, truth) in snapshots.items():
        as_of = date(2026, 5, 31)
        state = build_state(txs, snapshot, as_of)
        expected = truth["daily_balance"][as_of.strftime("%Y%m%d")][state.primary_account_no]
        assert state.liquidity == expected, profile_id


def test_as_of_filters_future_transactions(snapshots):
    snapshot, txs, _ = snapshots["B_card_crunch"]
    as_of = date(2026, 8, 25)
    state = build_state(txs, snapshot, as_of)
    truncated = [tx for tx in txs if tx.day <= as_of]
    expected = build_state(truncated, snapshot, as_of)
    assert state.model_dump() == expected.model_dump()


def test_as_of_before_first_transaction_uses_opening_balance_not_snapshot_final(snapshots):
    snapshot, txs, _ = snapshots["A_steady"]
    state = build_state(txs, snapshot, date(2026, 3, 1))
    assert state.liquidity == 1_850_000


def test_propose_budgets_uses_median_for_three_complete_months(snapshots):
    _, txs, _ = snapshots["A_steady"]
    as_of = date(2026, 5, 31)
    got = propose_budgets(txs, as_of)
    expected = {}
    for env in ENVELOPES:
        monthly = []
        for month_start in (date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)):
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            monthly.append(-sum(
                tx.amount for tx in txs
                if month_start <= tx.day <= month_end
                and tx.flow in (Flow.SPEND, Flow.REFUND) and tx.envelope == env
            ))
        expected[env] = max(10_000, ((int(median(monthly)) + 9_999) // 10_000) * 10_000)
    assert got == expected


def test_propose_budgets_uses_28_day_fallback():
    profile = load_profile("A_steady")
    profile["period"]["end"] = date(2026, 3, 15)
    snapshot, _ = Generator(profile).run()
    txs = ingest(snapshot)
    as_of = date(2026, 3, 15)
    got = propose_budgets(txs, as_of)
    for env in ENVELOPES:
        spend = -sum(
            tx.amount for tx in txs
            if as_of - timedelta(days=27) <= tx.day <= as_of
            and tx.flow in (Flow.SPEND, Flow.REFUND) and tx.envelope == env
        )
        expected = max(10_000, ((spend * 30 + 28 * 10_000 - 1) // (28 * 10_000)) * 10_000)
        assert got[env] == expected


def test_b_card_and_unbilled_queue_on_tuesday(snapshots):
    snapshot, txs, _ = snapshots["B_card_crunch"]
    as_of = date(2026, 8, 25)
    state = build_state(txs, snapshot, as_of)
    cards = {card.card_no: card for card in state.cards}
    for card in snapshot.cards:
        expected = -sum(
            tx.amount for tx in txs
            if tx.instrument_no == card.cardNo and tx.instrument.value == "CARD"
            and as_of - timedelta(days=as_of.weekday()) <= tx.day <= as_of
            and tx.flow in (Flow.SPEND, Flow.REFUND, Flow.FIXED)
        )
        assert cards[card.cardNo].unbilled == expected
    card_items = [item for item in state.committed if item.kind == "카드대금"]
    assert any(item.amount == 122_300 and item.due == date(2026, 8, 29) for item in card_items)
    assert any(item.amount == 19_500 and item.due == date(2026, 9, 1) for item in card_items)
    assert any(item.amount == 22_700 and item.due == date(2026, 9, 5) for item in card_items)


def test_card_fixed_commitments_keep_card_identity_and_repeat_through_60_days(snapshots):
    snapshot, txs, _ = snapshots["A_steady"]
    state = build_state(txs, snapshot, date(2026, 5, 31))
    card_numbers = {card.cardNo for card in snapshot.cards}
    recurring = [item for item in state.committed if item.kind in {"통신", "구독"}]
    assert recurring
    assert {item.card_no for item in recurring} <= card_numbers
    transfers = [item for item in state.committed if item.kind == "비상금이체"]
    assert [item.due for item in transfers] == [date(2026, 6, 25), date(2026, 7, 25)]


def test_monday_unbilled_starts_on_monday_and_bills_not_in_envelopes(snapshots):
    snapshot, txs, _ = snapshots["B_card_crunch"]
    as_of = date(2026, 8, 24)
    state = build_state(txs, snapshot, as_of)
    card_values = sorted(card.unbilled for card in state.cards)
    assert card_values == [6_100, 19_500]
    expected_spend = {
        env: -sum(
            tx.amount for tx in txs
            if tx.day.month == as_of.month and tx.day.year == as_of.year and tx.day <= as_of
            and tx.flow in (Flow.SPEND, Flow.REFUND) and tx.envelope == env
        )
        for env in ENVELOPES
    }
    assert {item.envelope: item.spent for item in state.envelopes} == expected_spend
