from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from moex_carry.config import load_settings, resolve_paths  # noqa: E402
from moex_carry.news import (  # noqa: E402
    bootstrap_silver_from_v2_targets,
    rebuild_event_target_v2,
    run_factor_autolabel_v2,
    run_news_backfill,
)
from moex_carry.storage import models as db  # noqa: E402
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db  # noqa: E402


DEFAULT_SYMBOLS = ("NG_US", "BRN", "GOLD")


def _parse_symbols(raw: str | None) -> list[str]:
    values = [str(item).strip().upper() for item in str(raw or "").split(",")]
    normalized = [item for item in values if item]
    return normalized or list(DEFAULT_SYMBOLS)


def _parse_date(raw: str | None, *, fallback: date) -> date:
    if raw is None:
        return fallback
    return date.fromisoformat(str(raw).strip())


def _to_iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def _label_direction_from_target(label_v2: int) -> str:
    if int(label_v2) > 0:
        return "up"
    if int(label_v2) < 0:
        return "down"
    return "neutral"


def _count_silver_labels(
    session: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    quality: str,
    label_schema_version: str,
    from_dt: datetime,
    to_dt: datetime,
) -> int:
    query = (
        select(func.count(func.distinct(db.NewsGoldLabelModel.target_id)))
        .join(db.EventTargetV2Model, db.EventTargetV2Model.event_id == db.NewsGoldLabelModel.target_id)
        .where(db.NewsGoldLabelModel.target_type == "event")
        .where(db.NewsGoldLabelModel.source == str(source).strip())
        .where(db.NewsGoldLabelModel.quality == str(quality).strip())
        .where(db.NewsGoldLabelModel.label_schema_version == str(label_schema_version).strip())
        .where(db.EventTargetV2Model.symbol == str(symbol).strip().upper())
        .where(db.EventTargetV2Model.horizon == str(horizon).strip().lower())
        .where(db.EventTargetV2Model.t0 >= from_dt)
        .where(db.EventTargetV2Model.t0 <= to_dt)
    )
    value = session.execute(query).scalar()
    return int(value or 0)


def _count_silver_high_conf_labels(
    session: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    quality: str,
    label_schema_version: str,
    from_dt: datetime,
    to_dt: datetime,
    include_overlap: bool,
) -> int:
    query = (
        select(func.count(func.distinct(db.NewsGoldLabelModel.target_id)))
        .join(db.EventTargetV2Model, db.EventTargetV2Model.event_id == db.NewsGoldLabelModel.target_id)
        .where(db.NewsGoldLabelModel.target_type == "event")
        .where(db.NewsGoldLabelModel.source == str(source).strip())
        .where(db.NewsGoldLabelModel.quality == str(quality).strip())
        .where(db.NewsGoldLabelModel.label_schema_version == str(label_schema_version).strip())
        .where(db.EventTargetV2Model.symbol == str(symbol).strip().upper())
        .where(db.EventTargetV2Model.horizon == str(horizon).strip().lower())
        .where(db.EventTargetV2Model.t0 >= from_dt)
        .where(db.EventTargetV2Model.t0 <= to_dt)
        .where(db.EventTargetV2Model.is_hi_conf.is_(True))
        .where(db.EventTargetV2Model.leakage_postmove.is_(False))
        .where(db.EventTargetV2Model.is_repost.is_(False))
    )
    if not include_overlap:
        query = query.where(db.EventTargetV2Model.is_overlapped.is_(False))
    value = session.execute(query).scalar()
    return int(value or 0)


def _latest_factor_label_map(
    session: Session,
    *,
    event_ids: list[str],
) -> dict[str, dict[str, Any]]:
    normalized = [str(item).strip() for item in event_ids if str(item).strip()]
    if not normalized:
        return {}
    rows = (
        session.execute(
            select(db.NewsLabelModel)
            .where(db.NewsLabelModel.target_level == "event")
            .where(db.NewsLabelModel.label_source == "auto_factor_v2")
            .where(db.NewsLabelModel.target_id.in_(normalized))
            .order_by(db.NewsLabelModel.created_at.desc())
        )
        .scalars()
        .all()
    )
    by_event: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_id = str(row.target_id or "").strip()
        if not event_id or event_id in by_event:
            continue
        primary = None
        secondary = None
        if isinstance(row.news_type_json, list) and row.news_type_json:
            primary = str(row.news_type_json[0] or "").strip() or None
            if len(row.news_type_json) > 1:
                secondary = str(row.news_type_json[1] or "").strip() or None
        by_event[event_id] = {
            "factor_primary": primary,
            "factor_secondary": secondary,
            "factor_label_confidence": float(row.confidence or 0.0),
        }
    return by_event


