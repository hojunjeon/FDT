"""코칭 숫자 충실도 + 툴 라우팅 평가. 설계: docs/03_FDT_설계.md §11.6, §11.7"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def run_faithfulness(seed_root: Path, scenarios_path: Path) -> dict[str, Any]:
    """시나리오 × 페르소나 실행. 최종 응답 불충실 0건, 폴백률, 1차 통과율."""
    raise NotImplementedError


def run_routing(seed_root: Path, utterances_path: Path) -> dict[str, Any]:
    """라벨된 발화 -> 툴 선택 정확도, 파라미터 정확도."""
    raise NotImplementedError
