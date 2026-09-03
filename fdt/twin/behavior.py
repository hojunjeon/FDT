"""개인화 행동 모델 추정. 설계: docs/03_FDT_설계.md §7.2

원장 이력(as_of 이하, 최근 90일)에서 봉투별 발생률·요일 배수·금액 분포·카드 비율·급여 효과·탄력도를 추정한다.
관측 가능한 원장만 사용하고 생성기 설정은 읽지 않는다.
"""
from __future__ import annotations

import calendar
import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import fmean, median, stdev
from typing import Iterable

from fdt.schemas.domain import Behavior, EnvelopeBehavior, Instrument, LedgerTx
from fdt.taxonomy.categories import ENVELOPES, Envelope, Flow

_MIN_WINDOW_DAYS = 28
_ALPHA = 2.0
_DEFAULT_AMOUNT_MU = math.log(10_000)
_DEFAULT_AMOUNT_SIGMA = 0.6


def _window_start(txs: list[LedgerTx], as_of: date, window_days: int) -> tuple[date, int]:
    """§7.2 관측 창의 시작일과 실제 일수를 계산한다."""
    requested_days = max(_MIN_WINDOW_DAYS, int(window_days))
    requested_start = as_of - timedelta(days=requested_days - 1)
    available = [tx.day for tx in txs if tx.day <= as_of]
    if not available:
        return as_of, 1
    start = max(requested_start, min(available))
    return start, (as_of - start).days + 1


def _in_window(tx: LedgerTx, start: date, as_of: date) -> bool:
    return start <= tx.day <= as_of


def _cancel_key(tx: LedgerTx) -> tuple[str, str, date, int]:
    return (str(tx.instrument), tx.instrument_no, tx.day, abs(int(tx.amount)))


def _effective_spends(txs: Iterable[LedgerTx], start: date, as_of: date) -> list[LedgerTx]:
    """§7.2 취소 승인과 환불 쌍을 제거한 소비 원장을 만든다."""
    candidates = [
        tx for tx in txs
        if _in_window(tx, start, as_of) and tx.flow == Flow.SPEND and tx.envelope is not None and tx.amount != 0
    ]
    refunds = Counter(
        _cancel_key(tx) for tx in txs
        if _in_window(tx, start, as_of)
        and tx.flow == Flow.REFUND
        and tx.instrument == Instrument.CARD
        and tx.amount != 0
    )
    spends: list[LedgerTx] = []
    for tx in candidates:
        key = _cancel_key(tx)
        if tx.instrument == Instrument.CARD and refunds[key]:
            refunds[key] -= 1
            continue
        spends.append(tx)
    return spends


def _all_effective_spends(txs: list[LedgerTx], as_of: date) -> list[LedgerTx]:
    """§7.2 탄력도 계산용으로 기준일 이하의 유효 소비를 만든다."""
    earliest = min((tx.day for tx in txs if tx.day <= as_of), default=as_of)
    return _effective_spends(txs, earliest, as_of)


def _amount_params(amounts: list[int]) -> tuple[float, float]:
    """§7.2.2 양수 금액 목록에서 로그정규 파라미터를 추정한다."""
    if len(amounts) < 5:
        return _DEFAULT_AMOUNT_MU, _DEFAULT_AMOUNT_SIGMA
    logs = [math.log(amount) for amount in amounts if amount > 0]
    if len(logs) < 5:
        return _DEFAULT_AMOUNT_MU, _DEFAULT_AMOUNT_SIGMA
    sigma = stdev(logs) if len(logs) > 1 else 0.0
    return fmean(logs), min(1.5, max(0.2, sigma))


def _as_envelope(value: Envelope | str) -> Envelope:
    return value if isinstance(value, Envelope) else Envelope(value)


def _fallback_budgets(spends: list[LedgerTx], start: date, as_of: date) -> dict[Envelope, int]:
    """§7.2.5 공개 예산 함수가 아직 준비되지 않은 동안의 최소 관측 fallback."""
    days = max(1, (as_of - start).days + 1)
    totals: dict[Envelope, int] = {env: 0 for env in ENVELOPES}
    for tx in spends:
        totals[tx.envelope] += abs(int(tx.amount))
    return {
        env: max(10_000, math.ceil(total * 30 / days / 10_000) * 10_000)
        for env, total in totals.items()
    }


def _resolve_budgets(
    txs: list[LedgerTx],
    as_of: date,
    spends: list[LedgerTx],
    start: date,
    budgets: dict | None,
) -> dict[Envelope, int]:
    if budgets is not None:
        return {_as_envelope(env): int(amount) for env, amount in budgets.items()}
    # Import at call time because state.build_state calls estimate_behavior.
    from fdt.twin.state import propose_budgets

    proposed = propose_budgets(txs, as_of)
    if proposed is not None:
        return {_as_envelope(env): int(amount) for env, amount in proposed.items()}
    # ponytail: linear observed-spend fallback until State's budget proposal is available.
    return _fallback_budgets(spends, start, as_of)


