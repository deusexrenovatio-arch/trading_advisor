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
    sequential_entry_enabled: bool = False
    sequential_entry_first_leg: str = "future"
    sequential_entry_second_leg_max_wait_minutes: int = 5
    sequential_entry_unwind_penalty_bps: float = 0.0
    sequential_exit_enabled: bool = False
    sequential_exit_first_leg: str = "future"
    sequential_exit_second_leg_max_wait_minutes: int = 5
    sequential_exit_force_penalty_bps: Optional[float] = None
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
    signal_refresh_singleton: bool = True
    signal_refresh_lease_sec: int = 180
    signal_refresh_lease_renew_sec: int = 30
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
    ff_news_bridge_enabled: bool = False
    ff_news_bridge_persist_links_on_read: bool = False
    ff_news_model_advisory_enabled: bool = False
    ff_news_model_decision_weight_enabled: bool = False
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
    shock_alerts_enabled: bool = False
    shock_feed_path: str | None = None
    shock_primary_min_z: float = 2.5
    shock_aftershock_min_z: float = 2.0
    shock_topic_reopen_after_hours: int = 168
    shock_aftershock_cooldown_minutes: int = 60
    shock_max_alerts_per_cycle: int = 20
    shock_sent_fingerprint_ttl_hours: int = 24 * 21


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
    live_ingest_enabled: bool = False
    live_db_url: str = "sqlite:///./data/news_livecheck_ng.db"
    live_min_impact_score: float = 0.35
    live_min_confidence: float = 0.9
    live_max_items: int = 200
    lookback_minutes: int = 180
    block_severity_threshold: str = "high"
    reduce_severity_threshold: str = "medium"
    sources: list[str] = []
    enforce_source_allowlist: bool = False


class NewsIngestConfig(BaseModel):
    class CommodityProfile(BaseModel):
        ticker: str
        name: str
        gdelt_query: str
        newsapi_query: str | None = None
        rss_urls: list[str] = []
        price_source: str = "yfinance"
        price_symbol: str = ""
        price_interval: str = "1d"

    @staticmethod
    def _default_profiles() -> list["NewsIngestConfig.CommodityProfile"]:
        return [
            NewsIngestConfig.CommodityProfile(
                ticker="BRN",
                name="Brent Crude Oil",
                gdelt_query=(
                    '("brent crude" OR "brent oil" OR "ice brent" OR "oil prices" OR opec '
                    'OR "strait of hormuz" OR iran OR israel OR "middle east conflict" '
                    'OR "red sea shipping" OR houthi OR "shipping disruption")'
                ),
                newsapi_query=(
                    '("brent" OR "crude oil" OR "oil prices" OR opec OR "strait of hormuz" OR iran '
                    'OR israel OR houthi OR "red sea shipping" OR "middle east conflict") '
                    "AND (oil OR brent OR crude OR tanker OR opec)"
                ),
                rss_urls=[
                    "https://news.google.com/rss/search?q=Brent+crude+oil+futures",
                ],
                price_source="yfinance",
                price_symbol="BZ=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="GOLD",
                name="Gold",
                gdelt_query=(
                    '("gold futures" OR "gold price" OR bullion OR "safe haven" OR "real yields" '
                    'OR "middle east conflict" OR iran OR israel OR "geopolitical risk" '
                    'OR "war escalation" OR "risk-off")'
                ),
                newsapi_query=(
                    '("gold" OR bullion OR "safe haven" OR "real yields" OR "fed rates" '
                    'OR iran OR israel OR "middle east conflict" OR "geopolitical risk" '
                    'OR "war escalation" OR "risk-off") '
                    "AND (gold OR bullion OR xau OR \"safe haven\")"
                ),
                rss_urls=[
                    "https://news.google.com/rss/search?q=gold+futures",
                ],
                price_source="yfinance",
                price_symbol="GC=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="NG_US",
                name="US Natural Gas",
                gdelt_query=(
                    '("natural gas" OR "henry hub" OR "nymex gas" OR "us lng" OR "eia storage" '
                    'OR "freeze-off" OR "us weather gas" OR "arctic blast" '
                    'OR "strait of hormuz" OR iran OR israel OR "lng shipping disruption")'
                ),
                newsapi_query=(
                    '("natural gas" OR "henry hub" OR "nymex gas" OR "eia storage" OR "freeze-off" '
                    'OR "arctic blast" OR "us lng exports" OR "strait of hormuz" OR iran OR israel '
                    'OR "lng shipping disruption") '
                    "AND (\"natural gas\" OR \"henry hub\" OR lng OR feedgas)"
                ),
                rss_urls=[
                    "https://news.google.com/rss/search?q=henry+hub+natural+gas+futures",
                ],
                price_source="yfinance",
                price_symbol="NG=F",
                price_interval="1d",
            ),
        ]

    enabled: bool = False
    rss_urls: list[str] = []
    max_items_per_run: int = 100
    gdelt_enabled: bool = True
    gdelt_max_records_per_call: int = 250
    gdelt_backfill_max_pages_per_window: int = 8
    gdelt_min_request_interval_sec: float = 5.2
    gdelt_request_timeout_sec: int = 40
    newsapi_enabled: bool = False
    newsapi_base_url: str = "https://newsapi.org/v2/everything"
    newsapi_api_key_env: str = "NEWSAPI_API_KEY"
    newsapi_api_key: str | None = None
    newsapi_language: str = "en"
    newsapi_sort_by: str = "publishedAt"
    newsapi_domains: list[str] = []
    newsapi_max_records_per_call: int = 100
    newsapi_backfill_max_pages_per_window: int = 2
    newsapi_request_timeout_sec: int = 30
    newsapi_daily_limit: int = 100
    newsapi_daily_state_path: str = "./data/state/newsapi_usage.json"
    backfill_start_date: str = "2018-01-01"
    backfill_chunk_days: int = 7
    backfill_max_windows_per_commodity: int = 0
    backfill_window_order: str = "chronological"
    backfill_shock_bar_minutes: int = 60
    qc_min_news_per_ticker: int = 500
    qc_min_price_points_per_ticker: int = 500
    commodity_profiles: list[CommodityProfile] = Field(default_factory=_default_profiles)


