from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from moex_carry.signal_engine.core.math_utils import normalize_three_way_probabilities

Side = Literal["BUY", "SELL"]
OutcomeLabel = Literal["TP", "SL", "EXIT"]
ConfidenceTier = Literal["low", "mid", "high"]
SignalAction = Literal["BUY", "SELL", "ADVISORY", "NO_TRADE"]


@dataclass(frozen=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class MarketRegimeFlags:
    is_first_5m: bool = False
    is_last_5m: bool = False
    is_intraday_clearing_window: bool = False
    is_evening_clearing_window: bool = False


@dataclass(frozen=True)
class AlphaProposal:
    strategy_id: str
    instrument_id: str
    side: Side
    entry_ts: datetime
    horizon_sec: int
    tp_ticks: int
    sl_ticks: int
    exit_rule: dict[str, Any] = field(default_factory=dict)
    features_snapshot: dict[str, Any] = field(default_factory=dict)
    market_regime_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HistoricalOutcome:
    ts: datetime
    outcome: OutcomeLabel


@dataclass(frozen=True)
class OutcomeForecast:
    p_tp: float
    p_sl: float
    p_exit: float
    n_effective: float
    confidence_tier: ConfidenceTier
    probability_source: str

    def normalized(self) -> "OutcomeForecast":
        p_tp, p_sl, p_exit = normalize_three_way_probabilities(self.p_tp, self.p_sl, self.p_exit)
        return OutcomeForecast(
            p_tp=p_tp,
            p_sl=p_sl,
            p_exit=p_exit,
            n_effective=float(max(self.n_effective, 0.0)),
            confidence_tier=self.confidence_tier,
            probability_source=self.probability_source,
        )


@dataclass(frozen=True)
class StrategySignal:
    action: SignalAction
    confidence: float
    expected_return_ticks: float
    risk_ticks: float
    metadata: dict[str, Any] = field(default_factory=dict)
