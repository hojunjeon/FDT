from datetime import date
from pathlib import Path

import pytest

from fdt.data.generator import Generator, load_profile
from fdt.ledger.classify import classify_account_summary, classify_merchant, normalize_merchant
from fdt.ledger.ingest import ingest, reconcile
from fdt.schemas.domain import Instrument
from fdt.taxonomy.categories import Envelope, Flow


@pytest.fixture(scope="module")
def snapshots():
    out = {}
    for pid in ("A_steady", "B_card_crunch", "C_impulsive"):
        prof = load_profile(pid)
        prof["period"]["end"] = date(2026, 5, 31)  # 3개월만 (테스트 속도)
        snap, truth = Generator(prof).run()
        out[pid] = (snap, truth)
    return out


def test_classify_mapping_table():
    assert classify_merchant("GS25").envelope == Envelope.GROCERY
    assert classify_merchant("SKT").flow == Flow.FIXED
    assert classify_merchant("SKT").fixed_kind == "통신"
    unknown = classify_merchant("알수없는가게")
    assert unknown.envelope == Envelope.ETC and unknown.confidence < 0.5


def test_classify_account_summary():
    assert normalize_merchant("스타벅스 체크카드") == "스타벅스"
    assert classify_account_summary("급여 (주)키핀테크", True).flow == Flow.INCOME
    assert classify_account_summary("카드대금 신한카드", False).flow == Flow.CARD_BILL
    assert classify_account_summary("월세 임대인박OO", False).flow == Flow.FIXED
    assert classify_account_summary("스타벅스 체크카드", False).envelope == Envelope.DINING
    assert classify_account_summary("더치페이 친구", True).flow == Flow.REFUND


def test_reconcile_all_profiles(snapshots):
    for pid, (snap, _) in snapshots.items():
        txs = ingest(snap)
        issues = reconcile(snap, txs)
        assert issues["balance_mismatch"] == 0, pid
        assert issues["unclassified"] == 0, pid
        assert issues["low_confidence"] == 0, pid  # 시딩 가맹점은 전부 매핑 테이블에 있어야 함


def test_card_bill_not_double_counted(snapshots):
    snap, _ = snapshots["B_card_crunch"]
    txs = ingest(snap)
    bills = [t for t in txs if t.flow == Flow.CARD_BILL]
    assert bills and all(t.envelope is None for t in bills)
    assert all(t.instrument == Instrument.ACCOUNT for t in bills)


def test_envelope_spend_matches_ground_truth(snapshots):
    """원장 봉투 합산(취소 상쇄 포함)이 생성기 정답과 월별로 일치해야 한다."""
    snap, truth = snapshots["C_impulsive"]
    txs = ingest(snap)
    got: dict[str, dict[str, int]] = {}
    for t in txs:
        if t.flow in (Flow.SPEND, Flow.REFUND) and t.envelope is not None and t.instrument == Instrument.CARD:
            got.setdefault(t.occurred_at.strftime("%Y%m"), {}).setdefault(str(t.envelope), 0)
            got[t.occurred_at.strftime("%Y%m")][str(t.envelope)] += -t.amount
        elif t.flow == Flow.SPEND and t.envelope is not None:
            got.setdefault(t.occurred_at.strftime("%Y%m"), {}).setdefault(str(t.envelope), 0)
            got[t.occurred_at.strftime("%Y%m")][str(t.envelope)] += -t.amount
    for month, envs in truth["envelope_true_spend"].items():
        for env, amt in envs.items():
            assert got[month][env] == amt, (month, env, got[month][env], amt)