class NewsModelsConfig(BaseModel):
    enabled_models: list[str] = ["finbert", "nli"]
    primary_model: str = "finbert"
    finbert_model_name: str = "ProsusAI/finbert"
    nli_model_name: str = "facebook/bart-large-mnli"
    multilingual_nli_model_name: str = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
    model_version: str = "v1"
    inference_batch_size: int = 16
    inference_text_max_chars: int = 2000
    inference_thread_cap: int = 0
    calibration_mode: str = "none"
    calibration_min_train_samples: int = 30
    epsilon_default: float = 0.0005
    horizons: list[str] = ["5m", "1h", "4h", "1d", "5d"]
    promotion_min_accuracy: float = 0.70
    promotion_min_coverage: float = 0.20
    promotion_max_brier: float = 0.25
    promotion_min_sample_count: int = 30
    promotion_min_ticker_stability: float = 0.55
    decision_weight_quality_horizon: str = "1h"
    decision_weight_quality_max_age_hours: int = 72
    decision_weight_rollout_mode: str = "limited"
    decision_weight_min_sample_size: int = 3
    decision_weight_limited_max_deviation: float = 0.25
    decision_weight_signal_threshold: float = 0.12
    decision_weight_min_impact: float = 0.6
    decision_weight_reduce_factor: float = 0.5
    decision_weight_boost_factor: float = 1.1
    target_mode_default: str = "legacy"
    target_v2_processing_lag_sec: int = 60
    target_v2_use_midpoint: bool = True
    target_v2_market_min_clean_events_5m: int = 400
    target_v2_market_min_clean_events_1h: int = 300
    target_v2_market_min_clean_events_4h: int = 250
    target_v2_market_min_clean_events_1d: int = 200


class NewsEventsConfig(BaseModel):
    enabled: bool = True
    cluster_version: str = "det-v1"
    cluster_window_hours: int = 48
    similarity_threshold: float = 0.35
    resolve_after_hours: int = 72
    anchor_seed_enabled: bool = True
    anchor_link_enabled: bool = True
    anchor_cluster_version: str = "anchor-scheduled-v1"
    anchor_match_window_minutes: int = 90
    anchor_seed_padding_days: int = 2
    anchor_episode_seed_enabled: bool = False
    anchor_episode_cluster_version: str = "anchor-episodic-v1"
    anchor_episode_sources: list[str] = ["nws_alerts", "nhc", "ukmto"]
    anchor_episode_match_window_minutes: int = 240
    anchor_request_timeout_sec: int = 20
    anchor_user_agent: str = "moex-carry/0.1 (+news-anchor)"
    anchor_nws_url: str = "https://api.weather.gov/alerts/active?event=Hurricane%20Warning,Storm%20Warning,Tropical%20Storm%20Warning"
    anchor_nhc_url: str = "https://www.nhc.noaa.gov/CurrentStorms.json"
    anchor_ukmto_url: str = "https://www.ukmto.org/recent-incidents"
    anchor_bsee_url: str = "https://www.bsee.gov/resources-tools/planning-preparedness/hurricane/hurricane-history"
    anchor_panama_url: str = "https://pancanal.com/en/maritime-services/advisory-to-shipping/"
    anchor_suez_url: str = "https://www.suezcanal.gov.eg/English/Navigation/NavigationCirculars/Pages/default.aspx"
    anchor_fred_release_url: str = "https://api.stlouisfed.org/fred/release/dates"
    anchor_fred_release_ids: list[int] = []
    anchor_fred_api_key_env: str = "FRED_API_KEY"


class NewsLlmConfig(BaseModel):
    enabled: bool = False
    full_pass_enabled: bool = False
    provider: str = "openai"
    model_id: str = "gpt-5-mini"
    api_base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    prompt_version: str = "news-v1"
    label_version: str = "v1"
    max_items_per_run: int = 50
    max_input_chars: int = 6000
    max_output_tokens: int = 512
    max_calls_per_run: int = 0
    max_prompt_tokens_per_run: int = 0
    max_completion_tokens_per_run: int = 0
    max_total_tokens_per_run: int = 0
    request_timeout_sec: int = 45
    max_retries: int = 2
    retry_backoff_sec: float = 1.5
    temperature: float = 0.0
    top_impact_priority: bool = True
    min_impact_for_priority: float = 0.0


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
    news_ingest: NewsIngestConfig = NewsIngestConfig()
    news_models: NewsModelsConfig = NewsModelsConfig()
    news_events: NewsEventsConfig = NewsEventsConfig()
    news_llm: NewsLlmConfig = NewsLlmConfig()


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

