from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from moex_carry.domain.portfolio import Order, PairSpec

SoftRebalanceFrequency = Literal["NONE", "DAILY", "WEEKLY"]
HardChecksFrequency = Literal["DAILY", "SOFT", "REBALANCE", "NONE"]
ScoreThresholdMode = Literal["PERCENTILE", "ABSOLUTE"]
AllocationMethod = Literal[
    "EQUAL",
    "SCORE_WEIGHTED",
    "SCORE_RISK_PARITY",
    "FLOOR_PLUS_ALPHA_OVERLAY",
]
CapitalBaseMode = Literal["FULL_CASH", "MARGIN_AWARE"]
TpNetMode = Literal["INCLUDE_RTC", "EXCLUDE_RTC"]


class RebalanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    soft_rebalance_frequency: SoftRebalanceFrequency = "WEEKLY"
    soft_rebalance_day_of_week: int = 0
    hard_checks_frequency: HardChecksFrequency = "DAILY"

    max_pairs_held: int = 6
    cooldown_days: int = 0
    enter_min_DTE: int = 7
    block_news_severities: list[str] = Field(default_factory=list)

    score_threshold_mode: ScoreThresholdMode = "PERCENTILE"
    enter_threshold: float = 0.8
    keep_threshold: float = 0.5
    enter_total_score_min: float | None = None
    keep_total_score_min: float | None = None
    drop_rank_threshold: int | None = None
    drop_rank_grace_days: int = 0
    replacement_threshold_score_gap_pct: float = 0.2

    kill_switch: bool = False
    close_buffer_days: int = 3
    TP_pct: float = 0.01
    SL_pct: float = 0.01
    tp_net_mode: TpNetMode = "INCLUDE_RTC"
    h_max_days: int = 20
    liquidity_exit_streak: int = 2
    exit_on_floor_fail: bool = True
    trailing_stop_pct: float | None = None
    trailing_start_pct: float | None = None

    allocation_method: AllocationMethod = "EQUAL"
    target_utilization: float = 1.0
    max_weight_per_pair: float | None = 0.35
    alpha_overlay_weight: float = 1.0

    capital_base_mode: CapitalBaseMode = "FULL_CASH"
    margin_stock_pct: float = 0.0
    margin_fut_pct: float = 0.0
    var_margin_buffer_pct: float = 0.0
    min_contracts_per_pair: int = 0
    max_contracts_per_pair: int | None = None

    rebalance_band: float = 0.05
    turnover_limit_pct: float | None = None
    turnover_limit_notional: float | None = None

    default_direction: str = "cash_and_carry"
    epsilon: float = 1e-9


@dataclass
class TargetPosition:
    pair: PairSpec
    direction: str
    contracts: int
    quantity_stock: float
    quantity_fut: float
    weight: float
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RebalanceResult:
    date: date
    orders: list[Order]
    target_positions: list[TargetPosition]
    reasons: dict[str, list[str]]
    turnover_estimate_notional: float
    warnings: list[str] = field(default_factory=list)
