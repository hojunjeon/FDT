"""트윈 상태 -> 방·캐릭터 파라미터 매핑 (FDT-INT-02). 설계: docs/03_FDT_설계.md §7.7"""
from __future__ import annotations

from fdt.schemas.domain import Alert, RoomProjection, State
from fdt.taxonomy.categories import ENVELOPES, Envelope


def project_room(state: State, alerts: list[Alert]) -> RoomProjection:
    """§7.7 State와 알림을 대시보드용 방·캐릭터 파라미터로 변환한다."""
    level = state.health_level.upper()
    weather = {"SAFE": "맑음", "WARNING": "흐림", "DANGER": "비"}.get(level, "흐림")
    mood = {"SAFE": "만족", "WARNING": "걱정", "DANGER": "울상"}.get(level, "걱정")
    if any(alert.severity == "DANGER" for alert in alerts):
        mood = "울상"

    progress: dict[str, float] = {}
    ratios: dict[Envelope, float] = {}
    for item in state.envelopes:
        ratio = item.spent / item.budget if item.budget > 0 else (1.0 if item.spent > 0 else 0.0)
        ratios[item.envelope] = ratio
        progress[item.envelope.value] = round(ratio, 3)

    overrun = [env for env in ENVELOPES if ratios.get(env, 0.0) > 1.0]
    action_map = {
        Envelope.DINING: "포크질",
        Envelope.TRANSPORT: "택시타기",
        Envelope.HEALTH: "약봉투",
        Envelope.LEISURE: "게임패드",
        Envelope.SHOPPING: "쇼핑백",
        Envelope.GROCERY: "장바구니",
        Envelope.ETC: "서류",
    }
    action = action_map[max(overrun, key=lambda env: ratios[env])] if overrun else "휴식"
    return RoomProjection(
        level=level,
        weather=weather,
        avatar_mood=mood,
        avatar_action=action,
        board_progress=progress,
        seizure_sticker=sum(item.spent for item in state.envelopes)
        > sum(item.budget for item in state.envelopes),
        coin_eligible_today=state.unconfirmed_count == 0,
    )
