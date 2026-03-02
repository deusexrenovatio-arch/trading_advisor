from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MoexIssConfig(BaseModel):
    base_url: str = "https://iss.moex.com"
    fallback_ips: list[str] = []
    force_fallback: bool = False
    engine_shares: str = "stock"
    market_shares: str = "shares"
    shares_board: str = "TQBR"
    engine_futures: str = "futures"
    market_futures: str = "forts"
    futures_board: str = "RFUD"
    request_timeout_sec: int = 20
    request_max_retries: int = 3
    request_retry_backoff_sec: float = 0.5
    request_retry_max_backoff_sec: float = 4.0


class CbrConfig(BaseModel):
    base_url: str = "https://www.cbr.ru"
    key_rate_path: str = "/Queries/UniDbQuery/DownloadExcel/132934"


class DatabaseConfig(BaseModel):
    url: str = "sqlite:///./data/moex_carry.db"
    echo: bool = False


class CostsConfig(BaseModel):
    stock_commission_bps: float = 1.5
    futures_commission_bps: float = 1.0
    exchange_fee_bps: float = 0.5
    slippage_bps: float = 0.5


class TaxesConfig(BaseModel):
    profit_tax_rate: float = 0.13
    dividend_tax_rate: float = 0.13


class StrategyConfig(BaseModel):
    z_window: int = 60
    z_min_window: int = 10
    z_entry: float = 2.0
    z_exit: float = 0.5
    implied_rate_buffer: float = 0.005
    min_days_to_expiry: int = 7
    min_days_to_exdiv: int = 5
    term_premium_base: float = 0.01
    term_premium_slope: float = 0.02
    max_pairs: int = 25
    intraday_marketdata: bool = True


class SpreadCarryAlphaConfig(BaseModel):
    day_count: str = "ACT/365"
    use_trading_days: bool = False
    # Price source for spread strategy/backtest inputs:
    # - daily_close: end-of-day candle close (legacy behavior)
    # - common_minute_close: last/first common minute close between stock/future per day
    price_source: str = "daily_close"
    common_minute_anchor: str = "last"
    # 0 enables same-day submission at signal_ts + execution_lag_minutes.
    signal_exec_lag_days: int = 1
    execution_lag_minutes: int = 1
    execution_max_wait_minutes: int = 1440
    force_exit_policy: str = "next_anchor"
    force_exit_penalty_bps: float = 0.0
    annual_target_threshold: Optional[float] = None

    r_cb_annual: Optional[float] = None
    r_fund_annual: Optional[float] = None
    r_disc_annual: Optional[float] = None

    price_mode: str = "BIDASK"
    half_spread_bps: float = 0.0
    slip_stock_bps: float = 0.0
    slip_fut_bps: float = 0.0
    slip_fut_ticks: Optional[float] = None
    tick_size_fut: Optional[float] = None

    fee_stock_per_share: Optional[float] = None
    fee_stock_bps: Optional[float] = None
    fee_fut_per_contract: Optional[float] = None

    floor_tolerance: float = 0.0
    riskbuffer_floor: float = 0.0
    capital_base_mode: str = "FULL_CASH"
    margin_stock_pct: float = 0.0
    margin_fut_pct: float = 0.0
    var_margin_buffer_pct: float = 0.0

    max_spread_bps_stock: Optional[float] = None
    max_spread_bps_fut: Optional[float] = None
    min_avg_dollarvol_stock: Optional[float] = None
    min_avg_dollarvol_fut: Optional[float] = None
    min_open_interest: Optional[float] = None
    require_live_orderbook_for_entry: bool = False
    min_orderbook_depth_stock: Optional[float] = None
    min_orderbook_depth_fut: Optional[float] = None
    max_orderbook_age_sec_stock: Optional[float] = None
    max_orderbook_age_sec_fut: Optional[float] = None
    max_orderbook_imbalance_ratio_stock: Optional[float] = None
    max_orderbook_imbalance_ratio_fut: Optional[float] = None
    participation_rate: float = 0.1
    max_days_to_exit: Optional[float] = None

    min_DTE_entry: int = 7
    close_buffer_days: int = 3
    roll_trigger_days: int = 0

    H_max_days: int = 20
    TP_pct: float = 0.01
    SL_pct: float = 0.01

    z_window: int = 60
    z_entry_threshold: Optional[float] = None
    entry_price_tolerance_pct: float = 0.0015
    entry_stock_tolerance_pct: Optional[float] = None
    entry_future_tolerance_pct: Optional[float] = None
    entry_spread_tolerance_pct: Optional[float] = None
    signal_cutoff_before_day_end_minutes: int = 0

    max_gross_notional: Optional[float] = None
    max_contracts_per_pair: int = 1
    capital_allocated_per_trade: Optional[float] = None
    margin_proxy: float = 1.0

    w1: float = 1.0
    w2: float = 1.0
    w3: float = 1.0
    w4: float = 1.0
    c1: float = 1.0
    c2: float = 1.0
    k_event: float = 0.0

    min_floor_score: Optional[float] = None
    min_alpha_score: Optional[float] = None
    min_total_score: Optional[float] = None
    ranking_primary_metric: str = "avg_trade_return_annual_operational_recent"
    allowed_expiry_months: Optional[list[int]] = None
    allowed_expiry_years: Optional[list[int]] = None