def _load_silver_high_conf_dataset(
    session: Session,
    *,
    symbols: list[str],
    horizon: str,
    source: str,
    quality: str,
    label_schema_version: str,
    from_dt: datetime,
    to_dt: datetime,
    include_overlap: bool,
) -> list[dict[str, Any]]:
    query = (
        select(db.EventTargetV2Model, db.NewsGoldLabelModel)
        .join(db.NewsGoldLabelModel, db.NewsGoldLabelModel.target_id == db.EventTargetV2Model.event_id)
        .where(db.NewsGoldLabelModel.target_type == "event")
        .where(db.NewsGoldLabelModel.source == str(source).strip())
        .where(db.NewsGoldLabelModel.quality == str(quality).strip())
        .where(db.NewsGoldLabelModel.label_schema_version == str(label_schema_version).strip())
        .where(db.EventTargetV2Model.horizon == str(horizon).strip().lower())
        .where(db.EventTargetV2Model.symbol.in_([str(item).strip().upper() for item in symbols]))
        .where(db.EventTargetV2Model.t0 >= from_dt)
        .where(db.EventTargetV2Model.t0 <= to_dt)
        .where(db.EventTargetV2Model.is_hi_conf.is_(True))
        .where(db.EventTargetV2Model.leakage_postmove.is_(False))
        .where(db.EventTargetV2Model.is_repost.is_(False))
        .order_by(db.EventTargetV2Model.symbol.asc(), db.EventTargetV2Model.t0.asc(), db.EventTargetV2Model.event_id.asc())
    )
    if not include_overlap:
        query = query.where(db.EventTargetV2Model.is_overlapped.is_(False))
    rows = session.execute(query).all()
    if not rows:
        return []

    event_ids = [str(target.event_id or "").strip() for target, _ in rows if str(target.event_id or "").strip()]
    factor_map = _latest_factor_label_map(session, event_ids=event_ids)

    result: list[dict[str, Any]] = []
    for target, label in rows:
        event_id = str(target.event_id or "").strip()
        factor = factor_map.get(event_id, {})
        result.append(
            {
                "event_id": event_id,
                "symbol": str(target.symbol or ""),
                "horizon": str(target.horizon or ""),
                "t0": _to_iso_z(target.t0),
                "t1": _to_iso_z(target.t1),
                "z_post": float(target.z_post or 0.0),
                "z_pre": float(target.z_pre or 0.0),
                "impact_score": float(target.impact_score or 0.0),
                "impact_bin": int(target.impact_bin or 0),
                "target_confidence": float(target.confidence or 0.0),
                "target_label_v2": int(target.label_v2 or 0),
                "target_direction": _label_direction_from_target(int(target.label_v2 or 0)),
                "silver_direction_label": str(label.direction_label or ""),
                "silver_confidence": float(label.confidence or 0.0),
                "silver_source": str(label.source or ""),
                "silver_quality": str(label.quality or ""),
                "silver_schema_version": str(label.label_schema_version or ""),
                "is_hi_conf": bool(target.is_hi_conf),
                "is_overlapped": bool(target.is_overlapped),
                "leakage_postmove": bool(target.leakage_postmove),
                "price_source": str(target.price_source or ""),
                "factor_primary": str(factor.get("factor_primary") or ""),
                "factor_secondary": str(factor.get("factor_secondary") or ""),
                "factor_label_confidence": float(factor.get("factor_label_confidence") or 0.0),
                "label_created_at": _to_iso_z(label.created_at),
            }
        )
    return result


