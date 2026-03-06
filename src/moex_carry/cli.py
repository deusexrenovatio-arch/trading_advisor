import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from moex_carry.cli_news_handlers import handle_news_command
from moex_carry.cli_news_runtime_handlers import handle_news_runtime_command
from moex_carry.config import load_settings, resolve_paths
from moex_carry.logging import configure_logging


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


def _parse_utc_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_shock_pack_name(
    min_abs_z: float,
    *,
    causal_only: bool,
    candidate_sources: tuple[str, ...] | None,
) -> str:
    z_tag = str(min_abs_z).replace(".", "p")
    if not causal_only and not candidate_sources:
        return f"shock_label_pack_zge{z_tag}.jsonl"
    mode = "causal" if causal_only else "direction"
    source_tag = "any" if not candidate_sources else "-".join(candidate_sources)
    return f"shock_label_pack_{mode}_{source_tag}_zge{z_tag}.jsonl"


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

    news_ingest_parser = subparsers.add_parser(
        "news_ingest",
        help="Ingest commodity news from GDELT/NewsAPI and score impact",
    )
    _add_common_args(news_ingest_parser)
    news_ingest_parser.add_argument(
        "--news-config",
        type=str,
        default="configs/news-livecheck-ng.yaml",
        help="Path to news ingestion YAML config.",
    )
    news_ingest_parser.add_argument(
        "--mode",
        type=str,
        choices=["live", "backfill"],
        default="live",
        help="Ingestion mode.",
    )

    news_compare_parser = subparsers.add_parser(
        "news_mode_compare",
        help="Compare current broad-first vs proposed root-event news matching",
    )
    _add_common_args(news_compare_parser)
    news_compare_parser.add_argument("--input-csv", type=str, required=True)
    news_compare_parser.add_argument("--output-dir", type=str, default=None)
    news_compare_parser.add_argument("--max-delay-min", type=float, default=60.0)
    news_compare_parser.add_argument("--broad-min-relevance", type=float, default=1.0)
    news_compare_parser.add_argument("--v2-min-relevance", type=float, default=0.4)

    shock_episode_parser = subparsers.add_parser(
        "shock_episode_analysis",
        help="Analyze primary and aftershock capture for current/proposed news matching modes",
    )
    _add_common_args(shock_episode_parser)
    shock_episode_parser.add_argument("--input-csv", type=str, required=True)
    shock_episode_parser.add_argument("--output-dir", type=str, default=None)
    shock_episode_parser.add_argument("--start-ts", type=str, default=None)
    shock_episode_parser.add_argument("--end-ts", type=str, default=None)
    shock_episode_parser.add_argument("--max-delay-min", type=float, default=60.0)
    shock_episode_parser.add_argument("--broad-min-relevance", type=float, default=1.0)
    shock_episode_parser.add_argument("--v2-min-relevance", type=float, default=0.4)
    shock_episode_parser.add_argument("--primary-z", type=float, default=2.5)
    shock_episode_parser.add_argument("--aftershock-z", type=float, default=2.0)
    shock_episode_parser.add_argument("--episode-window-min", type=int, default=360)
    shock_episode_parser.add_argument("--max-gap-min", type=int, default=120)
    shock_episode_parser.add_argument("--same-direction-aftershock-only", action="store_true")

    shock_pack_parser = subparsers.add_parser(
        "shock_label_pack",
        help="Build high-impact shock label pack for Chat Pro annotation",
    )
    _add_common_args(shock_pack_parser)
    shock_pack_parser.add_argument("--input-csv", type=str, required=True)
    shock_pack_parser.add_argument("--output-dir", type=str, default=None)
    shock_pack_parser.add_argument("--start-ts", type=str, default=None)
    shock_pack_parser.add_argument("--end-ts", type=str, default=None)
    shock_pack_parser.add_argument("--min-abs-z", type=float, default=2.5)
    shock_pack_parser.add_argument("--max-tasks-total", type=int, default=1200)
    shock_pack_parser.add_argument("--max-tasks-per-day-symbol", type=int, default=20)
    shock_pack_parser.add_argument("--max-delay-min", type=float, default=60.0)
    shock_pack_parser.add_argument(
        "--candidate-source",
        action="append",
        choices=["root", "v2_clean", "broad", "none"],
        default=None,
        help="Primary candidate source filter; repeat for multiple values.",
    )
    shock_pack_parser.add_argument(
        "--causal-only",
        action="store_true",
        help="Build causal-only task pack (direction optional).",
    )

    shock_ingest_parser = subparsers.add_parser(
        "shock_labels_ingest",
        help="Ingest Chat Pro label JSONL and build silver shock dataset",
    )
    _add_common_args(shock_ingest_parser)
    shock_ingest_parser.add_argument("--tasks-jsonl", type=str, required=True)
    shock_ingest_parser.add_argument("--labels-jsonl", type=str, required=True)
    shock_ingest_parser.add_argument("--output-dir", type=str, default=None)
    shock_ingest_parser.add_argument("--min-confidence", type=float, default=0.60)

    silver_ingest_parser = subparsers.add_parser(
        "news_silver_ingest",
        help="Ingest Chat Pro event-level labels into SQLite silver store",
    )
    _add_common_args(silver_ingest_parser)
    silver_ingest_parser.add_argument("--labels-jsonl", action="append", type=str, required=True)
    silver_ingest_parser.add_argument("--tasks-jsonl", type=str, default=None)
    silver_ingest_parser.add_argument("--database-url", type=str, default="sqlite:///./data/news_livecheck_ng.db")
    silver_ingest_parser.add_argument("--data-dir", type=str, default="./data")
    silver_ingest_parser.add_argument("--source-tag", type=str, default="chatpro_event")
    silver_ingest_parser.add_argument("--min-confidence", type=float, default=0.60)
    silver_ingest_parser.add_argument("--min-relevance", type=float, default=0.50)

    shock_ready_parser = subparsers.add_parser(
        "news_shock_readiness",
        help="Run launch-readiness checks for shock-news workflow",
    )
    _add_common_args(shock_ready_parser)
    shock_ready_parser.add_argument("--input-csv", type=str, required=True)
    shock_ready_parser.add_argument("--output-dir", type=str, default=None)
    shock_ready_parser.add_argument("--start-ts", type=str, default=None)
    shock_ready_parser.add_argument("--end-ts", type=str, default=None)
    shock_ready_parser.add_argument("--max-delay-min", type=float, default=60.0)
    shock_ready_parser.add_argument("--primary-z", type=float, default=2.5)
    shock_ready_parser.add_argument("--aftershock-z", type=float, default=2.0)
    shock_ready_parser.add_argument("--episode-window-min", type=int, default=10080)
    shock_ready_parser.add_argument("--max-gap-min", type=int, default=2880)

    shock_rows_backfill_parser = subparsers.add_parser(
        "news_shock_backfill",
        help="Backfill news_shock_rows table by historical windows with cursor progression",
    )
    _add_common_args(shock_rows_backfill_parser)
    shock_rows_backfill_parser.add_argument("--news-config", type=str, default="configs/news-livecheck-ng.yaml")
    shock_rows_backfill_parser.add_argument("--cursor-key", type=str, default="shock_rows_backfill_cursor_utc")
    shock_rows_backfill_parser.add_argument("--start-ts", type=str, default="2025-01-01T00:00:00Z")
    shock_rows_backfill_parser.add_argument("--end-ts", type=str, default="")
    shock_rows_backfill_parser.add_argument("--window-hours", type=int, default=24)
    shock_rows_backfill_parser.add_argument("--windows-per-run", type=int, default=5)
    shock_rows_backfill_parser.add_argument("--bar-minutes", type=int, default=5)
    shock_rows_backfill_parser.add_argument("--min-abs-z", type=float, default=2.0)
    shock_rows_backfill_parser.add_argument("--rolling-window-bars", type=int, default=96)
    shock_rows_backfill_parser.add_argument("--rolling-min-bars", type=int, default=24)
    shock_rows_backfill_parser.add_argument("--max-delay-min", type=float, default=60.0)
    shock_rows_backfill_parser.add_argument("--strict-pre-shock-min", type=float, default=10.0)
    shock_rows_backfill_parser.add_argument("--broad-context-lookback-min", type=float, default=2880.0)
    shock_rows_backfill_parser.add_argument("--v2-min-relevance", type=float, default=0.4)
    shock_rows_backfill_parser.add_argument("--broad-min-relevance", type=float, default=0.2)
    shock_rows_backfill_parser.add_argument("--cross-commodity-min-relevance", type=float, default=0.8)
    shock_rows_backfill_parser.add_argument("--news-min-impact-score", type=float, default=0.35)
    shock_rows_backfill_parser.add_argument("--news-min-confidence", type=float, default=0.6)
    shock_rows_backfill_parser.add_argument("--news-max-items-per-symbol", type=int, default=3000)
    shock_rows_backfill_parser.add_argument("--front-contract-candidates", type=int, default=4)
    shock_rows_backfill_parser.add_argument("--history-padding-days", type=int, default=10)
    shock_rows_backfill_parser.add_argument("--root-reuse-lookback-min", type=float, default=2880.0)
    shock_rows_backfill_parser.add_argument("--root-min-fundamental-score", type=float, default=0.45)
    shock_rows_backfill_parser.add_argument("--root-min-cause-confidence", type=float, default=0.45)
    shock_rows_backfill_parser.add_argument("--aftershock-max-gap-min", type=float, default=2880.0)
    shock_rows_backfill_parser.add_argument("--enable-candidate-newsapi-enrichment", action="store_true")
    shock_rows_backfill_parser.add_argument("--enrichment-window-min", type=int, default=90)
    shock_rows_backfill_parser.add_argument("--enrichment-max-requests-per-symbol", type=int, default=4)
    shock_rows_backfill_parser.add_argument("--no-root-maintenance", action="store_true")
    shock_rows_backfill_parser.add_argument("--write-snapshot-csv", action="store_true")
    shock_rows_backfill_parser.add_argument("--snapshot-dir", type=str, default="data/output/shock_backfill_snapshots")

    root_cycle_parser = subparsers.add_parser(
        "news_root_cycle",
        help="Run unified root pipeline: ingest -> shock input -> root maintenance.",
    )
    _add_common_args(root_cycle_parser)
    root_cycle_parser.add_argument("--news-config", type=str, default="configs/news-livecheck-ng.yaml")
    root_cycle_parser.add_argument("--ingest-mode", type=str, choices=["live", "backfill"], default="live")
    root_cycle_parser.add_argument("--lookback-hours", type=int, default=6)
    root_cycle_parser.add_argument("--bar-minutes", type=int, default=5)
    root_cycle_parser.add_argument("--min-abs-z", type=float, default=2.0)
    root_cycle_parser.add_argument("--root-min-fundamental-score", type=float, default=0.45)
    root_cycle_parser.add_argument("--root-min-cause-confidence", type=float, default=0.45)
    root_cycle_parser.add_argument("--aftershock-max-gap-min", type=float, default=2880.0)
    root_cycle_parser.add_argument("--enable-candidate-newsapi-enrichment", action="store_true")
    root_cycle_parser.add_argument("--enrichment-window-min", type=int, default=90)
    root_cycle_parser.add_argument("--enrichment-max-requests-per-symbol", type=int, default=4)
    root_cycle_parser.add_argument("--no-root-maintenance", action="store_true")

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
    elif handle_news_runtime_command(args, settings):
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
    elif args.command == "news_ingest":
        from moex_carry.news_live_runtime import NewsIngestConfig, run_news_ingest_cycle

        cfg = NewsIngestConfig.from_yaml(Path(args.news_config))
        result = run_news_ingest_cycle(config=cfg, mode=args.mode)
        print(json.dumps(result, ensure_ascii=False))
    elif args.command == "news_mode_compare":
        from moex_carry.news_mode_compare import CompareConfig, run_compare

        input_csv = Path(args.input_csv)
        if not input_csv.exists():
            raise FileNotFoundError(f"Input file not found: {input_csv}")
        if args.output_dir:
            output_dir = Path(args.output_dir)
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_dir = Path("data/output") / f"news_mode_compare_{stamp}"

        config = CompareConfig(
            max_delay_minutes=args.max_delay_min,
            broad_min_relevance=args.broad_min_relevance,
            v2_min_relevance=args.v2_min_relevance,
        )
        result = run_compare(input_csv=input_csv, output_dir=output_dir, config=config)
        payload = {key: str(value) for key, value in result.items()}
        print(json.dumps(payload, ensure_ascii=False))
    elif args.command == "shock_episode_analysis":
        from moex_carry.news_mode_compare import CompareConfig, compare_modes
        from moex_carry.shock_episodes import ShockEpisodeConfig, run_shock_episode_analysis

        input_csv = Path(args.input_csv)
        if not input_csv.exists():
            raise FileNotFoundError(f"Input file not found: {input_csv}")
        if args.output_dir:
            output_dir = Path(args.output_dir)
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_dir = Path("data/output") / f"shock_episode_analysis_{stamp}"

        input_df = pd.read_csv(input_csv)
        input_df["shock_ts_dt"] = pd.to_datetime(input_df["shock_ts"], utc=True, errors="coerce")
        if args.start_ts:
            start_ts = pd.to_datetime(args.start_ts, utc=True, errors="coerce")
            if pd.isna(start_ts):
                raise ValueError(f"Invalid --start-ts: {args.start_ts}")
            input_df = input_df[input_df["shock_ts_dt"] >= start_ts]
        if args.end_ts:
            end_ts = pd.to_datetime(args.end_ts, utc=True, errors="coerce")
            if pd.isna(end_ts):
                raise ValueError(f"Invalid --end-ts: {args.end_ts}")
            input_df = input_df[input_df["shock_ts_dt"] <= end_ts]
        if input_df.empty:
            raise ValueError("No rows available after date filtering.")

        compare_cfg = CompareConfig(
            max_delay_minutes=args.max_delay_min,
            broad_min_relevance=args.broad_min_relevance,
            v2_min_relevance=args.v2_min_relevance,
        )
        detail_df, _, _ = compare_modes(input_df.drop(columns=["shock_ts_dt"]), compare_cfg)

        episode_cfg = ShockEpisodeConfig(
            primary_z_threshold=args.primary_z,
            aftershock_z_threshold=args.aftershock_z,
            episode_window_minutes=args.episode_window_min,
            max_gap_minutes=args.max_gap_min,
            same_direction_aftershock_required=args.same_direction_aftershock_only,
        )
        result = run_shock_episode_analysis(
            detail_df=detail_df,
            output_dir=output_dir,
            config=episode_cfg,
            min_delay_minutes=0.0,
            max_delay_minutes=args.max_delay_min,
        )
        payload = {key: str(value) for key, value in result.items()}
        print(json.dumps(payload, ensure_ascii=False))
    elif args.command == "shock_label_pack":
        from moex_carry.news_shock_pipeline import (
            LabelPackConfig,
            ShockCurationConfig,
            build_shock_label_pack,
            curate_shock_dataset,
            write_label_pack_jsonl,
        )

        input_csv = Path(args.input_csv)
        if not input_csv.exists():
            raise FileNotFoundError(f"Input file not found: {input_csv}")
        if args.output_dir:
            output_dir = Path(args.output_dir)
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_dir = Path("data/output") / f"shock_label_pack_{stamp}"
        output_dir.mkdir(parents=True, exist_ok=True)

        df = pd.read_csv(input_csv)
        df["shock_ts_dt"] = pd.to_datetime(df["shock_ts"], utc=True, errors="coerce")
        if args.start_ts:
            start_ts = pd.to_datetime(args.start_ts, utc=True, errors="coerce")
            if pd.isna(start_ts):
                raise ValueError(f"Invalid --start-ts: {args.start_ts}")
            df = df[df["shock_ts_dt"] >= start_ts]
        if args.end_ts:
            end_ts = pd.to_datetime(args.end_ts, utc=True, errors="coerce")
            if pd.isna(end_ts):
                raise ValueError(f"Invalid --end-ts: {args.end_ts}")
            df = df[df["shock_ts_dt"] <= end_ts]
        if df.empty:
            raise ValueError("No rows available after date filtering.")
        df = df.drop(columns=["shock_ts_dt"])

        curated, issues, curation_summary = curate_shock_dataset(df, ShockCurationConfig.defaults())
        candidate_sources = tuple(args.candidate_source) if args.candidate_source else None
        tasks, pack_summary = build_shock_label_pack(
            curated,
            LabelPackConfig(
                min_abs_z=args.min_abs_z,
                max_tasks_total=args.max_tasks_total,
                max_tasks_per_day_symbol=args.max_tasks_per_day_symbol,
                max_delay_minutes=args.max_delay_min,
                candidate_sources=candidate_sources,
                causal_only=args.causal_only,
            ),
        )
        jsonl_path = output_dir / _build_shock_pack_name(
            args.min_abs_z,
            causal_only=args.causal_only,
            candidate_sources=candidate_sources,
        )
        write_label_pack_jsonl(tasks, jsonl_path)
        pack_summary_path = output_dir / "shock_label_pack_summary.csv"
        issues_path = output_dir / "shock_label_pack_curation_issues.csv"
        curation_summary_path = output_dir / "shock_label_pack_curation_summary.csv"
        pack_summary.to_csv(pack_summary_path, index=False)
        issues.to_csv(issues_path, index=False)
        curation_summary.to_csv(curation_summary_path, index=False)
        payload = {
            "tasks": str(jsonl_path),
            "summary": str(pack_summary_path),
            "issues": str(issues_path),
            "curation_summary": str(curation_summary_path),
            "tasks_count": len(tasks),
        }
        print(json.dumps(payload, ensure_ascii=False))
    elif args.command == "shock_labels_ingest":
        from moex_carry.news_shock_pipeline import ingest_chat_labels

        tasks_jsonl = Path(args.tasks_jsonl)
        labels_jsonl = Path(args.labels_jsonl)
        if not tasks_jsonl.exists():
            raise FileNotFoundError(f"Tasks JSONL not found: {tasks_jsonl}")
        if not labels_jsonl.exists():
            raise FileNotFoundError(f"Labels JSONL not found: {labels_jsonl}")
        if args.output_dir:
            output_dir = Path(args.output_dir)
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_dir = Path("data/output") / f"shock_silver_ingest_{stamp}"
        output_dir.mkdir(parents=True, exist_ok=True)

        merged, summary = ingest_chat_labels(
            tasks_jsonl=tasks_jsonl,
            labels_jsonl=labels_jsonl,
            min_confidence=args.min_confidence,
        )
        merged_path = output_dir / "shock_silver_labels.csv"
        summary_path = output_dir / "shock_silver_labels_summary.csv"
        merged.to_csv(merged_path, index=False)
        summary.to_csv(summary_path, index=False)
        payload = {
            "labels": str(merged_path),
            "summary": str(summary_path),
            "rows_total": int(len(merged)),
            "high_conf_count": int((merged.get("is_high_conf", 0) == 1).sum()) if not merged.empty else 0,
        }
        print(json.dumps(payload, ensure_ascii=False))
    elif args.command == "news_silver_ingest":
        from moex_carry.news_silver_store import ingest_event_labels_jsonl_to_db

        tasks_jsonl = Path(args.tasks_jsonl) if args.tasks_jsonl else None
        per_file: list[dict[str, object]] = []
        parsed_total = 0
        stored_total = 0
        high_conf_total = 0
        for raw_path in args.labels_jsonl:
            labels_jsonl = Path(raw_path)
            if not labels_jsonl.exists():
                raise FileNotFoundError(f"Labels JSONL not found: {labels_jsonl}")
            result = ingest_event_labels_jsonl_to_db(
                labels_jsonl=labels_jsonl,
                tasks_jsonl=tasks_jsonl,
                database_url=args.database_url,
                data_dir=args.data_dir,
                source_tag=args.source_tag,
                min_confidence=args.min_confidence,
                min_relevance=args.min_relevance,
            )
            per_file.append(result)
            parsed_total += int(result.get("records_parsed") or 0)
            stored_total += int(result.get("records_stored") or 0)
            high_conf_total += int(result.get("high_conf_causal") or 0)
        payload = {
            "database_url": args.database_url,
            "data_dir": args.data_dir,
            "source_tag": args.source_tag,
            "files": len(per_file),
            "records_parsed_total": parsed_total,
            "records_stored_total": stored_total,
            "high_conf_causal_total": high_conf_total,
            "per_file": per_file,
        }
        print(json.dumps(payload, ensure_ascii=False))
    elif args.command == "news_shock_readiness":
        from moex_carry.news_shock_readiness import ReadinessConfig, run_readiness_assessment

        input_csv = Path(args.input_csv)
        if not input_csv.exists():
            raise FileNotFoundError(f"Input file not found: {input_csv}")
        if args.output_dir:
            output_dir = Path(args.output_dir)
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_dir = Path("data/output") / f"news_shock_readiness_{stamp}"

        result = run_readiness_assessment(
            input_csv=input_csv,
            output_dir=output_dir,
            config=ReadinessConfig(
                max_delay_minutes=args.max_delay_min,
                primary_z_threshold=args.primary_z,
                aftershock_z_threshold=args.aftershock_z,
                episode_window_minutes=args.episode_window_min,
                max_gap_minutes=args.max_gap_min,
            ),
            start_ts=args.start_ts,
            end_ts=args.end_ts,
        )
        payload = {key: str(value) for key, value in result.items()}
        print(json.dumps(payload, ensure_ascii=False))
if __name__ == "__main__":
    main()
