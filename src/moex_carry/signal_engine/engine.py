from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from moex_carry.signal_engine.core.types import (
    AlphaProposal,
    HistoricalOutcome,
    MarketRegimeFlags,
    OutcomeForecast,
    StrategySignal,
)
from moex_carry.signal_engine.cost.model_ticks import (
    TickCostModelConfig,
    expected_return_ticks,
    round_trip_cost_ticks,
)
from moex_carry.signal_engine.gate.gate import GateConfig, apply_signal_gate
from moex_carry.signal_engine.prob.empirical_dirichlet import (
    DirichletDecayConfig,
    estimate_outcome_probabilities,
)


@dataclass(frozen=True)
class CandidateEvaluation:
    proposal: AlphaProposal
    forecast: OutcomeForecast
    cost_ticks: float
    expected_return_ticks: float
    signal: StrategySignal


def evaluate_candidate(
    *,
    proposal: AlphaProposal,
    historical_outcomes: Sequence[HistoricalOutcome],
    as_of_ts: datetime,
    regime_flags: MarketRegimeFlags = MarketRegimeFlags(),
    spread_ticks_value: int | None = None,
    depth_lots: float | None = None,
    vacuum: bool = False,
    exit_return_ticks: float = 0.0,
    probability_config: DirichletDecayConfig = DirichletDecayConfig(),
    cost_config: TickCostModelConfig = TickCostModelConfig(),
    gate_config: GateConfig = GateConfig(),
    vol_regime: str | None = None,
) -> CandidateEvaluation:
    forecast = estimate_outcome_probabilities(
        outcomes=historical_outcomes,
        as_of_ts=as_of_ts,
        config=probability_config,
    )
    cost_ticks = round_trip_cost_ticks(
        spread_ticks_value=spread_ticks_value,
        depth_lots=depth_lots,
        vacuum=vacuum,
        config=cost_config,
    )
    expectancy = expected_return_ticks(
        forecast=forecast,
        tp_ticks=int(proposal.tp_ticks),
        sl_ticks=int(proposal.sl_ticks),
        cost_ticks=float(cost_ticks),
        exit_return_ticks=float(exit_return_ticks),
    )
    signal = apply_signal_gate(
        proposal=proposal,
        forecast=forecast,
        expected_return_ticks_value=expectancy,
        cost_ticks=float(cost_ticks),
        regime_flags=regime_flags,
        spread_ticks_value=spread_ticks_value,
        vacuum=vacuum,
        config=gate_config,
        vol_regime=vol_regime,
    )
    return CandidateEvaluation(
        proposal=proposal,
        forecast=forecast,
        cost_ticks=float(cost_ticks),
        expected_return_ticks=float(expectancy),
        signal=signal,
    )
