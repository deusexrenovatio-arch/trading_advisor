from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class RiskProfile:
    account_equity: float
    account_currency: str
    max_risk_per_trade_pct: float
    max_daily_loss_pct: float
    max_open_risk_pct: float
    max_leverage: float
    max_margin_pct: float
    max_contracts_per_instrument: int
    max_positions: int
    max_correlated_exposure_pct: float
    stop_loss_required: bool
    time_stop_minutes: int
    slippage_tolerance_ticks: int


@dataclass
class NewsItem:
    item_id: str
    timestamp: datetime
    source: str
    title: str
    severity: str
    impact_score: float


@dataclass
class DecisionRecord:
    decision_log: dict[str, Any]
    decision_view: dict[str, Any]
