"""목표 역산 (FDT-SIM-04). 설계: docs/03_FDT_설계.md §7.5"""
from __future__ import annotations

from datetime import date

from fdt.schemas.domain import Behavior, GoalPlan, State


def plan_goal(state: State, behavior: Behavior, target_amount: int, target_date: date, seed: int = 42) -> GoalPlan:
    """목표 잔액을 고정하고 역산해 주차별·봉투별 지출 상한을 낸다. 필수 봉투는 기준선의 80% 이상 보장."""
    raise NotImplementedError
