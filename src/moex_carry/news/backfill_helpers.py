from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Iterable

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moex_carry.config import AppSettings
from moex_carry.storage import models as db

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
def _normalize_window_order(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"chronological", "recent_first", "shock_first"}:
        return mode
    return "chronological"
def _quote_price_for_backfill(row: db.QuoteModel) -> float | None:
    if row.last is not None:
        last = float(row.last)
        if last > 0.0:
            return last
    if row.bid is not None and row.ask is not None:
        bid = float(row.bid)
        ask = float(row.ask)
        if bid > 0.0 and ask > 0.0:
            return (bid + ask) / 2.0
    if row.bid is not None:
        bid = float(row.bid)
        if bid > 0.0:
            return bid
    if row.ask is not None:
        ask = float(row.ask)
        if ask > 0.0:
            return ask
    return None
def _floor_to_bar_start(ts: datetime, *, bar_minutes: int) -> datetime:
    effective_bar = max(int(bar_minutes), 1)
    minute_of_day = ts.hour * 60 + ts.minute
    floored = (minute_of_day // effective_bar) * effective_bar
    hour, minute = divmod(floored, 60)
    return ts.replace(hour=hour, minute=minute, second=0, microsecond=0)
def _resample_points_to_bar_close(
    points: list[tuple[datetime, float]],
    *,
    bar_minutes: int,
) -> list[tuple[datetime, float]]:
    effective_bar = max(int(bar_minutes), 1)
    if effective_bar <= 1 or len(points) <= 1:
        return points
    bucket_closes: dict[datetime, tuple[datetime, float]] = {}
    for ts, price in points:
        bucket_start = _floor_to_bar_start(ts, bar_minutes=effective_bar)
        current = bucket_closes.get(bucket_start)
        if current is None or ts >= current[0]:
            bucket_closes[bucket_start] = (ts, price)
    ordered = [bucket_closes[key] for key in sorted(bucket_closes)]
    return ordered

@dataclass
class _NewsApiDailyBudget:
    limit: int
    state_path: Path
    date_iso: str
    used: int

    @classmethod
    def load(cls, *, limit: int, state_path: str) -> "_NewsApiDailyBudget":
        effective_limit = max(int(limit), 0)
        path = Path(str(state_path)).expanduser()
        today = datetime.now(timezone.utc).date().isoformat()
        used = 0
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                payload = {}
            if isinstance(payload, dict) and str(payload.get("date") or "") == today:
                try:
                    used = max(int(payload.get("used") or 0), 0)
                except (TypeError, ValueError):
                    used = 0
        budget = cls(limit=effective_limit, state_path=path, date_iso=today, used=min(used, effective_limit))
        budget._persist()
        return budget

    @property
    def remaining(self) -> int:
        return max(self.limit - self.used, 0)

    def reserve(self, count: int = 1) -> bool:
        step = max(int(count), 0)
        if step == 0:
            return True
        if self.used + step > self.limit:
            return False
        self.used += step
        self._persist()
        return True

    def _persist(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(
                    {
                        "date": self.date_iso,
                        "used": int(self.used),
                        "limit": int(self.limit),
                        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            return


def _parse_news_published_at(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc_naive(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc_naive(parsed)
def _merge_news_rows(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip().lower()
        title = str(row.get("title") or "").strip().lower()
        published_at = str(row.get("published_at") or "").strip()
        hash_value = str(row.get("hash") or "").strip()
        news_id = str(row.get("news_id") or "").strip()
        dedupe_key = "|".join([url, title, published_at, hash_value, news_id])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        merged.append(row)
    return merged
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
