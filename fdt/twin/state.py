"""State(t) 산출. 설계: docs/03_FDT_설계.md §7.1

원장(as_of 이하 거래만) + 스냅샷 메타(계좌·카드·구독·대출) -> State.
숫자 규칙은 전부 설계 문서의 공식을 따른다. LLM 개입 없음.
"""
from __future__ import annotations

from datetime import date

from fdt.schemas.domain import Behavior, EnvelopeState, FixedCommitment, LedgerTx, State
from fdt.schemas.finapi import FinSnapshot
from fdt.taxonomy.categories import Envelope


def propose_budgets(txs: list[LedgerTx], as_of: date) -> dict[Envelope, int]:
    """FR-BGT-01 결정론적 예산 제안. 완결된 월들의 봉투 순지출 중앙값을 만원 단위로 올림. §7.1.4"""
    raise NotImplementedError


def build_committed_queue(txs: list[LedgerTx], snap: FinSnapshot, as_of: date, horizon_days: int = 35) -> list[FixedCommitment]:
    """약정 지출 큐: 반복 고정비 + 구독 + 대출이자 + 카드 청구(미청구 누적·발행 미결제). §7.1.3"""
    raise NotImplementedError


def build_state(
    txs: list[LedgerTx],
    snap: FinSnapshot,
    as_of: date,
    budgets: dict[Envelope, int] | None = None,
) -> State:
    """State(t) 조립. health_score/level 은 analytics.health() 가 채운다 (SIM-03 필요). §7.1"""
    raise NotImplementedError


def envelope_states(txs: list[LedgerTx], as_of: date, budgets: dict[Envelope, int]) -> list[EnvelopeState]:
    """이번 달(1일~as_of) 봉투별 순지출(SPEND+REFUND). §7.1.4"""
    raise NotImplementedError
