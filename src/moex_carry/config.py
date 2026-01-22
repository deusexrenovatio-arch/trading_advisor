from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class MoexIssConfig(BaseModel):
    base_url: str = "https://iss.moex.com"
    engine_shares: str = "stock"
    market_shares: str = "shares"
    shares_board: str = "TQBR"
    engine_futures: str = "futures"
    market_futures: str = "forts"
    futures_board: str = "RFUD"
    request_timeout_sec: int = 20


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
    aggregation: AggregationConfig = AggregationConfig()
    ui: UiConfig = UiConfig()
    data: DataConfig = DataConfig()
    environment: EnvironmentConfig = EnvironmentConfig()
    risk_profile: RiskProfileConfig = RiskProfileConfig()
    news_filter: NewsFilterConfig = NewsFilterConfig()


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge_dicts(base[key], value)
        else:
            base[key] = value
    return base


def load_settings(config_path: Optional[str] = None) -> AppSettings:
    config_data: dict[str, Any] = {}
    if config_path:
        path = Path(config_path)
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                yaml_data = yaml.safe_load(handle) or {}
            if isinstance(yaml_data, dict):
                config_data = _merge_dicts(config_data, yaml_data)
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