class AggregationConfig(BaseModel):
    weights: dict[str, float] = {
        "fundamental": 0.4,
        "speculative": 0.3,
        "arbitrage": 0.3,
    }
    min_confidence: float = 0.2
    max_signals: int = 3
    rebalance_cadence: str = "weekly"
    rebalance_threshold_pct: float = 0.02
    max_turnover_pct: float = 0.2
    min_trade_weight: float = 0.01
    cooldown_days: int = 3


class UiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8050
    signal_refresh_enabled: bool = False
    signal_refresh_interval_sec: int = 60
    signal_refresh_daily_time: Optional[str] = None
    signal_refresh_timezone: Optional[str] = None
    signal_refresh_max_pairs: Optional[int] = None
    signal_refresh_save_csv: bool = True
    incremental_replay_enabled: bool = True
    incremental_overlap_minutes: int = 180
    incremental_checkpoint_dir: str = "./data/state/incremental_replay"
    incremental_checkpoint_interval_minutes: int = 60
    pretrade_fail_open_on_transport_error: bool = True
    ff_db_projection_source: bool = False
    ff_fail_closed_execution: bool = False
    auto_unwind_timeout_sec: int = 600
    use_unified_signal_engine: bool = True
    unified_allow_legacy_fallback: bool = True
    unified_snapshot_ttl_sec: int = 120
    unified_pair_workers: int | None = None
    unified_pair_replay_cache_max: int = 64
    unified_front_only: bool = True
    unified_front_roll_days: int = 7
    require_score_gate_by_default: bool = True
    require_score_gate_top_pairs_by_default: bool = False
    signal_entry_intent_ttl_hours: int = 72
    max_api_payload_bytes: int = 262144


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str | None = None
    backend_base_url: str = "http://127.0.0.1:8050"
    allowed_user_ids: list[int] = []
    poll_timeout_sec: int = 25
    signal_fetch_interval_sec: int = 30
    hold_open_daily_limit: int = 1
    enter_resend_cooldown_minutes: int = 60
    callback_ttl_hours: int = 72
    daily_healthcheck_enabled: bool = True
    daily_healthcheck_time_local: str = "09:00"
    state_path: str = "./data/telegram/bot_state.json"
    ui_base_url: str | None = None


class DataConfig(BaseModel):
    data_dir: str = "./data"
    compute_lookback_days: int = 120
    backtest_lookback_days: int = 365


class EnvironmentConfig(BaseModel):
    mode: str = "paper"
    venue: str = "MOEX"
    timezone: str = "Europe/Moscow"


class RiskProfileConfig(BaseModel):
    account_equity: float = 1_000_000.0
    account_currency: str = "RUB"
    max_risk_per_trade_pct: float = 0.5
    max_daily_loss_pct: float = 2.0
    max_open_risk_pct: float = 1.5
    max_leverage: float = 3.0
    max_margin_pct: float = 60.0
    max_contracts_per_instrument: int = 10
    max_positions: int = 6
    max_correlated_exposure_pct: float = 40.0
    stop_loss_required: bool = True
    time_stop_minutes: int = 90
    slippage_tolerance_ticks: int = 2


class NewsFilterConfig(BaseModel):
    lookback_minutes: int = 180
    block_severity_threshold: str = "high"
    reduce_severity_threshold: str = "medium"
    sources: list[str] = []


class SignalEngineIssRetryConfig(BaseModel):
    max_attempts: int = 5
    base_backoff_ms: int = 200
    max_backoff_ms: int = 5000


class SignalEngineIssConfig(BaseModel):
    page_size: int = 100
    retry: SignalEngineIssRetryConfig = SignalEngineIssRetryConfig()


class SignalEngineDataConfig(BaseModel):
    bar_interval_sec: int = 60
    timezone: str = "Europe/Moscow"
    iss: SignalEngineIssConfig = SignalEngineIssConfig()


