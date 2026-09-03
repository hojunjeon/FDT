"""금융망 스냅샷(FinSnapshot) -> 정규화 원장(LedgerTx 목록).

규칙 (NFR-BGT-01: 모든 소비는 정확히 한 봉투에 정확히 한 번)
- 카드 승인: 봉투 차감 대상(SPEND) 또는 고정비. 취소(cardStatus=취소)는 REFUND 로 넣고 금액 부호 반대.
- 카드대금 출금(계좌): CARD_BILL. 봉투에 반영하지 않는다 (승인 시점에 이미 차감).
- 내 계좌 간 이체: 양쪽 계좌에 각각 기록되되 흐름은 TRANSFER_INTERNAL.
- 더치페이 입금: REFUND (봉투 지출 상쇄 후보). 원 결제와의 매칭은 하지 않고 봉투 합산에서 뺀다.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fdt.ledger.classify import FallbackClassifier, classify_account_summary, classify_merchant
from fdt.schemas.domain import Instrument, LedgerTx, Source
from fdt.schemas.finapi import FinSnapshot
from fdt.taxonomy.categories import Flow


def _dt(d: str, t: str) -> datetime:
    return datetime.strptime(d + t, "%Y%m%d%H%M%S")


def load_snapshot(path: Path | str) -> FinSnapshot:
    p = Path(path)
    if p.is_dir():
        p = p / "snapshot.json"
    return FinSnapshot.model_validate_json(p.read_text(encoding="utf-8"))


def ingest(snap: FinSnapshot, source: Source = Source.SEED, fallback: FallbackClassifier | None = None) -> list[LedgerTx]:
    my_accounts = {a.accountNo for a in snap.accounts}
    txs: list[LedgerTx] = []

    for hist in snap.accountTransactions:
        for t in hist.list:
            deposit = t.transactionType == "1"
            amt = int(t.transactionBalance)
            label = classify_account_summary(t.transactionSummary, deposit, fallback)
            flow = label.flow
            if t.transactionAccountNo and t.transactionAccountNo in my_accounts:
                flow = Flow.TRANSFER_INTERNAL
            txs.append(LedgerTx(
                tx_id=f"A:{hist.accountNo}:{t.transactionUniqueNo}", source=source,
                occurred_at=_dt(t.transactionDate, t.transactionTime), instrument=Instrument.ACCOUNT,
                instrument_no=hist.accountNo, amount=amt if deposit else -amt, merchant=label.merchant,
                summary=t.transactionSummary, flow=flow, subcategory=label.subcategory, envelope=label.envelope,
                confidence=label.confidence, fixed_kind=label.fixed_kind, counterpart_account=t.transactionAccountNo,
            ))

    for hist in snap.cardTransactions:
        for t in hist.transactionList:
            amt = int(t.transactionBalance)
            label = classify_merchant(t.merchantName, hint=t.categoryName, fallback=fallback)
            base = dict(
                occurred_at=_dt(t.transactionDate, t.transactionTime), instrument=Instrument.CARD,
                instrument_no=hist.cardNo, merchant=t.merchantName, fin_category_id=t.categoryId,
                fin_category_name=t.categoryName, subcategory=label.subcategory, envelope=label.envelope,
                confidence=label.confidence, fixed_kind=label.fixed_kind, source=source,
            )
            txs.append(LedgerTx(tx_id=f"C:{hist.cardNo}:{t.transactionUniqueNo}", amount=-amt, summary="승인", flow=label.flow, **base))
            if t.cardStatus == "취소":
                # 금융망은 취소 시 원 승인 레코드의 상태만 바뀐다. 승인(-)과 취소 환불(+)을 모두 남겨 이력 보존, 순액 0.
                txs.append(LedgerTx(tx_id=f"C:{hist.cardNo}:{t.transactionUniqueNo}:cancel", amount=amt, summary="취소", flow=Flow.REFUND, **base))

    txs.sort(key=lambda x: (x.occurred_at, x.tx_id))
    return txs


def save_ledger(txs: list[LedgerTx], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for t in txs:
            f.write(t.model_dump_json() + "\n")


def load_ledger(path: Path) -> list[LedgerTx]:
    with open(path, encoding="utf-8") as f:
        return [LedgerTx.model_validate_json(line) for line in f if line.strip()]


def reconcile(snap: FinSnapshot, txs: list[LedgerTx]) -> dict[str, int]:
    """대사: 계좌별 원장 합계 == 잔액 변화, 취소된 카드 승인이 정확히 한 번 상쇄되는지 (NFR-BGT-01)."""
    issues: dict[str, int] = {"balance_mismatch": 0, "unclassified": 0, "low_confidence": 0}
    for hist in snap.accountTransactions:
        if not hist.list:
            continue
        first = hist.list[0]
        opening = int(first.transactionAfterBalance) - (int(first.transactionBalance) if first.transactionType == "1" else -int(first.transactionBalance))
        ledger_sum = sum(t.amount for t in txs if t.instrument == Instrument.ACCOUNT and t.instrument_no == hist.accountNo)
        final = int(next(a.accountBalance for a in snap.accounts if a.accountNo == hist.accountNo))
        if opening + ledger_sum != final:
            issues["balance_mismatch"] += 1
    for t in txs:
        if t.flow == Flow.SPEND and t.envelope is None:
            issues["unclassified"] += 1
        if t.confidence < 0.7:
            issues["low_confidence"] += 1
    return issues


def ledger_summary(txs: list[LedgerTx]) -> dict:
    by_flow: dict[str, int] = {}
    by_env: dict[str, int] = {}
    for t in txs:
        by_flow[t.flow] = by_flow.get(t.flow, 0) + t.amount
        if t.flow in (Flow.SPEND, Flow.REFUND) and t.envelope is not None:
            by_env[t.envelope] = by_env.get(t.envelope, 0) + t.amount
    return {"count": len(txs), "by_flow": by_flow, "by_envelope": by_env}


if __name__ == "__main__":
    import sys

    snap = load_snapshot(sys.argv[1])
    txs = ingest(snap)
    print(json.dumps(ledger_summary(txs), ensure_ascii=False, indent=1))
    print(reconcile(snap, txs))
