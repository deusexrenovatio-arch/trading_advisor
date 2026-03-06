from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from moex_carry.config import load_settings
from moex_carry.news_live_runtime import NewsIngestConfig
from moex_carry.news_root_maintenance import RootMaintenanceConfig, refresh_root_maintenance
from moex_carry.news_shock_live_input import LiveShockInputConfig, build_live_shock_input
from moex_carry.news_shock_store import upsert_live_shock_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build live shock input dataset from MOEX futures + live news DB.")
    parser.add_argument("--config", type=str, default=None, help="Path to main YAML config.")
    parser.add_argument("--news-config", type=str, default="configs/news-livecheck-ng.yaml")
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--lookback-hours", type=int, default=6)
    parser.add_argument("--bar-minutes", type=int, default=5)
    parser.add_argument("--min-abs-z", type=float, default=2.0)
    parser.add_argument("--rolling-window-bars", type=int, default=96)
    parser.add_argument("--rolling-min-bars", type=int, default=24)
    parser.add_argument("--max-delay-min", type=float, default=60.0)
    parser.add_argument("--strict-pre-shock-min", type=float, default=10.0)
    parser.add_argument("--broad-context-lookback-min", type=float, default=2880.0)
    parser.add_argument("--v2-min-relevance", type=float, default=0.4)
    parser.add_argument("--broad-min-relevance", type=float, default=0.2)
    parser.add_argument("--cross-commodity-min-relevance", type=float, default=0.8)
    parser.add_argument("--news-min-impact-score", type=float, default=0.35)
    parser.add_argument("--news-min-confidence", type=float, default=0.55)
    parser.add_argument("--news-max-items-per-symbol", type=int, default=3000)
    parser.add_argument("--front-contract-candidates", type=int, default=4)
    parser.add_argument("--history-padding-days", type=int, default=10)
    parser.add_argument("--root-reuse-lookback-min", type=float, default=2880.0)
    parser.add_argument("--root-min-fundamental-score", type=float, default=0.45)
    parser.add_argument("--root-min-cause-confidence", type=float, default=0.45)
    parser.add_argument("--aftershock-max-gap-min", type=float, default=2880.0)
    parser.add_argument("--enable-candidate-newsapi-enrichment", action="store_true")
    parser.add_argument("--enrichment-window-min", type=int, default=90)
    parser.add_argument("--enrichment-max-requests-per-symbol", type=int, default=4)
    parser.add_argument("--no-write-db", action="store_true")
    parser.add_argument("--no-root-maintenance", action="store_true")
    parser.add_argument("--write-db-url", type=str, default="")
    parser.add_argument("--write-db-data-dir", type=str, default="")
    parser.add_argument("--end-ts", type=str, default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    news_cfg = NewsIngestConfig.from_yaml(Path(args.news_config))
    end_ts = None
    if args.end_ts:
        parsed = datetime.fromisoformat(args.end_ts.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        end_ts = parsed.astimezone(timezone.utc)

    frame = build_live_shock_input(
        settings=settings,
        news_config=news_cfg,
        cfg=LiveShockInputConfig(
            lookback_hours=args.lookback_hours,
            bar_minutes=args.bar_minutes,
            min_abs_z=args.min_abs_z,
            rolling_window_bars=args.rolling_window_bars,
            rolling_min_bars=args.rolling_min_bars,
            max_delay_minutes=args.max_delay_min,
            strict_pre_shock_minutes=args.strict_pre_shock_min,
            broad_context_lookback_minutes=args.broad_context_lookback_min,
            v2_min_relevance=args.v2_min_relevance,
            broad_min_relevance=args.broad_min_relevance,
            cross_commodity_min_relevance=args.cross_commodity_min_relevance,
            news_min_impact_score=args.news_min_impact_score,
            news_min_confidence=args.news_min_confidence,
            news_max_items_per_symbol=args.news_max_items_per_symbol,
            front_contract_candidates=args.front_contract_candidates,
            history_padding_days=args.history_padding_days,
            root_reuse_lookback_minutes=args.root_reuse_lookback_min,
            root_min_fundamental_score=args.root_min_fundamental_score,
            root_min_cause_confidence=args.root_min_cause_confidence,
            aftershock_max_gap_minutes=args.aftershock_max_gap_min,
            enable_candidate_newsapi_enrichment=bool(args.enable_candidate_newsapi_enrichment),
            enrichment_window_minutes=args.enrichment_window_min,
            enrichment_max_requests_per_symbol=args.enrichment_max_requests_per_symbol,
        ),
        end_utc=end_ts,
    )
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output_csv, index=False)
    db_rows_upserted = 0
    root_maintenance = {"links_upserted": 0, "registry_upserted": 0, "edges_upserted": 0}
    if not bool(args.no_write_db):
        database_url = str(args.write_db_url or news_cfg.database_url)
        data_dir = str(args.write_db_data_dir or news_cfg.data_dir)
        db_rows_upserted = int(
            upsert_live_shock_rows(
                frame=frame,
                database_url=database_url,
                data_dir=data_dir,
            )
        )
        if not bool(args.no_root_maintenance):
            root_maintenance = refresh_root_maintenance(
                database_url=database_url,
                data_dir=data_dir,
                cfg=RootMaintenanceConfig(
                    bar_minutes=args.bar_minutes,
                    max_rows=0,
                ),
            )
    payload = {
        "output_csv": str(args.output_csv),
        "rows": int(len(frame)),
        "symbols": sorted(frame["symbol"].dropna().astype(str).unique().tolist()) if not frame.empty else [],
        "db_rows_upserted": db_rows_upserted,
        "root_maintenance": root_maintenance,
    }
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
