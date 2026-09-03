"""홀드아웃 백테스트 (SIM-01 정확도). 설계: docs/03_FDT_설계.md §11.4"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any


def backtest_profile(seed_dir: Path, holdout_days: int = 30, n_paths: int = 1000, seed: int = 42) -> dict[str, Any]:
    """as_of = 마지막 날 - holdout_days. 예측 중앙값 vs 정답 일별 잔액. MAE/MAPE/최저점 오차/P10-P90 커버리지."""
    raise NotImplementedError


def run_all(seed_root: Path) -> dict[str, Any]:
    raise NotImplementedError
