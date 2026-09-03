"""State(t) 산출. 설계: docs/03_FDT_설계.md §7.1

원장(as_of 이하 거래만) + 스냅샷 메타(계좌·카드·구독·대출) -> State.
숫자 규칙은 전부 설계 문서의 공식을 따른다. LLM 개입 없음.
"""
from __future__ import annotations

import math
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Iterable

from fdt.schemas.domain import CardState, EnvelopeState, FixedCommitment, LedgerTx, State
from fdt.schemas.finapi import FinSnapshot
from fdt.taxonomy.categories import ENVELOPES, Envelope, Flow


def _as_date(value: str) -> date:
    """금융망 날짜 문자열을 date로 변환한다."""
    if len(value) == 8 and value.isdigit():
        return datetime.strptime(value, "%Y%m%d").date()
    return date.fromisoformat(value[:10])


def _month_add(day: date, months: int = 1) -> date:
    """달력 월을 더하고 말일을 보정한다."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _month_end(day: date) -> date:
    return date(day.year, day.month, monthrange(day.year, day.month)[1])


def _filtered(txs: Iterable[LedgerTx], as_of: date) -> list[LedgerTx]:
    return [tx for tx in txs if tx.occurred_at.date() <= as_of]


def _budget_map(budgets: dict[Envelope, int]) -> dict[Envelope, int]:
    return {env: int(budgets.get(env, budgets.get(str(env), 0))) for env in ENVELOPES}


def _spend_amount(txs: Iterable[LedgerTx], env: Envelope, start: date, end: date) -> int:
    """SPEND(-)와 봉투가 있는 REFUND(+)를 양의 순지출로 합산한다."""
    return int(-sum(
        tx.amount
        for tx in txs
        if start <= tx.day <= end
        and tx.flow in (Flow.SPEND, Flow.REFUND)
        and tx.envelope == env
    ))


def _ceil_10k(value: float) -> int:
    return max(10_000, int(math.ceil(max(0.0, value) / 10_000) * 10_000))


def _opening_balance(snap: FinSnapshot, account_no: str, as_of: date) -> int | None:
    """첫 원장 레코드로 계좌 개설잔액을 역산한다."""
    history = next((h for h in snap.accountTransactions if h.accountNo == account_no), None)
    if history is None or not history.list:
        return None
    # 금융망의 첫 레코드는 거래 시각이 아니라 원장 순번 기준이다.
    first = history.list[0]
    signed = int(first.transactionBalance) if first.transactionType == "1" else -int(first.transactionBalance)
    return int(first.transactionAfterBalance) - signed


def _account_balances(txs: list[LedgerTx], snap: FinSnapshot, as_of: date) -> dict[str, int]:
    balances: dict[str, int] = {}
    for account in snap.accounts:
        account_no = account.accountNo
        opening = _opening_balance(snap, account_no, as_of)
        account_txs = [
            tx for tx in txs
            if tx.instrument.value == "ACCOUNT" and tx.instrument_no == account_no
        ]
        balances[account_no] = (
            int(opening + sum(tx.amount for tx in account_txs))
            if opening is not None
            else int(account.accountBalance)
        )
    return balances


def _primary_account(txs: list[LedgerTx], snap: FinSnapshot) -> str:
    account_nos = {account.accountNo for account in snap.accounts}
    for card in snap.cards:
        if card.withdrawalAccountNo in account_nos:
            return card.withdrawalAccountNo
    counts = defaultdict(int)
    for tx in txs:
        if tx.instrument.value == "ACCOUNT" and tx.flow == Flow.INCOME:
            counts[tx.instrument_no] += 1
    if counts:
        order = {account.accountNo: -i for i, account in enumerate(snap.accounts)}
        return max(account_nos, key=lambda account_no: (counts[account_no], order[account_no]))
    return snap.accounts[0].accountNo


def propose_budgets(txs: list[LedgerTx], as_of: date) -> dict[Envelope, int]:
    """§7.1.4 완결 월 순지출의 중앙값·평균으로 결정론적 예산을 제안한다."""
    visible = _filtered(txs, as_of)
    first_day = min((tx.day for tx in visible), default=as_of)
    month = first_day.replace(day=1)
    complete: list[date] = []
    while month <= as_of.replace(day=1):
        if _month_end(month) <= as_of:
            complete.append(month)
        month = _month_add(month)

    monthly = {
        month: {
            env: _spend_amount(visible, env, month, _month_end(month))
            for env in ENVELOPES
        }
        for month in complete
    }
    result: dict[Envelope, int] = {}
    for env in ENVELOPES:
        if len(complete) >= 3:
            raw = median(monthly[month][env] for month in complete)
        elif complete:
            raw = sum(monthly[month][env] for month in complete) / len(complete)
        else:
            raw = _spend_amount(visible, env, as_of - timedelta(days=27), as_of) * 30 / 28
        result[env] = _ceil_10k(raw)
    return result


def envelope_states(txs: list[LedgerTx], as_of: date, budgets: dict[Envelope, int]) -> list[EnvelopeState]:
    """§7.1.4 이번 달 1일~as_of 봉투 순지출과 잔여 예산을 만든다."""
    visible = _filtered(txs, as_of)
    start = as_of.replace(day=1)
    normalized = _budget_map(budgets)
    states: list[EnvelopeState] = []
    for env in ENVELOPES:
        spent = _spend_amount(visible, env, start, as_of)
        states.append(EnvelopeState(
            envelope=env,
            budget=normalized[env],
            spent=spent,
            remaining=normalized[env] - spent,
            cycle_start=start,
            cycle_end=_month_end(as_of),
        ))
    return states


def _next_weekday(day: date, weekday: int, *, include: bool = True) -> date:
    delta = (weekday - day.weekday()) % 7
    if not include and delta == 0:
        delta = 7
    return day + timedelta(days=delta)


def _card_states(txs: list[LedgerTx], snap: FinSnapshot, as_of: date) -> list[CardState]:
    """카드별 현재 미청구액과 as_of 기준 미결제 청구액을 만든다."""
    visible = _filtered(txs, as_of)
    bills = [
        tx for tx in visible
        if tx.instrument.value == "ACCOUNT" and tx.flow == Flow.CARD_BILL and tx.amount < 0
    ]
    cycle_start = as_of - timedelta(days=as_of.weekday())
    unused_bills = set(range(len(bills)))
    states: list[CardState] = []
    for card in snap.cards:
        card_txs = [
            tx for tx in visible
            if tx.instrument.value == "CARD" and tx.instrument_no == card.cardNo
            and tx.flow in (Flow.SPEND, Flow.REFUND, Flow.FIXED)
        ]
        unbilled = max(0, int(-sum(tx.amount for tx in card_txs if cycle_start <= tx.day <= as_of)))
        statement_totals: dict[date, int] = defaultdict(int)
        for tx in card_txs:
            issue = tx.day + timedelta(days=7 - tx.day.weekday())
            if issue <= as_of:
                statement_totals[issue] -= tx.amount

        for billing in snap.billingStatements:
            if billing.cardNo != card.cardNo:
                continue
            for month in billing.months:
                for statement in month.billingList:
                    issue = _as_date(statement.billingDate)
                    if issue <= as_of and statement.status == "미결제":
                        statement_totals.setdefault(issue, int(statement.totalBalance))

        unpaid_by_due: dict[date, int] = defaultdict(int)
        withdrawal_weekday = int(card.withdrawalDate) - 1
        for issue, amount in sorted(statement_totals.items()):
            amount = int(amount)
            if amount <= 0:
                continue
            matched = None
            for i in sorted(unused_bills):
                bill = bills[i]
                if -bill.amount != amount or bill.instrument_no != card.withdrawalAccountNo:
                    continue
                text = f"{bill.merchant} {bill.summary}"
                if card.cardIssuerName not in text and len(snap.cards) > 1:
                    continue
                matched = i
                break
            if matched is not None:
                unused_bills.remove(matched)
                continue
            due = _next_weekday(as_of, withdrawal_weekday)
            unpaid_by_due[due] += amount

        issued_unpaid = [
            FixedCommitment(
                kind="카드대금",
                name=card.cardName,
                amount=amount,
                due=due,
                account_no=card.withdrawalAccountNo,
                certainty=1.0,
                card_no=card.cardNo,
            )
            for due, amount in sorted(unpaid_by_due.items())
        ]
        states.append(CardState(
            card_no=card.cardNo,
            withdrawal_account_no=card.withdrawalAccountNo,
            withdrawal_weekday=withdrawal_weekday,
            unbilled=unbilled,
            issued_unpaid=issued_unpaid,
        ))
    return states


def _recurring_fixed(txs: list[LedgerTx], snap: FinSnapshot, as_of: date) -> list[FixedCommitment]:
    visible = _filtered(txs, as_of)
    active_subs = {sub.subscriptionName for sub in snap.subscriptions if sub.status == "ACTIVE"}
    card_accounts = {card.cardNo: card.withdrawalAccountNo for card in snap.cards}
    groups: dict[tuple[str, str, str, str | None], list[LedgerTx]] = defaultdict(list)
    for tx in visible:
        if tx.flow not in (Flow.FIXED, Flow.TRANSFER_INTERNAL) or tx.amount >= 0 or tx.fixed_kind == "대출이자":
            continue
        if tx.fixed_kind == "구독" and tx.merchant in active_subs:
            continue
        account_no = tx.instrument_no if tx.instrument.value == "ACCOUNT" else card_accounts.get(tx.instrument_no, tx.instrument_no)
        kind = tx.fixed_kind or ("비상금이체" if tx.flow == Flow.TRANSFER_INTERNAL else "고정비")
        card_no = tx.instrument_no if tx.instrument.value == "CARD" else None
        groups[(kind, tx.merchant, account_no, card_no)].append(tx)

    commitments: list[FixedCommitment] = []
    for (kind, name, account_no, card_no), events in groups.items():
        events.sort(key=lambda tx: (tx.day, tx.occurred_at, tx.tx_id))
        gaps = [(b.day - a.day).days for a, b in zip(events, events[1:])]
        if len(events) < 2 or not any(25 <= gap <= 35 for gap in gaps):
            continue
        due = _month_add(events[-1].day)
        while due <= as_of:
            due = _month_add(due)
        commitments.append(FixedCommitment(
            kind=kind,
            name=name,
            amount=int(median(-tx.amount for tx in events[-3:])),
            due=due,
            account_no=account_no,
            certainty=1.0,
            card_no=card_no,
        ))
    return commitments


def _snapshot_subscriptions(snap: FinSnapshot, as_of: date) -> list[FixedCommitment]:
    card_accounts = {card.cardNo: card.withdrawalAccountNo for card in snap.cards}
    result: list[FixedCommitment] = []
    for sub in snap.subscriptions:
        if sub.status != "ACTIVE":
            continue
        due = _as_date(sub.nextPaymentDate)
        while due <= as_of:
            due = _month_add(due)
        result.append(FixedCommitment(
            kind="구독",
            name=sub.subscriptionName,
            amount=int(sub.paymentAmount),
            due=due,
            account_no=card_accounts.get(sub.cardNo, ""),
            certainty=1.0,
            card_no=sub.cardNo or None,
        ))
    return result


def _loan_commitments(txs: list[LedgerTx], snap: FinSnapshot, as_of: date) -> list[FixedCommitment]:
    visible = _filtered(txs, as_of)
    result: list[FixedCommitment] = []
    for loan in snap.loans:
        if loan.status not in ("상환중", "ACTIVE", "active"):
            continue
        events = [
            tx for tx in visible
            if tx.flow == Flow.FIXED and tx.fixed_kind == "대출이자"
            and tx.instrument_no == loan.withdrawalAccountNo
        ]
        due = _month_add(max((tx.day for tx in events), default=_month_end(as_of)))
        while due <= as_of:
            due = _month_add(due)
        amount = int(round(int(loan.loanBalance) * float(loan.interestRate) / 100 / 12 / 10) * 10)
        result.append(FixedCommitment(
            kind="대출이자",
            name=loan.accountName,
            amount=amount,
            due=due,
            account_no=loan.withdrawalAccountNo,
            certainty=1.0,
        ))
    return result


def _expand_monthly(
    commitments: list[FixedCommitment], as_of: date, end: date
) -> list[FixedCommitment]:
    expanded: list[FixedCommitment] = []
    for item in commitments:
        expanded.append(item)
        if item.kind == "카드대금":
            continue
        due = _month_add(item.due)
        while due <= end:
            expanded.append(item.model_copy(update={"due": due}))
            due = _month_add(due)
    return expanded


def build_committed_queue(
    txs: list[LedgerTx],
    snap: FinSnapshot,
    as_of: date,
    horizon_days: int = 60,
) -> list[FixedCommitment]:
    """§7.1.3 as_of 이후 반복 고정비·구독·대출·카드 청구 큐를 만든다."""
    if horizon_days <= 0:
        return []
    visible = _filtered(txs, as_of)
    end = as_of + timedelta(days=horizon_days)
    commitments = _recurring_fixed(visible, snap, as_of)
    commitments.extend(_snapshot_subscriptions(snap, as_of))
    commitments.extend(_loan_commitments(visible, snap, as_of))
    commitments = _expand_monthly(commitments, as_of, end)
    card_states = _card_states(visible, snap, as_of)
    cards_by_no = {card.cardNo: card for card in snap.cards}
    for state in card_states:
        card = cards_by_no[state.card_no]
        if state.unbilled > 0:
            issue = _next_weekday(as_of, 0, include=False)
            due = _next_weekday(issue, state.withdrawal_weekday)
            commitments.append(FixedCommitment(
                kind="카드대금", name=card.cardName, amount=state.unbilled, due=due,
                account_no=state.withdrawal_account_no, certainty=0.9, card_no=state.card_no,
            ))
        commitments.extend(state.issued_unpaid)

    merged: dict[tuple[str, str, date, str, str | None], FixedCommitment] = {}
    for item in commitments:
        if not as_of < item.due <= end:
            continue
        key = (item.kind, item.name, item.due, item.account_no, item.card_no)
        if key in merged:
            old = merged[key]
            merged[key] = old.model_copy(update={
                "amount": old.amount + item.amount,
                "certainty": min(old.certainty, item.certainty),
            })
        else:
            merged[key] = item
    return sorted(merged.values(), key=lambda item: (item.due, item.kind, item.name, item.account_no, item.card_no or ""))


def build_state(
    txs: list[LedgerTx],
    snap: FinSnapshot,
    as_of: date,
    budgets: dict[Envelope, int] | None = None,
) -> State:
    """§7.1 State(t)를 원장·스냅샷에서 조립한다. 건강도는 analytics가 채운다."""
    visible = _filtered(txs, as_of)
    account_balances = _account_balances(visible, snap, as_of)
    primary = _primary_account(visible, snap)
    emergency = sum(balance for account_no, balance in account_balances.items() if account_no != primary)
    selected_budgets = _budget_map(budgets) if budgets is not None else propose_budgets(visible, as_of)
    envelopes = envelope_states(visible, as_of, selected_budgets)
    from fdt.twin.behavior import detect_income_schedule

    _income_dates, expected_income, _irregular, next_income = detect_income_schedule(visible, as_of)
    spend_7d = sum(_spend_amount(visible, env, as_of - timedelta(days=6), as_of) for env in ENVELOPES) / 7
    data_start = min((tx.day for tx in visible), default=as_of)
    window_start = max(as_of - timedelta(days=89), data_start)
    denominator = max(1, (as_of - window_start).days + 1)
    spend_90d = sum(_spend_amount(visible, env, window_start, as_of) for env in ENVELOPES) / denominator
    acceleration = spend_7d / max(spend_90d, 1000)
    unconfirmed = sum(
        1 for tx in visible
        if tx.day.month == as_of.month and tx.day.year == as_of.year
        and tx.flow == Flow.SPEND and tx.confidence < 0.7
    )
    return State(
        as_of=as_of,
        user_name=snap.userName,
        liquidity=account_balances.get(primary, 0),
        emergency_fund=emergency,
        account_balances=account_balances,
        primary_account_no=primary,
        committed=build_committed_queue(visible, snap, as_of),
        envelopes=envelopes,
        cards=_card_states(visible, snap, as_of),
        next_income_date=next_income,
        expected_income=int(expected_income),
        spend_7d_avg=float(spend_7d),
        spend_90d_avg=float(spend_90d),
        acceleration=float(acceleration),
        unconfirmed_count=unconfirmed,
        health_score=0.0,
        health_level="SAFE",
    )