class SignalEngineAtrConfig(BaseModel):
    period: int = 14
    timeframe_sec: int = 300


class SignalEngineRealizedVolConfig(BaseModel):
    window_bars: int = 60


class SignalEngineVwapConfig(BaseModel):
    use_typical_price: bool = True
    reset: str = "session_start"


class SignalEngineWindowConfig(BaseModel):
    window_bars: int = 60


class SignalEngineFeaturesConfig(BaseModel):
    atr: SignalEngineAtrConfig = SignalEngineAtrConfig()
    realized_vol: SignalEngineRealizedVolConfig = SignalEngineRealizedVolConfig()
    vwap: SignalEngineVwapConfig = SignalEngineVwapConfig()
    zscore: SignalEngineWindowConfig = SignalEngineWindowConfig()
    rel_volume: SignalEngineWindowConfig = SignalEngineWindowConfig()


class SignalEngineVolatilityRegimeConfig(BaseModel):
    lookback_days: int = 20
    high_quantile: float = 0.60
    low_quantile: float = 0.40


class SignalEngineVacuumConfig(BaseModel):
    spread_ticks: int = 4
    depth_lots: float = 20.0


class SignalEngineLiquidityRegimeConfig(BaseModel):
    max_spread_ticks: int = 2
    min_depth_lots: float = 50.0
    vacuum: SignalEngineVacuumConfig = SignalEngineVacuumConfig()


class SignalEngineRegimesConfig(BaseModel):
    volatility: SignalEngineVolatilityRegimeConfig = SignalEngineVolatilityRegimeConfig()
    liquidity: SignalEngineLiquidityRegimeConfig = SignalEngineLiquidityRegimeConfig()


class SignalEngineOrbConfig(BaseModel):
    opening_range_min: int = 15
    buffer_atr_mult: float = 0.10
    buffer_ticks_min: int = 1
    tp_atr_mult: float = 1.0
    sl_atr_mult: float = 0.7
    horizon_min: int = 90
    require_high_vol: bool = True


class SignalEngineVwapMrConfig(BaseModel):
    z_enter: float = 2.0
    z_exit: float = 0.5
    sl_atr_mult: float = 0.8
    min_tp_ticks: int = 2
    horizon_min: int = 45


class SignalEngineMicroMomoConfig(BaseModel):
    ema_fast: int = 9
    ema_slow: int = 21
    rel_volume_min: float = 1.2
    tp_atr_mult: float = 0.8
    sl_atr_mult: float = 0.6
    horizon_min: int = 60


class SignalEngineStrategiesConfig(BaseModel):
    orb: SignalEngineOrbConfig = SignalEngineOrbConfig()
    vwap_mr: SignalEngineVwapMrConfig = SignalEngineVwapMrConfig()
    micro_momo: SignalEngineMicroMomoConfig = SignalEngineMicroMomoConfig()


class SignalEngineTripleBarrierConfig(BaseModel):
    on_same_bar_tp_sl: str = "worst_case"
    price_source: str = "ohlc"


class SignalEngineLabelingConfig(BaseModel):
    triple_barrier: SignalEngineTripleBarrierConfig = SignalEngineTripleBarrierConfig()


class SignalEngineTierThresholdConfig(BaseModel):
    mid: int = 100
    high: int = 500


class SignalEngineCalibrationConfig(BaseModel):
    method: str = "binning_ovr_renorm"
    bins: int = 15
    min_bin_count: int = 30
    smoothing_alpha: float = 1.0


class SignalEngineProbabilityConfig(BaseModel):
    method: str = "dirichlet_decay_v1"
    dirichlet_alpha: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0])
    decay_half_life_days: int = 30
    tier_thresholds: SignalEngineTierThresholdConfig = SignalEngineTierThresholdConfig()
    calibration: SignalEngineCalibrationConfig = SignalEngineCalibrationConfig()


class SignalEngineLiquidityPenaltyConfig(BaseModel):
    enable: bool = True
    depth_ref_lots: float = 100.0
    max_penalty_ticks: float = 2.0


class SignalEngineCostConfig(BaseModel):
    model: str = "ticks_v1"
    commission_ticks_per_side: float = 0.5
    slippage_ticks_per_side: float = 1.0
    spread_half_ticks_fallback: float = 1.0
    liquidity_penalty: SignalEngineLiquidityPenaltyConfig = SignalEngineLiquidityPenaltyConfig()


class SignalEngineGateConfig(BaseModel):
    forbid_windows_min: int = 5
    min_expected_return_ticks: float = 1.0


class SignalEngineRuntimeAdapterConfig(BaseModel):
    enabled: bool = False
    override_signal_fields: bool = True
    synthetic_history_cap: int = 2000