def _income_events(txs: Iterable[LedgerTx], as_of: date) -> tuple[list[date], list[int]]:
    by_day: defaultdict[date, int] = defaultdict(int)
    for tx in txs:
        if tx.day <= as_of and tx.flow == Flow.INCOME and tx.confidence >= 0.5 and tx.amount > 0:
            by_day[tx.day] += int(tx.amount)
    dates = sorted(by_day)
    return dates, [by_day[day] for day in dates]


def _next_day_of_month(as_of: date, day_of_month: int) -> date:
    candidate = as_of + timedelta(days=1)
    for _ in range(63):
        last_day = calendar.monthrange(candidate.year, candidate.month)[1]
        if candidate.day == min(day_of_month, last_day):
            return candidate
        candidate += timedelta(days=1)
    return candidate


def _median_int(values: list[int]) -> int:
    return int(round(float(median(values))))


def _population_stdev(values: list[float]) -> float:
    if not values:
        return 0.0
    average = fmean(values)
    return math.sqrt(fmean((value - average) ** 2 for value in values))


def _payday_boost(spends: list[LedgerTx], start: date, as_of: date, income_dates: list[date]) -> float:
    """§7.2.4 급여 후 7일 소비 배수를 계산한다."""
    if not income_dates:
        return 1.0
    daily_total: defaultdict[date, int] = defaultdict(int)
    for tx in spends:
        daily_total[tx.day] += abs(int(tx.amount))
    after_days = []
    other_days = []
    day = start
    while day <= as_of:
        after = any(0 <= (day - income_day).days < 7 for income_day in income_dates)
        (after_days if after else other_days).append(daily_total[day])
        day += timedelta(days=1)
    if len(after_days) < 14 or not other_days:
        return 1.0
    baseline = fmean(other_days)
    if baseline <= 0:
        return 1.0
    return min(2.0, max(0.7, fmean(after_days) / baseline))


def _elasticity(
    env: Envelope,
    all_spends: list[LedgerTx],
    start: date,
    as_of: date,
    budget: int,
) -> float:
    """§7.2.5 월 누적 잔여율에 따른 봉투별 탄력도를 계산한다."""
    daily: defaultdict[date, int] = defaultdict(int)
    for tx in all_spends:
        if tx.envelope != env:
            continue
        amount = abs(int(tx.amount))
        daily[tx.day] += amount

    prior_by_month: defaultdict[tuple[int, int], int] = defaultdict(int)
    for tx in all_spends:
        if tx.envelope == env and tx.day < start and tx.day <= as_of:
            prior_by_month[(tx.day.year, tx.day.month)] += abs(int(tx.amount))

    low_days: list[int] = []
    low_values: list[int] = []
    normal_values: list[int] = []
    prior = 0
    previous_month: tuple[int, int] | None = None
    day = start
    safe_budget = max(1, budget)
    while day <= as_of:
        month = (day.year, day.month)
        if month != previous_month:
            prior = prior_by_month[month]
            previous_month = month
        amount = daily[day]
        if 1 - prior / safe_budget < 0.2:
            low_days.append(day.toordinal())
            low_values.append(amount)
        else:
            normal_values.append(amount)
        prior += amount
        day += timedelta(days=1)

    if len(low_days) < 5 or not normal_values:
        return 1.0
    baseline = fmean(normal_values)
    if baseline <= 0:
        return 1.0
    return min(2.0, max(0.5, fmean(low_values) / baseline))


def _shock_params(
    spends: list[LedgerTx],
    amount_mu: dict[Envelope, float],
    n_days: int,
) -> tuple[float, float, float]:
    """§7.2.7 큰 소비의 일 확률과 로그정규 파라미터를 계산한다."""
    shocks: list[int] = []
    for tx in spends:
        amount = abs(int(tx.amount))
        threshold = max(50_000.0, 5 * math.exp(amount_mu[tx.envelope]))
        if amount >= threshold:
            shocks.append(amount)
    if not shocks:
        return 0.01, math.log(100_000), 0.6
    logs = [math.log(amount) for amount in shocks]
    sigma = _population_stdev(logs)
    return len(shocks) / max(1, n_days), fmean(logs), max(0.3, sigma)


