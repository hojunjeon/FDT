"""개인화 행동 모델 추정. 설계: docs/03_FDT_설계.md §7.2

원장 이력(as_of 이하, 최근 90일)에서 봉투별 발생률·요일 배수·금액 분포·카드 비율·급여 효과·탄력도를 추정한다.
생성기의 숨은 파라미터를 절대 읽지 않는다 (순환 논증 금지).
"""
from __future__ import annotations

from datetime import date

from fdt.schemas.domain import Behavior, LedgerTx


def estimate_behavior(txs: list[LedgerTx], as_of: date, window_days: int = 90, budgets: dict | None = None) -> Behavior:
    """§7.2 의 공식대로 추정. 데이터 부족 시 문서에 명시된 기본값·축소(shrinkage) 적용."""
    raise NotImplementedError


def detect_income_schedule(txs: list[LedgerTx], as_of: date) -> tuple[list[date], int, bool, date | None]:
    """수입 일자 목록, 중앙값 금액, 불규칙 여부, 다음 예상 수입일. §7.2.6"""
    raise NotImplementedError
