from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moex_carry.config import AppSettings
from moex_carry.news.backfill import NewsBackfillReport, run_news_backfill
from moex_carry.news.gold_bootstrap import V2SilverBootstrapReport, bootstrap_silver_from_v2_targets
from moex_carry.news.target_v2 import EventTargetV2BuildReport, rebuild_event_target_v2
from moex_carry.storage import models as db


def _as_datetime_utc(value: date) -> datetime:
    return datetime(value.year, value.month, value.day)


def _count_silver_labels_for_symbol_horizon(
    session: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    quality: str,
    label_schema_version: str,
) -> int:
    query = (
        select(func.count(func.distinct(db.NewsGoldLabelModel.target_id)))
        .join(
            db.EventTargetV2Model,
            db.EventTargetV2Model.event_id == db.NewsGoldLabelModel.target_id,
        )
        .where(db.NewsGoldLabelModel.target_type == "event")
        .where(db.NewsGoldLabelModel.source == str(source).strip())
        .where(db.NewsGoldLabelModel.quality == str(quality).strip())
        .where(db.NewsGoldLabelModel.label_schema_version == str(label_schema_version).strip())
        .where(db.EventTargetV2Model.symbol == str(symbol).strip().upper())
        .where(db.EventTargetV2Model.horizon == str(horizon).strip().lower())
    )
    value = session.execute(query).scalar()
    return int(value or 0)


@dataclass(frozen=True)
class DailySilverCycleReport:
    run_date: str
    symbol: str
    horizon: str
    fresh_backfill: NewsBackfillReport
    backlog_backfill: NewsBackfillReport | None
    target_report: EventTargetV2BuildReport
    silver_report: V2SilverBootstrapReport
    silver_labels_before: int
    silver_labels_after: int
    silver_labels_new: int


def run_news_daily_silver_cycle(
    session: Session,
    settings: AppSettings,
    *,
    run_date: date,
    symbol: str,
    horizon: str = "5m",
    fresh_days: int = 2,
    fresh_chunk_days: int = 1,
    fresh_max_windows: int = 40,
    backlog_from_date: date | None = None,
    backlog_chunk_days: int = 30,
    backlog_max_windows: int = 1,
    include_prices: bool = True,
    run_inference: bool = False,
    processing_lag_sec: int = 60,
    use_midpoint: bool = True,
    min_model_confidence: float = 0.55,
    require_both_models: bool = False,
    require_direction_match_to_target: bool = False,
    allow_no_model_scores: bool = True,
    include_overlapped: bool = False,
    target_selector: str = "impact",
    min_target_confidence: float = 0.35,
    min_impact_bin: int = 1,
    min_abs_z_post: float = 1.0,
    min_abs_ar: float = 0.0005,
    require_primary_news_relevance: bool = True,
    allowed_languages: tuple[str, ...] = ("en",),
    allow_target_only_fallback: bool = False,
    source_v2: str = "auto_target_v2",
    quality_v2: str = "silver",
    label_schema_version: str = "v2",
) -> DailySilverCycleReport:
    normalized_symbol = str(symbol or "").strip().upper()
    normalized_horizon = str(horizon or "5m").strip().lower()
    day = run_date

    effective_fresh_days = max(int(fresh_days), 1)
    fresh_from = day - timedelta(days=effective_fresh_days - 1)
    fresh_to = day
    fresh_report = run_news_backfill(
        session,
        settings,
        period_from=fresh_from,
        period_to=fresh_to,
        commodities=[normalized_symbol],
        include_prices=include_prices,
        run_inference=run_inference,
        chunk_days_override=max(int(fresh_chunk_days), 1),
        max_windows_per_commodity=max(int(fresh_max_windows), 0),
        window_order_override="recent_first",
    )

    backlog_report: NewsBackfillReport | None = None
    backlog_from = backlog_from_date if backlog_from_date is not None else (day - timedelta(days=365))
    backlog_to = fresh_from - timedelta(days=1)
    if backlog_to >= backlog_from:
        backlog_report = run_news_backfill(
            session,
            settings,
            period_from=backlog_from,
            period_to=backlog_to,
            commodities=[normalized_symbol],
            include_prices=include_prices,
            run_inference=run_inference,
            chunk_days_override=max(int(backlog_chunk_days), 1),
            max_windows_per_commodity=max(int(backlog_max_windows), 0),
            window_order_override="shock_first",
        )

    target_from = min(backlog_from, fresh_from) if backlog_report is not None else fresh_from
    target_to = fresh_to
    target_report = rebuild_event_target_v2(
        session,
        horizon=normalized_horizon,
        symbol=normalized_symbol,
        published_from=_as_datetime_utc(target_from),
        published_to=_as_datetime_utc(target_to) + timedelta(hours=23, minutes=59, seconds=59),
        processing_lag_sec=max(int(processing_lag_sec), 0),
        max_events=0,
        use_midpoint=bool(use_midpoint),
    )

    labels_before = _count_silver_labels_for_symbol_horizon(
        session,
        symbol=normalized_symbol,
        horizon=normalized_horizon,
        source=source_v2,
        quality=quality_v2,
        label_schema_version=label_schema_version,
    )
    silver_report = bootstrap_silver_from_v2_targets(
        session,
        horizon=normalized_horizon,
        symbol=normalized_symbol,
        published_from=_as_datetime_utc(target_from),
        published_to=_as_datetime_utc(target_to) + timedelta(hours=23, minutes=59, seconds=59),
        min_model_confidence=max(float(min_model_confidence), 0.0),
        require_both_models=bool(require_both_models),
        require_direction_match_to_target=bool(require_direction_match_to_target),
        allow_no_model_scores=bool(allow_no_model_scores),
        source=str(source_v2 or "auto_target_v2"),
        quality=str(quality_v2 or "silver"),
        label_schema_version=str(label_schema_version or "v2"),
        max_events=0,
        include_overlapped=bool(include_overlapped),
        target_selector=str(target_selector or "impact"),
        min_target_confidence=max(float(min_target_confidence), 0.0),
        min_impact_bin=max(int(min_impact_bin), 0),
        min_abs_z_post=max(float(min_abs_z_post), 0.0),
        min_abs_ar=max(float(min_abs_ar), 0.0),
        require_primary_news_relevance=bool(require_primary_news_relevance),
        allowed_languages=tuple(allowed_languages),
        allow_target_only_fallback=bool(allow_target_only_fallback),
    )
    labels_after = _count_silver_labels_for_symbol_horizon(
        session,
        symbol=normalized_symbol,
        horizon=normalized_horizon,
        source=source_v2,
        quality=quality_v2,
        label_schema_version=label_schema_version,
    )

    return DailySilverCycleReport(
        run_date=day.isoformat(),
        symbol=normalized_symbol,
        horizon=normalized_horizon,
        fresh_backfill=fresh_report,
        backlog_backfill=backlog_report,
        target_report=target_report,
        silver_report=silver_report,
        silver_labels_before=labels_before,
        silver_labels_after=labels_after,
        silver_labels_new=max(labels_after - labels_before, 0),
    )
