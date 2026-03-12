from __future__ import annotations

import importlib
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from moex_carry.config import AppSettings
from moex_carry.news.anchors import (
    link_news_to_scheduled_anchors,
    seed_canonical_scheduled_events,
    seed_episodic_anchor_events,
)
from moex_carry.news.events import cluster_news_events
from moex_carry.news.ingestion import fetch_gdelt_news, fetch_newsapi_news
from moex_carry.news.inference import run_dual_model_inference_batch
from moex_carry.news.linking import default_tag_rows, link_news_item, text_supports_ticker
from moex_carry.news.backfill_helpers import (
    _NewsApiDailyBudget,
    _as_utc_naive,
    _fetch_fred_daily_series,
    _fetch_stooq_daily_series,
    _iter_date_windows,
    _merge_news_rows,
    _normalize_window_order,
    _parse_news_published_at,
    _quote_price_for_backfill,
    _resample_points_to_bar_close,
    _selected_profiles,
    _table_count,
    build_news_backfill_qc_report,
)
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
    window_order: str
    newsapi_requests_used: int
    newsapi_requests_remaining: int | None
    qc_report: dict[str, object]

def _shock_score_by_window(
    session: Session,
    *,
    ticker: str,
    windows: list[tuple[datetime, datetime]],
    shock_bar_minutes: int = 60,
) -> dict[tuple[datetime, datetime], float]:
    if not windows:
        return {}
    global_start = _as_utc_naive(min(window_start for window_start, _ in windows) - timedelta(days=1))
    global_end = _as_utc_naive(max(window_end for _, window_end in windows) + timedelta(days=1))
    quote_rows = (
        session.execute(
            select(db.QuoteModel)
            .where(db.QuoteModel.secid == ticker)
            .where(db.QuoteModel.timestamp >= global_start)
            .where(db.QuoteModel.timestamp <= global_end)
            .order_by(db.QuoteModel.timestamp.asc())
        )
        .scalars()
        .all()
    )
    points: list[tuple[datetime, float]] = []
    for row in quote_rows:
        price = _quote_price_for_backfill(row)
        if price is None:
            continue
        points.append((_as_utc_naive(row.timestamp), price))
    points = _resample_points_to_bar_close(points, bar_minutes=max(int(shock_bar_minutes), 1))
    if len(points) < 2:
        return {}

    abs_returns: list[tuple[datetime, float]] = []
    for idx in range(1, len(points)):
        ts0, p0 = points[idx - 1]
        ts1, p1 = points[idx]
        if p0 <= 0.0 or p1 <= 0.0 or ts1 <= ts0:
            continue
        abs_returns.append((ts1, abs(math.log(p1 / p0))))
    if not abs_returns:
        return {}

    score_map: dict[tuple[datetime, datetime], float] = {}
    for window_start, window_end in windows:
        window_start_naive = _as_utc_naive(window_start)
        window_end_naive = _as_utc_naive(window_end)
        score = 0.0
        found = False
        for ts, abs_ret in abs_returns:
            if ts < window_start_naive:
                continue
            if ts > window_end_naive:
                break
            found = True
            if abs_ret > score:
                score = abs_ret
        if found:
            score_map[(window_start, window_end)] = score
    return score_map

def _order_windows(
    session: Session,
    *,
    ticker: str,
    windows: list[tuple[datetime, datetime]],
    order: str,
    shock_bar_minutes: int = 60,
) -> list[tuple[datetime, datetime]]:
    if not windows:
        return []
    mode = _normalize_window_order(order)
    if mode == "recent_first":
        return sorted(windows, key=lambda item: item[1], reverse=True)
    if mode != "shock_first":
        return windows

    score_map = _shock_score_by_window(
        session,
        ticker=ticker,
        windows=windows,
        shock_bar_minutes=max(int(shock_bar_minutes), 1),
    )
    if not score_map:
        return sorted(windows, key=lambda item: item[1], reverse=True)
    return sorted(
        windows,
        key=lambda item: (float(score_map.get(item, -1.0)), item[1]),
        reverse=True,
    )



