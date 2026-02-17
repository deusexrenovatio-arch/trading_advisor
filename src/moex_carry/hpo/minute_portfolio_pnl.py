from __future__ import annotations

from datetime import date
from pathlib import Path

from moex_carry.backtest_v2.minute_portfolio_engine import run_minute_portfolio_backtest
from moex_carry.backtest_v2.runtime import build_universe_from_request
from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.data.history_store import HistoryDataStore


def compute_minute_portfolio_window_metrics(
    *,
    request: BacktestRequest,
    data_dir: Path,
    start_date: date,
    end_date: date,
    metric_start: date,
    metric_end: date,
) -> dict[str, float]:
    scoped_request = _with_dates(request, start_date=start_date, end_date=end_date)
    universe = build_universe_from_request(scoped_request, data_dir)
    data_store = HistoryDataStore(
        data_dir,
        universe,
        start_date=scoped_request.test.start_date,
        end_date=scoped_request.test.end_date,
    )
    report = run_minute_portfolio_backtest(
        request=scoped_request,
        universe=universe,
        data_store=data_store,
        metric_start=metric_start,
        metric_end=metric_end,
    )
    return dict(report.summary_metrics)


def _with_dates(request: BacktestRequest, *, start_date: date, end_date: date) -> BacktestRequest:
    payload = request.model_dump(mode="python")
    payload.setdefault("test", {})["start_date"] = start_date
    payload.setdefault("test", {})["end_date"] = end_date
    return BacktestRequest.model_validate(payload)
