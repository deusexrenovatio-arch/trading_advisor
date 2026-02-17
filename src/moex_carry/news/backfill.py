from __future__ import annotations

import csv
import importlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO
from typing import Iterable

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moex_carry.config import AppSettings
from moex_carry.news.events import cluster_news_events
from moex_carry.news.ingestion import fetch_gdelt_news
from moex_carry.news.inference import run_dual_model_inference_batch
from moex_carry.news.linking import default_tag_rows, link_news_item
from moex_carry.storage import models as db
from moex_carry.storage.repositories import (
    upsert_news_entity_links,
    upsert_news_impact_scores,
    upsert_news_item_tags,
    upsert_news_items,
    upsert_news_tags,
    upsert_quotes,
)


@dataclass(frozen=True)
class NewsBackfillReport:
    period_from: str
    period_to: str
    commodities: list[str]
    ingested_count: int
    entity_link_count: int
    tag_link_count: int
    score_count: int
    event_link_count: int
    event_created_count: int
    event_updated_count: int
    event_refuted_count: int
    event_resolved_count: int
    quote_count: int
    windows_processed: int
    qc_report: dict[str, object]


def _as_utc_naive(value: datetime) -> datetime:
    normalized = value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    else:
        normalized = normalized.astimezone(timezone.utc)
    return normalized.replace(tzinfo=None)


def _table_count(session: Session, table_model) -> int:
    value = session.execute(select(func.count()).select_from(table_model)).scalar()
    return int(value or 0)


def _iter_date_windows(
    *,
    start_date: date,
    end_date: date,
    chunk_days: int,
    max_windows: int,
) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    cursor = start_date
    effective_chunk = max(int(chunk_days), 1)
    limit = max(int(max_windows), 0)
    while cursor <= end_date:
        window_end = min(cursor + timedelta(days=effective_chunk - 1), end_date)
        windows.append(
            (
                datetime.combine(cursor, time.min).replace(tzinfo=timezone.utc),
                datetime.combine(window_end, time.max).replace(tzinfo=timezone.utc),
            )
        )
        if limit > 0 and len(windows) >= limit:
            break
        cursor = window_end + timedelta(days=1)
    return windows


def _selected_profiles(settings: AppSettings, commodities: Iterable[str] | None) -> list[object]:
    allowed = None
    if commodities:
        allowed = {str(item).strip().upper() for item in commodities if str(item).strip()}
    selected = []
    for profile in settings.news_ingest.commodity_profiles:
        ticker = str(profile.ticker).strip().upper()
        if allowed is not None and ticker not in allowed:
            continue
        selected.append(profile)
    return selected


def _fetch_fred_daily_series(
    *,
    series_id: str,
    period_from: date,
    period_to: date,
    timeout_sec: int,
) -> list[dict[str, object]]:
    symbol = str(series_id or "").strip()
    if not symbol:
        return []
    try:
        response = requests.get(
            "https://fred.stlouisfed.org/graph/fredgraph.csv",
            params={"id": symbol},
            timeout=max(int(timeout_sec), 5),
        )
    except requests.RequestException:
        return []
    if response.status_code != 200:
        return []

    reader = csv.DictReader(StringIO(response.text))
    rows: list[dict[str, object]] = []
    for row in reader:
        if not isinstance(row, dict):
            continue
        raw_date = str(row.get("observation_date") or "").strip()
        if not raw_date:
            continue
        try:
            point_date = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if point_date < period_from or point_date > period_to:
            continue
        raw_value = str(row.get(symbol) or "").strip()
        if not raw_value or raw_value == ".":
            continue
        try:
            close = float(raw_value)
        except ValueError:
            continue
        ts = datetime.combine(point_date, time(hour=20, minute=0)).replace(tzinfo=timezone.utc)
        rows.append(
            {
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "last": close,
                "bid": None,
                "ask": None,
                "volume": None,
            }
        )
    return rows