def _fetch_gdelt_window_paginated(
    *,
    query: str,
    start_dt: datetime,
    end_dt: datetime,
    max_items: int,
    min_request_interval_sec: float,
    timeout_sec: int,
    max_pages: int,
) -> list[dict[str, object]]:
    page_limit = max(int(max_pages), 1)
    cursor_end = end_dt
    seen_ids: set[str] = set()
    collected: list[dict[str, object]] = []
    for _ in range(page_limit):
        if cursor_end <= start_dt:
            break
        rows = fetch_gdelt_news(
            query=query,
            start_dt=start_dt,
            end_dt=cursor_end,
            max_items=max_items,
            min_request_interval_sec=min_request_interval_sec,
            timeout_sec=timeout_sec,
        )
        if not rows:
            break
        oldest_published: datetime | None = None
        new_rows = 0
        for row in rows:
            news_id = str(row.get("news_id") or "").strip()
            if news_id and news_id in seen_ids:
                continue
            if news_id:
                seen_ids.add(news_id)
            collected.append(row)
            new_rows += 1
            published_at = _parse_news_published_at(row.get("published_at"))
            if published_at is None:
                continue
            if oldest_published is None or published_at < oldest_published:
                oldest_published = published_at
        if new_rows <= 0:
            break
        if oldest_published is None:
            break
        next_end = oldest_published.replace(tzinfo=timezone.utc) - timedelta(seconds=1)
        if next_end >= cursor_end:
            break
        cursor_end = next_end
    return collected

def _resolve_newsapi_key(settings: AppSettings) -> str:
    env_name = str(settings.news_ingest.newsapi_api_key_env or "").strip()
    if env_name:
        env_value = str(os.getenv(env_name) or "").strip()
        if env_value:
            return env_value
    config_value = str(settings.news_ingest.newsapi_api_key or "").strip()
    return config_value

