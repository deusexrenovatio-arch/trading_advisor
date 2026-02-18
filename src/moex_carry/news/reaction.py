from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median, stdev
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from moex_carry.storage import models as db
from moex_carry.storage.repositories import (
    load_news_entity_links,
    load_news_event_items,
    load_news_events,
    load_news_labels,
    upsert_event_market_reactions,
)


@dataclass(frozen=True)
class EventReactionBuildReport:
    events_seen: int
    events_processed: int
    windows_processed: int
    rows_upserted: int
    overlap_rows: int
    skipped_rows: int


DEFAULT_WINDOW_IDS: tuple[str, ...] = (
    "0_30m",
    "30m_2h",
    "2h_1d",
    "1d_5d",
)


def _parse_iso_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _to_iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def _normalize_event_time_mode(value: str | None) -> str:
    raw = str(value or "published").strip().lower()
    if raw in {"published", "ingested"}:
        return raw
    return "published"


def _duration_from_token(token: str) -> timedelta | None:
    raw = str(token or "").strip().lower()
    if raw in {"0", "0m", "0h", "0d"}:
        return timedelta(0)
    try:
        if raw.endswith("m"):
            return timedelta(minutes=max(int(raw[:-1]), 0))
        if raw.endswith("h"):
            return timedelta(hours=max(int(raw[:-1]), 0))
        if raw.endswith("d"):
            return timedelta(days=max(int(raw[:-1]), 0))
    except ValueError:
        return None
    return None


def parse_window_id(window_id: str) -> tuple[timedelta, timedelta] | None:
    raw = str(window_id or "").strip().lower()
    if "_" not in raw:
        return None
    start_token, end_token = raw.split("_", 1)
    start_delta = _duration_from_token(start_token)
    end_delta = _duration_from_token(end_token)
    if start_delta is None or end_delta is None:
        return None
    if end_delta <= start_delta:
        return None
    return start_delta, end_delta


def _parse_sampling_minutes(value: str) -> int:
    raw = str(value or "").strip().lower()
    if not raw:
        return 5
    try:
        if raw.endswith("m"):
            return max(int(raw[:-1]), 1)
        if raw.endswith("h"):
            return max(int(raw[:-1]) * 60, 1)
    except ValueError:
        return 5
    return 5