def _fetch_stooq_daily_series(
    *,
    symbol: str,
    period_from: date,
    period_to: date,
    timeout_sec: int,
) -> list[dict[str, object]]:
    ticker = str(symbol or "").strip().lower()
    if not ticker:
        return []
    try:
        response = requests.get(
            "https://stooq.com/q/d/l/",
            params={"s": ticker, "i": "d"},
            timeout=max(int(timeout_sec), 5),
        )
    except requests.RequestException:
        return []
    if response.status_code != 200:
        return []
    if "Date,Open,High,Low,Close" not in response.text:
        return []

    reader = csv.DictReader(StringIO(response.text))
    rows: list[dict[str, object]] = []
    for row in reader:
        if not isinstance(row, dict):
            continue
        raw_date = str(row.get("Date") or "").strip()
        if not raw_date:
            continue
        try:
            point_date = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if point_date < period_from or point_date > period_to:
            continue
        raw_close = str(row.get("Close") or "").strip()
        if not raw_close:
            continue
        try:
            close = float(raw_close)
        except ValueError:
            continue
        ts = datetime.combine(point_date, time(hour=20, minute=0)).replace(tzinfo=timezone.utc)
        rows.append(
            {
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "last": close,
                "bid": None,
                "ask": None,
                "volume": None,
            }
        )
    return rows


def _fetch_yfinance_series(
    *,
    symbol: str,
    interval: str,
    period_from: date,
    period_to: date,
) -> list[dict[str, object]]:
    ticker = str(symbol or "").strip()
    normalized_interval = str(interval or "1d").strip().lower()
    if not ticker:
        return []
    try:
        yfinance = importlib.import_module("yfinance")
    except Exception:
        return []
    try:
        frame = yfinance.download(
            ticker,
            start=period_from.isoformat(),
            end=(period_to + timedelta(days=1)).isoformat(),
            interval=normalized_interval,
            progress=False,
            auto_adjust=False,
            actions=False,
            threads=False,
        )
    except Exception:
        return []
    if frame is None or getattr(frame, "empty", True):
        return []

    close_series = None
    volume_series = None
    columns = getattr(frame, "columns", None)
    if columns is None:
        return []

    if hasattr(columns, "nlevels") and int(getattr(columns, "nlevels", 1)) > 1:
        try:
            close_frame = frame["Close"]
            volume_frame = frame["Volume"] if "Volume" in frame.columns.get_level_values(0) else None
        except Exception:
            return []

        if hasattr(close_frame, "columns"):
            if ticker in close_frame.columns:
                close_series = close_frame[ticker]
            elif len(close_frame.columns) > 0:
                close_series = close_frame.iloc[:, 0]
        else:
            close_series = close_frame

        if volume_frame is not None:
            if hasattr(volume_frame, "columns"):
                if ticker in volume_frame.columns:
                    volume_series = volume_frame[ticker]
                elif len(volume_frame.columns) > 0:
                    volume_series = volume_frame.iloc[:, 0]
            else:
                volume_series = volume_frame
    else:
        if "Close" not in frame.columns:
            return []
        close_series = frame["Close"]
        volume_series = frame["Volume"] if "Volume" in frame.columns else None

    if close_series is None:
        return []

    rows: list[dict[str, object]] = []
    for idx, value in close_series.items():
        try:
            close = float(value)
        except (TypeError, ValueError):
            continue

        ts_value = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
        if not isinstance(ts_value, datetime):
            try:
                ts_value = datetime.fromisoformat(str(ts_value))
            except ValueError:
                continue
        point_date = ts_value.date()
        if point_date < period_from or point_date > period_to:
            continue

        if normalized_interval in {"1d", "5d", "1wk", "1mo", "3mo"}:
            ts = datetime.combine(point_date, time(hour=20, minute=0)).replace(tzinfo=timezone.utc)
        else:
            if ts_value.tzinfo is None:
                ts = ts_value.replace(tzinfo=timezone.utc)
            else:
                ts = ts_value.astimezone(timezone.utc)

        volume_value = None
        if volume_series is not None:
            raw_volume = volume_series.get(idx)
            try:
                volume_value = float(raw_volume) if raw_volume is not None else None
            except (TypeError, ValueError):
                volume_value = None

        rows.append(
            {
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "last": close,
                "bid": None,
                "ask": None,
                "volume": volume_value,
            }
        )
    return rows


