"""FDT 코어 통합 스모크 테스트. 설계: docs/03_FDT_설계.md §11.3"""
from __future__ import annotations

import json
from datetime import date

import pytest

from fdt.agent.coach import template_fallback
from fdt.data.generator import generate
from fdt.ledger.ingest import ingest, load_snapshot
from fdt.twin.analytics import detect_alerts, health, rebalance, safe_to_spend
from fdt.twin.behavior import estimate_behavior
from fdt.twin.projection import project_room
from fdt.twin.simulate import forecast, risk
from fdt.twin.state import build_state, propose_budgets


@pytest.mark.parametrize("profile", ["A_steady", "B_card_crunch", "C_impulsive"])
def test_generated_profile_pipeline(profile: str, tmp_path) -> None:
    """§11.3 gen → ingest → twin → analysis → projection → template coaching."""
    seed_dir, _ = generate(profile, tmp_path / "seed", seed=123, end=date(2026, 6, 30))
    snapshot = load_snapshot(seed_dir / "snapshot.json")
    transactions = ingest(snapshot)
    as_of = date(2026, 6, 30)
    budgets = propose_budgets(transactions, as_of)
    state = build_state(transactions, snapshot, as_of, budgets=budgets)
    behavior = estimate_behavior(transactions, as_of, budgets=budgets)

    forecast_result = forecast(state, behavior, horizon_days=7, n_paths=25, seed=42)
    risk_result = risk(state, behavior, horizon_days=7, n_paths=25, seed=42)
    score, level = health(state, risk_result)
    state = state.model_copy(update={"health_score": score, "health_level": level})
    today = [transaction for transaction in transactions if transaction.day == as_of]
    safe_result = safe_to_spend(state, today)
    alerts = detect_alerts(state, behavior, today)
    rebalance_result = rebalance(state, behavior)
    room_result = project_room(state, alerts)
    reply = template_fallback("safe_to_spend", safe_result.model_dump(mode="json"), "온순냥")

    payload = {"state": state.model_dump(mode="json"), "forecast": forecast_result.model_dump(mode="json"),
               "risk": risk_result.model_dump(mode="json"), "safe": safe_result.model_dump(mode="json"),
               "rebalance": rebalance_result.model_dump(mode="json"), "room": room_result.model_dump(mode="json"),
               "reply": reply}
    json.dumps(payload, ensure_ascii=False)
    assert forecast_result.dates[0] == as_of
    assert 0.0 <= risk_result.card_shortfall_prob <= 1.0
    assert safe_result.safe_today >= 0
    assert room_result.level == state.health_level
