"""단일 시뮬레이터와 회계 전이 함수. 설계: §7.3, §7.4.

SIM-01(궤적), SIM-02(What-if), SIM-03(리스크)은 같은 전이 엔진의
출력에서 파생된다. 금융 숫자는 이 모듈에서만 계산하고 LLM은 사용하지 않는다.
"""
from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from fdt.schemas.domain import (
    Behavior,
    CardState,
    FixedCommitment,
    PathStats,
    RiskResult,
    State,
    VirtualSpend,
    WhatIfResult,
)
from fdt.taxonomy.categories import ENVELOPES, Envelope


@dataclass
class _Bill:
    amount: int
    issued: date
    due: date
    failed: bool = False
    liability_recorded: bool = False


@dataclass
class _Schedules:
    account: list[tuple[date, int]]
    card_fixed: list[tuple[date, int, int]]
    card_bill: list[tuple[date, int, int]]


@dataclass
class SimulationResult:
    dates: list[date]
    balances: np.ndarray          # shape (n_paths, horizon+1), primary 현금 잔액
    economic_balances: np.ndarray  # 현금 잔액 - 미결제 카드부채
    card_shortfall: np.ndarray    # shape (n_paths,), 카드 출금일 부족
    any_shortfall: np.ndarray     # shape (n_paths,), 어느 날이든 잔액 < 0
    first_shortfall_idx: np.ndarray  # shape (n_paths,), 없으면 -1
    envelope_spend: np.ndarray    # shape (n_paths, 7), 기간 내 봉투별 지출

    def stats(self, *, economic: bool = False) -> PathStats:
        """§7.4 경로 배열을 UI·분석용 통계로 집계한다."""
        paths = self.economic_balances if economic else self.balances
        median = _int_series(np.percentile(paths, 50, axis=0))
        p10 = _int_series(np.percentile(paths, 10, axis=0))
        p90 = _int_series(np.percentile(paths, 90, axis=0))
        mean = _int_series(np.mean(paths, axis=0))
        min_idx = int(np.argmin(median))
        if economic:
            below = paths < 0
            any_shortfall = below.any(axis=1)
            first_shortfall_idx = np.where(any_shortfall, below.argmax(axis=1), -1)
        else:
            any_shortfall = self.any_shortfall
            first_shortfall_idx = self.first_shortfall_idx
        first = first_shortfall_idx[first_shortfall_idx >= 0]
        first_date = None
        if first.size:
            ordinals = np.array([self.dates[int(i)].toordinal() for i in first], dtype=float)
            ordinal = int(np.floor(float(np.median(ordinals)) + 0.5))
            first_date = date.fromordinal(ordinal)
        return PathStats(
            dates=list(self.dates),
            median=median,
            p10=p10,
            p90=p90,
            mean=mean,
            min_balance=int(median[min_idx]),
            min_balance_date=self.dates[min_idx],
            shortfall_prob=float(np.mean(any_shortfall)),
            card_shortfall_prob=float(np.mean(self.card_shortfall)),
            first_shortfall_date_median=first_date,
        )


def _int_series(values: np.ndarray) -> list[int]:
    return np.rint(values).astype(np.int64).tolist()


def _next_income(day: date, behavior: Behavior) -> date:
    if not behavior.irregular_income:
        doms = Counter(item.day for item in behavior.income_dates)
        dom = max(doms, key=lambda value: (doms[value], -value)) if doms else day.day
        year, month = day.year, day.month + 1
        if month == 13:
            year, month = year + 1, 1
        return date(year, month, min(dom, calendar.monthrange(year, month)[1]))
    dates = sorted(behavior.income_dates)
    if len(dates) > 1:
        gaps = np.diff([d.toordinal() for d in dates])
        gap = max(1, int(np.rint(np.median(gaps))))
    else:
        gap = 30
    return day + timedelta(days=gap)


