from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from moex_carry.backtest_v2.minute_portfolio_engine import (
    clear_minute_replay_tape_cache,
    minute_replay_tape_cache_size,
    prewarm_minute_replay_tape_cache,
    run_minute_portfolio_backtest,
)
from moex_carry.backtest_v2.engine import build_rebalance_config
from moex_carry.config_resolver import resolve_backtest_request
from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.domain.portfolio import PairSpec
from moex_carry.hpo.minute_period_pnl import compute_minute_window_metrics


@dataclass
class _DummyMinuteStore:
    data_dir: Path
    days: list[date]

    def get_calendar(self, start_date: date, end_date: date) -> list[date]:
        return [day for day in self.days if start_date <= day <= end_date]

    def get_key_rates(self):
        return []

    def get_stock_bars(self, as_of: date, secids):  # pragma: no cover - not used by minute engine
        del as_of, secids
        return []

    def get_fut_bars(self, as_of: date, secids):  # pragma: no cover - not used by minute engine
        del as_of, secids
        return []

    def get_dividends(self):  # pragma: no cover - not used by minute engine
        return []

    def get_events(self):  # pragma: no cover - not used by minute engine
        return {}


def test_minute_portfolio_engine_returns_portfolio_metrics(tmp_path):
    fixture = pd.read_csv("tests/fixtures/minute_replay/FLOT_FLH6.csv")
    fixture["date"] = pd.to_datetime(fixture["date"]).dt.date
    days = sorted(fixture["date"].unique().tolist())[:8]
    frame = fixture[fixture["date"].isin(days)].copy()

    out_dir = tmp_path / "output" / "intraday_minute_series"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "intraday_minute_series_FLOT_FLH6.csv"
    frame.to_csv(path, index=False)

    request = BacktestRequest()
    request.test.start_date = min(days)
    request.test.end_date = max(days)
    request.execution.mode = "INTRADAY_MINUTE"
    request.strategy.signal_exec_lag_days = 0
    request.strategy.execution_lag_minutes = 20
    request.strategy.execution_max_wait_minutes = 360
    request.strategy.entry_price_tolerance_pct = 0.02
    request.rebalance.cadence = "daily"
    request.universe.max_pairs = 1

    universe = [
        PairSpec(
            stock_secid="FLOT",
            future_secid="FLH6",
            expiry=date(2026, 3, 19),
            lot_size=1.0,
            multiplier=1.0,
            tick_size=0.01,
        )
    ]
    store = _DummyMinuteStore(data_dir=tmp_path, days=days)
    report = run_minute_portfolio_backtest(
        request=request,
        universe=universe,
        data_store=store,
    )
    assert len(report.equity_curve) == len(days)
    assert "PortfolioExcessAnn" in report.summary_metrics
    assert "PortfolioIdleRatio" in report.summary_metrics
    assert "PortfolioForcedExitRate" in report.summary_metrics
    assert "PortfolioUnfilledEntryRate" in report.summary_metrics
    assert report.execution_model["mode"] == "MINUTE_REPLAY"
    assert 0.0 <= float(report.summary_metrics["PortfolioIdleRatio"]) <= 1.0
    assert 0.0 <= float(report.summary_metrics["PortfolioUnfilledEntryRate"]) <= 1.0


def test_daily_cadence_maps_to_daily_soft_rebalance():
    request = BacktestRequest()
    request.rebalance.cadence = "daily"
    resolved = resolve_backtest_request(request).resolved_config
    config = build_rebalance_config(resolved)
    assert config.soft_rebalance_frequency == "DAILY"


