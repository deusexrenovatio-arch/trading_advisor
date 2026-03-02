from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Sequence, cast

from moex_carry.signal_engine.core.types import ConfidenceTier, HistoricalOutcome, OutcomeForecast


@dataclass(frozen=True)
class DirichletDecayConfig:
    alpha_tp: float = 1.0
    alpha_sl: float = 1.0
    alpha_exit: float = 1.0
    half_life_days: float = 30.0
    tier_mid_threshold: float = 100.0
    tier_high_threshold: float = 500.0
    probability_source: str = "dirichlet_decay_v1"


def _event_weight(ts: datetime, as_of_ts: datetime, half_life_days: float) -> float:
    half_life = max(float(half_life_days), 1e-9)
    age_days = max((as_of_ts - ts).total_seconds() / 86_400.0, 0.0)
    return float(math.exp(-math.log(2.0) * age_days / half_life))


def _confidence_tier(n_effective: float, *, mid: float, high: float) -> str:
    sample = max(float(n_effective), 0.0)
    if sample >= float(high):
        return "high"
    if sample >= float(mid):
        return "mid"
    return "low"


def estimate_outcome_probabilities(
    *,
    outcomes: Sequence[HistoricalOutcome],
    as_of_ts: datetime,
    config: DirichletDecayConfig = DirichletDecayConfig(),
) -> OutcomeForecast:
    n_tp = 0.0
    n_sl = 0.0
    n_exit = 0.0
    sum_w = 0.0
    sum_w2 = 0.0

    for record in outcomes:
        weight = _event_weight(record.ts, as_of_ts, float(config.half_life_days))
        sum_w += weight
        sum_w2 += weight * weight
        if record.outcome == "TP":
            n_tp += weight
        elif record.outcome == "SL":
            n_sl += weight
        else:
            n_exit += weight

    alpha_tp = max(float(config.alpha_tp), 0.0)
    alpha_sl = max(float(config.alpha_sl), 0.0)
    alpha_exit = max(float(config.alpha_exit), 0.0)
    denominator = n_tp + n_sl + n_exit + alpha_tp + alpha_sl + alpha_exit
    if denominator <= 0.0:
        p_tp = p_sl = p_exit = 1.0 / 3.0
    else:
        p_tp = (n_tp + alpha_tp) / denominator
        p_sl = (n_sl + alpha_sl) / denominator
        p_exit = (n_exit + alpha_exit) / denominator

    n_effective = ((sum_w * sum_w) / sum_w2) if sum_w2 > 0.0 else 0.0
    tier = _confidence_tier(
        n_effective,
        mid=float(config.tier_mid_threshold),
        high=float(config.tier_high_threshold),
    )
    return OutcomeForecast(
        p_tp=float(p_tp),
        p_sl=float(p_sl),
        p_exit=float(p_exit),
        n_effective=float(n_effective),
        confidence_tier=cast(ConfidenceTier, tier),
        probability_source=str(config.probability_source),
    ).normalized()
