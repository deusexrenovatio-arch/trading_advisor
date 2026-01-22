import argparse
from datetime import date

from moex_carry.config import load_settings
from moex_carry.logging import configure_logging


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=str, default=None, help="Path to YAML config")
    parser.add_argument("--log-level", type=str, default="INFO")


def main() -> None:
    parser = argparse.ArgumentParser(prog="moex-carry")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch", help="Download MOEX + CBR data")
    _add_common_args(fetch_parser)

    compute_parser = subparsers.add_parser("compute", help="Compute pair ranking + signals")
    _add_common_args(compute_parser)

    backtest_parser = subparsers.add_parser("backtest", help="Run EOD backtest")
    _add_common_args(backtest_parser)

    paper_parser = subparsers.add_parser(
        "paper", help="Run paper decision pipeline (decision log + view)"
    )
    _add_common_args(paper_parser)

    signals_parser = subparsers.add_parser("signals", help="Run live signal cycle")
    _add_common_args(signals_parser)
    signals_parser.add_argument("--max-pairs", type=int, default=None)
    signals_parser.add_argument("--no-csv", action="store_true")
    signals_parser.add_argument(
        "--history-days",
        type=int,
        default=0,
        help="Backfill signal history for the last N days.",
    )

    ui_parser = subparsers.add_parser("ui", help="Run Dash UI")
    _add_common_args(ui_parser)

    history_parser = subparsers.add_parser("history", help="Incremental historical data collection")
    _add_common_args(history_parser)
    history_parser.add_argument(
        "--kind",
        type=str,
        choices=["shares", "futures", "both"],
        default="both",
        help="Which dataset to collect.",
    )
    history_parser.add_argument("--symbols-per-run", type=int, default=20)
    history_parser.add_argument("--max-days-per-run", type=int, default=60)
    history_parser.add_argument("--chunk-days", type=int, default=30)
    history_parser.add_argument("--start-date", type=str, default="2010-01-01")
    history_parser.add_argument("--end-date", type=str, default=None)
    history_parser.add_argument("--sleep-sec", type=float, default=0.2)
    history_parser.add_argument("--retries", type=int, default=3)
    history_parser.add_argument("--retry-backoff-sec", type=float, default=2.0)

    args = parser.parse_args()
    configure_logging(args.log_level)
    settings = load_settings(args.config)

    if args.command == "fetch":
        from moex_carry.pipeline import fetch_data

        fetch_data(settings)
    elif args.command == "compute":
        from moex_carry.pipeline import compute_pairs

        compute_pairs(settings)
    elif args.command == "backtest":
        from moex_carry.pipeline import run_backtest

        run_backtest(settings)
    elif args.command == "paper":
        from moex_carry.pipeline import run_paper_trading

        run_paper_trading(settings)
    elif args.command == "signals":
        from moex_carry.pipeline import backfill_signal_history, run_signal_cycle

        if args.history_days and args.history_days > 0:
            backfill_signal_history(
                settings,
                days=args.history_days,
                max_pairs=args.max_pairs,
                save_csv_latest=not args.no_csv,
            )
        else:
            run_signal_cycle(settings, max_pairs=args.max_pairs, save_csv=not args.no_csv)
    elif args.command == "ui":
        from moex_carry.ui.app import run_ui

        run_ui(settings)
    elif args.command == "history":
        from moex_carry.history import collect_history

        start_date = date.fromisoformat(args.start_date) if args.start_date else None
        end_date = date.fromisoformat(args.end_date) if args.end_date else None
        collect_history(
            settings,
            kind=args.kind,
            symbols_per_run=args.symbols_per_run,
            max_days_per_run=args.max_days_per_run,
            chunk_days=args.chunk_days,
            start_date=start_date,
            end_date=end_date,
            sleep_sec=args.sleep_sec,
            retries=args.retries,
            retry_backoff_sec=args.retry_backoff_sec,
        )


if __name__ == "__main__":
    main()