def test_minute_portfolio_parity_single_pair_matches_pair_metrics(tmp_path):
    fixture = pd.read_csv("tests/fixtures/minute_replay/FLOT_FLH6.csv")
    fixture["date"] = pd.to_datetime(fixture["date"]).dt.date
    days = sorted(fixture["date"].unique().tolist())[:30]
    frame = fixture[fixture["date"].isin(days)].copy()

    out_dir = tmp_path / "output" / "intraday_minute_series"
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_dir / "intraday_minute_series_FLOT_FLH6.csv", index=False)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [{"SECID": "FLOT", "SHORTNAME": "FLOT", "CURRENCYID": "RUB", "BOARDID": "TQBR"}]
    ).to_csv(raw_dir / "shares.csv", index=False)
    pd.DataFrame(
        [
            {
                "SECID": "FLH6",
                "ASSETCODE": "FLOT",
                "LASTTRADEDATE": "2026-03-19",
                "LOTVOLUME": 1,
                "MINSTEP": 0.01,
                "MULTIPLIER": 1,
            }
        ]
    ).to_csv(raw_dir / "futures.csv", index=False)
    pd.DataFrame([{"date": str(min(days)), "rate": 0.1}, {"date": str(max(days)), "rate": 0.1}]).to_csv(
        raw_dir / "key_rates.csv",
        index=False,
    )

    request = BacktestRequest()
    request.test.start_date = min(days)
    request.test.end_date = max(days)
    request.execution.mode = "INTRADAY_MINUTE"
    request.execution.execution_model = "MINUTE_REPLAY"
    request.execution.minute_fail_fast = True
    request.strategy.signal_exec_lag_days = 0
    request.strategy.execution_lag_minutes = 20
    request.strategy.execution_max_wait_minutes = 360
    request.strategy.entry_price_tolerance_pct = 0.02
    request.strategy.min_DTE_entry = 1
    request.strategy.close_buffer_days = 0
    request.strategy.H_max_days = 20
    request.strategy.w_floor = 0.5
    request.strategy.w_alpha = 0.5
    request.rates.r_cb_annual = 0.0
    request.rates.r_fund_annual = 0.0
    request.rates.r_disc_annual = 0.0
    request.rebalance.cadence = "daily"
    request.rebalance.target_utilization = 1.0
    request.universe.include_stocks = ["FLOT"]
    request.universe.include_futures = ["FLH6"]
    request.universe.max_pairs = 1

    pair_metrics = compute_minute_window_metrics(
        request=request,
        start_date=min(days),
        end_date=max(days),
        data_dir=tmp_path,
    )
    universe = [
        PairSpec(
            stock_secid="FLOT",
            future_secid="FLH6",
            expiry=date(2026, 3, 19),
            lot_size=1.0,
            multiplier=1.0,
            tick_size=0.01,
        )
    ]
    store = _DummyMinuteStore(data_dir=tmp_path, days=days)
    report = run_minute_portfolio_backtest(
        request=request,
        universe=universe,
        data_store=store,
    )

    assert len(report.trades) == int(pair_metrics["MinuteTradesClosedTotal"])
    assert float(report.summary_metrics["CAGR"]) == pytest.approx(float(pair_metrics["MinuteRealizedAnnualMean"]))
    assert float(report.summary_metrics["PortfolioForcedExitRate"]) == pytest.approx(
        float(pair_metrics["MinuteForcedExitRateMean"])
    )


def test_minute_portfolio_tape_cache_prewarm_and_clear(tmp_path):
    fixture = pd.read_csv("tests/fixtures/minute_replay/FLOT_FLH6.csv")
    fixture["date"] = pd.to_datetime(fixture["date"]).dt.date
    days = sorted(fixture["date"].unique().tolist())[:8]
    frame = fixture[fixture["date"].isin(days)].copy()

    out_dir = tmp_path / "output" / "intraday_minute_series"
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_dir / "intraday_minute_series_FLOT_FLH6.csv", index=False)

    request = BacktestRequest()
    request.test.start_date = min(days)
    request.test.end_date = max(days)
    request.execution.mode = "INTRADAY_MINUTE"
    request.execution.execution_model = "MINUTE_REPLAY"
    request.execution.minute_fail_fast = True
    request.strategy.signal_exec_lag_days = 0
    request.strategy.execution_lag_minutes = 20
    request.strategy.execution_max_wait_minutes = 360
    request.strategy.entry_price_tolerance_pct = 0.02
    request.strategy.min_DTE_entry = 1
    request.strategy.close_buffer_days = 0
    request.strategy.H_max_days = 20
    request.rebalance.cadence = "daily"
    request.universe.max_pairs = 1

    universe = [
        PairSpec(
            stock_secid="FLOT",
            future_secid="FLH6",
            expiry=date(2026, 3, 19),
            lot_size=1.0,
            multiplier=1.0,
            tick_size=0.01,
        )
    ]
    store = _DummyMinuteStore(data_dir=tmp_path, days=days)

    clear_minute_replay_tape_cache()
    assert minute_replay_tape_cache_size() == 0

    first = prewarm_minute_replay_tape_cache(request=request, universe=universe, data_store=store)
    assert first["pairs_total"] == 1
    assert first["cache_misses"] == 1
    assert first["cache_hits"] == 0
    assert minute_replay_tape_cache_size() >= 1

    second = prewarm_minute_replay_tape_cache(request=request, universe=universe, data_store=store)
    assert second["pairs_total"] == 1
    assert second["cache_hits"] == 1

    clear_minute_replay_tape_cache()
    assert minute_replay_tape_cache_size() == 0