def _irregular_income_schedule(
    state: State, behavior: Behavior, horizon_days: int
) -> set[date]:
    """§7.3 관측된 최근 월의 입금 묶음을 다음 월들에 투영한다."""
    first = state.next_income_date
    if first is None:
        return set()
    observed = sorted(day for day in behavior.income_dates if day <= state.as_of)
    if not observed:
        return {first} if first <= state.as_of + timedelta(days=horizon_days) else set()
    latest_month = max((day.year, day.month) for day in observed)
    pattern = [
        day for day in observed
        if (day.year, day.month) == latest_month
    ]
    if not pattern:
        return {first}
    offsets = [max(0, (day - pattern[0]).days) for day in pattern]
    end = state.as_of + timedelta(days=horizon_days)
    result: set[date] = set()
    anchor = first
    while anchor <= end:
        month = anchor.replace(day=1)
        for offset in offsets:
            candidate = anchor + timedelta(days=offset)
            if candidate.month != month.month or candidate > end:
                break
            result.add(candidate)
        if month.month == 12:
            month = month.replace(year=month.year + 1, month=1)
        else:
            month = month.replace(month=month.month + 1)
        anchor = month.replace(day=min(pattern[0].day, calendar.monthrange(month.year, month.month)[1]))
    return {day for day in result if state.as_of < day <= end}


def _bill_issue_day(due: date) -> date:
    return due - timedelta(days=due.weekday())


def _next_withdrawal(day: date, weekday: int) -> date:
    return day + timedelta(days=(weekday - day.weekday()) % 7)


def _card_index(commitment: FixedCommitment, cards: list[CardState]) -> int | None:
    if not cards:
        return None
    if commitment.card_no:
        for i, card in enumerate(cards):
            if commitment.card_no == card.card_no:
                return i
    for i, card in enumerate(cards):
        if commitment.account_no == card.card_no:
            return i
    if commitment.kind in {"통신", "구독", "카드대금"}:
        for i, card in enumerate(cards):
            if commitment.account_no == card.withdrawal_account_no:
                return i
        return 0
    return None


def _schedules(state: State) -> _Schedules:
    """약정 큐를 계좌 지출, 카드 고정비, 카드 청구로 분리한다."""
    account: list[tuple[date, int]] = []
    card_fixed: list[tuple[date, int, int]] = []
    card_bill: list[tuple[date, int, int]] = []
    initial_unbilled = [max(0, int(card.unbilled)) for card in state.cards]
    issued = {
        (i, int(b.amount), b.due)
        for i, card in enumerate(state.cards)
        for b in card.issued_unpaid
    }
    for commitment in state.committed:
        amount = int(commitment.amount)
        if amount <= 0:
            continue
        card_idx = _card_index(commitment, state.cards)
        if commitment.kind == "카드대금":
            # State.committed includes the current unbilled total; Monday billing
            # below is the source of truth for that amount, so do not duplicate it.
            if card_idx is not None and (
                (initial_unbilled[card_idx] == amount and commitment.due > state.as_of)
                or (card_idx, amount, commitment.due) in issued
            ):
                continue
            if card_idx is not None:
                card_bill.append((commitment.due, card_idx, amount))
            continue
        if card_idx is not None:
            card_fixed.append((commitment.due, card_idx, amount))
        else:
            account.append((commitment.due, amount))
    return _Schedules(account=account, card_fixed=card_fixed, card_bill=card_bill)


def _model_arrays(state: State, behavior: Behavior) -> tuple[np.ndarray, ...]:
    state_envs = {item.envelope: item for item in state.envelopes}
    model = {item.envelope: item for item in behavior.envelopes}
    rates, weekday, mu, sigma, card_share, boost, elasticity, budgets, spent = [], [], [], [], [], [], [], [], []
    for env in ENVELOPES:
        item = model.get(env)
        current = state_envs.get(env)
        rates.append(float(item.daily_rate) if item else 0.0)
        mult = np.asarray(item.weekday_mult if item else [1.0] * 7, dtype=float)
        weekday.append(np.pad(mult[:7], (0, max(0, 7 - mult.size)), constant_values=1.0))
        mu.append(float(item.amount_mu) if item else float(np.log(10000)))
        sigma.append(float(item.amount_sigma) if item else 0.6)
        card_share.append(float(np.clip(item.card_share, 0.0, 1.0)) if item else 0.0)
        boost.append(float(item.payday_boost) if item else 1.0)
        elasticity.append(float(item.elasticity) if item else 1.0)
        budgets.append(max(1, int(current.budget)) if current else 1)
        spent.append(int(current.spent) if current else 0)
    return (
        np.asarray(rates), np.asarray(weekday), np.asarray(mu), np.asarray(sigma),
        np.asarray(card_share), np.asarray(boost), np.asarray(elasticity),
        np.asarray(budgets, dtype=np.int64), np.asarray(spent, dtype=np.int64),
    )