class SignalEngineTimeWindowConfig(BaseModel):
    start: str
    end: str


class SignalEngineMorningCalendarConfig(BaseModel):
    sessions: list[SignalEngineTimeWindowConfig] = Field(
        default_factory=lambda: [
            SignalEngineTimeWindowConfig(start="10:00", end="14:00"),
            SignalEngineTimeWindowConfig(start="14:05", end="18:50"),
            SignalEngineTimeWindowConfig(start="19:05", end="23:50"),
        ]
    )
    clearing_windows: list[SignalEngineTimeWindowConfig] = Field(
        default_factory=lambda: [
            SignalEngineTimeWindowConfig(start="14:00", end="14:05"),
            SignalEngineTimeWindowConfig(start="18:50", end="19:05"),
        ]
    )
    forbid_new_positions_margin_min: int = 5
    entry_expiry_policy: str = "EOD_BEFORE_EVENING_CLEARING"


class SignalEngineMorningDataConfig(BaseModel):
    d1_limit: int = 200
    h1_limit: int = 300
    m5_limit: int = 300


class SignalEngineMorningRegimeD1Config(BaseModel):
    ema_fast: int = 20
    ema_slow: int = 50
    adx_period: int = 14
    er_period: int = 20
    dir_band_atr_mult: float = 0.25
    adx_trend_min: float = 25.0
    adx_range_max: float = 18.0
    er_trend_min: float = 0.30
    er_range_max: float = 0.20
    atr_period: int = 14
    atr_rank_lookback: int = 60
    vol_high_pct: float = 0.70
    vol_low_pct: float = 0.30


class SignalEngineMorningRegimeH1Config(BaseModel):
    ema_fast: int = 20
    ema_slow: int = 50
    atr_period: int = 14
    dir_band_atr_mult: float = 0.20


class SignalEngineMorningLiquidityConfig(BaseModel):
    use_orderbook_if_available: bool = True
    spread_thin_ticks: int = 2
    spread_vacuum_ticks: int = 4
    depth_thin_lots: float = 50.0
    depth_vacuum_lots: float = 20.0


class SignalEngineMorningRegimeConfig(BaseModel):
    d1: SignalEngineMorningRegimeD1Config = SignalEngineMorningRegimeD1Config()
    h1: SignalEngineMorningRegimeH1Config = SignalEngineMorningRegimeH1Config()
    liquidity: SignalEngineMorningLiquidityConfig = SignalEngineMorningLiquidityConfig()


class SignalEngineMorningLevelsD1Config(BaseModel):
    donchian_period: int = 20
    pivots: bool = True


class SignalEngineMorningLevelsH1Config(BaseModel):
    swing_k: int = 2
    max_swings_each_side: int = 8
    box_hours: int = 6
    box_range_atr_mult: float = 1.2
    include_ema20_level: bool = True


class SignalEngineMorningLevelsConfig(BaseModel):
    merge_distance_ticks: int = 2
    d1: SignalEngineMorningLevelsD1Config = SignalEngineMorningLevelsD1Config()
    h1: SignalEngineMorningLevelsH1Config = SignalEngineMorningLevelsH1Config()


class SignalEngineMorningExecutionConfig(BaseModel):
    m5_atr_period: int = 14
    buffer_atr_mult: float = 0.10
    buffer_min_ticks: int = 1
    limit_slip_ticks: int = 2
    noise_warn_high: float = 2.5
    noise_warn_low: float = 0.4
    swing_k: int = 2


class SignalEngineMorningSetupsConfig(BaseModel):
    mode: str = "trend_first"
    max_setups_per_instrument: int = 2
    require_vol_not_low: bool = True
    pullback_max_dist_atr_mult: float = 1.0
    rr_default: float = 1.6
    min_target_ticks: int = 3
    max_risk_atr_mult: float = 1.2
    sl_atr_mult: float = 0.8
    qty_lots: int = 1
    horizon: str = "EOD"
    entry_tif: str = "GTT"
    entry_expiry_policy: str = "EOD_BEFORE_EVENING_CLEARING"
    entry_zone_offset_ticks: int = 0
    enable_cost_net_gate: bool = True
    estimated_round_trip_cost_ticks: float = 5.0
    min_reward_net_ticks: float = 2.0
    min_rr_net: float = 1.1
    min_reward_gross_ticks: float = 10.0