def _fetch_price_rows_for_profile(
    *,
    profile,
    period_from: date,
    period_to: date,
    timeout_sec: int,
) -> list[dict[str, object]]:
    source = str(profile.price_source or "").strip().lower()
    symbol = str(profile.price_symbol or "").strip()
    interval = str(getattr(profile, "price_interval", "1d") or "1d").strip().lower()
    if source == "fred":
        points = _fetch_fred_daily_series(
            series_id=symbol,
            period_from=period_from,
            period_to=period_to,
            timeout_sec=timeout_sec,
        )
    elif source == "stooq":
        points = _fetch_stooq_daily_series(
            symbol=symbol,
            period_from=period_from,
            period_to=period_to,
            timeout_sec=timeout_sec,
        )
    elif source == "yfinance":
        points = _fetch_yfinance_series(
            symbol=symbol,
            interval=interval,
            period_from=period_from,
            period_to=period_to,
        )
    else:
        points = []
    ticker = str(profile.ticker).strip().upper()
    return [
        {
            "secid": ticker,
            "timestamp": item.get("timestamp"),
            "last": item.get("last"),
            "bid": item.get("bid"),
            "ask": item.get("ask"),
            "volume": item.get("volume"),
        }
        for item in points
    ]


def _has_quote_after(
    session: Session,
    *,
    ticker: str,
    ts: datetime,
    max_ts: datetime | None = None,
) -> bool:
    if max_ts is not None:
        query = session.execute(
            select(db.QuoteModel.id)
            .where(db.QuoteModel.secid == ticker)
            .where(db.QuoteModel.timestamp >= ts)
            .where(db.QuoteModel.timestamp <= max_ts)
            .order_by(db.QuoteModel.timestamp.asc())
            .limit(1)
        )
    else:
        query = session.execute(
            select(db.QuoteModel.id)
            .where(db.QuoteModel.secid == ticker)
            .where(db.QuoteModel.timestamp >= ts)
            .order_by(db.QuoteModel.timestamp.asc())
            .limit(1)
        )
    row = (
        query
        .scalars()
        .first()
    )
    return row is not None


def build_news_backfill_qc_report(
    session: Session,
    *,
    tickers: Iterable[str],
    period_from: date,
    period_to: date,
    min_news_per_ticker: int,
    min_price_points_per_ticker: int,
) -> dict[str, object]:
    from_dt = datetime.combine(period_from, time.min)
    to_dt = datetime.combine(period_to, time.max)
    report_items: list[dict[str, object]] = []
    all_passed = True
    for raw_ticker in tickers:
        ticker = str(raw_ticker).strip().upper()
        if not ticker:
            continue
        joined_rows = session.execute(
            select(db.NewsItemModel.news_id, db.NewsItemModel.published_at)
            .join(db.NewsEntityLinkModel, db.NewsEntityLinkModel.news_id == db.NewsItemModel.news_id)
            .where(
                db.NewsItemModel.published_at >= from_dt,
                db.NewsItemModel.published_at <= to_dt,
                (db.NewsEntityLinkModel.ticker == ticker) | (db.NewsEntityLinkModel.entity_id == ticker),
            )
        ).all()
        news_by_id: dict[str, datetime] = {}
        per_year: dict[str, int] = {}
        backtest_ready_1d = 0
        for news_id, published_at in joined_rows:
            if news_id in news_by_id:
                continue
            ts = _as_utc_naive(published_at)
            news_by_id[news_id] = ts
            per_year[str(ts.year)] = per_year.get(str(ts.year), 0) + 1
            if _has_quote_after(
                session,
                ticker=ticker,
                ts=ts,
                max_ts=ts + timedelta(days=7),
            ) and _has_quote_after(
                session,
                ticker=ticker,
                ts=ts + timedelta(days=1),
                max_ts=ts + timedelta(days=8),
            ):
                backtest_ready_1d += 1

        quote_rows = (
            session.execute(
                select(db.QuoteModel.timestamp)
                .where(db.QuoteModel.secid == ticker)
                .where(db.QuoteModel.timestamp >= from_dt)
                .where(db.QuoteModel.timestamp <= to_dt)
                .order_by(db.QuoteModel.timestamp.asc())
            )
            .scalars()
            .all()
        )
        news_count = len(news_by_id)
        quote_count = len(quote_rows)
        passed = news_count >= min_news_per_ticker and quote_count >= min_price_points_per_ticker
        all_passed = all_passed and passed
        report_items.append(
            {
                "ticker": ticker,
                "news_count": news_count,
                "quote_count": quote_count,
                "backtest_ready_1d_samples": backtest_ready_1d,
                "news_per_year": per_year,
                "first_quote_at": quote_rows[0].isoformat() + "Z" if quote_rows else None,
                "last_quote_at": quote_rows[-1].isoformat() + "Z" if quote_rows else None,
                "checks": {
                    "min_news_per_ticker": {
                        "threshold": int(min_news_per_ticker),
                        "value": news_count,
                        "passed": news_count >= min_news_per_ticker,
                    },
                    "min_price_points_per_ticker": {
                        "threshold": int(min_price_points_per_ticker),
                        "value": quote_count,
                        "passed": quote_count >= min_price_points_per_ticker,
                    },
                },
                "passed": passed,
            }
        )

    return {
        "period": {
            "from": period_from.isoformat(),
            "to": period_to.isoformat(),
        },
        "passed": all_passed,
        "commodities": report_items,
    }


