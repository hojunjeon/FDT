"""진단·처방 엔진 (FDT-ANL-01~03) 과 건전성 점수. 설계: docs/03_FDT_설계.md §7.6

전부 결정론적 규칙. LLM 판단 없음 (FR-AI-03 은 잔여 일수 정규화 규칙으로 대체, §3 충돌 해소 참조).
"""
from __future__ import annotations

from datetime import date

from fdt.schemas.domain import Alert, Behavior, LedgerTx, RebalancePlan, RiskResult, SafeToSpend, State


def safe_to_spend(state: State, txs_today: list[LedgerTx]) -> SafeToSpend:
    """FDT-ANL-01. §7.6.1"""
    raise NotImplementedError


def rebalance(state: State, behavior: Behavior) -> RebalancePlan:
    """FDT-ANL-02. 필수 봉투에서는 절대 빼지 않는다. §7.6.2"""
    raise NotImplementedError


def detect_alerts(state: State, behavior: Behavior, recent_txs: list[LedgerTx]) -> list[Alert]:
    """FDT-ANL-03 / FR-AI-01. 가속도 이상 + 우려 결제(잔여 일수 정규화). §7.6.3"""
    raise NotImplementedError


def health(state: State, risk_result: RiskResult) -> tuple[float, str]:
    """건전성 점수 0~100 과 SAFE/WARNING/DANGER. §7.6.4"""
    raise NotImplementedError
