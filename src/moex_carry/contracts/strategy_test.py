from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AutoFloat = float | Literal["AUTO"]


class BacktestTestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None
    timezone: str = "Europe/Moscow"
    cost_stress_mult: float = 1.0
    seed: int | None = None


class BacktestUniverseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair_ids: list[str] = Field(default_factory=list)
    include_stocks: list[str] = Field(default_factory=list)
    include_futures: list[str] = Field(default_factory=list)
    max_pairs: int | None = None
    allowed_expiry_months: list[int] | None = None
    allowed_expiry_years: list[int] | None = None


class BacktestExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slip_stock_bps: float = 0.0
    slip_fut_bps: float = 0.0
    slip_fut_ticks: float | None = None
    tick_size_fut: float | None = None


class BacktestRatesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_count: str = "ACT/365"
    use_trading_days: bool = False
    r_cb_annual: float | None = None
    r_fund_annual: float | None = None
    r_disc_annual: float | None = None


class BacktestCostsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock_commission_bps: float = 1.5
    futures_commission_bps: float = 1.0
    exchange_fee_bps: float = 0.5
    fee_stock_per_share: float | None = None
    fee_stock_bps: float | None = None
    fee_fut_per_contract: float | None = None


class BacktestLiquidityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_spread_bps_stock: float | None = None
    max_spread_bps_fut: float | None = None
    min_avg_dollarvol_stock: AutoFloat | None = None
    min_avg_dollarvol_fut: AutoFloat | None = None
    min_open_interest: float | None = None
    participation_rate: float = 0.1
    max_days_to_exit: float | None = None


class BacktestStrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    floor_tolerance: float = 0.0
    riskbuffer_floor: float = 0.0
    capital_base_mode: str = "FULL_CASH"
    margin_stock_pct: float = 0.0
    margin_fut_pct: float = 0.0
    var_margin_buffer_pct: float = 0.0
    min_DTE_entry: int = 7
    close_buffer_days: int = 3
    roll_trigger_days: int = 0
    H_max_days: int = 20
    TP_pct: float = 0.01
    SL_pct: float = 0.01
    z_window: int = 60
    z_entry_threshold: float | None = None
    min_floor_score: float | None = None
    min_alpha_score: float | None = None
    min_total_score: float | None = None
    w_floor: float = 0.5
    w_alpha: float = 0.5
    w_liq: float = 1.0
    w_event: float = 1.0
    k_event: float = 0.0


class BacktestPortfolioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_equity: float | None = 1_000_000.0
    account_currency: str = "RUB"
    max_gross_notional: float | None = None
    max_contracts_per_pair: int | None = 1
    capital_allocated_per_trade: float | None = None
    margin_proxy: float = 1.0


class BacktestAllocationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "fundamental": 0.4,
            "speculative": 0.3,
            "arbitrage": 0.3,
        }
    )
    min_confidence: float = 0.2
    max_signals: int = 3
    max_turnover_pct: float = 0.2
    min_trade_weight: float = 0.01


class BacktestRebalanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cadence: str = "weekly"
    threshold_pct: float = 0.02
    cooldown_days: int = 3


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test: BacktestTestConfig = Field(default_factory=BacktestTestConfig)
    universe: BacktestUniverseConfig = Field(default_factory=BacktestUniverseConfig)
    execution: BacktestExecutionConfig = Field(default_factory=BacktestExecutionConfig)
    rates: BacktestRatesConfig = Field(default_factory=BacktestRatesConfig)
    costs: BacktestCostsConfig = Field(default_factory=BacktestCostsConfig)
    liquidity: BacktestLiquidityConfig = Field(default_factory=BacktestLiquidityConfig)
    strategy: BacktestStrategyConfig = Field(default_factory=BacktestStrategyConfig)
    portfolio: BacktestPortfolioConfig = Field(default_factory=BacktestPortfolioConfig)
    allocation: BacktestAllocationConfig = Field(default_factory=BacktestAllocationConfig)
    rebalance: BacktestRebalanceConfig = Field(default_factory=BacktestRebalanceConfig)


class ForwardTestRequest(BacktestRequest):
    model_config = ConfigDict(extra="forbid")

    as_of_date: date | None = None
    forward_days: int | None = None


class HpoCvConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folds: int = 3
    test_size: float | None = None
    embargo_days: int = 0
    purged: bool = False


class HpoOptimizationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = "sharpe"
    mode: Literal["max", "min"] = "max"
    max_trials: int = 50
    random_seed: int | None = None
    timeout_sec: int | None = None


class HpoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: BacktestRequest = Field(default_factory=BacktestRequest)
    search_space: dict[str, Any] = Field(default_factory=dict)
    cv: HpoCvConfig = Field(default_factory=HpoCvConfig)
    optimization: HpoOptimizationConfig = Field(default_factory=HpoOptimizationConfig)


class ParameterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value_type: str
    default: Any | None = None
    min_value: float | None = None
    max_value: float | None = None
    options: list[Any] | None = None
    description: str | None = None
