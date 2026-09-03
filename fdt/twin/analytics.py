"""진단·처방 엔진 (FDT-ANL-01~03) 과 건전성 점수. 설계: docs/03_FDT_설계.md §7.6

전부 결정론적 규칙. LLM 판단 없음 (FR-AI-03 은 잔여 일수 정규화 규칙으로 대체, §3 충돌 해소 참조).
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from math import ceil, floor

from fdt.schemas.domain import Alert, Behavior, LedgerTx, RebalancePlan, RiskResult, SafeToSpend, State
from fdt.taxonomy.categories import FLEXIBLE_ENVELOPES, Flow, Envelope
from fdt.twin.behavior import _effective_spends


def safe_to_spend(state: State, txs_today: list[LedgerTx]) -> SafeToSpend:
    """FDT-ANL-01. §7.6.1"""
    next_income = state.next_income_date
    if next_income is None:
        days = 30
        income_boundary = state.as_of.fromordinal(state.as_of.toordinal() + days)
    else:
        days = max(1, (next_income - state.as_of).days)
        income_boundary = next_income

    committed = sum(
        c.amount for c in state.committed if state.as_of < c.due < income_boundary
    )
    available = state.liquidity - committed
    raw_daily = floor(available / days)
    factor = 1.0 / state.acceleration if state.acceleration > 1 else 1.0
    spent_today = -sum(
        tx.amount
        for tx in txs_today
        if tx.day == state.as_of and tx.flow in (Flow.SPEND, Flow.REFUND)
    )
    safe_today = max(0, floor((raw_daily * factor - spent_today) / 100) * 100)

    if available < 0:
        note = f"다음 수입 전 고정비를 감당할 수 없음. 부족 {-available:,}원."
    else:
        note = ""
    note += f" 비상금 {state.emergency_fund:,}원 별도"
    return SafeToSpend(
        as_of=state.as_of,
        liquidity=state.liquidity,
        committed_until_income=committed,
        days_until_income=days,
        raw_daily=raw_daily,
        acceleration=state.acceleration,
        safe_today=safe_today,
        note=note.strip(),
    )


def rebalance(state: State, behavior: Behavior) -> RebalancePlan:
    """FDT-ANL-02. 필수 봉투에서는 절대 빼지 않는다. §7.6.2"""
    del behavior  # 행동 모델은 공개 계약상 받지만, v1 규칙은 State만 사용한다.
    days_in_month = monthrange(state.as_of.year, state.as_of.month)[1]
    progress = state.as_of.day / days_in_month
    projected: dict[Envelope, float] = {}
    for item in state.envelopes:
        projected[item.envelope] = item.spent / max(progress, 0.15)

    trigger_item = max(
        (
            item
            for item in state.envelopes
            if projected[item.envelope] - item.budget > 0
            and item.remaining < 0.2 * item.budget
        ),
        key=lambda item: projected[item.envelope] - item.budget,
        default=None,
    )
    if trigger_item is None:
        return RebalancePlan(
            trigger=None,
            shortfall=0,
            moves=[],
            feasible=True,
            note="재배분이 필요하지 않습니다.",
        )

    trigger = trigger_item.envelope
    shortfall = max(0, int(projected[trigger] - trigger_item.budget))
    supply: dict[Envelope, float] = {
        item.envelope: max(0.0, item.budget - projected[item.envelope])
        for item in state.envelopes
        if item.envelope in FLEXIBLE_ENVELOPES and item.envelope != trigger
    }
    total_slack = sum(supply.values())
    moves = [
        {
            "from_envelope": source,
            "to_envelope": trigger,
            "amount": int(shortfall * slack / total_slack // 1000) * 1000,
        }
        for source, slack in supply.items()
        if total_slack > 0 and slack > 0
    ]
    plan_moves = [move for move in moves if move["amount"] > 0]
    feasible = total_slack >= shortfall
    if feasible:
        note = "유연 봉투에서 재배분할 수 있습니다."
    else:
        note = f"가용한 유연 봉투가 {shortfall - int(total_slack):,}원 부족합니다."
    return RebalancePlan(
        trigger=trigger,
        shortfall=shortfall,
        moves=plan_moves,
        feasible=feasible,
        note=note,
    )


def detect_alerts(state: State, behavior: Behavior, recent_txs: list[LedgerTx]) -> list[Alert]:
    """FDT-ANL-03 / FR-AI-01. 가속도 이상 + 우려 결제(잔여 일수 정규화). §7.6.3"""
    del behavior  # v1의 우려 결제 판정은 State와 원장만으로 결정한다.
    alerts: list[Alert] = []
    if state.acceleration >= 1.3 and state.spend_7d_avg >= 10_000:
        severity = "DANGER" if state.acceleration >= 1.6 else "WARNING"
        alerts.append(
            Alert(
                kind="ACCELERATION",
                severity=severity,
                ratio=state.acceleration,
                message=f"최근 7일 소비 속도가 평소보다 {state.acceleration:.2f}배입니다.",
            )
        )

    cycle_start = state.as_of.replace(day=1)
    candidates = sorted(
        (
            tx
            for tx in _effective_spends(recent_txs, cycle_start, state.as_of)
            if tx.amount < 0
        ),
        key=lambda tx: tx.occurred_at,
    )
    for index, tx in enumerate(candidates):
        envelope = tx.envelope
        envelope_state = next((item for item in state.envelopes if item.envelope == envelope), None)
        if envelope_state is None:
            continue
        amount = -tx.amount
        later_spend = sum(
            -other.amount
            for other in candidates[index:]
            if other.envelope == envelope
        )
        spent_before = envelope_state.spent - later_spend
        remaining_before = envelope_state.budget - spent_before
        days_in_cycle = monthrange(state.as_of.year, state.as_of.month)[1]
        pace_unit = envelope_state.budget / days_in_cycle
        threshold = ceil(max(0.5 * max(remaining_before, 0), 3 * pace_unit, 20_000))
        if (
            amount >= 0.5 * max(remaining_before, 0)
            and amount >= 3 * pace_unit
            and amount >= 20_000
        ):
            severity = "DANGER" if amount >= remaining_before else "WARNING"
            alerts.append(
                Alert(
                    kind="CONCERNING_PAYMENT",
                    severity=severity,
                    envelope=envelope,
                    tx_id=tx.tx_id,
                    amount=amount,
                    threshold=threshold,
                    message=f"{envelope.value}에서 {amount:,}원 결제를 확인하세요.",
                )
            )
    return alerts


def health(state: State, risk_result: RiskResult) -> tuple[float, str]:
    """건전성 점수 0~100 과 SAFE/WARNING/DANGER. §7.6.4"""
    end = state.as_of.fromordinal(state.as_of.toordinal() + 30)
    committed_30d = sum(c.amount for c in state.committed if state.as_of < c.due <= end)
    monthly_spend = state.spend_90d_avg * 30
    cov = _clip((state.liquidity - committed_30d) / max(monthly_spend, 1), 0.0, 1.0)

    days_in_month = monthrange(state.as_of.year, state.as_of.month)[1]
    progress = state.as_of.day / days_in_month
    overrun = [
        _clip(item.spent / max(item.budget, 1) - progress, 0.0, 1.0)
        for item in state.envelopes
    ]
    adh = 1.0 - (sum(overrun) / len(overrun) if overrun else 0.0)
    rsk = 1.0 - _clip(risk_result.card_shortfall_prob, 0.0, 1.0)
    score = 100.0 * (0.4 * cov + 0.3 * adh + 0.3 * rsk)
    level = "SAFE" if score >= 70 else "WARNING" if score >= 40 else "DANGER"
    return score, level


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
