from __future__ import annotations

from typing import cast

from moex_carry.signal_engine.core.types import AlphaProposal, StrategySignal as EngineStrategySignal
from moex_carry.strategy.strategy_signal import (
    RuleEvaluation,
    SignalAction,
    StrategyAllocation,
    StrategySignal,
)


def to_strategy_signal(
    *,
    proposal: AlphaProposal,
    engine_signal: EngineStrategySignal,
) -> StrategySignal:
    action_value = "enter" if engine_signal.action in {"BUY", "SELL"} else "hold"
    action = cast(SignalAction, action_value)
    side = "long" if engine_signal.action == "BUY" else "short"
    allocations = (
        [StrategyAllocation(instrument=proposal.instrument_id, side=side, target_weight=1.0)]
        if action == "enter"
        else []
    )
    warnings: list[str] = []
    rules: list[RuleEvaluation] = []
    reasons = engine_signal.metadata.get("gate_reasons")
    if isinstance(reasons, list):
        for reason in reasons:
            text = str(reason)
            warnings.append(text)
            rules.append(
                RuleEvaluation(
                    rule_id=text,
                    result=False,
                    severity="block",
                    description="gate block",
                )
            )
    if engine_signal.action == "ADVISORY":
        warnings.append("advisory_low_confidence")

    metadata = dict(engine_signal.metadata)
    metadata.update(
        {
            "engine_action": engine_signal.action,
            "instrument_id": proposal.instrument_id,
            "entry_ts": proposal.entry_ts.isoformat(),
            "horizon_sec": int(proposal.horizon_sec),
            "tp_ticks": int(proposal.tp_ticks),
            "sl_ticks": int(proposal.sl_ticks),
        }
    )
    return StrategySignal(
        strategy_id=f"{proposal.strategy_id}_two_layer",
        strategy_type="speculative",
        cadence="intraday",
        horizon=f"{max(int(proposal.horizon_sec), 1) // 60}m",
        action=action,
        confidence=float(max(min(engine_signal.confidence, 1.0), 0.0)),
        expected_return=float(engine_signal.expected_return_ticks),
        risk_estimate=float(engine_signal.risk_ticks),
        instruments=[proposal.instrument_id],
        intent_allocations=allocations,
        rules_evaluated=rules,
        warnings=warnings,
        metadata=metadata,
    )