def _add_random_spend(
    rng: np.random.Generator,
    counts: np.ndarray,
    amount_mu: float,
    amount_sigma: float,
    card_share: float,
    env_idx: int,
    cash: np.ndarray,
    liquidity: np.ndarray,
    unbilled: np.ndarray,
    card_liability: np.ndarray,
    month_spent: np.ndarray,
    envelope_spend: np.ndarray,
) -> None:
    total = int(counts.sum())
    if total == 0:
        return
    path_ids = np.repeat(np.arange(counts.size), counts.astype(np.int64))
    # Card approvals arrive as a weekly lump, so retain extra balance
    # dispersion for card-heavy behavior before the next withdrawal cycle.
    effective_sigma = min(1.5, amount_sigma * (1.0 + 0.5 * float(np.clip(card_share, 0.0, 1.0))))
    amounts = np.maximum(100, np.rint(rng.lognormal(amount_mu, effective_sigma, total) / 100) * 100).astype(np.int64)
    card_mask = (
        rng.random(total) < float(np.clip(card_share, 0.0, 1.0))
        if unbilled.shape[1]
        else np.zeros(total, dtype=bool)
    )
    card_ids = (
        rng.integers(0, unbilled.shape[1], size=int(card_mask.sum()))
        if card_mask.any()
        else np.empty(0, dtype=np.int64)
    )
    card_offset = 0
    for path, amount, is_card in zip(path_ids, amounts, card_mask):
        path = int(path)
        amount = int(amount)
        if not is_card:
            if cash[path] < amount:
                continue
            cash[path] -= amount
            liquidity[path] -= amount
        else:
            unbilled[path, int(card_ids[card_offset])] += amount
            card_liability[path] += amount
            card_offset += 1
        month_spent[path, env_idx] += amount
        envelope_spend[path, env_idx] += amount


def _pay_cards(
    day: date,
    cards: list[CardState],
    pending: list[list[list[_Bill]]],
    cash: np.ndarray,
    liquidity: np.ndarray,
    card_liability: np.ndarray,
    card_shortfall: np.ndarray,
) -> None:
    # ponytail: pending bills remain small Python lists; vectorize only if card/queue scale grows.
    for card_idx, card in enumerate(cards):
        withdrawal_day = day.weekday() == int(card.withdrawal_weekday)
        for path, path_bills in enumerate(pending):
            bills = path_bills[card_idx]
            if not bills:
                continue
            remaining: list[_Bill] = []
            for bill in sorted(bills, key=lambda item: (item.issued, item.due, item.amount)):
                age = (day - bill.issued).days
                eligible = day >= bill.issued and day >= bill.due and (withdrawal_day or age >= 7)
                if not eligible:
                    remaining.append(bill)
                elif cash[path] - bill.amount < 0:
                    card_shortfall[path] = True
                    bill.failed = True
                    # A failed withdrawal does not change the account balance;
                    # the bill remains pending for a later retry.
                    remaining.append(bill)
                else:
                    cash[path] -= bill.amount
                    if not bill.liability_recorded:
                        liquidity[path] -= bill.amount
                        card_liability[path] -= bill.amount
                        bill.liability_recorded = True
            bills[:] = remaining


def _apply_injections(
    day: date,
    injections: dict[date, list[VirtualSpend]],
    cash: np.ndarray,
    liquidity: np.ndarray,
    unbilled: np.ndarray,
    card_liability: np.ndarray,
    month_spent: np.ndarray,
    envelope_spend: np.ndarray,
    env_index: dict[Envelope, int],
) -> None:
    for injection in injections.get(day, []):
        amount = int(injection.amount)
        if amount < 0:
            raise ValueError("VirtualSpend.amount must be non-negative")
        env_idx = env_index[injection.envelope]
        month_spent[:, env_idx] += amount
        envelope_spend[:, env_idx] += amount
        if injection.via_card and unbilled.shape[1]:
            unbilled[:, 0] += amount
            card_liability += amount
        else:
            cash -= amount
            liquidity -= amount