def estimate_behavior(txs: list[LedgerTx], as_of: date, window_days: int = 90, budgets: dict | None = None) -> Behavior:
    """§7.2 의 공식대로 추정. 데이터 부족 시 문서에 명시된 기본값·축소(shrinkage) 적용."""
    start, n_days = _window_start(txs, as_of, window_days)
    window_txs = [tx for tx in txs if _in_window(tx, start, as_of)]
    spends = _effective_spends(window_txs, start, as_of)
    all_spends = _all_effective_spends(txs, as_of)

    income_dates, income_median, irregular, _ = detect_income_schedule(window_txs, as_of)
    common_amounts = [abs(int(tx.amount)) for tx in spends]
    pooled_mu, pooled_sigma = _amount_params(common_amounts)
    resolved_budgets = _resolve_budgets(txs, as_of, spends, start, budgets)
    total_spends = len(spends)
    card_spends = sum(tx.instrument == Instrument.CARD for tx in spends)
    overall_card_share = card_spends / total_spends if total_spends else 0.5

    by_env: dict[Envelope, list[LedgerTx]] = {env: [] for env in ENVELOPES}
    for tx in spends:
        by_env[tx.envelope].append(tx)
    payday_boost = _payday_boost(spends, start, as_of, income_dates)
    amount_mu: dict[Envelope, float] = {}
    amount_sigma: dict[Envelope, float] = {}
    for env in ENVELOPES:
        amounts = [abs(int(tx.amount)) for tx in by_env[env]]
        if len(amounts) >= 5:
            amount_mu[env], amount_sigma[env] = _amount_params(amounts)
        else:
            amount_mu[env], amount_sigma[env] = pooled_mu, pooled_sigma

    envelope_behaviors: list[EnvelopeBehavior] = []
    for env in ENVELOPES:
        env_txs = by_env[env]
        n_env = len(env_txs)
        daily_rate = n_env / n_days
        if n_env < 10:
            weekday_mult = [1.0] * 7
        else:
            counts = [0] * 7
            days_per_weekday = [0] * 7
            day = start
            while day <= as_of:
                days_per_weekday[day.weekday()] += 1
                day += timedelta(days=1)
            for tx in env_txs:
                counts[tx.day.weekday()] += 1
            raw = [
                (counts[weekday] + _ALPHA) /
                (daily_rate * days_per_weekday[weekday] + _ALPHA)
                for weekday in range(7)
            ]
            raw_mean = fmean(raw)
            weekday_mult = [value / raw_mean for value in raw]
        card_share = (
            sum(tx.instrument == Instrument.CARD for tx in env_txs) / n_env
            if n_env else overall_card_share
        )
        envelope_behaviors.append(EnvelopeBehavior(
            envelope=env,
            daily_rate=float(daily_rate),
            weekday_mult=[float(value) for value in weekday_mult],
            amount_mu=float(amount_mu[env]),
            amount_sigma=float(amount_sigma[env]),
            card_share=float(card_share),
            payday_boost=float(payday_boost),
            elasticity=float(_elasticity(
                env, all_spends, start, as_of, resolved_budgets.get(env, 10_000)
            )),
        ))

    shock_prob, shock_mu, shock_sigma = _shock_params(spends, amount_mu, n_days)
    return Behavior(
        estimated_from=start,
        estimated_to=as_of,
        n_days=n_days,
        envelopes=envelope_behaviors,
        income_dates=income_dates,
        income_amount_median=income_median,
        irregular_income=irregular,
        shock_daily_prob=float(shock_prob),
        shock_amount_mu=float(shock_mu),
        shock_amount_sigma=float(shock_sigma),
    )


def detect_income_schedule(txs: list[LedgerTx], as_of: date) -> tuple[list[date], int, bool, date | None]:
    """§7.2.6 수입 일자 목록, 중앙값 금액, 불규칙 여부, 다음 예상 수입일."""
    dates, amounts = _income_events(txs, as_of)
    if len(dates) <= 1:
        return dates, 0, True, None

    gaps = [(right - left).days for left, right in zip(dates, dates[1:])]
    mean_gap = fmean(gaps)
    cv = (_population_stdev([float(gap) for gap in gaps]) / mean_gap) if mean_gap else 0.0
    dom_counts = Counter(day.day for day in dates)
    mode_dom, mode_count = min(
        dom_counts.items(), key=lambda item: (-item[1], item[0])
    )
    p_dom = mode_count / len(dates)
    expected = _median_int(amounts)
    if cv <= 0.25 and p_dom >= 0.6:
        return dates, expected, False, _next_day_of_month(as_of, mode_dom)

    median_gap = max(1, int(round(float(median(gaps)))))
    next_date = dates[-1] + timedelta(days=median_gap)
    if next_date <= as_of:
        # The last observed interval is right-censored at as_of.  Leave one
        # extra day before the first projected irregular payment instead of
        # treating the boundary day as observed cadence.
        next_date = as_of + timedelta(days=2)
    return dates, expected, True, next_date
