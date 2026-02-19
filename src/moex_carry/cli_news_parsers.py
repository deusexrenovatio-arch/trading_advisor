import argparse
from collections.abc import Callable


def register_news_subcommands(
    subparsers: argparse._SubParsersAction,
    add_common_args: Callable[[argparse.ArgumentParser], None],
) -> None:
    news_sync_parser = subparsers.add_parser("news_sync", help="Run news ingestion/linking/inference worker")
    add_common_args(news_sync_parser)
    news_sync_parser.add_argument("--once", action="store_true", help="Run one sync iteration and exit")
    news_sync_parser.add_argument("--interval-sec", type=int, default=300)
    news_sync_parser.add_argument("--limit", type=int, default=None)
    news_sync_parser.add_argument(
        "--skip-inference",
        action="store_true",
        help="Disable model inference in worker mode and run ingest/link only.",
    )

    news_backfill_parser = subparsers.add_parser(
        "news_backfill",
        help="Backfill historical commodity news and aligned price series for backtesting.",
    )
    add_common_args(news_backfill_parser)
    news_backfill_parser.add_argument("--from-date", type=str, default=None)
    news_backfill_parser.add_argument("--to-date", type=str, default=None)
    news_backfill_parser.add_argument(
        "--commodities",
        type=str,
        default=None,
        help="Comma-separated list (e.g. BRN,GOLD,NG_US). Default: all configured profiles.",
    )
    news_backfill_parser.add_argument("--without-prices", action="store_true")
    news_backfill_parser.add_argument("--run-inference", action="store_true")
    news_backfill_parser.add_argument("--chunk-days", type=int, default=None)
    news_backfill_parser.add_argument("--max-windows-per-commodity", type=int, default=None)
    news_backfill_parser.add_argument(
        "--window-order",
        type=str,
        default=None,
        choices=["chronological", "recent_first", "shock_first"],
        help="Backfill window processing order. Default: config value.",
    )

    news_qc_parser = subparsers.add_parser(
        "news_qc",
        help="Build quality/readiness report for news backtest datasets.",
    )
    add_common_args(news_qc_parser)
    news_qc_parser.add_argument("--from-date", type=str, default=None)
    news_qc_parser.add_argument("--to-date", type=str, default=None)
    news_qc_parser.add_argument(
        "--commodities",
        type=str,
        default=None,
        help="Comma-separated list (e.g. BRN,GOLD,NG_US). Default: all configured profiles.",
    )

    news_llm_pass_parser = subparsers.add_parser(
        "news_llm_pass",
        help="Run full LLM pass over event-layer records with cache/retry policy.",
    )
    add_common_args(news_llm_pass_parser)
    news_llm_pass_parser.add_argument("--max-items", type=int, default=None)

    news_llm_batch_parser = subparsers.add_parser(
        "news_llm_batch_export",
        help="Export OpenAI Batch API request rows for event-layer LLM labeling.",
    )
    add_common_args(news_llm_batch_parser)
    news_llm_batch_parser.add_argument("--max-items", type=int, default=None)
    news_llm_batch_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSONL path. Default: data/output/news_llm_batch_requests.jsonl",
    )
    news_llm_batch_parser.add_argument(
        "--include-cached",
        action="store_true",
        help="Include events that already have cache hits for the same model/prompt/input_hash.",
    )

    news_hitl_export_parser = subparsers.add_parser(
        "news_hitl_export",
        help="Export top event tasks for manual ChatGPT-web labeling (no API token spend).",
    )
    add_common_args(news_hitl_export_parser)
    news_hitl_export_parser.add_argument("--max-items", type=int, default=10)
    news_hitl_export_parser.add_argument("--min-impact", type=float, default=0.0)
    news_hitl_export_parser.add_argument("--ticker", type=str, default=None, help="Optional ticker filter, e.g. NG_US")
    news_hitl_export_parser.add_argument("--include-labeled", action="store_true")
    news_hitl_export_parser.add_argument(
        "--format",
        type=str,
        default="batch",
        choices=["jsonl", "json", "md", "batch"],
        help="Output format for manual labeling payload.",
    )
    news_hitl_export_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path. Default: data/output/news_hitl_tasks.<format>",
    )
    news_hitl_export_parser.add_argument(
        "--print",
        action="store_true",
        help="Print exported prompt content to stdout for direct copy/paste.",
    )

    news_hitl_import_parser = subparsers.add_parser(
        "news_hitl_import",
        help="Import manual ChatGPT-web labels into event-level labels + annotations.",
    )
    add_common_args(news_hitl_import_parser)
    news_hitl_import_parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Input path with labels. Default: data/output/news_hitl_answer.jsonl",
    )
    news_hitl_import_parser.add_argument("--author-id", type=str, default="operator")
    news_hitl_import_parser.add_argument("--reason", type=str, default="chatgpt_web_manual_label")
    news_hitl_import_parser.add_argument("--label-version", type=str, default="v1")
    news_hitl_import_parser.add_argument("--prompt-version", type=str, default=None)

    news_gold_bootstrap_parser = subparsers.add_parser(
        "news_gold_bootstrap",
        help="Automate gold/silver label bootstrap from HITL human labels and/or target_v2 high-confidence rows.",
    )
    add_common_args(news_gold_bootstrap_parser)
    news_gold_bootstrap_parser.add_argument(
        "--mode",
        type=str,
        default="both",
        choices=["human_to_gold", "v2_silver", "both"],
    )
    news_gold_bootstrap_parser.add_argument("--from-date", type=str, default=None)
    news_gold_bootstrap_parser.add_argument("--to-date", type=str, default=None)
    news_gold_bootstrap_parser.add_argument("--symbol", type=str, default=None, help="Optional symbol filter, e.g. NG_US")
    news_gold_bootstrap_parser.add_argument("--horizon", type=str, default="1h", help="Horizon for v2_silver mode.")
    news_gold_bootstrap_parser.add_argument("--min-model-confidence", type=float, default=0.62)
    news_gold_bootstrap_parser.add_argument("--max-events", type=int, default=0)
    news_gold_bootstrap_parser.add_argument("--quality-human", type=str, default="gold")
    news_gold_bootstrap_parser.add_argument("--quality-v2", type=str, default="silver")
    news_gold_bootstrap_parser.add_argument("--source-human", type=str, default="human_hitl")
    news_gold_bootstrap_parser.add_argument("--source-v2", type=str, default="auto_target_v2")
    news_gold_bootstrap_parser.add_argument(
        "--allow-model-disagreement",
        action="store_true",
        help="If set, v2_silver mode will not require finbert/nli direction agreement.",
    )
    news_gold_bootstrap_parser.add_argument(
        "--allow-target-mismatch",
        action="store_true",
        help="If set, v2_silver mode will not require model direction to match target_v2 label.",
    )
    news_gold_bootstrap_parser.add_argument(
        "--allow-no-model-scores",
        action="store_true",
        help="If set, v2_silver mode can emit labels from hi-conf target_v2 rows even when model scores are missing.",
    )
    news_gold_bootstrap_parser.add_argument(
        "--include-overlap",
        action="store_true",
        help="If set, v2_silver mode can include hi-conf rows marked as overlapped.",
    )
    news_gold_bootstrap_parser.add_argument(
        "--v2-selector",
        type=str,
        default="hi_conf",
        choices=["hi_conf", "impact", "hybrid"],
        help="Candidate selector for target_v2 rows in v2_silver mode.",
    )
    news_gold_bootstrap_parser.add_argument(
        "--v2-min-target-confidence",
        type=float,
        default=0.0,
        help="Minimum target_v2 confidence for impact/hybrid selectors.",
    )
    news_gold_bootstrap_parser.add_argument(
        "--v2-min-impact-bin",
        type=int,
        default=1,
        help="Minimum target_v2 impact_bin for impact/hybrid selectors.",
    )
    news_gold_bootstrap_parser.add_argument(
        "--v2-min-abs-z",
        type=float,
        default=0.0,
        help="Minimum abs(z_post) for impact/hybrid selectors.",
    )
    news_gold_bootstrap_parser.add_argument(
        "--v2-min-abs-ar",
        type=float,
        default=0.0,
        help="Minimum abs(ar) for impact/hybrid selectors.",
    )

    news_daily_silver_cycle_parser = subparsers.add_parser(
        "news_daily_silver_cycle",
        help="Run one daily cycle: fresh backfill + shock-first backlog + target_v2 + impact-based v2_silver.",
    )
    add_common_args(news_daily_silver_cycle_parser)
    news_daily_silver_cycle_parser.add_argument("--date", type=str, default=None, help="UTC date (YYYY-MM-DD).")
    news_daily_silver_cycle_parser.add_argument("--symbol", type=str, default="NG_US")
    news_daily_silver_cycle_parser.add_argument("--horizon", type=str, default="5m")
    news_daily_silver_cycle_parser.add_argument("--fresh-days", type=int, default=2)
    news_daily_silver_cycle_parser.add_argument("--fresh-chunk-days", type=int, default=1)
    news_daily_silver_cycle_parser.add_argument("--fresh-max-windows", type=int, default=40)
    news_daily_silver_cycle_parser.add_argument("--backlog-from-date", type=str, default=None)
    news_daily_silver_cycle_parser.add_argument("--backlog-chunk-days", type=int, default=30)
    news_daily_silver_cycle_parser.add_argument("--backlog-max-windows", type=int, default=1)
    news_daily_silver_cycle_parser.add_argument("--without-prices", action="store_true")
    news_daily_silver_cycle_parser.add_argument("--run-inference", action="store_true")
    news_daily_silver_cycle_parser.add_argument("--processing-lag-sec", type=int, default=60)
    news_daily_silver_cycle_parser.add_argument("--use-midpoint", action="store_true")
    news_daily_silver_cycle_parser.add_argument("--min-model-confidence", type=float, default=0.55)
    news_daily_silver_cycle_parser.add_argument("--allow-model-disagreement", action="store_true")
    news_daily_silver_cycle_parser.add_argument("--allow-target-mismatch", action="store_true")
    news_daily_silver_cycle_parser.add_argument("--allow-no-model-scores", action="store_true")
    news_daily_silver_cycle_parser.add_argument("--include-overlap", action="store_true")
    news_daily_silver_cycle_parser.add_argument(
        "--v2-selector",
        type=str,
        default="impact",
        choices=["hi_conf", "impact", "hybrid"],
    )
    news_daily_silver_cycle_parser.add_argument("--v2-min-target-confidence", type=float, default=0.35)
    news_daily_silver_cycle_parser.add_argument("--v2-min-impact-bin", type=int, default=1)
    news_daily_silver_cycle_parser.add_argument("--v2-min-abs-z", type=float, default=1.0)
    news_daily_silver_cycle_parser.add_argument("--v2-min-abs-ar", type=float, default=0.0005)
    news_daily_silver_cycle_parser.add_argument("--source-v2", type=str, default="auto_target_v2")
    news_daily_silver_cycle_parser.add_argument("--quality-v2", type=str, default="silver")
    news_daily_silver_cycle_parser.add_argument("--label-schema-version", type=str, default="v2")

    news_event_score_backfill_parser = subparsers.add_parser(
        "news_event_score_backfill",
        help="Backfill event-level model scores for gold/silver event labels to improve supervised coverage.",
    )
    add_common_args(news_event_score_backfill_parser)
    news_event_score_backfill_parser.add_argument("--quality", type=str, default="gold", help="gold|silver|any")
    news_event_score_backfill_parser.add_argument("--source", type=str, default=None)
    news_event_score_backfill_parser.add_argument("--label-schema-version", type=str, default=None)
    news_event_score_backfill_parser.add_argument("--max-events", type=int, default=500)
    news_event_score_backfill_parser.add_argument(
        "--include-existing",
        action="store_true",
        help="If set, recompute scores even when event-level rows already exist.",
    )
    news_event_score_backfill_parser.add_argument(
        "--models",
        type=str,
        default="finbert,nli",
        help="Comma-separated list from {finbert,nli}.",
    )
    news_event_score_backfill_parser.add_argument("--text-max-chars", type=int, default=None)

    news_reactions_parser = subparsers.add_parser(
        "news_reactions",
        help="Rebuild event-market reaction rows (raw/abnormal/CAR) for event-study validation.",
    )
    add_common_args(news_reactions_parser)
    news_reactions_parser.add_argument("--from-date", type=str, default=None)
    news_reactions_parser.add_argument("--to-date", type=str, default=None)
    news_reactions_parser.add_argument(
        "--event-ids",
        type=str,
        default=None,
        help="Comma-separated event IDs to rebuild.",
    )
    news_reactions_parser.add_argument(
        "--window-ids",
        type=str,
        default="0_30m,30m_2h,2h_1d,1d_5d",
        help="Comma-separated window ids.",
    )
    news_reactions_parser.add_argument(
        "--sampling-freqs",
        type=str,
        default="1m,5m,15m",
        help="Comma-separated sampling frequencies.",
    )
    news_reactions_parser.add_argument("--max-events", type=int, default=0)
    news_reactions_parser.add_argument("--estimation-lookback-days", type=int, default=7)
    news_reactions_parser.add_argument(
        "--event-time-mode",
        type=str,
        choices=["published", "ingested"],
        default="published",
        help="Anchor event windows to published or ingested timestamp.",
    )

    news_target_v2_parser = subparsers.add_parser(
        "news_target_v2",
        help="Build target_v2 rows (t0/t1, AR, sigma_pre, labels) for causal news-impact evaluation.",
    )
    add_common_args(news_target_v2_parser)
    news_target_v2_parser.add_argument("--from-date", type=str, default=None)
    news_target_v2_parser.add_argument("--to-date", type=str, default=None)
    news_target_v2_parser.add_argument("--symbol", type=str, default=None, help="Optional symbol filter, e.g. NG_US")
    news_target_v2_parser.add_argument("--horizon", type=str, default="5m", help="Horizon: 5m, 1h, 4h, 1d")
    news_target_v2_parser.add_argument("--processing-lag-sec", type=int, default=60)
    news_target_v2_parser.add_argument("--max-events", type=int, default=0)
    news_target_v2_parser.add_argument(
        "--use-midpoint",
        action="store_true",
        help="Prefer midpoint price from bid/ask when available.",
    )
    news_target_v2_parser.add_argument(
        "--event-time-mode",
        type=str,
        choices=["first_seen", "published", "min"],
        default="min",
        help="Reserved compatibility flag. target_v2 currently uses min(first_seen, published).",
    )

    news_factor_autolabel_parser = subparsers.add_parser(
        "news_factor_autolabel",
        help="Auto-extract event factors (A/B/C labelers) without human budget from 5m target_v2 rows.",
    )
    add_common_args(news_factor_autolabel_parser)
    news_factor_autolabel_parser.add_argument("--from-date", type=str, default=None)
    news_factor_autolabel_parser.add_argument("--to-date", type=str, default=None)
    news_factor_autolabel_parser.add_argument("--symbol", type=str, default=None, help="Optional symbol filter")
    news_factor_autolabel_parser.add_argument("--horizon", type=str, default="5m")
    news_factor_autolabel_parser.add_argument("--min-confidence", type=float, default=0.35)
    news_factor_autolabel_parser.add_argument("--top-k", type=int, default=3)
    news_factor_autolabel_parser.add_argument("--include-overlap", action="store_true")
    news_factor_autolabel_parser.add_argument("--disable-nli", action="store_true")
    news_factor_autolabel_parser.add_argument(
        "--nli-model-name",
        type=str,
        default="facebook/bart-large-mnli",
    )
    news_factor_autolabel_parser.add_argument("--label-version", type=str, default="autolabel-v2")
    news_factor_autolabel_parser.add_argument("--text-max-chars", type=int, default=4000)
    news_factor_autolabel_parser.add_argument("--max-events", type=int, default=0)

    news_benchmark_parser = subparsers.add_parser(
        "news_benchmark",
        help="Benchmark news model inference matrix and suggest host-optimized safe profile.",
    )
    add_common_args(news_benchmark_parser)
    news_benchmark_parser.add_argument("--sample-size", type=int, default=60)
    news_benchmark_parser.add_argument("--lookback-days", type=int, default=365 * 3)
    news_benchmark_parser.add_argument("--ticker", type=str, default=None)
    news_benchmark_parser.add_argument(
        "--batch-sizes",
        type=str,
        default="1,2,4,8",
        help="Comma-separated positive ints.",
    )
    news_benchmark_parser.add_argument(
        "--thread-caps",
        type=str,
        default="2,4,6",
        help="Comma-separated positive ints.",
    )
    news_benchmark_parser.add_argument(
        "--text-caps",
        type=str,
        default="1200,1500,2000",
        help="Comma-separated positive ints.",
    )
    news_benchmark_parser.add_argument("--warmup-runs", type=int, default=1)
    news_benchmark_parser.add_argument("--repeat-runs", type=int, default=2)
    news_benchmark_parser.add_argument(
        "--write-profile",
        type=str,
        default=None,
        help="Optional path to write recommended YAML overrides.",
    )

