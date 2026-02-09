from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from moex_carry.domain.models import FutMarketPoint, StockMarketPoint


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick(row: Mapping[str, Any], keys: list[str]) -> Optional[float]:
    for key in keys:
        if key in row:
            value = _to_float(row.get(key))
            if value is not None:
                return value
    return None


def _mid_from_bid_ask(bid: Optional[float], ask: Optional[float], last: Optional[float]) -> Optional[float]:
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0
    if last is not None:
        return last
    return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("T", " ")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _parse_hms(value: Any) -> Optional[tuple[int, int, int]]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(float(parts[2]))
    except ValueError:
        return None
    if hh < 0 or hh > 23 or mm < 0 or mm > 59 or ss < 0 or ss > 59:
        return None
    return hh, mm, ss


def _quote_age_sec(row: Mapping[str, Any]) -> Optional[float]:
    system_time = _parse_datetime(row.get("SYSTIME"))
    quote_hms = _parse_hms(row.get("UPDATETIME") or row.get("TIME"))
    if system_time is None or quote_hms is None:
        return None
    quote_time = system_time.replace(
        hour=quote_hms[0],
        minute=quote_hms[1],
        second=quote_hms[2],
        microsecond=0,
    )
    if quote_time > system_time:
        quote_time = quote_time - timedelta(days=1)
    age_sec = (system_time - quote_time).total_seconds()
    if age_sec < 0:
        return None
    return float(age_sec)


def build_stock_point(
    row: Mapping[str, Any],
    timestamp: Optional[datetime] = None,
) -> StockMarketPoint:
    ts = timestamp or datetime.now(timezone.utc)
    bid = _pick(row, ["BID", "BIDPRICE", "BUY"])
    ask = _pick(row, ["OFFER", "ASK", "ASKPRICE", "SELL"])
    last = _pick(row, ["LAST", "LCLOSE", "CLOSE", "MARKETPRICE", "OPEN"])
    volume = _pick(row, ["VOLUME", "VOLTODAY", "NUMTRADES"])
    bid_depth = _pick(row, ["BIDDEPTHT", "BIDDEPTH", "NUMBIDS"])
    ask_depth = _pick(row, ["OFFERDEPTHT", "OFFERDEPTH", "NUMOFFERS"])
    mid = _mid_from_bid_ask(bid, ask, last)
    dollar_volume = mid * volume if mid is not None and volume is not None else None
    return StockMarketPoint(
        timestamp=ts,
        bid=bid,
        ask=ask,
        mid=mid,
        last=last,
        volume=volume,
        dollar_volume=dollar_volume,
        bid_depth=bid_depth,
        ask_depth=ask_depth,
        quote_age_sec=_quote_age_sec(row),
    )


def build_fut_point(
    row: Mapping[str, Any],
    timestamp: Optional[datetime] = None,
) -> FutMarketPoint:
    ts = timestamp or datetime.now(timezone.utc)
    bid = _pick(row, ["BID", "BIDPRICE", "BUY"])
    ask = _pick(row, ["OFFER", "ASK", "ASKPRICE", "SELL"])
    last = _pick(row, ["LAST", "LCLOSE", "CLOSE", "MARKETPRICE", "OPEN"])
    volume = _pick(row, ["VOLUME", "VOLTODAY", "NUMTRADES"])
    open_interest = _pick(row, ["OPENPOSITION", "OPENPOSITIONVALUE", "OPENPOSITIONVOLUME"])
    bid_depth = _pick(row, ["BIDDEPTHT", "BIDDEPTH", "NUMBIDS"])
    ask_depth = _pick(row, ["OFFERDEPTHT", "OFFERDEPTH", "NUMOFFERS"])
    mid = _mid_from_bid_ask(bid, ask, last)
    return FutMarketPoint(
        timestamp=ts,
        bid=bid,
        ask=ask,
        mid=mid,
        last=last,
        volume=volume,
        open_interest=open_interest,
        bid_depth=bid_depth,
        ask_depth=ask_depth,
        quote_age_sec=_quote_age_sec(row),
    )