def run_cycle(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    symbols = _parse_symbols(args.symbols)
    horizon = str(args.horizon or "5m").strip().lower()
    today = date.today()
    to_day = _parse_date(args.to_date, fallback=today)
    from_day = _parse_date(args.from_date, fallback=(to_day - timedelta(days=max(int(args.period_days), 1))))
    if from_day > to_day:
        raise ValueError(f"from_date must be <= to_date: {from_day} > {to_day}")

    from_dt = datetime.combine(from_day, time.min)
    to_dt = datetime.combine(to_day, time.max).replace(microsecond=0)
    out_dir = Path(args.out_dir) if args.out_dir else (resolve_paths(settings).data_dir / "output" / "shock_silver_cycle")
    out_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    report: dict[str, Any] = {
        "run_ts_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "from_date": from_day.isoformat(),
        "to_date": to_day.isoformat(),
        "symbols": symbols,
        "horizon": horizon,
        "backfill_enabled": bool(args.run_backfill),
        "backfill": None,
        "per_symbol": [],
    }

    with session_factory() as session:
        if args.run_backfill:
            backfill_report = run_news_backfill(
                session,
                settings,
                period_from=from_day,
                period_to=to_day,
                commodities=symbols,
                include_prices=not bool(args.without_prices),
                run_inference=bool(args.run_inference),
                chunk_days_override=max(int(args.backfill_chunk_days), 1),
                max_windows_per_commodity=max(int(args.backfill_max_windows_per_commodity), 0),
                window_order_override=str(args.backfill_window_order or "shock_first").strip().lower(),
            )
            report["backfill"] = {
                "period_from": backfill_report.period_from,
                "period_to": backfill_report.period_to,
                "commodities": backfill_report.commodities,
                "windows_processed": backfill_report.windows_processed,
                "window_order": backfill_report.window_order,
                "ingested_count": backfill_report.ingested_count,
                "entity_link_count": backfill_report.entity_link_count,
                "event_link_count": backfill_report.event_link_count,
                "score_count": backfill_report.score_count,
                "quote_count": backfill_report.quote_count,
                "newsapi_requests_used": backfill_report.newsapi_requests_used,
                "newsapi_requests_remaining": backfill_report.newsapi_requests_remaining,
                "qc_report": backfill_report.qc_report,
            }

        for symbol in symbols:
            silver_before = _count_silver_labels(
                session,
                symbol=symbol,
                horizon=horizon,
                source=str(args.source_v2 or "auto_target_v2"),
                quality=str(args.quality_v2 or "silver"),
                label_schema_version=str(args.label_schema_version or "v2"),
                from_dt=from_dt,
                to_dt=to_dt,
            )
            target_report = rebuild_event_target_v2(
                session,
                horizon=horizon,
                symbol=symbol,
                published_from=from_dt,
                published_to=to_dt,
                processing_lag_sec=max(int(args.processing_lag_sec), 0),
                max_events=max(int(args.max_events), 0),
                use_midpoint=bool(args.use_midpoint),
            )
            factor_report = run_factor_autolabel_v2(
                session,
                horizon=horizon,
                symbol=symbol,
                from_ts=from_dt,
                to_ts=to_dt,
                min_confidence=max(float(args.factor_min_confidence), 0.0),
                top_k=max(int(args.factor_top_k), 1),
                include_overlapped=bool(args.include_overlap),
                nli_enabled=not bool(args.factor_disable_nli),
                nli_model_name=str(args.factor_nli_model_name or "facebook/bart-large-mnli").strip(),
                nli_device=str(args.factor_nli_device or "auto").strip(),
                nli_batch_size=max(int(args.factor_nli_batch_size), 1),
                nli_text_max_chars=max(int(args.factor_nli_max_chars), 0),
                label_version=str(args.factor_label_version or "autolabel-v2").strip(),
                text_max_chars=max(int(args.factor_text_max_chars), 0),
                max_events=max(int(args.factor_max_events), 0),
            )
            silver_report = bootstrap_silver_from_v2_targets(
                session,
                horizon=horizon,
                symbol=symbol,
                published_from=from_dt,
                published_to=to_dt,
                min_model_confidence=max(float(args.min_model_confidence), 0.0),
                require_both_models=not bool(args.allow_model_disagreement),
                require_direction_match_to_target=not bool(args.allow_target_mismatch),
                allow_no_model_scores=bool(args.allow_no_model_scores),
                source=str(args.source_v2 or "auto_target_v2"),
                quality=str(args.quality_v2 or "silver"),
                label_schema_version=str(args.label_schema_version or "v2"),
                max_events=max(int(args.max_events), 0),
                include_overlapped=bool(args.include_overlap),
                target_selector=str(args.v2_selector or "impact").strip().lower(),
                min_target_confidence=max(float(args.v2_min_target_confidence), 0.0),
                min_impact_bin=max(int(args.v2_min_impact_bin), 0),
                min_abs_z_post=max(float(args.v2_min_abs_z), 0.0),
                min_abs_ar=max(float(args.v2_min_abs_ar), 0.0),
                allow_target_only_fallback=bool(args.allow_target_only_fallback),
                require_primary_news_relevance=not bool(args.disable_primary_news_relevance),
                require_ticker_text_support=not bool(args.disable_ticker_text_support),
            )
            silver_after = _count_silver_labels(
                session,
                symbol=symbol,
                horizon=horizon,
                source=str(args.source_v2 or "auto_target_v2"),
                quality=str(args.quality_v2 or "silver"),
                label_schema_version=str(args.label_schema_version or "v2"),
                from_dt=from_dt,
                to_dt=to_dt,
            )
            silver_hi_conf_after = _count_silver_high_conf_labels(
                session,
                symbol=symbol,
                horizon=horizon,
                source=str(args.source_v2 or "auto_target_v2"),
                quality=str(args.quality_v2 or "silver"),
                label_schema_version=str(args.label_schema_version or "v2"),
                from_dt=from_dt,
                to_dt=to_dt,
                include_overlap=bool(args.include_overlap),
            )

            report["per_symbol"].append(
                {
                    "symbol": symbol,
                    "horizon": horizon,
                    "target_report": {
                        "events_seen": target_report.events_seen,
                        "rows_candidate": target_report.rows_candidate,
                        "rows_upserted": target_report.rows_upserted,
                        "clean_rows": target_report.clean_rows,
                        "hi_conf_rows": target_report.hi_conf_rows,
                        "overlap_rows": target_report.overlap_rows,
                        "leakage_rows": target_report.leakage_rows,
                        "skipped_no_ticker": target_report.skipped_no_ticker,
                        "skipped_missing_quotes": target_report.skipped_missing_quotes,
                    },
                    "factor_report": {
                        "events_seen": factor_report.events_seen,
                        "events_scored": factor_report.events_scored,
                        "factor_rows_upserted": factor_report.factor_rows_upserted,
                        "labels_upserted": factor_report.labels_upserted,
                        "unknown_primary_count": factor_report.unknown_primary_count,
                        "nli_used": factor_report.nli_used,
                        "nli_events_requested": factor_report.nli_events_requested,
                        "nli_events_skipped": factor_report.nli_events_skipped,
                        "nli_pipeline_calls": factor_report.nli_pipeline_calls,
                        "nli_batch_groups": factor_report.nli_batch_groups,
                    },
                    "silver_report": {
                        "scanned": silver_report.scanned,
                        "eligible_targets": silver_report.eligible_targets,
                        "accepted": silver_report.accepted,
                        "stored": silver_report.stored,
                        "skipped_no_primary_news": silver_report.skipped_no_primary_news,
                        "skipped_missing_scores": silver_report.skipped_missing_scores,
                        "skipped_confidence": silver_report.skipped_confidence,
                        "skipped_disagreement": silver_report.skipped_disagreement,
                        "skipped_relevance": silver_report.skipped_relevance,
                    },
                    "silver_labels_before": silver_before,
                    "silver_labels_after": silver_after,
                    "silver_labels_new": max(int(silver_after) - int(silver_before), 0),
                    "silver_hi_conf_after": silver_hi_conf_after,
                }
            )

        dataset_rows = _load_silver_high_conf_dataset(
            session,
            symbols=symbols,
            horizon=horizon,
            source=str(args.source_v2 or "auto_target_v2"),
            quality=str(args.quality_v2 or "silver"),
            label_schema_version=str(args.label_schema_version or "v2"),
            from_dt=from_dt,
            to_dt=to_dt,
            include_overlap=bool(args.include_overlap),
        )

    report["totals"] = {
        "symbols": len(symbols),
        "silver_labels_new_total": sum(int(item.get("silver_labels_new") or 0) for item in report["per_symbol"]),
        "silver_hi_conf_total": sum(int(item.get("silver_hi_conf_after") or 0) for item in report["per_symbol"]),
        "dataset_rows": len(dataset_rows),
    }

    summary_csv_path = out_dir / f"shock_silver_cycle_summary_{horizon}.csv"
    with summary_csv_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "symbol",
            "horizon",
            "events_seen",
            "rows_upserted",
            "clean_rows",
            "hi_conf_rows",
            "factor_events_scored",
            "factor_rows_upserted",
            "silver_accepted",
            "silver_stored",
            "silver_labels_before",
            "silver_labels_after",
            "silver_labels_new",
            "silver_hi_conf_after",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in report["per_symbol"]:
            target_report = item["target_report"]
            factor_report = item["factor_report"]
            silver_report = item["silver_report"]
            writer.writerow(
                {
                    "symbol": item["symbol"],
                    "horizon": item["horizon"],
                    "events_seen": target_report["events_seen"],
                    "rows_upserted": target_report["rows_upserted"],
                    "clean_rows": target_report["clean_rows"],
                    "hi_conf_rows": target_report["hi_conf_rows"],
                    "factor_events_scored": factor_report["events_scored"],
                    "factor_rows_upserted": factor_report["factor_rows_upserted"],
                    "silver_accepted": silver_report["accepted"],
                    "silver_stored": silver_report["stored"],
                    "silver_labels_before": item["silver_labels_before"],
                    "silver_labels_after": item["silver_labels_after"],
                    "silver_labels_new": item["silver_labels_new"],
                    "silver_hi_conf_after": item["silver_hi_conf_after"],
                }
            )

    dataset_csv_path = out_dir / f"silver_high_conf_dataset_{horizon}.csv"
    with dataset_csv_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(dataset_rows[0].keys()) if dataset_rows else []
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(dataset_rows)

    dataset_jsonl_path = out_dir / f"silver_high_conf_dataset_{horizon}.jsonl"
    with dataset_jsonl_path.open("w", encoding="utf-8") as handle:
        for row in dataset_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    report["outputs"] = {
        "summary_csv": str(summary_csv_path),
        "silver_high_conf_csv": str(dataset_csv_path),
        "silver_high_conf_jsonl": str(dataset_jsonl_path),
    }
    report_path = out_dir / f"shock_silver_cycle_report_{horizon}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["outputs"]["report_json"] = str(report_path)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_news_shock_silver_cycle",
        description="Run shock-first -> target_v2 -> factor autolabel -> silver bootstrap cycle and export silver_high_conf dataset.",
    )
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--from-date", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--to-date", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--period-days", type=int, default=365)
    parser.add_argument("--symbols", type=str, default="NG_US,BRN,GOLD")
    parser.add_argument("--horizon", type=str, default="5m", choices=["5m", "1h", "4h", "1d"])
    parser.add_argument("--out-dir", type=str, default=None)

    parser.add_argument("--run-backfill", action="store_true")
    parser.add_argument("--without-prices", action="store_true")
    parser.add_argument("--run-inference", action="store_true")
    parser.add_argument("--backfill-chunk-days", type=int, default=30)
    parser.add_argument("--backfill-max-windows-per-commodity", type=int, default=1)
    parser.add_argument(
        "--backfill-window-order",
        type=str,
        default="shock_first",
        choices=["chronological", "recent_first", "shock_first"],
    )

    parser.add_argument("--processing-lag-sec", type=int, default=60)
    parser.add_argument("--use-midpoint", action="store_true")
    parser.add_argument("--max-events", type=int, default=0)

    parser.add_argument("--factor-min-confidence", type=float, default=0.35)
    parser.add_argument("--factor-top-k", type=int, default=3)
    parser.add_argument("--factor-disable-nli", action="store_true")
    parser.add_argument("--factor-nli-model-name", type=str, default="facebook/bart-large-mnli")
    parser.add_argument("--factor-nli-device", type=str, default="cuda:0")
    parser.add_argument("--factor-nli-batch-size", type=int, default=64)
    parser.add_argument("--factor-nli-max-chars", type=int, default=800)
    parser.add_argument("--factor-label-version", type=str, default="autolabel-v2")
    parser.add_argument("--factor-text-max-chars", type=int, default=4000)
    parser.add_argument("--factor-max-events", type=int, default=0)

    parser.add_argument("--min-model-confidence", type=float, default=0.55)
    parser.add_argument("--allow-model-disagreement", action="store_true")
    parser.add_argument("--allow-target-mismatch", action="store_true")
    parser.add_argument("--allow-no-model-scores", action="store_true")
    parser.add_argument("--allow-target-only-fallback", action="store_true")
    parser.add_argument("--include-overlap", action="store_true")
    parser.add_argument(
        "--disable-primary-news-relevance",
        action="store_true",
        help="Do not require primary news language/source/text quality relevance checks when building silver labels.",
    )
    parser.add_argument(
        "--disable-ticker-text-support",
        action="store_true",
        help="Do not require ticker text mention in primary news relevance checks.",
    )
    parser.add_argument("--v2-selector", type=str, default="impact", choices=["hi_conf", "impact", "hybrid"])
    parser.add_argument("--v2-min-target-confidence", type=float, default=0.35)
    parser.add_argument("--v2-min-impact-bin", type=int, default=1)
    parser.add_argument("--v2-min-abs-z", type=float, default=1.0)
    parser.add_argument("--v2-min-abs-ar", type=float, default=0.0005)
    parser.add_argument("--source-v2", type=str, default="auto_target_v2")
    parser.add_argument("--quality-v2", type=str, default="silver")
    parser.add_argument("--label-schema-version", type=str, default="v2")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_cycle(args)


if __name__ == "__main__":
    raise SystemExit(main())
