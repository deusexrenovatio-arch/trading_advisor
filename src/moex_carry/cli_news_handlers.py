import json
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from moex_carry.config import resolve_paths


def handle_news_command(args, settings) -> bool:
    if args.command == "news_sync":
        from moex_carry.news import run_news_sync_worker

        run_news_sync_worker(
            settings,
            once=args.once,
            interval_sec=args.interval_sec,
            recent_limit=args.limit,
            run_inference=not args.skip_inference,
        )
    elif args.command == "news_backfill":
        from moex_carry.news import run_news_backfill
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        from_date = date.fromisoformat(args.from_date) if args.from_date else date.fromisoformat(
            settings.news_ingest.backfill_start_date
        )
        to_date = date.fromisoformat(args.to_date) if args.to_date else date.today()
        commodities = (
            [item.strip() for item in str(args.commodities).split(",") if item.strip()]
            if args.commodities
            else None
        )
        with session_factory() as session:
            report = run_news_backfill(
                session,
                settings,
                period_from=from_date,
                period_to=to_date,
                commodities=commodities,
                include_prices=not args.without_prices,
                run_inference=args.run_inference,
                chunk_days_override=args.chunk_days,
                max_windows_per_commodity=args.max_windows_per_commodity,
                window_order_override=args.window_order,
            )
        print(
            json.dumps(
                {
                    "period_from": report.period_from,
                    "period_to": report.period_to,
                    "commodities": report.commodities,
                    "ingested_count": report.ingested_count,
                    "entity_link_count": report.entity_link_count,
                    "tag_link_count": report.tag_link_count,
                    "score_count": report.score_count,
                    "event_link_count": report.event_link_count,
                    "event_created_count": report.event_created_count,
                    "event_updated_count": report.event_updated_count,
                    "event_refuted_count": report.event_refuted_count,
                    "event_resolved_count": report.event_resolved_count,
                    "quote_count": report.quote_count,
                    "windows_processed": report.windows_processed,
                    "window_order": report.window_order,
                    "newsapi_requests_used": report.newsapi_requests_used,
                    "newsapi_requests_remaining": report.newsapi_requests_remaining,
                    "qc_report": report.qc_report,
                },
                ensure_ascii=False,
                default=str,
            )
        )
    elif args.command == "news_qc":
        from moex_carry.news import run_news_qc
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        from_date = date.fromisoformat(args.from_date) if args.from_date else (date.today() - timedelta(days=365 * 5))
        to_date = date.fromisoformat(args.to_date) if args.to_date else date.today()
        commodities = (
            [item.strip() for item in str(args.commodities).split(",") if item.strip()]
            if args.commodities
            else None
        )
        with session_factory() as session:
            report = run_news_qc(
                session,
                settings,
                period_from=from_date,
                period_to=to_date,
                commodities=commodities,
            )
        print(json.dumps(report, ensure_ascii=False, default=str))
    elif args.command == "news_llm_pass":
        from moex_carry.news import run_news_llm_full_pass
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            report = run_news_llm_full_pass(
                session,
                settings,
                max_items=args.max_items,
            )
        print(
            json.dumps(
                {
                    "processed_count": report.processed_count,
                    "completed_count": report.completed_count,
                    "skipped_count": report.skipped_count,
                    "failed_count": report.failed_count,
                    "labeled_count": report.labeled_count,
                    "provider": report.provider,
                    "model_id": report.model_id,
                    "prompt_version": report.prompt_version,
                    "token_in_total": report.token_in_total,
                    "token_out_total": report.token_out_total,
                    "budget_exhausted": report.budget_exhausted,
                    "budget_reason": report.budget_reason,
                },
                ensure_ascii=False,
            )
        )
    elif args.command == "news_llm_batch_export":
        from moex_carry.news import build_news_llm_batch_requests
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            report = build_news_llm_batch_requests(
                session,
                settings,
                max_items=args.max_items,
                include_cached=bool(args.include_cached),
            )

        output_path = Path(args.output) if args.output else (resolve_paths(settings).data_dir / "output" / "news_llm_batch_requests.jsonl")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        requests_rows = report.get("requests") if isinstance(report, dict) else []
        if not isinstance(requests_rows, list):
            requests_rows = []
        with output_path.open("w", encoding="utf-8") as handle:
            for row in requests_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            json.dumps(
                {
                    "output_path": str(output_path),
                    "provider": report.get("provider"),
                    "model_id": report.get("model_id"),
                    "prompt_version": report.get("prompt_version"),
                    "requested_count": int(report.get("requested_count") or 0),
                    "exported_count": int(report.get("exported_count") or 0),
                    "skipped_cached_count": int(report.get("skipped_cached_count") or 0),
                    "include_cached": bool(args.include_cached),
                },
                ensure_ascii=False,
                default=str,
            )
        )
    elif args.command == "news_hitl_export":
        from moex_carry.news.hitl import build_news_hitl_tasks, export_news_hitl_tasks, summarize_news_hitl_state
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        output_format = str(args.format).strip().lower()
        if args.output:
            output_path = Path(args.output)
        else:
            output_path = resolve_paths(settings).data_dir / "output" / f"news_hitl_tasks.{output_format}"
        answer_path = resolve_paths(settings).data_dir / "output" / "news_hitl_answer.jsonl"

        with session_factory() as session:
            tasks = build_news_hitl_tasks(
                session,
                settings,
                max_items=args.max_items,
                min_impact=args.min_impact,
                only_unlabeled=not bool(args.include_labeled),
                ticker=args.ticker,
            )
            state = summarize_news_hitl_state(session)
        exported_path = export_news_hitl_tasks(tasks=tasks, output_path=output_path, output_format=output_format)
        if not answer_path.exists():
            answer_path.write_text("", encoding="utf-8")
        if args.print:
            print("----- COPY THIS TO CHATGPT WEB -----")
            print(exported_path.read_text(encoding="utf-8"))
            print("----- END COPY BLOCK -----")
            print()
        next_command = (
            "python -m moex_carry.cli news_hitl_import "
            f"--config {args.config or 'configs/default.yaml'} "
            f"--input {answer_path}"
        )
        print(
            json.dumps(
                {
                    "output_path": str(exported_path),
                    "answer_path": str(answer_path),
                    "output_format": output_format,
                    "tasks_exported": len(tasks),
                    "max_items": int(args.max_items),
                    "min_impact": float(args.min_impact),
                    "ticker": str(args.ticker).strip().upper() if args.ticker else None,
                    "include_labeled": bool(args.include_labeled),
                    "next_command": next_command,
                    "state": state,
                },
                ensure_ascii=False,
                default=str,
            )
        )
    elif args.command == "news_hitl_import":
        from moex_carry.news.hitl import apply_news_hitl_labels, load_hitl_label_rows, summarize_news_hitl_state
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        input_path = Path(args.input) if args.input else (resolve_paths(settings).data_dir / "output" / "news_hitl_answer.jsonl")
        rows = load_hitl_label_rows(input_path)
        prompt_version = str(args.prompt_version or settings.news_llm.prompt_version or "news-v1")
        with session_factory() as session:
            report = apply_news_hitl_labels(
                session,
                label_rows=rows,
                author_id=args.author_id,
                reason=args.reason,
                label_version=args.label_version,
                prompt_version=prompt_version,
            )
            state = summarize_news_hitl_state(session)
        print(
            json.dumps(
                {
                    "input_path": str(input_path),
                    "loaded_rows": len(rows),
                    "report": report,
                    "state": state,
                },
                ensure_ascii=False,
                default=str,
            )
        )
    elif args.command == "news_gold_bootstrap":
        from moex_carry.news import bootstrap_silver_from_v2_targets, promote_human_labels_to_gold
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        from_dt = datetime.fromisoformat(args.from_date) if args.from_date else None
        to_dt = datetime.fromisoformat(args.to_date) if args.to_date else None
        mode = str(args.mode or "both").strip().lower()

        result: dict[str, object] = {
            "mode": mode,
            "from_date": args.from_date,
            "to_date": args.to_date,
        }
        with session_factory() as session:
            if mode in {"human_to_gold", "both"}:
                human_report = promote_human_labels_to_gold(
                    session,
                    source=str(args.source_human or "human_hitl"),
                    quality=str(args.quality_human or "gold"),
                    label_schema_version="v1",
                    created_from=from_dt,
                    created_to=to_dt,
                    max_rows=max(int(args.max_events), 0),
                )
                result["human_to_gold"] = {
                    "scanned": human_report.scanned,
                    "accepted": human_report.accepted,
                    "stored": human_report.stored,
                    "quality": str(args.quality_human or "gold"),
                    "source": str(args.source_human or "human_hitl"),
                }
            if mode in {"v2_silver", "both"}:
                v2_report = bootstrap_silver_from_v2_targets(
                    session,
                    horizon=str(args.horizon or "1h").strip().lower(),
                    symbol=str(args.symbol or "").strip().upper() or None,
                    published_from=from_dt,
                    published_to=to_dt,
                    min_model_confidence=max(float(args.min_model_confidence), 0.0),
                    require_both_models=not bool(args.allow_model_disagreement),
                    require_direction_match_to_target=not bool(args.allow_target_mismatch),
                    allow_no_model_scores=bool(args.allow_no_model_scores),
                    source=str(args.source_v2 or "auto_target_v2"),
                    quality=str(args.quality_v2 or "silver"),
                    label_schema_version="v2",
                    max_events=max(int(args.max_events), 0),
                    include_overlapped=bool(args.include_overlap),
                    target_selector=str(args.v2_selector or "hi_conf").strip().lower(),
                    min_target_confidence=max(float(args.v2_min_target_confidence), 0.0),
                    min_impact_bin=max(int(args.v2_min_impact_bin), 0),
                    min_abs_z_post=max(float(args.v2_min_abs_z), 0.0),
                    min_abs_ar=max(float(args.v2_min_abs_ar), 0.0),
                )
                result["v2_silver"] = {
                    "scanned": v2_report.scanned,
                    "eligible_targets": v2_report.eligible_targets,
                    "accepted": v2_report.accepted,
                    "stored": v2_report.stored,
                    "skipped_no_primary_news": v2_report.skipped_no_primary_news,
                    "skipped_missing_scores": v2_report.skipped_missing_scores,
                    "skipped_confidence": v2_report.skipped_confidence,
                    "skipped_disagreement": v2_report.skipped_disagreement,
                    "skipped_relevance": v2_report.skipped_relevance,
                    "horizon": str(args.horizon or "1h").strip().lower(),
                    "symbol": str(args.symbol or "").strip().upper() or None,
                    "quality": str(args.quality_v2 or "silver"),
                    "source": str(args.source_v2 or "auto_target_v2"),
                    "min_model_confidence": max(float(args.min_model_confidence), 0.0),
                    "require_both_models": not bool(args.allow_model_disagreement),
                    "require_direction_match_to_target": not bool(args.allow_target_mismatch),
                    "allow_no_model_scores": bool(args.allow_no_model_scores),
                    "include_overlap": bool(args.include_overlap),
                    "target_selector": str(args.v2_selector or "hi_conf").strip().lower(),
                    "min_target_confidence": max(float(args.v2_min_target_confidence), 0.0),
                    "min_impact_bin": max(int(args.v2_min_impact_bin), 0),
                    "min_abs_z": max(float(args.v2_min_abs_z), 0.0),
                    "min_abs_ar": max(float(args.v2_min_abs_ar), 0.0),
                }
        print(json.dumps(result, ensure_ascii=False, default=str))
    elif args.command == "news_daily_silver_cycle":
        from moex_carry.news import run_news_daily_silver_cycle
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        run_day = date.fromisoformat(args.date) if args.date else date.today()
        backlog_from_date = date.fromisoformat(args.backlog_from_date) if args.backlog_from_date else None
        with session_factory() as session:
            report = run_news_daily_silver_cycle(
                session,
                settings,
                run_date=run_day,
                symbol=str(args.symbol or "NG_US").strip().upper(),
                horizon=str(args.horizon or "5m").strip().lower(),
                fresh_days=max(int(args.fresh_days), 1),
                fresh_chunk_days=max(int(args.fresh_chunk_days), 1),
                fresh_max_windows=max(int(args.fresh_max_windows), 0),
                backlog_from_date=backlog_from_date,
                backlog_chunk_days=max(int(args.backlog_chunk_days), 1),
                backlog_max_windows=max(int(args.backlog_max_windows), 0),
                include_prices=not bool(args.without_prices),
                run_inference=bool(args.run_inference),
                processing_lag_sec=max(int(args.processing_lag_sec), 0),
                use_midpoint=bool(args.use_midpoint),
                min_model_confidence=max(float(args.min_model_confidence), 0.0),
                require_both_models=not bool(args.allow_model_disagreement),
                require_direction_match_to_target=not bool(args.allow_target_mismatch),
                allow_no_model_scores=bool(args.allow_no_model_scores),
                include_overlapped=bool(args.include_overlap),
                target_selector=str(args.v2_selector or "impact").strip().lower(),
                min_target_confidence=max(float(args.v2_min_target_confidence), 0.0),
                min_impact_bin=max(int(args.v2_min_impact_bin), 0),
                min_abs_z_post=max(float(args.v2_min_abs_z), 0.0),
                min_abs_ar=max(float(args.v2_min_abs_ar), 0.0),
                source_v2=str(args.source_v2 or "auto_target_v2").strip(),
                quality_v2=str(args.quality_v2 or "silver").strip(),
                label_schema_version=str(args.label_schema_version or "v2").strip(),
            )

        result = {
            "run_date": report.run_date,
            "symbol": report.symbol,
            "horizon": report.horizon,
            "silver_labels_before": report.silver_labels_before,
            "silver_labels_after": report.silver_labels_after,
            "silver_labels_new": report.silver_labels_new,
            "fresh_backfill": {
                "period_from": report.fresh_backfill.period_from,
                "period_to": report.fresh_backfill.period_to,
                "windows_processed": report.fresh_backfill.windows_processed,
                "window_order": report.fresh_backfill.window_order,
                "ingested_count": report.fresh_backfill.ingested_count,
                "entity_link_count": report.fresh_backfill.entity_link_count,
                "event_link_count": report.fresh_backfill.event_link_count,
                "quote_count": report.fresh_backfill.quote_count,
                "newsapi_requests_used": report.fresh_backfill.newsapi_requests_used,
                "newsapi_requests_remaining": report.fresh_backfill.newsapi_requests_remaining,
            },
            "backlog_backfill": (
                {
                    "period_from": report.backlog_backfill.period_from,
                    "period_to": report.backlog_backfill.period_to,
                    "windows_processed": report.backlog_backfill.windows_processed,
                    "window_order": report.backlog_backfill.window_order,
                    "ingested_count": report.backlog_backfill.ingested_count,
                    "entity_link_count": report.backlog_backfill.entity_link_count,
                    "event_link_count": report.backlog_backfill.event_link_count,
                    "quote_count": report.backlog_backfill.quote_count,
                    "newsapi_requests_used": report.backlog_backfill.newsapi_requests_used,
                    "newsapi_requests_remaining": report.backlog_backfill.newsapi_requests_remaining,
                }
                if report.backlog_backfill is not None
                else None
            ),
            "target_report": {
                "events_seen": report.target_report.events_seen,
                "rows_candidate": report.target_report.rows_candidate,
                "rows_upserted": report.target_report.rows_upserted,
                "rows_deleted": report.target_report.rows_deleted,
                "clean_rows": report.target_report.clean_rows,
                "hi_conf_rows": report.target_report.hi_conf_rows,
                "overlap_rows": report.target_report.overlap_rows,
                "leakage_rows": report.target_report.leakage_rows,
                "skipped_no_ticker": report.target_report.skipped_no_ticker,
                "skipped_missing_quotes": report.target_report.skipped_missing_quotes,
            },
            "silver_report": {
                "scanned": report.silver_report.scanned,
                "eligible_targets": report.silver_report.eligible_targets,
                "accepted": report.silver_report.accepted,
                "stored": report.silver_report.stored,
                "skipped_no_primary_news": report.silver_report.skipped_no_primary_news,
                "skipped_missing_scores": report.silver_report.skipped_missing_scores,
                "skipped_confidence": report.silver_report.skipped_confidence,
                "skipped_disagreement": report.silver_report.skipped_disagreement,
                "skipped_relevance": report.silver_report.skipped_relevance,
            },
        }
        print(json.dumps(result, ensure_ascii=False, default=str))
    elif args.command == "news_event_score_backfill":
        from moex_carry.news import backfill_event_scores_for_gold
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        raw_models = [item.strip().lower() for item in str(args.models or "").split(",") if item.strip()]
        selected_models = [item for item in raw_models if item in {"finbert", "nli"}]
        with session_factory() as session:
            report = backfill_event_scores_for_gold(
                session,
                settings,
                quality=str(args.quality or "gold").strip().lower(),
                source=str(args.source).strip() if args.source else None,
                label_schema_version=str(args.label_schema_version).strip() if args.label_schema_version else None,
                max_events=max(int(args.max_events), 0),
                include_existing=bool(args.include_existing),
                model_ids=selected_models,
                text_max_chars=args.text_max_chars,
            )
        print(
            json.dumps(
                {
                    "quality": str(args.quality or "gold").strip().lower(),
                    "source": str(args.source).strip() if args.source else None,
                    "label_schema_version": str(args.label_schema_version).strip() if args.label_schema_version else None,
                    "max_events": max(int(args.max_events), 0),
                    "include_existing": bool(args.include_existing),
                    "models": selected_models or ["finbert", "nli"],
                    "text_max_chars": args.text_max_chars,
                    "report": {
                        "scanned_labels": report.scanned_labels,
                        "candidate_events": report.candidate_events,
                        "scored_events": report.scored_events,
                        "stored_scores": report.stored_scores,
                        "skipped_existing_complete": report.skipped_existing_complete,
                        "skipped_no_text": report.skipped_no_text,
                    },
                },
                ensure_ascii=False,
                default=str,
            )
        )
    elif args.command == "news_reactions":
        from moex_carry.news import rebuild_event_market_reactions
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        from_dt = datetime.fromisoformat(args.from_date) if args.from_date else None
        to_dt = datetime.fromisoformat(args.to_date) if args.to_date else None
        event_ids = (
            [item.strip() for item in str(args.event_ids).split(",") if item.strip()]
            if args.event_ids
            else None
        )
        window_ids = [item.strip() for item in str(args.window_ids).split(",") if item.strip()]
        sampling_freqs = [item.strip() for item in str(args.sampling_freqs).split(",") if item.strip()]
        with session_factory() as session:
            report = rebuild_event_market_reactions(
                session,
                event_ids=event_ids,
                published_from=from_dt,
                published_to=to_dt,
                window_ids=window_ids,
                sampling_freqs=sampling_freqs,
                estimation_lookback_days=args.estimation_lookback_days,
                max_events=args.max_events,
                event_time_mode=args.event_time_mode,
            )
        print(
            json.dumps(
                {
                    "event_time_mode": args.event_time_mode,
                    "events_seen": report.events_seen,
                    "events_processed": report.events_processed,
                    "windows_processed": report.windows_processed,
                    "rows_upserted": report.rows_upserted,
                    "overlap_rows": report.overlap_rows,
                    "skipped_rows": report.skipped_rows,
                },
                ensure_ascii=False,
            )
        )
    elif args.command == "news_target_v2":
        from moex_carry.news import rebuild_event_target_v2
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        from_dt = datetime.fromisoformat(args.from_date) if args.from_date else None
        to_dt = datetime.fromisoformat(args.to_date) if args.to_date else None
        with session_factory() as session:
            report = rebuild_event_target_v2(
                session,
                horizon=str(args.horizon or "5m").strip().lower(),
                symbol=str(args.symbol or "").strip().upper() or None,
                published_from=from_dt,
                published_to=to_dt,
                processing_lag_sec=max(int(args.processing_lag_sec), 0),
                max_events=max(int(args.max_events), 0),
                use_midpoint=bool(args.use_midpoint),
            )
        print(
            json.dumps(
                {
                    "horizon": report.horizon,
                    "symbol_filter": report.symbol_filter,
                    "events_seen": report.events_seen,
                    "rows_candidate": report.rows_candidate,
                    "rows_upserted": report.rows_upserted,
                    "rows_deleted": report.rows_deleted,
                    "clean_rows": report.clean_rows,
                    "hi_conf_rows": report.hi_conf_rows,
                    "overlap_rows": report.overlap_rows,
                    "leakage_rows": report.leakage_rows,
                    "skipped_no_ticker": report.skipped_no_ticker,
                    "skipped_missing_quotes": report.skipped_missing_quotes,
                    "skipped_invalid_time": report.skipped_invalid_time,
                    "skipped_short_history": report.skipped_short_history,
                },
                ensure_ascii=False,
                default=str,
            )
        )
    elif args.command == "news_factor_autolabel":
        from moex_carry.news import run_factor_autolabel_v2
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        from_dt = datetime.fromisoformat(args.from_date) if args.from_date else None
        to_dt = datetime.fromisoformat(args.to_date) if args.to_date else None
        with session_factory() as session:
            report = run_factor_autolabel_v2(
                session,
                horizon=str(args.horizon or "5m").strip().lower(),
                symbol=str(args.symbol or "").strip().upper() or None,
                from_ts=from_dt,
                to_ts=to_dt,
                min_confidence=float(args.min_confidence),
                top_k=max(int(args.top_k), 1),
                include_overlapped=bool(args.include_overlap),
                nli_enabled=not bool(args.disable_nli),
                nli_model_name=str(args.nli_model_name or "facebook/bart-large-mnli").strip(),
                nli_device=str(args.nli_device or "auto").strip(),
                nli_batch_size=max(int(args.nli_batch_size), 1),
                nli_text_max_chars=max(int(args.nli_max_chars), 0),
                label_version=str(args.label_version or "autolabel-v2").strip(),
                text_max_chars=max(int(args.text_max_chars), 0),
                max_events=max(int(args.max_events), 0),
            )
        print(
            json.dumps(
                {
                    "horizon": report.horizon,
                    "symbol_filter": report.symbol_filter,
                    "events_seen": report.events_seen,
                    "events_scored": report.events_scored,
                    "factor_rows_upserted": report.factor_rows_upserted,
                    "labels_upserted": report.labels_upserted,
                    "unknown_primary_count": report.unknown_primary_count,
                    "nli_used": report.nli_used,
                    "nli_events_requested": report.nli_events_requested,
                    "nli_events_skipped": report.nli_events_skipped,
                    "nli_pipeline_calls": report.nli_pipeline_calls,
                    "nli_batch_groups": report.nli_batch_groups,
                },
                ensure_ascii=False,
                default=str,
            )
        )
    elif args.command == "news_live_eval":
        from moex_carry.news.live_eval import build_news_live_eval_rows, render_news_live_eval_top
        from moex_carry.data.moex_iss import MoexIssClient
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        from_date = date.fromisoformat(args.from_date) if args.from_date else (date.today() - timedelta(days=1))
        to_date = date.fromisoformat(args.to_date) if args.to_date else (from_date + timedelta(days=1))
        tickers = [item.strip().upper() for item in str(args.tickers or "").split(",") if item.strip()]
        if not tickers:
            tickers = ["BRN", "GOLD", "NG_US"]
        horizon = str(args.horizon or "1h").strip().lower()
        timezone_name = str(args.timezone or "Europe/Moscow").strip() or "Europe/Moscow"
        limit = max(int(args.limit or 0), 1)
        top_per_ticker = max(int(args.top_per_ticker or 0), 1)
        gap_lag_minutes = max(int(args.gap_lag_minutes or 0), 1)
        moex_contract_eval = bool(args.moex_contract_eval)
        moex_roll_days = max(int(args.moex_roll_days or 0), 0)

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        preferred_models = [settings.news_models.primary_model] + list(settings.news_models.enabled_models)
        moex_client = None
        if moex_contract_eval:
            moex_client = MoexIssClient(
                base_url=settings.moex.base_url,
                timeout_sec=settings.moex.request_timeout_sec,
                max_retries=settings.moex.request_max_retries,
                retry_backoff_sec=settings.moex.request_retry_backoff_sec,
                retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
                fallback_ips=settings.moex.fallback_ips,
                force_fallback=settings.moex.force_fallback,
            )

        with session_factory() as session:
            rows, summary = build_news_live_eval_rows(
                session,
                from_date=from_date,
                to_date=to_date,
                tickers=tickers,
                horizon=horizon,
                timezone_name=timezone_name,
                limit=limit,
                preferred_models=preferred_models,
                gap_lag_minutes=gap_lag_minutes,
                moex_client=moex_client,
                moex_futures_board=str(settings.moex.futures_board or "RFUD").strip() or "RFUD",
                moex_roll_days=moex_roll_days,
            )

        output_dir = resolve_paths(settings).data_dir / "output"
        from_text = from_date.isoformat()
        to_text = to_date.isoformat()
        output_path = (
            Path(args.output)
            if args.output
            else (output_dir / f"news_live_eval_{from_text}_{to_text}.jsonl")
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        summary_path = (
            Path(args.summary_output)
            if args.summary_output
            else (output_dir / f"news_live_eval_{from_text}_{to_text}_top.txt")
        )
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            render_news_live_eval_top(rows, tickers=tickers, top_per_ticker=top_per_ticker),
            encoding="utf-8",
        )

        print(
            json.dumps(
                {
                    "from_date": from_text,
                    "to_date": to_text,
                    "timezone": timezone_name,
                    "horizon": horizon,
                    "tickers": tickers,
                    "gap_lag_minutes": gap_lag_minutes,
                    "moex_contract_eval": moex_contract_eval,
                    "moex_roll_days": moex_roll_days,
                    "rows_total": len(rows),
                    "output_path": str(output_path),
                    "summary_path": str(summary_path),
                    "summary": summary,
                },
                ensure_ascii=False,
                default=str,
            )
        )
    elif args.command == "news_benchmark":
        from moex_carry.news import parse_positive_int_list, run_news_inference_benchmark
        from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        batch_sizes = parse_positive_int_list(args.batch_sizes, default=[1, 2, 4, 8])
        thread_caps = parse_positive_int_list(args.thread_caps, default=[2, 4, 6])
        text_caps = parse_positive_int_list(args.text_caps, default=[1200, 1500, 2000])
        with session_factory() as session:
            report = run_news_inference_benchmark(
                session,
                settings,
                sample_size=args.sample_size,
                lookback_days=args.lookback_days,
                ticker=args.ticker,
                batch_sizes=batch_sizes,
                thread_caps=thread_caps,
                text_caps=text_caps,
                warmup_runs=args.warmup_runs,
                repeat_runs=args.repeat_runs,
            )
        if args.write_profile:
            output_path = Path(args.write_profile)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                yaml.safe_dump(report.get("recommended_profile") or {}, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
        print(json.dumps(report, ensure_ascii=False, default=str))
    else:
        return False
    return True
