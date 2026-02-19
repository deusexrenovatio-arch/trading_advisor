from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import Session

from moex_carry.news.target_v2_event_text import (
    build_event_echo_scores,
    build_event_text_by_id,
    ticker_has_text_support,
)
from moex_carry.news.target_v2_overlap import episode_key_from_event, mark_episode_aware_overlaps
from moex_carry.storage import models as db
from moex_carry.storage.repositories import (
    delete_event_target_v2_window,
    load_news_entity_links,
    load_news_event_items,
    load_news_events,
    load_news_labels,
    upsert_event_target_v2,
    upsert_exp_return_bucket_stats_v2,
)


@dataclass(frozen=True)
class TargetV2HorizonSpec:
    horizon: str
    delta: timedelta
    pre_window: timedelta
    lookback: timedelta
    pretrend_window: timedelta
    tau_sigma: float
    theta_abs: float
    tau_sigma_hi: float
    q_hi: float
    min_bucket_count: int
    p_hold: float
    p_big: float
    quantile_window: timedelta


@dataclass(frozen=True)
class EventTargetV2BuildReport:
    horizon: str
    symbol_filter: str | None
    events_seen: int
    rows_candidate: int
    rows_upserted: int
    rows_deleted: int
    clean_rows: int
    hi_conf_rows: int
    overlap_rows: int
    leakage_rows: int
    skipped_no_ticker: int
    skipped_missing_quotes: int
    skipped_invalid_time: int
    skipped_short_history: int


_TARGET_V2_SPECS: dict[str, TargetV2HorizonSpec] = {
    "5m": TargetV2HorizonSpec(
        horizon="5m",
        delta=timedelta(minutes=5),
        pre_window=timedelta(minutes=120),
        lookback=timedelta(days=120),
        pretrend_window=timedelta(minutes=15),
        tau_sigma=1.50,
        theta_abs=0.0010,
        tau_sigma_hi=2.25,
        q_hi=0.95,
        min_bucket_count=200,
        p_hold=0.85,
        p_big=0.97,
        quantile_window=timedelta(days=20),
    ),
    "1h": TargetV2HorizonSpec(
        horizon="1h",
        delta=timedelta(hours=1),
        pre_window=timedelta(hours=6),
        lookback=timedelta(days=180),
        pretrend_window=timedelta(hours=1),
        tau_sigma=1.20,
        theta_abs=0.0020,
        tau_sigma_hi=1.80,
        q_hi=0.90,
        min_bucket_count=120,
        p_hold=0.75,
        p_big=0.95,
        quantile_window=timedelta(days=20),
    ),
    "4h": TargetV2HorizonSpec(
        horizon="4h",
        delta=timedelta(hours=4),
        pre_window=timedelta(hours=48),
        lookback=timedelta(days=365),
        pretrend_window=timedelta(hours=4),
        tau_sigma=1.00,
        theta_abs=0.0035,
        tau_sigma_hi=1.50,
        q_hi=0.85,
        min_bucket_count=60,
        p_hold=0.65,
        p_big=0.95,
        quantile_window=timedelta(days=20),
    ),
    "1d": TargetV2HorizonSpec(
        horizon="1d",
        delta=timedelta(days=1),
        pre_window=timedelta(days=20),
        lookback=timedelta(days=365 * 5),
        pretrend_window=timedelta(days=1),
        tau_sigma=0.80,
        theta_abs=0.0060,
        tau_sigma_hi=1.20,
        q_hi=0.80,
        min_bucket_count=20,
        p_hold=0.55,
        p_big=0.95,
        quantile_window=timedelta(days=20),
    ),
}


def _to_iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


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


def _price_from_quote(row: db.QuoteModel, *, use_midpoint: bool) -> tuple[str, float] | None:
    bid = float(row.bid) if row.bid is not None else None
    ask = float(row.ask) if row.ask is not None else None
    last = float(row.last) if row.last is not None else None
    if use_midpoint and bid is not None and ask is not None and bid > 0.0 and ask > 0.0:
        return "mid", (bid + ask) / 2.0
    if last is not None and last > 0.0:
        return "last", last
    if bid is not None and bid > 0.0:
        return "bid", bid
    if ask is not None and ask > 0.0:
        return "ask", ask
    return None


