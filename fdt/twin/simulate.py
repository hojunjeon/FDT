"""단일 시뮬레이터 + 회계 전이 함수. 설계: docs/03_FDT_설계.md §7.3, §7.4

SIM-01(궤적), SIM-02(What-if), SIM-03(리스크)은 모두 이 시뮬레이터 하나의 출력에서 파생된다.
- 결정론 궤적 = 경로들의 중앙값
- What-if 는 동일 시드(공통 난수)로 기본/분기 두 번 실행해 델타를 구한다
- 리스크 확률 = 부족 발생 경로 비율
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from fdt.schemas.domain import Behavior, PathStats, RiskResult, State, VirtualSpend, WhatIfResult


@dataclass
class SimulationResult:
    dates: list[date]
    balances: np.ndarray          # shape (n_paths, horizon+1), 기준 계좌(primary) 유동성. 음수 허용
    card_shortfall: np.ndarray    # shape (n_paths,), 카드 출금일 잔액 부족 발생 여부
    any_shortfall: np.ndarray     # shape (n_paths,), 어느 날이든 잔액 < 0
    first_shortfall_idx: np.ndarray  # shape (n_paths,), 없으면 -1
    envelope_spend: np.ndarray    # shape (n_paths, 7), 기간 내 봉투별 지출 합

    def stats(self) -> PathStats:
        raise NotImplementedError


def simulate(
    state: State,
    behavior: Behavior,
    horizon_days: int = 30,
    n_paths: int = 1000,
    seed: int = 42,
    injections: list[VirtualSpend] | None = None,
) -> SimulationResult:
    """§7.3 전이 규칙을 horizon 일 동안 n_paths 개 경로에 벡터화해 적용."""
    raise NotImplementedError


def forecast(state: State, behavior: Behavior, horizon_days: int = 30, n_paths: int = 1000, seed: int = 42) -> PathStats:
    """FDT-SIM-01."""
    raise NotImplementedError


def what_if(state: State, behavior: Behavior, injections: list[VirtualSpend], horizon_days: int = 30, n_paths: int = 1000, seed: int = 42) -> WhatIfResult:
    """FDT-SIM-02. 기본/분기 동일 시드."""
    raise NotImplementedError


def risk(state: State, behavior: Behavior, horizon_days: int = 30, n_paths: int = 1000, seed: int = 42) -> RiskResult:
    """FDT-SIM-03."""
    raise NotImplementedError
