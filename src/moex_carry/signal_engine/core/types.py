from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from moex_carry.signal_engine.core.math_utils import normalize_three_way_probabilities


class TF(str, Enum):
    D1 = "D1"
    H1 = "H1"
    M5 = "M5"


class TrendState(str, Enum):
    TREND = "TREND"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"


class Direction(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    NEUTRAL = "NEUTRAL"


class VolState(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class LiquidityState(str, Enum):
    OK = "OK"
    THIN = "THIN"
    VACUUM = "VACUUM"
    UNKNOWN = "UNKNOWN"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    STOP_LIMIT = "STOP_LIMIT"
    STOP = "STOP"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OutcomeLabel(str, Enum):
    TP = "TP"
    SL = "SL"
    EXIT = "EXIT"


class ConfidenceTier(str, Enum):
    LOW = "low"
    MID = "mid"
    HIGH = "high"


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    ADVISORY = "ADVISORY"
    NO_TRADE = "NO_TRADE"


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
class Level:
    tf: TF
    kind: str
    price_ticks: int
    score: float
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RegimeState:
    as_of_ts: datetime
    daily_trend_state: TrendState
    daily_dir: Direction
    daily_strength: float
    daily_atr_ticks: int
    daily_vol_state: VolState
    h1_dir: Direction
    h1_alignment: bool
    h1_atr_ticks: int
    liquidity_state: LiquidityState
    components: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionParams:
    buffer_ticks: int
    limit_slip_ticks: int
    m5_atr_ticks: int
    m5_noise_ratio: float
    warnings: list[str] = field(default_factory=list)


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
class OrderIntent:
    order_type: OrderType
    side: Side
    price_ticks: int
    qty_lots: int
    tif: str
    price_range_low_ticks: int | None = None
    price_range_high_ticks: int | None = None
    activate_from_ts: datetime | None = None
    expire_ts: datetime | None = None
    link_group: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Setup:
    setup_id: str
    side: Side
    entry_level: Level
    entry_order: OrderIntent
    sl_order: OrderIntent
    tp_order: OrderIntent
    horizon: str
    rationale: list[str]
    risk_ticks: int


@dataclass(frozen=True)
class StrategySignal:
    action: SignalAction
    confidence: float
    expected_return_ticks: float
    risk_ticks: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MorningPlan:
    as_of_ts: datetime
    instrument_id: str
    regime: RegimeState
    levels: list[Level]
    exec_params: ExecutionParams
    setups: list[Setup]
    warnings: list[str] = field(default_factory=list)