def simulate(
    state: State,
    behavior: Behavior,
    horizon_days: int = 30,
    n_paths: int = 1000,
    seed: int = 42,
    injections: list[VirtualSpend] | None = None,
) -> SimulationResult:
    """§7.3 하루 전이 순서대로 n_paths 개 잔액 경로를 계산한다."""
    if horizon_days < 0:
        raise ValueError("horizon_days must be non-negative")
    if n_paths <= 0:
        raise ValueError("n_paths must be positive")
    rng = np.random.default_rng(seed)
    dates = [state.as_of + timedelta(days=i) for i in range(horizon_days + 1)]
    cash = np.full(n_paths, int(state.liquidity), dtype=np.int64)
    # cash and liquidity are the primary account balance; failed debits stay pending.
    liquidity = cash.copy()
    card_shortfall = np.zeros(n_paths, dtype=bool)
    envelope_spend = np.zeros((n_paths, len(ENVELOPES)), dtype=np.int64)
    rates, weekday, amount_mu, amount_sigma, card_share, boost, elasticity, budgets, initial_spent = _model_arrays(state, behavior)
    month_spent = np.broadcast_to(initial_spent, (n_paths, len(ENVELOPES))).copy()
    unbilled = np.tile(np.asarray([[max(0, int(c.unbilled)) for c in state.cards]], dtype=np.int64), (n_paths, 1))
    card_liability = unbilled.sum(axis=1)
    pending: list[list[list[_Bill]]] = [[[] for _ in state.cards] for _ in range(n_paths)]
    for card_idx, card in enumerate(state.cards):
        for bill in card.issued_unpaid:
            card_liability += int(bill.amount)
            for path in pending:
                path[card_idx].append(
                    _Bill(int(bill.amount), _bill_issue_day(bill.due), bill.due, bill.due <= state.as_of)
                )
    schedules = _schedules(state)
    env_index = {env: i for i, env in enumerate(ENVELOPES)}
    injection_map: dict[date, list[VirtualSpend]] = {}
    for injection in injections or []:
        if injection.amount < 0:
            raise ValueError("VirtualSpend.amount must be non-negative")
        injection_map.setdefault(injection.on, []).append(injection)
    _apply_injections(
        state.as_of, injection_map, cash, liquidity, unbilled, card_liability,
        month_spent, envelope_spend, env_index,
    )
    balances = np.empty((n_paths, horizon_days + 1), dtype=np.int64)
    economic_balances = np.empty((n_paths, horizon_days + 1), dtype=np.int64)
    balances[:, 0] = liquidity
    economic_balances[:, 0] = liquidity - card_liability
    any_shortfall = liquidity < 0
    first_shortfall = np.where(any_shortfall, 0, -1).astype(np.int64)
    last_income = max((d for d in behavior.income_dates if d <= state.as_of), default=None)
    irregular_income_dates = _irregular_income_schedule(state, behavior, horizon_days) if behavior.irregular_income else set()
    next_income = state.next_income_date
    while not behavior.irregular_income and next_income is not None and next_income <= state.as_of:
        next_income = _next_income(next_income, behavior)
    income_amount = max(0, int(state.expected_income or behavior.income_amount_median))
    for index, day in enumerate(dates[1:], start=1):
        if day.day == 1:
            month_spent.fill(0)
        income_today = day in irregular_income_dates if behavior.irregular_income else day == next_income
        if income_today:
            if income_amount:
                if behavior.irregular_income:
                    income = np.rint(rng.lognormal(np.log(max(1, income_amount)), 0.4, n_paths)).astype(np.int64)
                else:
                    income = income_amount
                cash += income
                liquidity += income
            last_income = day
            if not behavior.irregular_income:
                next_income = _next_income(day, behavior)
        for due, amount in schedules.account:
            if due == day:
                accepted = cash >= amount
                cash[accepted] -= amount
                liquidity[accepted] -= amount
        for due, card_idx, amount in schedules.card_fixed:
            if due == day and card_idx < unbilled.shape[1]:
                unbilled[:, card_idx] += amount
                card_liability += amount
        for due, card_idx, amount in schedules.card_bill:
            if due == day and card_idx < len(state.cards):
                card_liability += amount
                for path in pending:
                    path[card_idx].append(_Bill(amount, _bill_issue_day(due), due))
        if day.weekday() == 0:
            for path in range(n_paths):
                for card_idx in range(unbilled.shape[1]):
                    amount = int(unbilled[path, card_idx])
                    if amount > 0:
                        due = _next_withdrawal(day, int(state.cards[card_idx].withdrawal_weekday))
                        pending[path][card_idx].append(_Bill(amount, day, due))
                    unbilled[path, card_idx] = 0
        _pay_cards(day, state.cards, pending, cash, liquidity, card_liability, card_shortfall)
        payday = bool(last_income is not None and 0 <= (day - last_income).days < 7)
        for env_idx in range(len(ENVELOPES)):
            ratio = 1.0 - month_spent[:, env_idx] / budgets[env_idx]
            gate = np.where(ratio < 0.2, elasticity[env_idx], 1.0)
            lam = rates[env_idx] * weekday[env_idx, day.weekday()] * (boost[env_idx] if payday else 1.0) * gate
            _add_random_spend(
                rng, rng.poisson(np.maximum(0.0, lam), n_paths), amount_mu[env_idx], amount_sigma[env_idx],
                card_share[env_idx], env_idx, cash, liquidity, unbilled, card_liability,
                month_spent, envelope_spend,
            )
        shock = rng.random(n_paths) < float(np.clip(behavior.shock_daily_prob, 0.0, 1.0))
        if shock.any():
            _add_random_spend(
                rng, shock.astype(np.int64), behavior.shock_amount_mu, behavior.shock_amount_sigma,
                float(np.mean(card_share)) if len(state.cards) else 0.0, env_index[Envelope.ETC],
                cash, liquidity, unbilled, card_liability, month_spent, envelope_spend,
            )
        _apply_injections(
            day, injection_map, cash, liquidity, unbilled, card_liability,
            month_spent, envelope_spend, env_index,
        )
        balances[:, index] = liquidity
        economic_balances[:, index] = liquidity - card_liability
        newly_short = (liquidity < 0) & (first_shortfall < 0)
        first_shortfall[newly_short] = index
        any_shortfall |= liquidity < 0
    return SimulationResult(
        dates, balances, economic_balances, card_shortfall, any_shortfall,
        first_shortfall, envelope_spend,
    )