def _load_quote_series(
    session: Session,
    *,
    ticker: str,
    start_ts: datetime,
    end_ts: datetime,
    use_midpoint: bool,
) -> tuple[list[datetime], list[float], str]:
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
    ts_list: list[datetime] = []
    px_list: list[float] = []
    price_source = "last"
    for row in rows:
        picked = _price_from_quote(row, use_midpoint=use_midpoint)
        if picked is None:
            continue
        source, price = picked
        if not ts_list and source:
            price_source = source
        ts_list.append(row.timestamp)
        px_list.append(price)
    return ts_list, px_list, price_source


def _bucket_key(ts: datetime, horizon: str) -> int:
    minute_of_day = ts.hour * 60 + ts.minute
    if horizon == "5m":
        return int(minute_of_day // 5)
    if horizon == "1h":
        return int(ts.hour)
    if horizon == "4h":
        return int(ts.hour // 4)
    if horizon == "1d":
        return int(ts.weekday())
    return int(ts.hour)


def _compute_returns(ts_list: list[datetime], px_list: list[float], start_idx: int, end_idx: int) -> list[float]:
    if end_idx - start_idx < 2:
        return []
    values: list[float] = []
    for idx in range(start_idx + 1, end_idx):
        p0 = px_list[idx - 1]
        p1 = px_list[idx]
        if p0 <= 0.0 or p1 <= 0.0:
            continue
        values.append(math.log(p1 / p0))
    return values


def _mad_sigma(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    med = median(returns)
    deviations = [abs(value - med) for value in returns]
    mad = median(deviations)
    return float(1.4826 * mad)


def _realized_vol(returns: list[float]) -> float:
    if not returns:
        return 0.0
    return float(math.sqrt(sum(value * value for value in returns)))


def _sigmoid(value: float) -> float:
    clipped = max(min(float(value), 60.0), -60.0)
    return float(1.0 / (1.0 + math.exp(-clipped)))


def _safe_quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    normalized = sorted(values)
    if q <= 0.0:
        return float(normalized[0])
    if q >= 1.0:
        return float(normalized[-1])
    pos = (len(normalized) - 1) * q
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return float(normalized[low])
    weight = pos - low
    return float((1.0 - weight) * normalized[low] + weight * normalized[high])


def _expected_return_by_bucket(
    *,
    ts_list: list[datetime],
    px_list: list[float],
    idx0: int,
    spec: TargetV2HorizonSpec,
) -> tuple[float, int, float | None, float | None]:
    if idx0 <= 0:
        return 0.0, 0, None, None
    t0 = ts_list[idx0]
    lookback_start = t0 - spec.lookback
    left = bisect.bisect_left(ts_list, lookback_start)
    if left >= idx0:
        return 0.0, 0, None, None
    key = _bucket_key(t0, spec.horizon)
    bucket_returns: list[float] = []
    all_returns: list[float] = []
    for idx in range(left, idx0):
        t_start = ts_list[idx]
        idx_end = bisect.bisect_left(ts_list, t_start + spec.delta)
        if idx_end <= idx or idx_end >= len(ts_list):
            continue
        # Avoid leaking with history that completes after event start.
        if ts_list[idx_end] >= t0:
            continue
        p0 = px_list[idx]
        p1 = px_list[idx_end]
        if p0 <= 0.0 or p1 <= 0.0:
            continue
        ret = math.log(p1 / p0)
        all_returns.append(ret)
        if _bucket_key(t_start, spec.horizon) == key:
            bucket_returns.append(ret)
    selected = bucket_returns if len(bucket_returns) >= spec.min_bucket_count else all_returns
    if not selected:
        return 0.0, 0, None, None
    return float(mean(selected)), len(selected), float(mean(selected)), float(median(selected))


def _build_event_context(
    session: Session,
    *,
    event_ids: list[str],
) -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    if not event_ids:
        return {}, {}
    event_items = load_news_event_items(session, event_ids=event_ids, limit=max(len(event_ids) * 50, 5000))
    event_to_news: dict[str, list[str]] = {}
    for row in event_items:
        event_id = str(row.get("event_id") or "").strip()
        news_id = str(row.get("news_id") or "").strip()
        if not event_id or not news_id:
            continue
        event_to_news.setdefault(event_id, []).append(news_id)
    news_ids = sorted(
        {
            news_id
            for items in event_to_news.values()
            for news_id in items
            if isinstance(news_id, str) and news_id
        }
    )
    links = load_news_entity_links(session, news_ids=news_ids, limit=max(len(news_ids) * 10, 5000))
    labels = load_news_labels(session, target_level="event", target_ids=event_ids, limit=max(len(event_ids) * 5, 5000))

    tickers_by_news: dict[str, set[str]] = {}
    for row in links:
        news_id = str(row.get("news_id") or "").strip()
        ticker = str(row.get("ticker") or row.get("entity_id") or "").strip().upper()
        if not news_id or not ticker:
            continue
        tickers_by_news.setdefault(news_id, set()).add(ticker)

    tickers_by_event: dict[str, set[str]] = {}
    for event_id, rows in event_to_news.items():
        bucket: set[str] = set()
        for news_id in rows:
            bucket |= tickers_by_news.get(news_id, set())
        tickers_by_event[event_id] = bucket

    for row in labels:
        event_id = str(row.get("target_id") or "").strip()
        label_source = str(row.get("label_source") or "").strip().lower()
        if label_source == "auto_factor_v2":
            # Avoid feedback loop: target_v2 should not ingest its own derived labels.
            continue
        commodity_json = row.get("commodity_json")
        confidence = float(row.get("confidence") or 0.0)
        relevance = float(row.get("relevance") or 0.0)
        if not event_id or not isinstance(commodity_json, list) or (confidence < 0.40 and relevance < 0.40):
            continue
        for item in commodity_json:
            ticker = str(item or "").strip().upper()
            if ticker:
                tickers_by_event.setdefault(event_id, set()).add(ticker)
    return tickers_by_event, event_to_news


def _resolve_horizon_spec(horizon: str) -> TargetV2HorizonSpec:
    key = str(horizon or "").strip().lower()
    spec = _TARGET_V2_SPECS.get(key)
    if spec is None:
        raise ValueError(f"unsupported_horizon: {horizon}")
    return spec


def _mark_overlaps(rows: list[dict[str, object]]) -> int:
    return mark_episode_aware_overlaps(rows)


def rebuild_event_target_v2(
    session: Session,
    *,
    horizon: str,
    symbol: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    processing_lag_sec: int = 60,
    max_events: int = 0,
    use_midpoint: bool = True,
) -> EventTargetV2BuildReport:
    spec = _resolve_horizon_spec(horizon)
    normalized_symbol = str(symbol or "").strip().upper() or None
    events = load_news_events(
        session,
        published_from=_to_iso_z(published_from),
        published_to=_to_iso_z(published_to),
        limit=max_events if max_events > 0 else 0,
    )
    event_ids = [str(row.get("event_id") or "").strip() for row in events if str(row.get("event_id") or "").strip()]
    tickers_by_event, event_to_news = _build_event_context(session, event_ids=event_ids)
    event_text_by_id = build_event_text_by_id(session, event_to_news=event_to_news)
    event_echo_scores = build_event_echo_scores(session, event_to_news=event_to_news)

    # Prepare per-ticker quote caches for the full range.
    event_ts_values: list[datetime] = []
    for row in events:
        t_pub = _parse_iso_datetime(row.get("event_first_published_at_utc"))
        t_seen = _parse_iso_datetime(row.get("event_first_ingested_at_utc"))
        candidates = [value for value in (t_seen, t_pub) if isinstance(value, datetime)]
        if candidates:
            event_ts_values.append(min(candidates))
    if not event_ts_values:
        return EventTargetV2BuildReport(
            horizon=spec.horizon,
            symbol_filter=normalized_symbol,
            events_seen=len(events),
            rows_candidate=0,
            rows_upserted=0,
            rows_deleted=0,
            clean_rows=0,
            hi_conf_rows=0,
            overlap_rows=0,
            leakage_rows=0,
            skipped_no_ticker=0,
            skipped_missing_quotes=0,
            skipped_invalid_time=0,
            skipped_short_history=0,
        )
    global_start = min(event_ts_values) - max(spec.lookback, spec.pre_window, spec.pretrend_window) - timedelta(days=2)
    global_end = max(event_ts_values) + spec.delta + timedelta(days=2)

    tickers = sorted(
        {
            ticker
            for values in tickers_by_event.values()
            for ticker in values
            if isinstance(ticker, str) and ticker
        }
    )
    if normalized_symbol:
        tickers = [ticker for ticker in tickers if ticker == normalized_symbol]

    quote_cache: dict[str, tuple[list[datetime], list[float], str]] = {}
    for ticker in tickers:
        quote_cache[ticker] = _load_quote_series(
            session,
            ticker=ticker,
            start_ts=global_start,
            end_ts=global_end,
            use_midpoint=use_midpoint,
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    raw_rows: list[dict[str, object]] = []
    bucket_rows: list[dict[str, object]] = []
    skipped_no_ticker = 0
    skipped_missing_quotes = 0
    skipped_invalid_time = 0
    skipped_short_history = 0
    leakage_rows = 0

    eps = 1e-8
    z_pre_alert = 1.0
    alpha_premove = 1.0
    gamma_conf = 1.0
    lag = timedelta(seconds=max(int(processing_lag_sec), 0))
    for event in events:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            continue
        episode_key = episode_key_from_event(event)
        t_pub = _parse_iso_datetime(event.get("event_first_published_at_utc"))
        t_seen = _parse_iso_datetime(event.get("event_first_ingested_at_utc"))
        t_anchor = t_pub
        candidates = [value for value in (t_seen, t_pub) if isinstance(value, datetime)]
        if not candidates:
            skipped_invalid_time += 1
            continue
        t_event = min(candidates)
        event_time_source = "first_seen" if (t_seen is not None and t_event == t_seen) else "published"
        event_tickers = sorted(tickers_by_event.get(event_id, set()))
        event_text = str(event_text_by_id.get(event_id) or "")
        event_tickers = [ticker for ticker in event_tickers if ticker_has_text_support(ticker=ticker, text=event_text)]
        if normalized_symbol:
            event_tickers = [item for item in event_tickers if item == normalized_symbol]
        if not event_tickers:
            skipped_no_ticker += 1
            continue
        t_ref = t_event + lag

        for ticker in event_tickers:
            cached = quote_cache.get(ticker)
            if cached is None:
                skipped_missing_quotes += 1
                continue
            ts_list, px_list, price_source = cached
            if not ts_list or not px_list:
                skipped_missing_quotes += 1
                continue
            idx0 = bisect.bisect_left(ts_list, t_ref) - 1
            if idx0 < 0 or idx0 >= len(ts_list):
                skipped_missing_quotes += 1
                continue
            t0 = ts_list[idx0]
            p0 = px_list[idx0]
            if p0 <= 0.0:
                skipped_missing_quotes += 1
                continue
            idx1 = bisect.bisect_left(ts_list, t0 + spec.delta)
            if idx1 >= len(ts_list):
                skipped_missing_quotes += 1
                continue
            t1 = ts_list[idx1]
            p1 = px_list[idx1]
            if p1 <= 0.0 or t1 <= t0:
                skipped_missing_quotes += 1
                continue
            r_post = math.log(p1 / p0)
            raw_return = r_post

            pre_start = t0 - spec.pre_window
            pre_left = bisect.bisect_left(ts_list, pre_start)
            pre_returns = _compute_returns(ts_list, px_list, pre_left, idx0 + 1)
            rv_pre = _realized_vol(pre_returns)
            pre_window_minutes = max(int(spec.pre_window.total_seconds() // 60), 1)
            horizon_minutes = max(int(spec.delta.total_seconds() // 60), 1)
            sigma_hat = rv_pre * math.sqrt(float(horizon_minutes) / float(pre_window_minutes))
            if sigma_hat <= 0.0:
                sigma_hat = max(spec.theta_abs, 1e-6)
            sigma_pre = _mad_sigma(pre_returns)
            if sigma_pre <= 0.0:
                sigma_pre = max(spec.theta_abs / max(spec.tau_sigma, 1e-9), 1e-6)
            if len(pre_returns) < 2:
                skipped_short_history += 1

            exp_return, bucket_count, bucket_mean, bucket_median = _expected_return_by_bucket(
                ts_list=ts_list,
                px_list=px_list,
                idx0=idx0,
                spec=spec,
            )
            ar = raw_return - exp_return

            idx_pre = bisect.bisect_left(ts_list, t0 - spec.delta)
            r_pre = 0.0
            if 0 <= idx_pre < idx0 < len(ts_list):
                p_pre = px_list[idx_pre]
                if p_pre > 0.0:
                    r_pre = math.log(p0 / p_pre)
            z_post = raw_return / max(sigma_hat, eps)
            z_pre = r_pre / max(sigma_hat, eps)

            pretrend_start = t0 - spec.pretrend_window
            idx_pretrend_start = bisect.bisect_left(ts_list, pretrend_start)
            leakage_postmove = False
            if idx_pretrend_start < idx0 and idx_pretrend_start < len(ts_list):
                p_pretrend = px_list[idx_pretrend_start]
                if p_pretrend > 0.0:
                    pretrend_return = math.log(p0 / p_pretrend)
                    pretrend_returns = _compute_returns(ts_list, px_list, idx_pretrend_start, idx0 + 1)
                    sigma_pretrend = _mad_sigma(pretrend_returns)
                    if sigma_pretrend > 0.0 and abs(pretrend_return) > 2.0 * sigma_pretrend:
                        leakage_postmove = True

            if leakage_postmove:
                leakage_rows += 1

            row = {
                "event_id": event_id,
                "symbol": ticker,
                "horizon": spec.horizon,
                "t_pub": _to_iso_z(t_pub),
                "t_anchor": _to_iso_z(t_anchor),
                "t_event": _to_iso_z(t_event),
                "event_time_source": event_time_source,
                "t0": _to_iso_z(t0),
                "t1": _to_iso_z(t1),
                "p0": float(p0),
                "p1": float(p1),
                "r_raw": float(raw_return),
                "r_post": float(r_post),
                "r_pre": float(r_pre),
                "r_exp": float(exp_return),
                "ar": float(ar),
                "sigma_pre": float(sigma_pre),
                "sigma_hat": float(sigma_hat),
                "z_post": float(z_post),
                "z_pre": float(z_pre),
                "z_hold": 0.0,
                "z_big": 0.0,
                "impact_bin": 0,
                "impact_score": 0.0,
                "overlap_count": 0,
                "echo_score": float(event_echo_scores.get(event_id, 0.0)),
                "premove_penalty": 1.0,
                "confidence": 0.0,
                "label_v2": 0,
                "is_hi_conf": False,
                "leakage_postmove": leakage_postmove,
                "is_repost": False,
                "is_overlapped": False,
                "price_source": price_source,
                "created_at": _to_iso_z(now),
                "updated_at": _to_iso_z(now),
                "_t0_dt": t0,
                "_t1_dt": t1,
                "_episode_key": episode_key,
            }
            raw_rows.append(row)
            if bucket_mean is not None and bucket_median is not None:
                bucket_rows.append(
                    {
                        "symbol": ticker,
                        "horizon": spec.horizon,
                        "bucket_b": _bucket_key(t0, spec.horizon),
                        "bucket_v": 0,
                        "bucket_s": 0,
                        "lookback_start": _to_iso_z(t0 - spec.lookback),
                        "lookback_end": _to_iso_z(t0),
                        "n": bucket_count,
                        "mean_return": bucket_mean,
                        "median_return": bucket_median,
                        "updated_at": _to_iso_z(now),
                    }
                )

    if raw_rows:
        overlap_rows = _mark_overlaps(raw_rows)

        grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
        for row in raw_rows:
            symbol_key = str(row.get("symbol") or "").strip().upper()
            horizon_key = str(row.get("horizon") or "").strip().lower()
            grouped.setdefault((symbol_key, horizon_key), []).append(row)

        for items in grouped.values():
            ordered = sorted(
                items,
                key=lambda row: (
                    row.get("_t0_dt") if isinstance(row.get("_t0_dt"), datetime) else datetime.min,
                    str(row.get("event_id") or ""),
                ),
            )
            abs_all = [abs(float(row.get("z_post") or 0.0)) for row in ordered]
            history: list[tuple[datetime, float]] = []
            for row in ordered:
                t0_dt = row.get("_t0_dt")
                if not isinstance(t0_dt, datetime):
                    continue
                history = [(ts, value) for ts, value in history if (t0_dt - ts) <= spec.quantile_window]
                hist_values = [value for _, value in history]
                quantile_source = hist_values if hist_values else abs_all
                sigma_hat = max(float(row.get("sigma_hat") or 0.0), eps)
                z_floor = float(spec.theta_abs / sigma_hat)
                z_hold = max(_safe_quantile(quantile_source, spec.p_hold), z_floor)
                z_big = max(_safe_quantile(quantile_source, spec.p_big), z_hold)
                row["z_hold"] = float(z_hold)
                row["z_big"] = float(z_big)
                abs_z = abs(float(row.get("z_post") or 0.0))
                direction_score = float(row.get("ar") or row.get("r_post") or 0.0)
                direction = 1 if direction_score > 0.0 else (-1 if direction_score < 0.0 else 0)
                if abs_z < z_hold:
                    row["impact_bin"] = 0
                    row["label_v2"] = 0
                elif abs_z < z_big:
                    row["impact_bin"] = 1
                    row["label_v2"] = direction
                else:
                    row["impact_bin"] = 2
                    row["label_v2"] = direction
                history.append((t0_dt, abs_z))

        grouped_scores: dict[tuple[str, str], list[float]] = {}
        grouped_abs_z: dict[tuple[str, str], list[float]] = {}
        for row in raw_rows:
            symbol_key = str(row.get("symbol") or "").strip().upper()
            horizon_key = str(row.get("horizon") or "").strip().lower()
            overlap_count = int(row.get("overlap_count") or 0)
            w_overlap = 1.0 / float(1 + max(overlap_count, 0))
            echo_score = max(min(float(row.get("echo_score") or 0.0), 1.0), 0.0)
            w_echo = max(0.0, 1.0 - echo_score)
            z_post = abs(float(row.get("z_post") or 0.0))
            z_pre = abs(float(row.get("z_pre") or 0.0))
            premove_penalty = math.exp(-alpha_premove * max(0.0, z_pre - z_post))
            r_pre = float(row.get("r_pre") or 0.0)
            r_post = float(row.get("r_post") or 0.0)
            if z_pre > z_pre_alert and r_pre * r_post > 0.0:
                premove_penalty *= 0.5
            impact_score = z_post * w_overlap * w_echo * premove_penalty
            row["premove_penalty"] = float(premove_penalty)
            row["impact_score"] = float(impact_score)
            grouped_scores.setdefault((symbol_key, horizon_key), []).append(float(impact_score))
            grouped_abs_z.setdefault((symbol_key, horizon_key), []).append(float(z_post))

        for row in raw_rows:
            key = (
                str(row.get("symbol") or "").strip().upper(),
                str(row.get("horizon") or "").strip().lower(),
            )
            scores = grouped_scores.get(key) or [0.0]
            c0 = _safe_quantile(scores, 0.50)
            impact_score = float(row.get("impact_score") or 0.0)
            row["confidence"] = _sigmoid(gamma_conf * (impact_score - c0))
            abs_z = abs(float(row.get("z_post") or 0.0))
            z_big = float(row.get("z_big") or 0.0)
            z_hi = _safe_quantile(grouped_abs_z.get(key) or [0.0], spec.q_hi)
            row["is_hi_conf"] = bool(abs_z >= max(z_big, z_hi))
    else:
        overlap_rows = 0

    clean_rows = sum(
        1
        for row in raw_rows
        if not bool(row.get("leakage_postmove")) and not bool(row.get("is_repost")) and not bool(row.get("is_overlapped"))
    )
    hi_conf_rows = sum(1 for row in raw_rows if bool(row.get("is_hi_conf")))

    for row in raw_rows:
        row.pop("_t0_dt", None)
        row.pop("_t1_dt", None)
        row.pop("_episode_key", None)

    rows_deleted = 0
    if normalized_symbol and (published_from is not None or published_to is not None):
        rows_deleted = delete_event_target_v2_window(
            session,
            symbol=normalized_symbol,
            horizon=spec.horizon,
            from_ts=_to_iso_z(published_from),
            to_ts=_to_iso_z(published_to),
        )
    rows_upserted = upsert_event_target_v2(session, raw_rows) if raw_rows else 0
    if bucket_rows:
        upsert_exp_return_bucket_stats_v2(session, bucket_rows)

    return EventTargetV2BuildReport(
        horizon=spec.horizon,
        symbol_filter=normalized_symbol,
        events_seen=len(events),
        rows_candidate=len(raw_rows),
        rows_upserted=rows_upserted,
        rows_deleted=rows_deleted,
        clean_rows=clean_rows,
        hi_conf_rows=hi_conf_rows,
        overlap_rows=overlap_rows,
        leakage_rows=leakage_rows,
        skipped_no_ticker=skipped_no_ticker,
        skipped_missing_quotes=skipped_missing_quotes,
        skipped_invalid_time=skipped_invalid_time,
        skipped_short_history=skipped_short_history,
    )
