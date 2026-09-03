from __future__ import annotations

from datetime import date

from fdt.schemas.domain import Alert, EnvelopeState, State
from fdt.taxonomy.categories import ENVELOPES, Envelope
from fdt.twin.projection import project_room


def _state(level: str, spent: dict[Envelope, int] | None = None, unconfirmed: int = 0) -> State:
    spent = spent or {}
    envelopes = [
        EnvelopeState(
            envelope=env,
            budget=100_000,
            spent=spent.get(env, 0),
            remaining=100_000 - spent.get(env, 0),
            cycle_start=date(2026, 1, 1),
            cycle_end=date(2026, 1, 31),
        )
        for env in ENVELOPES
    ]
    return State(
        as_of=date(2026, 1, 15),
        user_name="테스트",
        liquidity=1_000_000,
        emergency_fund=0,
        account_balances={"p": 1_000_000},
        primary_account_no="p",
        committed=[],
        envelopes=envelopes,
        cards=[],
        next_income_date=None,
        expected_income=0,
        spend_7d_avg=0,
        spend_90d_avg=0,
        acceleration=1.0,
        unconfirmed_count=unconfirmed,
        health_level=level,
    )


def test_projection_maps_level_mood_and_danger_sticker():
    state = _state(
        "WARNING",
        {env: (125_000 if env == Envelope.DINING else 100_000) for env in ENVELOPES},
        unconfirmed=1,
    )
    alert = Alert(kind="CONCERNING_PAYMENT", severity="DANGER", envelope=Envelope.DINING, message="danger")
    result = project_room(state, [alert])

    assert result.level == "WARNING"
    assert result.weather == "흐림"
    assert result.avatar_mood == "울상"
    assert result.avatar_action == "포크질"
    assert result.board_progress[Envelope.DINING.value] == 1.25
    assert result.seizure_sticker
    assert not result.coin_eligible_today


def test_projection_covers_all_envelopes_and_rest_when_no_overrun():
    result = project_room(_state("SAFE"), [])

    assert result.weather == "맑음"
    assert result.avatar_mood == "만족"
    assert result.avatar_action == "휴식"
    assert set(result.board_progress) == {env.value for env in ENVELOPES}
    assert result.coin_eligible_today
