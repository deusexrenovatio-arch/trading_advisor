import argparse
import json
from datetime import date
from pathlib import Path

import yaml

from moex_carry.config import load_settings, resolve_paths
from moex_carry.logging import configure_logging
from moex_carry.cli_news_handlers import handle_news_command
from moex_carry.cli_news_parsers import register_news_subcommands


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=str, default=None, help="Path to YAML config")
    parser.add_argument("--log-level", type=str, default="INFO")


def _load_request_payload(path: str | None) -> dict:
    if not path:
        return {}
    payload_path = Path(path)
    if not payload_path.exists():
        raise FileNotFoundError(f"Request file not found: {path}")
    content = payload_path.read_text(encoding="utf-8")
    data = yaml.safe_load(content) or {}
    if not isinstance(data, dict):
        raise ValueError("Request payload must be a mapping object")
    return data


def _parse_precompute(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"auto", ""}:
        return None
    if lowered in {"true", "1", "yes", "y"}:
        return True
    if lowered in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"Unsupported precompute flag: {value}")


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

    telegram_parser = subparsers.add_parser("telegram_bot", help="Run Telegram signal worker")
    _add_common_args(telegram_parser)

    backtest_v2_parser = subparsers.add_parser("backtest_v2", help="Run Backtest v2")
    _add_common_args(backtest_v2_parser)
    backtest_v2_parser.add_argument("--request", type=str, default=None, help="Path to BacktestRequest YAML/JSON")
    backtest_v2_parser.add_argument("--start-date", type=str, default=None)
    backtest_v2_parser.add_argument("--end-date", type=str, default=None)
    backtest_v2_parser.add_argument(
        "--precompute",
        type=str,
        default="auto",
        help="auto|true|false (default: auto)",
    )
    backtest_v2_parser.add_argument("--json", action="store_true", help="Print full report as JSON")

    forward_start_parser = subparsers.add_parser("forward_start", help="Initialize forward paper run")
    _add_common_args(forward_start_parser)
    forward_start_parser.add_argument("--request", type=str, default=None, help="Path to ForwardTestRequest YAML/JSON")
    forward_start_parser.add_argument("--run-id", type=str, default=None)

    forward_status_parser = subparsers.add_parser("forward_status", help="Show forward run status")
    _add_common_args(forward_status_parser)
    forward_status_parser.add_argument("--run-id", type=str, default=None)

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

    register_news_subcommands(subparsers, _add_common_args)
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
    elif handle_news_command(args, settings):
        return
    elif args.command == "ui":
        from moex_carry.ui.app import run_ui

        run_ui(settings)
    elif args.command == "telegram_bot":
        from moex_carry.integrations.telegram_worker import run_telegram_worker

        run_telegram_worker(settings)
    elif args.command == "backtest_v2":
        from moex_carry.backtest_v2.runtime import run_backtest_v2_cached, serialize_backtest_report
        from moex_carry.contracts.strategy_test import BacktestRequest

        payload = _load_request_payload(args.request)
        request = BacktestRequest.model_validate(payload) if payload else BacktestRequest()
        if args.start_date:
            request.test.start_date = date.fromisoformat(args.start_date)
        if args.end_date:
            request.test.end_date = date.fromisoformat(args.end_date)
        precompute = _parse_precompute(args.precompute)
        data_dir = resolve_paths(settings).data_dir
        report = run_backtest_v2_cached(request, data_dir, precompute=precompute)
        if args.json:
            print(json.dumps(serialize_backtest_report(report), ensure_ascii=False, default=str))
        else:
            summary = {"summary_metrics": report.summary_metrics, "trades": len(report.trades)}
            print(json.dumps(summary, ensure_ascii=False, default=str))
    elif args.command == "forward_start":
        from moex_carry.contracts.strategy_test import ForwardTestRequest
        from moex_carry.forward.runtime import start_forward_run

        payload = _load_request_payload(args.request)
        request = ForwardTestRequest.model_validate(payload) if payload else ForwardTestRequest()
        data_dir = resolve_paths(settings).data_dir
        info = start_forward_run(request, data_dir, run_id=args.run_id)
        print(json.dumps(info, ensure_ascii=False, default=str))
    elif args.command == "forward_status":
        from moex_carry.forward.runtime import load_forward_status

        data_dir = resolve_paths(settings).data_dir
        status = load_forward_status(data_dir, run_id=args.run_id)
        print(json.dumps(status, ensure_ascii=False, default=str))
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