def _bucket_floor(ts: datetime, minutes: int) -> datetime:
    epoch = datetime(1970, 1, 1)
    step_seconds = max(int(minutes), 1) * 60
    offset = int((ts - epoch).total_seconds())
    bucket = (offset // step_seconds) * step_seconds
    return epoch + timedelta(seconds=bucket)


def _pick_price(row: db.QuoteModel) -> float | None:
    for value in (row.last, row.bid, row.ask):
        if value is not None:
            return float(value)
    return None


def _quote_point_at_or_after(session: Session, *, ticker: str, ts: datetime) -> tuple[datetime, float] | None:
    row = (
        session.execute(
            select(db.QuoteModel)
            .where(db.QuoteModel.secid == ticker)
            .where(db.QuoteModel.timestamp >= ts)
            .order_by(db.QuoteModel.timestamp.asc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if row is None:
        return None
    price = _pick_price(row)
    if price is None or price <= 0.0:
        return None
    return row.timestamp, price


def _quote_rows_between(
    session: Session,
    *,
    ticker: str,
    start_ts: datetime,
    end_ts: datetime,
) -> list[tuple[datetime, float, float | None]]:
    rows = (
        session.execute(
            select(db.QuoteModel)
            .where(db.QuoteModel.secid == ticker)
            .where(db.QuoteModel.timestamp >= start_ts)
            .where(db.QuoteModel.timestamp <= end_ts)
            .order_by(db.QuoteModel.timestamp.asc())
        )
        .scalars()
        .all()
    )
    normalized: list[tuple[datetime, float, float | None]] = []
    for row in rows:
        price = _pick_price(row)
        if price is None or price <= 0.0:
            continue
        volume = float(row.volume) if row.volume is not None else None
        normalized.append((row.timestamp, price, volume))
    return normalized


def _resample_rows(
    rows: list[tuple[datetime, float, float | None]],
    *,
    sampling_minutes: int,
) -> list[tuple[datetime, float, float | None]]:
    if sampling_minutes <= 1 or len(rows) <= 1:
        return rows
    buckets: dict[datetime, tuple[datetime, float, float | None]] = {}
    for row in rows:
        bucket = _bucket_floor(row[0], sampling_minutes)
        buckets[bucket] = row
    return [buckets[key] for key in sorted(buckets.keys())]


def _returns_with_dt(rows: list[tuple[datetime, float, float | None]]) -> list[tuple[float, float]]:
    values: list[tuple[float, float]] = []
    for prev, curr in zip(rows, rows[1:]):
        dt_seconds = float((curr[0] - prev[0]).total_seconds())
        if dt_seconds <= 0:
            continue
        if prev[1] <= 0.0 or curr[1] <= 0.0:
            continue
        ret = math.log(curr[1] / prev[1])
        values.append((ret, dt_seconds))
    return values


def _realized_volatility(returns: list[tuple[float, float]]) -> float:
    if not returns:
        return 0.0
    return math.sqrt(sum((ret * ret) for ret, _dt in returns))


def _expected_return(
    pre_returns: list[tuple[float, float]],
    *,
    window_seconds: float,
) -> tuple[float, bool]:
    if len(pre_returns) < 2:
        return 0.0, True
    total_seconds = sum(dt for _ret, dt in pre_returns)
    if total_seconds <= 0.0:
        return 0.0, True
    avg_per_second = sum(ret for ret, _dt in pre_returns) / total_seconds
    return avg_per_second * max(window_seconds, 0.0), False


def _window_lag_limit(window: timedelta) -> timedelta:
    minutes = int(max(window.total_seconds() / 60.0, 1.0))
    if minutes <= 30:
        return timedelta(minutes=30)
    if minutes <= 120:
        return timedelta(hours=2)
    if minutes <= 24 * 60:
        return timedelta(hours=18)
    return timedelta(days=3)


def _overlap_lookup(
    *,
    event_times_by_ticker: dict[str, list[tuple[str, datetime]]],
    window_map: dict[str, tuple[timedelta, timedelta]],
) -> set[tuple[str, str, str]]:
    overlap: set[tuple[str, str, str]] = set()
    if not window_map:
        return overlap
    max_end = max((spec[1] for spec in window_map.values()), default=timedelta(0))
    for ticker, rows in event_times_by_ticker.items():
        ordered = sorted(rows, key=lambda item: item[1])
        for idx, (event_id, event_ts) in enumerate(ordered):
            horizon_end = event_ts + max_end
            for other_id, other_ts in ordered[idx + 1 :]:
                if other_ts > horizon_end:
                    break
                for window_id, (start_delta, end_delta) in window_map.items():
                    if event_ts + start_delta <= other_ts <= event_ts + end_delta:
                        overlap.add((event_id, ticker, window_id))
    return overlap


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _two_sided_p_value(values: list[float]) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    mean_value = sum(values) / float(len(values))
    sample_std = stdev(values)
    if sample_std <= 0.0:
        if abs(mean_value) <= 1e-12:
            return 0.0, 1.0
        return float("inf"), 0.0
    t_stat = mean_value / (sample_std / math.sqrt(float(len(values))))
    p_value = 2.0 * (1.0 - _normal_cdf(abs(t_stat)))
    return t_stat, max(min(p_value, 1.0), 0.0)


def _bh_fdr(p_values: dict[str, float]) -> dict[str, float]:
    if not p_values:
        return {}
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    count = len(ordered)
    raw_adjusted: list[tuple[str, float]] = []
    for rank, (key, p_value) in enumerate(ordered, start=1):
        raw_adjusted.append((key, min(1.0, p_value * count / float(rank))))
    adjusted: dict[str, float] = {}
    running_min = 1.0
    for key, value in reversed(raw_adjusted):
        running_min = min(running_min, value)
        adjusted[key] = running_min
    return adjusted


def rebuild_event_market_reactions(
    session: Session,
    *,
    event_ids: Iterable[str] | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    window_ids: Iterable[str] | None = None,
    sampling_freqs: Iterable[str] = ("1m", "5m", "15m"),
    estimation_lookback_days: int = 7,
    max_events: int = 0,
    event_time_mode: str = "published",
) -> EventReactionBuildReport:
    normalized_event_time_mode = _normalize_event_time_mode(event_time_mode)
    normalized_window_ids = [str(item).strip() for item in (window_ids or DEFAULT_WINDOW_IDS) if str(item).strip()]
    window_map: dict[str, tuple[timedelta, timedelta]] = {}
    for window_id in normalized_window_ids:
        parsed = parse_window_id(window_id)
        if parsed is None:
            continue
        window_map[window_id] = parsed
    normalized_freqs = [str(item).strip().lower() for item in sampling_freqs if str(item).strip()]
    normalized_freqs = normalized_freqs or ["5m"]
    if not window_map:
        return EventReactionBuildReport(
            events_seen=0,
            events_processed=0,
            windows_processed=0,
            rows_upserted=0,
            overlap_rows=0,
            skipped_rows=0,
        )

    events = load_news_events(
        session,
        event_ids=event_ids,
        published_from=_to_iso_z(published_from),
        published_to=_to_iso_z(published_to),
        limit=max_events if max_events > 0 else 0,
    )
    if not events:
        return EventReactionBuildReport(
            events_seen=0,
            events_processed=0,
            windows_processed=0,
            rows_upserted=0,
            overlap_rows=0,
            skipped_rows=0,
        )

    event_ids_list = [str(row.get("event_id") or "").strip() for row in events if row.get("event_id")]
    event_items = load_news_event_items(session, event_ids=event_ids_list, limit=max(len(event_ids_list) * 50, 1000))
    event_to_news: dict[str, list[str]] = {}
    for row in event_items:
        event_id = str(row.get("event_id") or "").strip()
        news_id = str(row.get("news_id") or "").strip()
        if not event_id or not news_id:
            continue
        event_to_news.setdefault(event_id, []).append(news_id)

    all_news_ids = sorted(
        {news_id for values in event_to_news.values() for news_id in values if isinstance(news_id, str) and news_id}
    )
    entity_links = load_news_entity_links(session, news_ids=all_news_ids, limit=max(len(all_news_ids) * 10, 1000))
    labels = load_news_labels(session, target_level="event", target_ids=event_ids_list, limit=max(len(event_ids_list) * 5, 500))

    tickers_by_news: dict[str, set[str]] = {}
    for row in entity_links:
        news_id = str(row.get("news_id") or "").strip()
        ticker = str(row.get("ticker") or row.get("entity_id") or "").strip().upper()
        if not news_id or not ticker:
            continue
        tickers_by_news.setdefault(news_id, set()).add(ticker)

    tickers_by_event: dict[str, set[str]] = {}
    for event_id, news_ids in event_to_news.items():
        bucket: set[str] = set()
        for news_id in news_ids:
            bucket |= tickers_by_news.get(news_id, set())
        tickers_by_event[event_id] = bucket
    for row in labels:
        event_id = str(row.get("target_id") or "").strip()
        if not event_id:
            continue
        commodity_json = row.get("commodity_json")
        if not isinstance(commodity_json, list):
            continue
        for item in commodity_json:
            ticker = str(item or "").strip().upper()
            if not ticker:
                continue
            tickers_by_event.setdefault(event_id, set()).add(ticker)

    event_ts_by_id: dict[str, datetime] = {}
    event_ts_source_by_id: dict[str, str] = {}
    for row in events:
        event_id = str(row.get("event_id") or "").strip()
        published_ts = _parse_iso_datetime(row.get("event_first_published_at_utc"))
        ingested_ts = _parse_iso_datetime(row.get("event_first_ingested_at_utc"))
        event_ts = published_ts
        event_ts_source = "published"
        if normalized_event_time_mode == "ingested":
            if ingested_ts is not None:
                event_ts = ingested_ts
                event_ts_source = "ingested"
            elif published_ts is not None:
                event_ts = published_ts
                event_ts_source = "published_fallback"
        if event_id and event_ts is not None:
            event_ts_by_id[event_id] = event_ts
            event_ts_source_by_id[event_id] = event_ts_source

    event_times_by_ticker: dict[str, list[tuple[str, datetime]]] = {}
    for event_id, event_ts in event_ts_by_id.items():
        for ticker in sorted(tickers_by_event.get(event_id, set())):
            event_times_by_ticker.setdefault(ticker, []).append((event_id, event_ts))

    overlap_map = _overlap_lookup(event_times_by_ticker=event_times_by_ticker, window_map=window_map)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    lookback = timedelta(days=max(int(estimation_lookback_days), 1))
    upsert_rows: list[dict[str, object]] = []
    events_processed = 0
    windows_processed = 0
    overlap_rows = 0
    skipped_rows = 0

    for event_id, event_ts in event_ts_by_id.items():
        event_tickers = sorted(tickers_by_event.get(event_id, set()))
        if not event_tickers:
            skipped_rows += len(window_map) * len(normalized_freqs)
            continue
        produced_for_event = False
        for ticker in event_tickers:
            for window_id, (start_delta, end_delta) in window_map.items():
                target_start = event_ts + start_delta
                target_end = event_ts + end_delta
                start_point = _quote_point_at_or_after(session, ticker=ticker, ts=target_start)
                end_point = _quote_point_at_or_after(session, ticker=ticker, ts=target_end)
                if start_point is None or end_point is None:
                    skipped_rows += len(normalized_freqs)
                    continue
                start_ts, start_price = start_point
                end_ts, end_price = end_point
                if end_ts <= start_ts or start_price <= 0.0 or end_price <= 0.0:
                    skipped_rows += len(normalized_freqs)
                    continue
                window_lag = _window_lag_limit(end_delta - start_delta)
                start_lag_sec = max((start_ts - target_start).total_seconds(), 0.0)
                end_lag_sec = max((end_ts - target_end).total_seconds(), 0.0)
                session_gap = (
                    timedelta(seconds=start_lag_sec) > window_lag
                    or timedelta(seconds=end_lag_sec) > window_lag
                )
                raw_window_rows = _quote_rows_between(session, ticker=ticker, start_ts=start_ts, end_ts=end_ts)
                pre_start = max(event_ts - lookback, datetime(1970, 1, 1))
                raw_pre_rows = _quote_rows_between(session, ticker=ticker, start_ts=pre_start, end_ts=start_ts)
                overlap_flag = (event_id, ticker, window_id) in overlap_map
                if overlap_flag:
                    overlap_rows += len(normalized_freqs)
                for freq in normalized_freqs:
                    sampling_minutes = _parse_sampling_minutes(freq)
                    window_rows = _resample_rows(raw_window_rows, sampling_minutes=sampling_minutes)
                    pre_rows = _resample_rows(raw_pre_rows, sampling_minutes=sampling_minutes)
                    window_returns = _returns_with_dt(window_rows)
                    pre_returns = _returns_with_dt(pre_rows)
                    window_seconds = float((end_ts - start_ts).total_seconds())
                    expected_return, insufficient_history = _expected_return(
                        pre_returns,
                        window_seconds=window_seconds,
                    )
                    return_raw = math.log(end_price / start_price)
                    return_abnormal = return_raw - expected_return
                    rv = _realized_volatility(window_returns)
                    pre_rv = _realized_volatility(pre_returns)
                    vol_change = (rv / pre_rv - 1.0) if pre_rv > 0.0 else None

                    window_volume = sum(float(row[2]) for row in raw_window_rows if row[2] is not None)
                    pre_volume = sum(float(row[2]) for row in raw_pre_rows if row[2] is not None)
                    volume_change = (window_volume / pre_volume - 1.0) if pre_volume > 0.0 else None
                    quality_flags = {
                        "illiquid": len(window_rows) < 3,
                        "overlap_event": overlap_flag,
                        "session_gap": bool(session_gap),
                        "insufficient_history": bool(insufficient_history),
                        "event_time_mode": normalized_event_time_mode,
                        "event_ts_source": event_ts_source_by_id.get(event_id, normalized_event_time_mode),
                        "start_lag_sec": float(start_lag_sec),
                        "end_lag_sec": float(end_lag_sec),
                        "window_points": len(window_rows),
                        "pre_points": len(pre_rows),
                    }
                    upsert_rows.append(
                        {
                            "event_id": event_id,
                            "instrument_id": ticker,
                            "window_id": window_id,
                            "sampling_freq": freq,
                            "return_raw": float(return_raw),
                            "return_abnormal": float(return_abnormal),
                            "car": float(return_abnormal),
                            "rv": float(rv),
                            "vol_change": vol_change,
                            "volume_change": volume_change,
                            "quality_flags_json": quality_flags,
                            "computed_at": _to_iso_z(now),
                        }
                    )
                    produced_for_event = True
                    windows_processed += 1
        if produced_for_event:
            events_processed += 1

    rows_upserted = upsert_event_market_reactions(session, upsert_rows) if upsert_rows else 0
    return EventReactionBuildReport(
        events_seen=len(events),
        events_processed=events_processed,
        windows_processed=windows_processed,
        rows_upserted=rows_upserted,
        overlap_rows=overlap_rows,
        skipped_rows=skipped_rows,
    )


def build_event_study_leakage_audit(
    *,
    reactions: list[dict[str, object]],
    events: list[dict[str, object]],
    event_time_mode: str = "published",
) -> dict[str, object]:
    normalized_mode = _normalize_event_time_mode(event_time_mode)
    events_by_id: dict[str, dict[str, object]] = {
        str(row.get("event_id") or "").strip(): row for row in events if str(row.get("event_id") or "").strip()
    }
    checked_rows = 0
    violation_count = 0
    violation_event_ids: list[str] = []
    for row in reactions:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            continue
        event_row = events_by_id.get(event_id)
        if not isinstance(event_row, dict):
            continue
        published_ts = _parse_iso_datetime(event_row.get("event_first_published_at_utc"))
        ingested_ts = _parse_iso_datetime(event_row.get("event_first_ingested_at_utc"))
        if published_ts is None or ingested_ts is None:
            continue
        window_id = str(row.get("window_id") or "").strip().lower()
        parsed_window = parse_window_id(window_id)
        if parsed_window is None:
            continue
        start_delta, _end_delta = parsed_window
        if normalized_mode == "ingested":
            event_ts = ingested_ts
        else:
            event_ts = published_ts
        window_start = event_ts + start_delta
        checked_rows += 1
        if window_start < ingested_ts:
            violation_count += 1
            if event_id not in violation_event_ids and len(violation_event_ids) < 50:
                violation_event_ids.append(event_id)
    return {
        "event_time_mode": normalized_mode,
        "checked_rows": checked_rows,
        "violation_count": violation_count,
        "violation_rate": (float(violation_count) / float(checked_rows)) if checked_rows else 0.0,
        "violation_event_ids": violation_event_ids,
    }


def summarize_event_study(
    *,
    reactions: list[dict[str, object]],
    labels: list[dict[str, object]],
    events: list[dict[str, object]] | None = None,
    exclude_overlap: bool = False,
) -> dict[str, object]:
    events = events or []
    direction_by_event: dict[str, str] = {}
    event_family_by_event: dict[str, str] = {}
    event_kind_by_event: dict[str, str] = {}
    for event in events:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            continue
        mechanism = str(event.get("canonical_mechanism") or "").strip().lower()
        if "event_family=" in mechanism:
            for chunk in mechanism.split("|"):
                if "=" not in chunk:
                    continue
                key, value = chunk.split("=", 1)
                if key.strip().lower() == "event_family":
                    family = value.strip().upper()
                    if family:
                        event_family_by_event[event_id] = family
                    break
        if "scheduled_anchor" in mechanism:
            event_kind_by_event[event_id] = "scheduled"
        elif "episodic_anchor" in mechanism:
            event_kind_by_event[event_id] = "episodic"
        else:
            event_kind_by_event[event_id] = "internal"

    for row in labels:
        event_id = str(row.get("target_id") or "").strip()
        direction = str(row.get("direction") or "").strip().lower()
        if not event_id or direction not in {"positive", "negative", "neutral", "uncertain"}:
            continue
        direction_by_event.setdefault(event_id, direction)
        news_type_json = row.get("news_type_json")
        if isinstance(news_type_json, list):
            for item in news_type_json:
                code = str(item or "").strip().upper()
                if not code:
                    continue
                if "_" in code or code in {"NG_STORAGE_EIA", "OIL_INVENTORIES_EIA"}:
                    event_family_by_event.setdefault(event_id, code)
                    break
        evidence = row.get("evidence_json")
        if isinstance(evidence, dict):
            code = str(evidence.get("event_family") or "").strip().upper()
            if code:
                event_family_by_event.setdefault(event_id, code)

    filtered: list[dict[str, object]] = []
    excluded_overlap_count = 0
    for row in reactions:
        quality_flags = row.get("quality_flags_json")
        overlap = bool(quality_flags.get("overlap_event")) if isinstance(quality_flags, dict) else False
        if exclude_overlap and overlap:
            excluded_overlap_count += 1
            continue
        filtered.append(row)

    values_by_direction: dict[str, list[float]] = {
        "positive": [],
        "negative": [],
        "neutral": [],
        "uncertain": [],
        "unlabeled": [],
    }
    for row in filtered:
        event_id = str(row.get("event_id") or "").strip()
        direction = direction_by_event.get(event_id, "unlabeled")
        try:
            car_value = float(row.get("car"))
        except (TypeError, ValueError):
            continue
        values_by_direction.setdefault(direction, []).append(car_value)

    p_values: dict[str, float] = {}
    summary: dict[str, dict[str, object]] = {}
    for direction, values in values_by_direction.items():
        if not values:
            summary[direction] = {
                "count": 0,
                "avg_car": None,
                "median_car": None,
                "pos_rate": None,
                "t_stat": None,
                "p_value_raw": None,
                "p_value_fdr": None,
                "significant_5pct": None,
            }
            continue
        avg_car = sum(values) / float(len(values))
        med_car = median(values)
        pos_rate = sum(1 for value in values if value > 0.0) / float(len(values))
        t_stat, p_value = _two_sided_p_value(values)
        if p_value is not None:
            p_values[direction] = p_value
        summary[direction] = {
            "count": len(values),
            "avg_car": avg_car,
            "median_car": med_car,
            "pos_rate": pos_rate,
            "t_stat": t_stat,
            "p_value_raw": p_value,
            "p_value_fdr": None,
            "significant_5pct": None,
        }
    p_values_fdr = _bh_fdr(p_values)
    for direction, value in p_values_fdr.items():
        if direction not in summary:
            continue
        summary[direction]["p_value_fdr"] = value
        summary[direction]["significant_5pct"] = bool(value <= 0.05)

    family_counts: dict[str, int] = {}
    family_car_sum: dict[str, float] = {}
    kind_counts: dict[str, int] = {}
    kind_car_sum: dict[str, float] = {}
    for row in filtered:
        event_id = str(row.get("event_id") or "").strip()
        family = event_family_by_event.get(event_id, "UNKNOWN")
        kind = event_kind_by_event.get(event_id, "internal")
        try:
            car_value = float(row.get("car"))
        except (TypeError, ValueError):
            continue
        family_counts[family] = int(family_counts.get(family, 0)) + 1
        family_car_sum[family] = float(family_car_sum.get(family, 0.0)) + car_value
        kind_counts[kind] = int(kind_counts.get(kind, 0)) + 1
        kind_car_sum[kind] = float(kind_car_sum.get(kind, 0.0)) + car_value
    family_summary = {
        key: {
            "count": int(family_counts[key]),
            "avg_car": float(family_car_sum[key]) / float(family_counts[key]) if family_counts[key] else None,
        }
        for key in sorted(family_counts.keys())
    }
    kind_summary = {
        key: {
            "count": int(kind_counts[key]),
            "avg_car": float(kind_car_sum[key]) / float(kind_counts[key]) if kind_counts[key] else None,
        }
        for key in sorted(kind_counts.keys())
    }

    return {
        "sample_count_before_overlap_filter": len(reactions),
        "sample_count": len(filtered),
        "excluded_overlap_count": excluded_overlap_count,
        "exclude_overlap": bool(exclude_overlap),
        "car_summary_by_direction": summary,
        "car_summary_by_event_family": family_summary,
        "car_summary_by_event_kind": kind_summary,
        "fdr_method": "bh",
    }
