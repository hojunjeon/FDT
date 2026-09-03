"""트윈 상태 -> 방·캐릭터 파라미터 매핑 (FDT-INT-02). 설계: docs/03_FDT_설계.md §7.7"""
from __future__ import annotations

from fdt.schemas.domain import Alert, RoomProjection, State


def project_room(state: State, alerts: list[Alert]) -> RoomProjection:
    raise NotImplementedError