def _fetch_newsapi_window_paginated(
    *,
    query: str,
    start_dt: datetime,
    end_dt: datetime,
    api_key: str,
    base_url: str,
    max_items: int,
    timeout_sec: int,
    max_pages: int,
    language: str | None,
    sort_by: str,
    domains: Iterable[str] | None,
    daily_budget: _NewsApiDailyBudget | None,
) -> list[dict[str, object]]:
    query_value = str(query or "").strip()
    if not query_value or not str(api_key or "").strip():
        return []
    page_limit = max(int(max_pages), 1)
    effective_max = max(int(max_items), 1)
    seen_ids: set[str] = set()
    collected: list[dict[str, object]] = []
    for page in range(1, page_limit + 1):
        if len(collected) >= effective_max:
            break
        page_size = min(100, effective_max - len(collected))
        if page_size <= 0:
            break
        if daily_budget is not None and not daily_budget.reserve(1):
            break
        rows = fetch_newsapi_news(
            query=query_value,
            start_dt=start_dt,
            end_dt=end_dt,
            api_key=api_key,
            base_url=base_url,
            page=page,
            page_size=page_size,
            timeout_sec=timeout_sec,
            language=language,
            sort_by=sort_by,
            domains=domains,
        )
        if not rows:
            break
        new_rows = 0
        for row in rows:
            news_id = str(row.get("news_id") or "").strip()
            if news_id and news_id in seen_ids:
                continue
            if news_id:
                seen_ids.add(news_id)
            collected.append(row)
            new_rows += 1
        if new_rows <= 0 or len(rows) < page_size:
            break
    return collected

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
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing optional dependency 'yfinance'. Install extra: .[market]") from exc
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
    window_order_override: str | None = None,
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
    window_order = _normalize_window_order(
        window_order_override if window_order_override is not None else settings.news_ingest.backfill_window_order
    )
    shock_bar_minutes = max(int(settings.news_ingest.backfill_shock_bar_minutes), 1)
    newsapi_key = _resolve_newsapi_key(settings) if settings.news_ingest.newsapi_enabled else ""
    newsapi_budget: _NewsApiDailyBudget | None = None
    if settings.news_ingest.newsapi_enabled and newsapi_key:
        newsapi_budget = _NewsApiDailyBudget.load(
            limit=settings.news_ingest.newsapi_daily_limit,
            state_path=settings.news_ingest.newsapi_daily_state_path,
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
    episodic_seed_done = False
    newsapi_used_before = newsapi_budget.used if newsapi_budget is not None else 0

    for profile in profiles:
        ticker = str(profile.ticker).strip().upper()
        newsapi_query = str(profile.newsapi_query or profile.gdelt_query or "").strip()
        windows = _iter_date_windows(
            start_date=period_from,
            end_date=period_to,
            chunk_days=chunk_days,
            max_windows=max_windows,
        )
        windows = _order_windows(
            session,
            ticker=ticker,
            windows=windows,
            order=window_order,
            shock_bar_minutes=shock_bar_minutes,
        )
        for window_start, window_end in windows:
            windows_processed += 1
            rows: list[dict[str, object]] = []
            if settings.news_ingest.gdelt_enabled:
                rows.extend(
                    _fetch_gdelt_window_paginated(
                        query=str(profile.gdelt_query),
                        start_dt=window_start,
                        end_dt=window_end,
                        max_items=settings.news_ingest.gdelt_max_records_per_call,
                        min_request_interval_sec=settings.news_ingest.gdelt_min_request_interval_sec,
                        timeout_sec=settings.news_ingest.gdelt_request_timeout_sec,
                        max_pages=settings.news_ingest.gdelt_backfill_max_pages_per_window,
                    )
                )
            if settings.news_ingest.newsapi_enabled and newsapi_key and newsapi_query:
                rows.extend(
                    _fetch_newsapi_window_paginated(
                        query=newsapi_query,
                        start_dt=window_start,
                        end_dt=window_end,
                        api_key=newsapi_key,
                        base_url=settings.news_ingest.newsapi_base_url,
                        max_items=settings.news_ingest.newsapi_max_records_per_call,
                        timeout_sec=settings.news_ingest.newsapi_request_timeout_sec,
                        max_pages=settings.news_ingest.newsapi_backfill_max_pages_per_window,
                        language=settings.news_ingest.newsapi_language,
                        sort_by=settings.news_ingest.newsapi_sort_by,
                        domains=settings.news_ingest.newsapi_domains,
                        daily_budget=newsapi_budget,
                    )
                )
            rows = _merge_news_rows(rows)
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
                title = str(row.get("title") or "")
                content = str(row.get("content") or "")

                linking = link_news_item(
                    news_id=news_id,
                    title=title,
                    content=content,
                )
                supports_profile = text_supports_ticker(
                    ticker=ticker,
                    title=title,
                    content=content,
                )
                if supports_profile:
                    primary_id = ticker
                    primary_confidence = max(linking.confidence, 0.98)
                    primary_stage = "source_profile"
                else:
                    primary_id = linking.primary_commodity_id or "UNKNOWN"
                    primary_confidence = linking.confidence
                    primary_stage = linking.resolution_stage
                if primary_id != "UNKNOWN":
                    entity_rows.append(
                        {
                            "news_id": news_id,
                            "entity_type": "commodity",
                            "entity_id": primary_id,
                            "ticker": primary_id,
                            "link_confidence": primary_confidence,
                            "link_stage": primary_stage,
                        }
                    )
                for secondary_id in linking.secondary_commodity_ids:
                    if secondary_id == primary_id:
                        continue
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
                    text = " ".join([title, content]).strip()
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
                if settings.news_events.anchor_seed_enabled:
                    seed_canonical_scheduled_events(
                        session,
                        period_from=window_start.replace(tzinfo=None),
                        period_to=window_end.replace(tzinfo=None),
                        cluster_version=settings.news_events.anchor_cluster_version,
                        padding_days=settings.news_events.anchor_seed_padding_days,
                    )
                if settings.news_events.anchor_link_enabled:
                    link_news_to_scheduled_anchors(
                        session,
                        news_rows=rows,
                        cluster_version=settings.news_events.anchor_cluster_version,
                        window_minutes=settings.news_events.anchor_match_window_minutes,
                    )
                if settings.news_events.anchor_episode_seed_enabled and not episodic_seed_done:
                    seed_episodic_anchor_events(
                        session,
                        cluster_version=settings.news_events.anchor_episode_cluster_version,
                        sources=settings.news_events.anchor_episode_sources,
                        timeout_sec=settings.news_events.anchor_request_timeout_sec,
                        user_agent=settings.news_events.anchor_user_agent,
                        nws_url=settings.news_events.anchor_nws_url,
                        nhc_url=settings.news_events.anchor_nhc_url,
                        ukmto_url=settings.news_events.anchor_ukmto_url,
                        bsee_url=settings.news_events.anchor_bsee_url,
                        panama_url=settings.news_events.anchor_panama_url,
                        suez_url=settings.news_events.anchor_suez_url,
                        fred_release_url=settings.news_events.anchor_fred_release_url,
                        fred_release_ids=settings.news_events.anchor_fred_release_ids,
                        fred_api_key_env=settings.news_events.anchor_fred_api_key_env,
                    )
                    episodic_seed_done = True
                if settings.news_events.anchor_link_enabled:
                    link_news_to_scheduled_anchors(
                        session,
                        news_rows=rows,
                        cluster_version=settings.news_events.anchor_episode_cluster_version,
                        window_minutes=settings.news_events.anchor_episode_match_window_minutes,
                        link_role="episodic_anchor",
                        link_type="episodic_anchor",
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
    newsapi_requests_used = (
        max(int(newsapi_budget.used) - int(newsapi_used_before), 0)
        if newsapi_budget is not None
        else 0
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
        window_order=window_order,
        newsapi_requests_used=newsapi_requests_used,
        newsapi_requests_remaining=(
            int(newsapi_budget.remaining)
            if newsapi_budget is not None
            else None
        ),
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