def run_news_backfill(
    session: Session,
    settings: AppSettings,
    *,
    period_from: date,
    period_to: date,
    commodities: Iterable[str] | None = None,
    include_prices: bool = True,
    run_inference: bool = False,
    chunk_days_override: int | None = None,
    max_windows_per_commodity: int | None = None,
) -> NewsBackfillReport:
    profiles = _selected_profiles(settings, commodities)
    chunk_days = (
        max(int(chunk_days_override), 1)
        if chunk_days_override is not None
        else max(int(settings.news_ingest.backfill_chunk_days), 1)
    )
    max_windows = (
        max(int(max_windows_per_commodity), 0)
        if max_windows_per_commodity is not None
        else max(int(settings.news_ingest.backfill_max_windows_per_commodity), 0)
    )

    upsert_news_tags(session, default_tag_rows())
    ingested_count = 0
    entity_link_count = 0
    tag_link_count = 0
    score_count = 0
    event_link_count = 0
    event_created_count = 0
    event_updated_count = 0
    event_refuted_count = 0
    event_resolved_count = 0
    quote_count = 0
    windows_processed = 0

    for profile in profiles:
        ticker = str(profile.ticker).strip().upper()
        windows = _iter_date_windows(
            start_date=period_from,
            end_date=period_to,
            chunk_days=chunk_days,
            max_windows=max_windows,
        )
        for window_start, window_end in windows:
            windows_processed += 1
            if settings.news_ingest.gdelt_enabled:
                rows = fetch_gdelt_news(
                    query=str(profile.gdelt_query),
                    start_dt=window_start,
                    end_dt=window_end,
                    max_items=settings.news_ingest.gdelt_max_records_per_call,
                    min_request_interval_sec=settings.news_ingest.gdelt_min_request_interval_sec,
                    timeout_sec=settings.news_ingest.gdelt_request_timeout_sec,
                )
            else:
                rows = []
            if not rows:
                continue
            before_news = _table_count(session, db.NewsItemModel)
            upsert_news_items(session, rows)
            after_news = _table_count(session, db.NewsItemModel)
            ingested_count += max(after_news - before_news, 0)

            entity_rows: list[dict[str, object]] = []
            tag_rows: list[dict[str, object]] = []
            score_rows: list[dict[str, object]] = []
            inference_items: list[dict[str, str]] = []
            for row in rows:
                news_id = str(row.get("news_id") or "").strip()
                if not news_id:
                    continue
                entity_rows.append(
                    {
                        "news_id": news_id,
                        "entity_type": "commodity",
                        "entity_id": ticker,
                        "ticker": ticker,
                        "link_confidence": 0.98,
                        "link_stage": "source_profile",
                    }
                )

                linking = link_news_item(
                    news_id=news_id,
                    title=str(row.get("title") or ""),
                    content=str(row.get("content") or ""),
                )
                for secondary_id in linking.secondary_commodity_ids:
                    entity_rows.append(
                        {
                            "news_id": news_id,
                            "entity_type": "commodity",
                            "entity_id": secondary_id,
                            "ticker": secondary_id,
                            "link_confidence": max(linking.confidence - 0.1, 0.0),
                            "link_stage": linking.resolution_stage,
                        }
                    )
                for tag_code in linking.tag_codes:
                    tag_rows.append(
                        {
                            "news_id": news_id,
                            "tag_code": tag_code,
                            "score": linking.confidence,
                        }
                    )

                if run_inference:
                    text = " ".join([str(row.get("title") or ""), str(row.get("content") or "")]).strip()
                    if text:
                        inference_items.append({"news_id": news_id, "text": text})
            if inference_items:
                score_rows.extend(
                    run_dual_model_inference_batch(
                        news_items=inference_items,
                        enabled_models=settings.news_models.enabled_models,
                        finbert_model_name=settings.news_models.finbert_model_name,
                        nli_model_name=settings.news_models.nli_model_name,
                        model_version=settings.news_models.model_version,
                        batch_size=settings.news_models.inference_batch_size,
                        text_max_chars=settings.news_models.inference_text_max_chars,
                        thread_cap=settings.news_models.inference_thread_cap,
                    )
                )
            if entity_rows:
                before_links = _table_count(session, db.NewsEntityLinkModel)
                upsert_news_entity_links(session, entity_rows)
                after_links = _table_count(session, db.NewsEntityLinkModel)
                entity_link_count += max(after_links - before_links, 0)
            if tag_rows:
                before_tags = _table_count(session, db.NewsItemTagModel)
                upsert_news_item_tags(session, tag_rows)
                after_tags = _table_count(session, db.NewsItemTagModel)
                tag_link_count += max(after_tags - before_tags, 0)
            if score_rows:
                before_scores = _table_count(session, db.NewsImpactScoreModel)
                upsert_news_impact_scores(session, score_rows)
                after_scores = _table_count(session, db.NewsImpactScoreModel)
                score_count += max(after_scores - before_scores, 0)
            if settings.news_events.enabled:
                event_report = cluster_news_events(
                    session,
                    news_rows=rows,
                    cluster_window_hours=settings.news_events.cluster_window_hours,
                    similarity_threshold=settings.news_events.similarity_threshold,
                    resolve_after_hours=settings.news_events.resolve_after_hours,
                    cluster_version=settings.news_events.cluster_version,
                )
                event_link_count += int(event_report.linked_news)
                event_created_count += int(event_report.created_events)
                event_updated_count += int(event_report.updated_events)
                event_refuted_count += int(event_report.refuted_events)
                event_resolved_count += int(event_report.resolved_events)

        if include_prices:
            price_rows = _fetch_price_rows_for_profile(
                profile=profile,
                period_from=period_from,
                period_to=period_to,
                timeout_sec=settings.news_ingest.gdelt_request_timeout_sec,
            )
            if price_rows:
                before_quotes = _table_count(session, db.QuoteModel)
                upsert_quotes(session, price_rows)
                after_quotes = _table_count(session, db.QuoteModel)
                quote_count += max(after_quotes - before_quotes, 0)

    qc_report = build_news_backfill_qc_report(
        session,
        tickers=[str(item.ticker).strip().upper() for item in profiles],
        period_from=period_from,
        period_to=period_to,
        min_news_per_ticker=max(int(settings.news_ingest.qc_min_news_per_ticker), 0),
        min_price_points_per_ticker=max(int(settings.news_ingest.qc_min_price_points_per_ticker), 0),
    )
    return NewsBackfillReport(
        period_from=period_from.isoformat(),
        period_to=period_to.isoformat(),
        commodities=[str(item.ticker).strip().upper() for item in profiles],
        ingested_count=ingested_count,
        entity_link_count=entity_link_count,
        tag_link_count=tag_link_count,
        score_count=score_count,
        event_link_count=event_link_count,
        event_created_count=event_created_count,
        event_updated_count=event_updated_count,
        event_refuted_count=event_refuted_count,
        event_resolved_count=event_resolved_count,
        quote_count=quote_count,
        windows_processed=windows_processed,
        qc_report=qc_report,
    )


def run_news_qc(
    session: Session,
    settings: AppSettings,
    *,
    period_from: date,
    period_to: date,
    commodities: Iterable[str] | None = None,
) -> dict[str, object]:
    profiles = _selected_profiles(settings, commodities)
    return build_news_backfill_qc_report(
        session,
        tickers=[str(item.ticker).strip().upper() for item in profiles],
        period_from=period_from,
        period_to=period_to,
        min_news_per_ticker=max(int(settings.news_ingest.qc_min_news_per_ticker), 0),
        min_price_points_per_ticker=max(int(settings.news_ingest.qc_min_price_points_per_ticker), 0),
    )