class SignalEngineMorningPlanConfig(BaseModel):
    timezone: str = "Europe/Moscow"
    calendar: SignalEngineMorningCalendarConfig = SignalEngineMorningCalendarConfig()
    data: SignalEngineMorningDataConfig = SignalEngineMorningDataConfig()
    regime: SignalEngineMorningRegimeConfig = SignalEngineMorningRegimeConfig()
    levels: SignalEngineMorningLevelsConfig = SignalEngineMorningLevelsConfig()
    execution: SignalEngineMorningExecutionConfig = SignalEngineMorningExecutionConfig()
    setups: SignalEngineMorningSetupsConfig = SignalEngineMorningSetupsConfig()


class SignalEngineConfig(BaseModel):
    data: SignalEngineDataConfig = SignalEngineDataConfig()
    features: SignalEngineFeaturesConfig = SignalEngineFeaturesConfig()
    regimes: SignalEngineRegimesConfig = SignalEngineRegimesConfig()
    strategies: SignalEngineStrategiesConfig = SignalEngineStrategiesConfig()
    labeling: SignalEngineLabelingConfig = SignalEngineLabelingConfig()
    probability: SignalEngineProbabilityConfig = SignalEngineProbabilityConfig()
    cost: SignalEngineCostConfig = SignalEngineCostConfig()
    gate: SignalEngineGateConfig = SignalEngineGateConfig()
    runtime_adapter: SignalEngineRuntimeAdapterConfig = SignalEngineRuntimeAdapterConfig()
    morning_plan: SignalEngineMorningPlanConfig = SignalEngineMorningPlanConfig()

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOEX_CARRY_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    moex: MoexIssConfig = MoexIssConfig()
    cbr: CbrConfig = CbrConfig()
    database: DatabaseConfig = DatabaseConfig()
    costs: CostsConfig = CostsConfig()
    taxes: TaxesConfig = TaxesConfig()
    strategy: StrategyConfig = StrategyConfig()
    spread_carry_alpha: SpreadCarryAlphaConfig = SpreadCarryAlphaConfig()
    aggregation: AggregationConfig = AggregationConfig()
    ui: UiConfig = UiConfig()
    telegram: TelegramConfig = TelegramConfig()
    data: DataConfig = DataConfig()
    environment: EnvironmentConfig = EnvironmentConfig()
    risk_profile: RiskProfileConfig = RiskProfileConfig()
    news_filter: NewsFilterConfig = NewsFilterConfig()
    signal_engine: SignalEngineConfig = SignalEngineConfig()


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge_dicts(base[key], value)
        else:
            base[key] = value
    return base


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "default.yaml"


def _drop_yaml_keys_overridden_by_env(config_data: dict[str, Any]) -> dict[str, Any]:
    """
    Remove YAML values that are explicitly overridden via environment variables.

    AppSettings receives YAML as init kwargs, which otherwise has higher priority
    than env in pydantic-settings resolution order.
    """

    updated = dict(config_data)
    env_prefix = "MOEX_CARRY_"
    env_delimiter = "__"

    for section_key in list(updated.keys()):
        section_value = updated.get(section_key)
        section_env_key = f"{env_prefix}{str(section_key).upper()}"

        # Full-section override, e.g. MOEX_CARRY_TELEGRAM='{"enabled": true}'.
        if section_env_key in os.environ:
            updated.pop(section_key, None)
            continue

        if not isinstance(section_value, dict):
            continue

        section_copy = dict(section_value)
        for field_key in list(section_copy.keys()):
            field_env_key = f"{section_env_key}{env_delimiter}{str(field_key).upper()}"
            if field_env_key in os.environ:
                section_copy.pop(field_key, None)

        if section_copy:
            updated[section_key] = section_copy
        else:
            updated.pop(section_key, None)

    return updated


def load_settings(config_path: Optional[str] = None) -> AppSettings:
    config_data: dict[str, Any] = {}
    default_path = _default_config_path()
    config_paths: list[Path] = []

    if default_path.exists():
        config_paths.append(default_path)
    if config_path:
        override_path = Path(config_path)
        if override_path.exists():
            config_paths.append(override_path)

    for path in config_paths:
        with path.open("r", encoding="utf-8") as handle:
            yaml_data = yaml.safe_load(handle) or {}
        if isinstance(yaml_data, dict):
            config_data = _merge_dicts(config_data, yaml_data)
    config_data = _drop_yaml_keys_overridden_by_env(config_data)
    return AppSettings(**config_data)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass
class RuntimePaths:
    data_dir: Path


def resolve_paths(settings: AppSettings) -> RuntimePaths:
    data_dir = Path(settings.data.data_dir)
    if not data_dir.is_absolute():
        data_dir = _repo_root() / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    return RuntimePaths(data_dir=data_dir)


