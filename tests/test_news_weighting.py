from __future__ import annotations

from datetime import datetime, timezone

from moex_carry.config import AppSettings
from moex_carry.pipeline import (
    _apply_news_model_weighting,
    _evaluate_news_weight_quality_gate_report,
)


def test_news_model_weighting_reduces_on_conflict() -> None:
    settings = AppSettings()
    settings.news_models.decision_weight_rollout_mode = "full"
    settings.news_models.decision_weight_min_sample_size = 1
    base_weights = {"arbitrage": 1.0, "fundamental": 0.4}
    score_rows = [
        {
            "prob_up": 0.1,
            "prob_down": 0.8,
            "prob_neutral": 0.1,
            "impact_score": 0.9,
        }
    ]
    adjusted, context = _apply_news_model_weighting(
        base_weights=base_weights,
        signal_direction="cash_and_carry",
        gate_action="allow",
        score_rows=score_rows,
        settings=settings,
    )
    assert adjusted["arbitrage"] == base_weights["arbitrage"] * settings.news_models.decision_weight_reduce_factor
    assert context["applied"] is True
    assert context["reason"] == "model_conflict"


def test_news_model_weighting_boosts_on_alignment() -> None:
    settings = AppSettings()
    settings.news_models.decision_weight_rollout_mode = "full"
    settings.news_models.decision_weight_min_sample_size = 1
    base_weights = {"arbitrage": 1.0, "fundamental": 0.4}
    score_rows = [
        {
            "prob_up": 0.85,
            "prob_down": 0.05,
            "prob_neutral": 0.10,
            "impact_score": 0.9,
        }
    ]
    adjusted, context = _apply_news_model_weighting(
        base_weights=base_weights,
        signal_direction="cash_and_carry",
        gate_action="allow",
        score_rows=score_rows,
        settings=settings,
    )
    assert adjusted["arbitrage"] == base_weights["arbitrage"] * settings.news_models.decision_weight_boost_factor
    assert context["applied"] is True
    assert context["reason"] == "model_aligned"


def test_news_model_weighting_follows_gate_block() -> None:
    settings = AppSettings()
    settings.news_models.decision_weight_rollout_mode = "limited"
    settings.news_models.decision_weight_min_sample_size = 10
    base_weights = {"arbitrage": 1.0}
    adjusted, context = _apply_news_model_weighting(
        base_weights=base_weights,
        signal_direction="cash_and_carry",
        gate_action="block",
        score_rows=[],
        settings=settings,
    )
    assert adjusted["arbitrage"] == 0.0
    assert context["applied"] is True
    assert context["reason"] == "gate_block"


def test_news_model_weighting_limited_mode_clamps_reduce_factor() -> None:
    settings = AppSettings()
    settings.news_models.decision_weight_rollout_mode = "limited"
    settings.news_models.decision_weight_limited_max_deviation = 0.25
    settings.news_models.decision_weight_min_sample_size = 1
    base_weights = {"arbitrage": 1.0}
    score_rows = [
        {
            "prob_up": 0.05,
            "prob_down": 0.9,
            "prob_neutral": 0.05,
            "impact_score": 0.95,
        }
    ]
    adjusted, context = _apply_news_model_weighting(
        base_weights=base_weights,
        signal_direction="cash_and_carry",
        gate_action="allow",
        score_rows=score_rows,
        settings=settings,
    )
    assert adjusted["arbitrage"] == 0.75
    assert context["rollout_mode"] == "limited"
    assert context["limited_clamped"] is True
    assert context["reason"] == "model_conflict"


def test_news_weight_quality_gate_allows_recent_promoted_primary_winner() -> None:
    now = datetime(2026, 2, 18, 12, 0, tzinfo=timezone.utc)
    report = {
        "run_id": "cmp-1",
        "horizon": "1h",
        "created_at": "2026-02-18T10:00:00Z",
        "metrics_json": {
            "winner": {"model_id": "finbert"},
            "audit": {
                "decision": "promote",
                "recorded_at": "2026-02-18T10:00:00Z",
                "quality_gate": {"pass": True},
            },
        },
    }
    gate = _evaluate_news_weight_quality_gate_report(
        report,
        required_model="finbert",
        expected_horizon="1h",
        max_age_hours=72,
        now=now,
    )
    assert gate["allow_weighting"] is True
    assert gate["status"] == "ready"
    assert gate["winner_model"] == "finbert"


def test_news_weight_quality_gate_blocks_on_winner_mismatch() -> None:
    now = datetime(2026, 2, 18, 12, 0, tzinfo=timezone.utc)
    report = {
        "run_id": "cmp-2",
        "horizon": "1h",
        "created_at": "2026-02-18T10:00:00Z",
        "metrics_json": {
            "winner": {"model_id": "nli"},
            "audit": {
                "decision": "promote",
                "recorded_at": "2026-02-18T10:00:00Z",
                "quality_gate": {"pass": True},
            },
        },
    }
    gate = _evaluate_news_weight_quality_gate_report(
        report,
        required_model="finbert",
        expected_horizon="1h",
        max_age_hours=72,
        now=now,
    )
    assert gate["allow_weighting"] is False
    assert gate["status"] == "winner_model_mismatch"


def test_news_weight_quality_gate_blocks_stale_report() -> None:
    now = datetime(2026, 2, 18, 12, 0, tzinfo=timezone.utc)
    report = {
        "run_id": "cmp-3",
        "horizon": "1h",
        "created_at": "2026-02-10T10:00:00Z",
        "metrics_json": {
            "winner": {"model_id": "finbert"},
            "audit": {
                "decision": "promote",
                "recorded_at": "2026-02-10T10:00:00Z",
                "quality_gate": {"pass": True},
            },
        },
    }
    gate = _evaluate_news_weight_quality_gate_report(
        report,
        required_model="finbert",
        expected_horizon="1h",
        max_age_hours=24,
        now=now,
    )
    assert gate["allow_weighting"] is False
    assert gate["status"] == "stale_report"
