from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _parse_utc_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def handle_news_runtime_command(args, settings) -> bool:
    if args.command == "news_shock_backfill":
        from moex_carry.news_live_runtime import NewsIngestConfig
        from moex_carry.news_shock_backfill import ShockRowsBackfillConfig, run_shock_rows_backfill

        news_cfg = NewsIngestConfig.from_yaml(Path(args.news_config))
        start_utc = _parse_utc_datetime(args.start_ts)
        if start_utc is None:
            raise ValueError(f"Invalid --start-ts: {args.start_ts}")
        end_utc = _parse_utc_datetime(args.end_ts) if str(args.end_ts).strip() else None
        payload = run_shock_rows_backfill(
            settings=settings,
            news_config=news_cfg,
            cfg=ShockRowsBackfillConfig(
                cursor_key=str(args.cursor_key),
                start_utc=start_utc,
                end_utc=end_utc,
                window_hours=int(args.window_hours),
                windows_per_run=int(args.windows_per_run),
                bar_minutes=int(args.bar_minutes),
                min_abs_z=float(args.min_abs_z),
                rolling_window_bars=int(args.rolling_window_bars),
                rolling_min_bars=int(args.rolling_min_bars),
                max_delay_minutes=float(args.max_delay_min),
                strict_pre_shock_minutes=float(args.strict_pre_shock_min),
                broad_context_lookback_minutes=float(args.broad_context_lookback_min),
                v2_min_relevance=float(args.v2_min_relevance),
                broad_min_relevance=float(args.broad_min_relevance),
                cross_commodity_min_relevance=float(args.cross_commodity_min_relevance),
                news_min_impact_score=float(args.news_min_impact_score),
                news_min_confidence=float(args.news_min_confidence),
                news_max_items_per_symbol=int(args.news_max_items_per_symbol),
                front_contract_candidates=int(args.front_contract_candidates),
                history_padding_days=int(args.history_padding_days),
                root_reuse_lookback_minutes=float(args.root_reuse_lookback_min),
                root_min_fundamental_score=float(args.root_min_fundamental_score),
                root_min_cause_confidence=float(args.root_min_cause_confidence),
                aftershock_max_gap_minutes=float(args.aftershock_max_gap_min),
                enable_candidate_newsapi_enrichment=bool(args.enable_candidate_newsapi_enrichment),
                enrichment_window_minutes=int(args.enrichment_window_min),
                enrichment_max_requests_per_symbol=int(args.enrichment_max_requests_per_symbol),
                run_root_maintenance=not bool(args.no_root_maintenance),
                write_csv_snapshot=bool(args.write_snapshot_csv),
                snapshot_dir=str(args.snapshot_dir),
            ),
        )
        print(json.dumps(payload, ensure_ascii=False))
        return True

    if args.command == "news_root_cycle":
        from moex_carry.news_live_runtime import NewsIngestConfig, run_news_ingest_cycle
        from moex_carry.news_root_maintenance import RootMaintenanceConfig, refresh_root_maintenance
        from moex_carry.news_shock_live_input import LiveShockInputConfig, build_live_shock_input
        from moex_carry.news_shock_store import upsert_live_shock_rows

        news_cfg = NewsIngestConfig.from_yaml(Path(args.news_config))
        ingest_payload = run_news_ingest_cycle(config=news_cfg, mode=str(args.ingest_mode))
        frame = build_live_shock_input(
            settings=settings,
            news_config=news_cfg,
            cfg=LiveShockInputConfig(
                lookback_hours=int(args.lookback_hours),
                bar_minutes=int(args.bar_minutes),
                min_abs_z=float(args.min_abs_z),
                root_min_fundamental_score=float(args.root_min_fundamental_score),
                root_min_cause_confidence=float(args.root_min_cause_confidence),
                aftershock_max_gap_minutes=float(args.aftershock_max_gap_min),
                enable_candidate_newsapi_enrichment=bool(args.enable_candidate_newsapi_enrichment),
                enrichment_window_minutes=int(args.enrichment_window_min),
                enrichment_max_requests_per_symbol=int(args.enrichment_max_requests_per_symbol),
            ),
        )
        shock_rows_upserted = int(
            upsert_live_shock_rows(
                frame=frame,
                database_url=news_cfg.database_url,
                data_dir=news_cfg.data_dir,
            )
        )
        root_payload = (
            refresh_root_maintenance(
                database_url=news_cfg.database_url,
                data_dir=news_cfg.data_dir,
                cfg=RootMaintenanceConfig(bar_minutes=int(args.bar_minutes), max_rows=0),
            )
            if not bool(args.no_root_maintenance)
            else {"links_upserted": 0, "registry_upserted": 0, "edges_upserted": 0}
        )
        print(
            json.dumps(
                {
                    "ingest": ingest_payload,
                    "shock_rows": int(len(frame)),
                    "shock_rows_upserted": shock_rows_upserted,
                    "root_maintenance": root_payload,
                },
                ensure_ascii=False,
            )
        )
        return True

    return False
