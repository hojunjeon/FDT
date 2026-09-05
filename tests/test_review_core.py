"""리뷰 경계 사례: 월말 급여, 평가 표본, 재배분 공급량, 원장 중복."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdt.eval.calibration import calibration_report
from fdt.ledger.ingest import ingest, load_snapshot
from fdt.taxonomy.categories import ENVELOPES, Envelope
from fdt.twin.analytics import rebalance
from fdt.twin.goal import _expected_income, _fixed_outflow, plan_goal
from fdt.twin.simulate import _next_income
from fdt.schemas.domain import FixedCommitment


@pytest.mark.parametrize("year", [2024, 2026])
def test_goal_regular_income_preserves_31st_after_february(year):
    state = SimpleNamespace(as_of=date(year, 1, 30), next_income_date=date(year, 1, 31), expected_income=1_000_000)
    behavior = SimpleNamespace(income_amount_median=900_000, income_dates=[date(year-1, 10, 31), date(year-1, 12, 31)], irregular_income=False)
    horizon = (date(year, 3, 30) - state.as_of).days
    assert _expected_income(state, behavior, horizon) == 2_000_000
    february = _next_income(state.next_income_date, behavior)
    assert _next_income(february, behavior) == date(year, 3, 31)


def test_unknown_next_income_is_not_fabricated():
    state = SimpleNamespace(as_of=date(2026, 1, 30), next_income_date=None, expected_income=0)
    behavior = SimpleNamespace(income_amount_median=1_000_000, income_dates=[date(2026, 1, 25)], irregular_income=False)
    assert _expected_income(state, behavior, 60) == 0


def test_goal_horizon_limit_rejects_before_simulation(monkeypatch):
    monkeypatch.setattr("fdt.twin.goal.simulate", lambda *a, **k: pytest.fail("simulation must not run"))
    with pytest.raises(ValueError, match="365"):
        plan_goal(SimpleNamespace(as_of=date(2026, 1, 1)), None, 100, date(9999, 1, 1))


def test_fixed_outflow_preserves_month_end_anchor():
    state = SimpleNamespace(as_of=date(2026, 1, 30), committed=[
        FixedCommitment(kind="월세", name="월세", amount=100, due=date(2026, 1, 31), account_no="p"),
    ])
    assert _fixed_outflow(state, date(2026, 3, 30)) == 200
    assert _fixed_outflow(state, date(2026, 3, 31)) == 300


def test_calibration_tiny_sample_cannot_pass():
    report = calibration_report([(0.1, 0), (0.9, 1)])
    assert report["passed"] is False
    assert report["status"] == "insufficient_data"
    assert calibration_report([])["status"] == "blocked"


def test_calibration_requires_both_outcomes_and_populated_bin_samples():
    assert not calibration_report([(0.1, 0)] * 30)["passed"]
    assert not calibration_report([(0.1, 0)] * 29 + [(0.9, 1)])["passed"]
    report = calibration_report([(0.1, 0)] * 15 + [(0.9, 1)] * 15)
    assert report["passed"] is True
    assert report["status"] == "complete"


def test_infeasible_rebalance_does_not_propose_nonexistent_money():
    envelopes = [SimpleNamespace(envelope=env, budget=0, spent=0, remaining=0) for env in ENVELOPES]
    for item in envelopes:
        if item.envelope == Envelope.DINING:
            item.budget, item.spent, item.remaining = 100_000, 200_000, -100_000
        elif item.envelope == Envelope.SHOPPING:
            item.budget, item.spent, item.remaining = 10_000, 0, 10_000
    plan = rebalance(SimpleNamespace(as_of=date(2026, 1, 31), envelopes=envelopes), None)
    assert not plan.feasible
    assert sum(move.amount for move in plan.moves) <= 10_000
    assert all(move.from_envelope == Envelope.SHOPPING for move in plan.moves)


def test_identical_duplicate_transactions_are_idempotent():
    snapshot = load_snapshot(Path(__file__).parents[1] / "data/seed/A_steady")
    expected = ingest(snapshot)
    snapshot.accountTransactions[0].list.append(snapshot.accountTransactions[0].list[0].model_copy(deep=True))
    snapshot.cardTransactions[0].transactionList.append(snapshot.cardTransactions[0].transactionList[0].model_copy(deep=True))
    assert ingest(snapshot) == expected


def test_conflicting_duplicate_transaction_is_rejected():
    snapshot = load_snapshot(Path(__file__).parents[1] / "data/seed/A_steady")
    record = snapshot.accountTransactions[0].list[0]
    snapshot.accountTransactions[0].list.append(record.model_copy(update={"transactionBalance": str(int(record.transactionBalance) + 1)}))
    with pytest.raises(ValueError, match="중복 거래 ID"):
        ingest(snapshot)
