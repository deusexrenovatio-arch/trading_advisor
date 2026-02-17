from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from moex_carry.backtest_v2 import prewarm_minute_replay_tape_cache
from moex_carry.backtest_v2.runtime import build_universe_from_request
from moex_carry.config import load_settings
from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.data.history_store import HistoryDataStore


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover
        raise argparse.ArgumentTypeError(f"invalid date: {value}") from exc


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Prewarm minute replay tape cache for portfolio runtime.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--data-dir", default="", help="Override data directory.")
    parser.add_argument("--from-date", type=_parse_iso_date, required=True, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--till-date", type=_parse_iso_date, required=True, help="End date (YYYY-MM-DD).")
    parser.add_argument("--include-stocks", default="", help="Comma-separated stock secids.")
    parser.add_argument("--include-futures", default="", help="Comma-separated future secids.")
    parser.add_argument("--max-pairs", type=int, default=0, help="Max pairs to prewarm (0 = all).")
    parser.add_argument("--minute-fail-fast", action="store_true", help="Fail if minute series missing.")
    args = parser.parse_args()

    settings = load_settings(args.config)
    data_dir = Path(args.data_dir or settings.data.data_dir)

    request = BacktestRequest()
    request.test.start_date = args.from_date
    request.test.end_date = args.till_date
    request.execution.mode = "INTRADAY_MINUTE"
    request.execution.execution_model = "MINUTE_REPLAY"
    request.execution.minute_fail_fast = bool(args.minute_fail_fast)
    if args.max_pairs and args.max_pairs > 0:
        request.universe.max_pairs = int(args.max_pairs)
    stocks = _split_csv(args.include_stocks)
    futures = _split_csv(args.include_futures)
    if stocks:
        request.universe.include_stocks = stocks
    if futures:
        request.universe.include_futures = futures

    universe = build_universe_from_request(request, data_dir)
    data_store = HistoryDataStore(
        data_dir,
        universe,
        start_date=request.test.start_date,
        end_date=request.test.end_date,
    )
    stats = prewarm_minute_replay_tape_cache(request=request, universe=universe, data_store=data_store)
    payload = {
        "data_dir": str(data_dir),
        "from_date": request.test.start_date.isoformat() if request.test.start_date else None,
        "till_date": request.test.end_date.isoformat() if request.test.end_date else None,
        **stats,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
