"""에이전트 툴 정의와 실행기. 설계: docs/03_FDT_설계.md §8.2

툴은 전부 트윈 코어의 결정론 함수를 감싼다. LLM 은 툴 이름과 파라미터만 고른다 (FDT-INP-02).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fdt.schemas.domain import Behavior, LedgerTx, State
from fdt.schemas.finapi import FinSnapshot


@dataclass
class TwinContext:
    snap: FinSnapshot
    txs: list[LedgerTx]
    state: State
    behavior: Behavior
    seed: int = 42


TOOL_SPECS: list[dict[str, Any]] = []   # §8.2 표의 JSON Schema 를 그대로 옮긴다


def execute_tool(name: str, args: dict[str, Any], ctx: TwinContext) -> dict[str, Any]:
    """툴 이름 -> 트윈 함수 호출 -> 결과를 JSON 직렬화 가능한 dict 로. 알 수 없는 툴은 ValueError."""
    raise NotImplementedError
