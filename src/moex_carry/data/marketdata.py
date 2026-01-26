from __future__ import annotations

from datetime import datetime, timezone
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


def build_stock_point(
    row: Mapping[str, Any],
    timestamp: Optional[datetime] = None,
) -> StockMarketPoint:
    ts = timestamp or datetime.now(timezone.utc)
    bid = _pick(row, ["BID", "BIDPRICE", "BUY"])
    ask = _pick(row, ["OFFER", "ASK", "ASKPRICE", "SELL"])
    last = _pick(row, ["LAST", "LCLOSE", "CLOSE", "MARKETPRICE", "OPEN"])
    volume = _pick(row, ["VOLUME", "VOLTODAY", "NUMTRADES"])
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
    mid = _mid_from_bid_ask(bid, ask, last)
    return FutMarketPoint(
        timestamp=ts,
        bid=bid,
        ask=ask,
        mid=mid,
        last=last,
        volume=volume,
        open_interest=open_interest,
    )
