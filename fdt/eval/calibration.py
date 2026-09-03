"""리스크 확률 캘리브레이션 (SIM-03). 설계: docs/03_FDT_설계.md §11.5"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def collect_pairs(seed_root: Path, step_days: int = 7, extra_seeds: int = 20) -> list[tuple[float, int]]:
    """(예측 card_shortfall_prob, 실제 30일 내 카드 부족 발생 0/1) 쌍. 롤링 as_of + 시드 교란 프로필."""
    raise NotImplementedError


def calibration_report(pairs: list[tuple[float, int]], n_bins: int = 5) -> dict[str, Any]:
    """구간별 예측 평균 vs 실제 비율, ECE, Brier, 기준율 Brier."""
    raise NotImplementedError