def forecast(state: State, behavior: Behavior, horizon_days: int = 30, n_paths: int = 1000, seed: int = 42) -> PathStats:
    """§7.4 FDT-SIM-01 중앙값 궤적과 P10/P90 밴드를 반환한다."""
    return simulate(state, behavior, horizon_days, n_paths, seed).stats()


def what_if(state: State, behavior: Behavior, injections: list[VirtualSpend], horizon_days: int = 30, n_paths: int = 1000, seed: int = 42) -> WhatIfResult:
    """§7.4 FDT-SIM-02 동일 시드 기본/분기 비교를 반환한다."""
    if horizon_days < 0:
        raise ValueError("horizon_days must be non-negative")
    max_offset = max((injection.on - state.as_of).days for injection in injections) if injections else 0
    horizon_days = max(horizon_days, max(0, max_offset))
    base = simulate(state, behavior, horizon_days, n_paths, seed).stats(economic=True)
    branch = simulate(state, behavior, horizon_days, n_paths, seed, injections).stats(economic=True)
    delta_shortfall = branch.shortfall_prob - base.shortfall_prob
    if branch.card_shortfall_prob >= 0.5 or branch.min_balance < 0:
        verdict = "DANGER"
    elif delta_shortfall >= 0.15 or branch.min_balance < base.min_balance * 0.5:
        verdict = "CAUTION"
    else:
        verdict = "OK"
    return WhatIfResult(
        base=base,
        branch=branch,
        delta_min_balance=branch.min_balance - base.min_balance,
        delta_shortfall_prob=delta_shortfall,
        delta_end_balance=branch.median[-1] - base.median[-1],
        verdict=verdict,
    )


def risk(state: State, behavior: Behavior, horizon_days: int = 30, n_paths: int = 1000, seed: int = 42) -> RiskResult:
    """§7.4 FDT-SIM-03 부족 확률·위험 점수·예상 부족액을 반환한다."""
    result = simulate(state, behavior, horizon_days, n_paths, seed)
    stats = result.stats()
    score = int(np.rint(100 * max(stats.card_shortfall_prob, 0.6 * stats.shortfall_prob)))
    score = max(0, min(100, score))
    level = "SAFE" if score < 20 else "WARNING" if score < 50 else "DANGER"
    minima = np.min(result.balances, axis=1)
    shortfalls = minima[result.any_shortfall]
    expected = int(np.rint(np.mean(np.abs(shortfalls)))) if shortfalls.size else 0
    return RiskResult(
        horizon_days=horizon_days,
        n_paths=n_paths,
        shortfall_prob=stats.shortfall_prob,
        card_shortfall_prob=stats.card_shortfall_prob,
        risk_score=score,
        level=level,
        worst_day=stats.first_shortfall_date_median,
        expected_shortfall=expected,
    )
