from __future__ import annotations

from dataclasses import dataclass

from moex_carry.signal_engine.core.types import (
    AlphaProposal,
    MarketRegimeFlags,
    OutcomeForecast,
    StrategySignal,
)


@dataclass(frozen=True)
class GateConfig:
    forbid_windows_min: int = 5
    min_expected_return_ticks: float = 1.0
    max_spread_ticks: int = 2
    tier_mid_threshold: float = 100.0
    tier_high_threshold: float = 500.0


def _confidence_from_tier(tier: str) -> float:
    if tier == "high":
        return 0.9
    if tier == "mid":
        return 0.65
    return 0.35


def _tier_from_n_effective(
    n_effective: float,
    *,
    mid_threshold: float,
    high_threshold: float,
) -> str:
    sample = max(float(n_effective), 0.0)
    if sample >= float(high_threshold):
        return "high"
    if sample >= float(mid_threshold):
        return "mid"
    return "low"


def apply_signal_gate(
    *,
    proposal: AlphaProposal,
    forecast: OutcomeForecast,
    expected_return_ticks_value: float,
    cost_ticks: float,
    regime_flags: MarketRegimeFlags = MarketRegimeFlags(),
    spread_ticks_value: int | None = None,
    vacuum: bool = False,
    config: GateConfig = GateConfig(),
    vol_regime: str | None = None,
) -> StrategySignal:
    normalized = forecast.normalized()
    tier = _tier_from_n_effective(
        normalized.n_effective,
        mid_threshold=float(config.tier_mid_threshold),
        high_threshold=float(config.tier_high_threshold),
    )
    reasons: list[str] = []

    if regime_flags.is_intraday_clearing_window or regime_flags.is_evening_clearing_window:
        reasons.append("clearing_window_block")
    if vacuum:
        reasons.append("liquidity_vacuum_block")
    if spread_ticks_value is not None and int(spread_ticks_value) > int(config.max_spread_ticks):
        reasons.append("spread_block")
    if proposal.strategy_id == "orb_v1" and str(vol_regime or "").upper() != "HIGH":
        reasons.append("orb_requires_high_vol")

    if reasons:
        return StrategySignal(
            action="NO_TRADE",
            confidence=0.0,
            expected_return_ticks=float(expected_return_ticks_value),
            risk_ticks=float(proposal.sl_ticks),
            metadata={
                "gate_reasons": reasons,
                "p_tp": normalized.p_tp,
                "p_sl": normalized.p_sl,
                "p_exit": normalized.p_exit,
                "forecast_n_effective": normalized.n_effective,
                "forecast_probability_source": normalized.probability_source,
                "cost_ticks": float(cost_ticks),
                "confidence_tier": tier,
            },
        )

    if tier == "low":
        return StrategySignal(
            action="ADVISORY",
            confidence=_confidence_from_tier(tier),
            expected_return_ticks=float(expected_return_ticks_value),
            risk_ticks=float(proposal.sl_ticks),
            metadata={
                "reason_low_confidence": "n_effective_below_mid_threshold",
                "p_tp": normalized.p_tp,
                "p_sl": normalized.p_sl,
                "p_exit": normalized.p_exit,
                "forecast_n_effective": normalized.n_effective,
                "forecast_probability_source": normalized.probability_source,
                "cost_ticks": float(cost_ticks),
                "confidence_tier": tier,
            },
        )

    if float(expected_return_ticks_value) < float(config.min_expected_return_ticks):
        return StrategySignal(
            action="NO_TRADE",
            confidence=0.0,
            expected_return_ticks=float(expected_return_ticks_value),
            risk_ticks=float(proposal.sl_ticks),
            metadata={
                "gate_reasons": ["expected_return_below_threshold"],
                "min_expected_return_ticks": float(config.min_expected_return_ticks),
                "p_tp": normalized.p_tp,
                "p_sl": normalized.p_sl,
                "p_exit": normalized.p_exit,
                "forecast_n_effective": normalized.n_effective,
                "forecast_probability_source": normalized.probability_source,
                "cost_ticks": float(cost_ticks),
                "confidence_tier": tier,
            },
        )

    side_action = "BUY" if proposal.side == "BUY" else "SELL"
    return StrategySignal(
        action=side_action,
        confidence=_confidence_from_tier(tier),
        expected_return_ticks=float(expected_return_ticks_value),
        risk_ticks=float(proposal.sl_ticks),
        metadata={
            "p_tp": normalized.p_tp,
            "p_sl": normalized.p_sl,
            "p_exit": normalized.p_exit,
            "forecast_n_effective": normalized.n_effective,
            "forecast_probability_source": normalized.probability_source,
            "cost_ticks": float(cost_ticks),
            "confidence_tier": tier,
            "gate_reasons": [],
        },
    )
