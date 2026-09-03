"""FDT 도메인 스키마: 정규화 원장, State(t), Behavior, 시뮬레이션 결과."""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel

from fdt.taxonomy.categories import Envelope, Flow


class Source(StrEnum):
    SEED = "SEED"
    LIVE = "LIVE"


class Instrument(StrEnum):
    ACCOUNT = "ACCOUNT"
    CARD = "CARD"


class LedgerTx(BaseModel):
    """정규화 원장 한 건. 모든 소비는 정확히 한 봉투에 정확히 한 번 (NFR-BGT-01)."""

    tx_id: str
    source: Source
    occurred_at: datetime
    instrument: Instrument
    instrument_no: str              # accountNo 또는 cardNo
    amount: int                     # 원. 지출은 음수, 수입은 양수
    merchant: str = ""
    fin_category_id: str = ""
    fin_category_name: str = ""
    summary: str = ""
    flow: Flow
    subcategory: str | None = None
    envelope: Envelope | None = None
    confidence: float = 1.0         # 분류 확신도. 1.0 = 매핑 테이블 적중
    fixed_kind: str | None = None   # 고정비 종류(월세/통신/구독/보험/대출이자)
    counterpart_account: str = ""

    @property
    def day(self) -> date:
        return self.occurred_at.date()


class FixedCommitment(BaseModel):
    """약정 지출 큐 항목."""

    kind: str                       # 월세, 통신, 구독, 보험, 대출이자, 카드대금
    name: str
    amount: int
    due: date
    account_no: str
    certainty: float = 1.0          # 카드대금 예정액처럼 추정치는 <1
    card_no: str | None = None      # 카드 고정비·청구의 원 카드 식별자


class EnvelopeState(BaseModel):
    envelope: Envelope
    budget: int
    spent: int
    remaining: int
    cycle_start: date
    cycle_end: date


class CardState(BaseModel):
    card_no: str
    withdrawal_account_no: str
    withdrawal_weekday: int         # 0=월 .. 6=일 (금융망 withdrawalDate 1~7 -> 0~6)
    unbilled: int                   # 이번 주(월~오늘) 승인 누적, 다음 월요일 청구
    issued_unpaid: list[FixedCommitment]  # 발행됐지만 미결제 청구서


class State(BaseModel):
    """State(t): 시뮬레이션 기준점 스냅샷."""

    as_of: date
    user_name: str
    liquidity: int                  # 자유 입출금 잔액 합
    emergency_fund: int             # 비상금 계좌 잔액
    account_balances: dict[str, int]
    primary_account_no: str
    committed: list[FixedCommitment]
    envelopes: list[EnvelopeState]
    cards: list[CardState]
    next_income_date: date | None
    expected_income: int
    spend_7d_avg: float
    spend_90d_avg: float
    acceleration: float             # 7d / 90d
    unconfirmed_count: int
    health_score: float = 0.0       # 0~100
    health_level: str = "SAFE"      # SAFE / WARNING / DANGER

    def envelope(self, env: Envelope) -> EnvelopeState:
        return next(e for e in self.envelopes if e.envelope == env)


class EnvelopeBehavior(BaseModel):
    envelope: Envelope
    daily_rate: float               # 하루 평균 건수
    weekday_mult: list[float]       # 7개, 평균 1.0
    amount_mu: float                # 로그정규 mu
    amount_sigma: float
    card_share: float               # 카드 결제 비율
    payday_boost: float             # 급여 후 7일 배수
    elasticity: float               # 잔여 예산 < 20% 일 때 지출 배수 (충동 탄력도)


class Behavior(BaseModel):
    """개인화 행동 모델. 원장 이력에서 추정."""

    estimated_from: date
    estimated_to: date
    n_days: int
    envelopes: list[EnvelopeBehavior]
    income_dates: list[date]
    income_amount_median: int
    irregular_income: bool
    shock_daily_prob: float         # 돌발 대형 지출 확률/일
    shock_amount_mu: float
    shock_amount_sigma: float


class VirtualSpend(BaseModel):
    """What-if 가상 지출 (FDT-SIM-02)."""

    amount: int
    envelope: Envelope
    on: date
    via_card: bool = True
    label: str = ""


class PathStats(BaseModel):
    dates: list[date]
    median: list[int]
    p10: list[int]
    p90: list[int]
    mean: list[int]
    min_balance: int
    min_balance_date: date
    shortfall_prob: float           # 어느 날이든 잔액 < 0
    card_shortfall_prob: float      # 카드 출금일 잔액 부족
    first_shortfall_date_median: date | None


class WhatIfResult(BaseModel):
    base: PathStats
    branch: PathStats
    delta_min_balance: int
    delta_shortfall_prob: float
    delta_end_balance: int
    verdict: str                    # OK / CAUTION / DANGER


class RiskResult(BaseModel):
    horizon_days: int
    n_paths: int
    shortfall_prob: float
    card_shortfall_prob: float
    risk_score: int                 # 0~100
    level: str
    worst_day: date | None
    expected_shortfall: int         # 부족 발생 경로의 평균 부족액


class WeeklyCap(BaseModel):
    week_start: date
    week_end: date
    caps: dict[str, int]            # envelope -> 원
    total: int


class GoalPlan(BaseModel):
    target_amount: int
    target_date: date
    feasible: bool
    required_total_discretionary: int
    baseline_discretionary: int
    reduction_ratio: float
    weekly: list[WeeklyCap]
    note: str


class SafeToSpend(BaseModel):
    as_of: date
    liquidity: int
    committed_until_income: int
    days_until_income: int
    raw_daily: int
    acceleration: float
    safe_today: int
    note: str


class RebalanceMove(BaseModel):
    from_envelope: Envelope
    to_envelope: Envelope
    amount: int


class RebalancePlan(BaseModel):
    trigger: Envelope | None
    shortfall: int
    moves: list[RebalanceMove]
    feasible: bool
    note: str


class Alert(BaseModel):
    kind: str                        # ACCELERATION / CONCERNING_PAYMENT
    severity: str                    # INFO / WARNING / DANGER
    envelope: Envelope | None = None
    tx_id: str | None = None
    amount: int | None = None
    threshold: int | None = None
    ratio: float | None = None
    message: str


class RoomProjection(BaseModel):
    """FDT-INT-02: 트윈 상태 -> 방/캐릭터 파라미터."""

    level: str
    weather: str                     # 맑음 / 흐림 / 비
    avatar_mood: str
    avatar_action: str
    board_progress: dict[str, float]
    seizure_sticker: bool
    coin_eligible_today: bool
