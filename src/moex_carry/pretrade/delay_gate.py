from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Mapping

from moex_carry.data.marketdata import build_fut_point, build_stock_point


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("T", " ")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _future_price(value: float | None, scale: float) -> float | None:
    if value is None:
        return None
    if scale <= 0:
        return value
    return value / scale


def _hit_with_fallback(
    primary: float | None,
    fallback_last: float | None,
    predicate,
    *,
    require_tradeflow: bool,
    tradeflow: bool,
) -> bool:
    if primary is not None:
        return bool(predicate(primary))
    if fallback_last is None:
        return False
    if require_tradeflow and not tradeflow:
        return False
    return bool(predicate(fallback_last))


def _collect_snapshots(
    client: Any,
    *,
    stock: str,
    future: str,
    snapshots: int,
    poll_sec: float,
    stock_engine: str,
    stock_market: str,
    stock_board: str,
    fut_engine: str,
    fut_market: str,
    fut_board: str,
) -> list[dict[str, Mapping[str, Any]]]:
    rows: list[dict[str, Mapping[str, Any]]] = []
    for idx in range(max(1, snapshots)):
        stock_rows = client.get_marketdata(stock_engine, stock_market, stock_board, stock)
        fut_rows = client.get_marketdata(fut_engine, fut_market, fut_board, future)
        rows.append(
            {
                "stock": stock_rows[0] if stock_rows else {},
                "future": fut_rows[0] if fut_rows else {},
            }
        )
        if idx < snapshots - 1 and poll_sec > 0:
            time.sleep(poll_sec)
    return rows


def run_delay_gate(
    client: Any,
    *,
    stock: str,
    future: str,
    direction: str,
    spot_target: float,
    future_target: float,
    spread_target: float,
    future_scale: float,
    qty_fut: float,
    participation_rate: float,
    snapshots: int = 4,
    min_hits: int = 2,
    eps: float = 0.0015,
    sync_sec: float = 120.0,
    poll_sec: float = 5.0,
    require_tradeflow_for_last: bool = False,
    stock_engine: str = "stock",
    stock_market: str = "shares",
    stock_board: str = "TQBR",
    fut_engine: str = "futures",
    fut_market: str = "forts",
    fut_board: str = "RFUD",
) -> dict[str, Any]:
    snapshots_data = _collect_snapshots(
        client,
        stock=stock,
        future=future,
        snapshots=snapshots,
        poll_sec=poll_sec,
        stock_engine=stock_engine,
        stock_market=stock_market,
        stock_board=stock_board,
        fut_engine=fut_engine,
        fut_market=fut_market,
        fut_board=fut_board,
    )

    stock_buy_max = float(spot_target) * (1.0 + float(eps))
    stock_sell_min = float(spot_target) * (1.0 - float(eps))
    fut_buy_max = float(future_target) * (1.0 + float(eps))
    fut_sell_min = float(future_target) * (1.0 - float(eps))
    spread_band = float(spot_target) * float(eps)
    spread_min = float(spread_target) - spread_band
    spread_max = float(spread_target) + spread_band

    qty_fut = max(float(qty_fut), 0.0)
    participation_rate = max(float(participation_rate), 0.000001)
    qty_stock = qty_fut * max(float(future_scale), 1.0)
    min_session_volume_stock = qty_stock / participation_rate
    min_session_volume_fut = qty_fut / participation_rate

    stock_price_hits = 0
    fut_price_hits = 0
    spread_hits = 0
    sync_hits = 0
    stock_volume_hits = 0
    fut_volume_hits = 0

    prev_stock_numtrades: float | None = None
    prev_fut_numtrades: float | None = None
    last_snapshot_view: dict[str, Any] = {}

    for snapshot in snapshots_data:
        raw_stock = snapshot.get("stock", {})
        raw_fut = snapshot.get("future", {})

        stock_point = build_stock_point(raw_stock)
        fut_point = build_fut_point(raw_fut)

        stock_bid = stock_point.bid
        stock_ask = stock_point.ask
        stock_last = stock_point.last
        fut_bid = _future_price(fut_point.bid, future_scale)
        fut_ask = _future_price(fut_point.ask, future_scale)
        fut_last = _future_price(fut_point.last, future_scale)

        stock_numtrades = _to_float(raw_stock.get("NUMTRADES"))
        fut_numtrades = _to_float(raw_fut.get("NUMTRADES"))
        stock_tradeflow = (
            prev_stock_numtrades is not None
            and stock_numtrades is not None
            and stock_numtrades > prev_stock_numtrades
        )
        fut_tradeflow = (
            prev_fut_numtrades is not None
            and fut_numtrades is not None
            and fut_numtrades > prev_fut_numtrades
        )
        if stock_numtrades is not None:
            prev_stock_numtrades = stock_numtrades
        if fut_numtrades is not None:
            prev_fut_numtrades = fut_numtrades

        stock_time = _to_datetime(raw_stock.get("SYSTIME"))
        fut_time = _to_datetime(raw_fut.get("SYSTIME"))
        if stock_time is not None and fut_time is not None:
            if abs((stock_time - fut_time).total_seconds()) <= float(sync_sec):
                sync_hits += 1

        if direction == "reverse":
            stock_leg_hit = _hit_with_fallback(
                stock_bid,
                stock_last,
                lambda value: value >= stock_sell_min,
                require_tradeflow=require_tradeflow_for_last,
                tradeflow=stock_tradeflow,
            )
            fut_leg_hit = _hit_with_fallback(
                fut_ask,
                fut_last,
                lambda value: value <= fut_buy_max,
                require_tradeflow=require_tradeflow_for_last,
                tradeflow=fut_tradeflow,
            )
            stock_exec = stock_bid if stock_bid is not None else stock_last
            fut_exec = fut_ask if fut_ask is not None else fut_last
        else:
            stock_leg_hit = _hit_with_fallback(
                stock_ask,
                stock_last,
                lambda value: value <= stock_buy_max,
                require_tradeflow=require_tradeflow_for_last,
                tradeflow=stock_tradeflow,
            )
            fut_leg_hit = _hit_with_fallback(
                fut_bid,
                fut_last,
                lambda value: value >= fut_sell_min,
                require_tradeflow=require_tradeflow_for_last,
                tradeflow=fut_tradeflow,
            )
            stock_exec = stock_ask if stock_ask is not None else stock_last
            fut_exec = fut_bid if fut_bid is not None else fut_last

        if stock_leg_hit:
            stock_price_hits += 1
        if fut_leg_hit:
            fut_price_hits += 1

        spread_exec = None
        if stock_exec is not None and fut_exec is not None:
            spread_exec = stock_exec - fut_exec
            if spread_min <= spread_exec <= spread_max:
                spread_hits += 1

        stock_volume = stock_point.volume
        fut_volume = fut_point.volume
        if stock_volume is not None and stock_volume >= min_session_volume_stock:
            stock_volume_hits += 1
        if fut_volume is not None and fut_volume >= min_session_volume_fut:
            fut_volume_hits += 1

        last_snapshot_view = {
            "stock_bid": stock_bid,
            "stock_ask": stock_ask,
            "stock_last": stock_last,
            "stock_volume": stock_volume,
            "stock_numtrades": stock_numtrades,
            "fut_bid_per_share": fut_bid,
            "fut_ask_per_share": fut_ask,
            "fut_last_per_share": fut_last,
            "fut_volume_contracts": fut_volume,
            "fut_numtrades": fut_numtrades,
            "spread_exec": spread_exec,
            "stock_systime": raw_stock.get("SYSTIME"),
            "fut_systime": raw_fut.get("SYSTIME"),
        }

    required_hits = max(int(min_hits), 1)
    stock_price_pass = stock_price_hits >= required_hits
    fut_price_pass = fut_price_hits >= required_hits
    spread_pass = spread_hits >= required_hits
    sync_pass = sync_hits >= required_hits
    stock_volume_pass = stock_volume_hits >= required_hits
    fut_volume_pass = fut_volume_hits >= required_hits

    ready_to_place = (
        stock_price_pass
        and fut_price_pass
        and spread_pass
        and sync_pass
        and stock_volume_pass
        and fut_volume_pass
    )

    reasons: list[str] = []
    if not stock_price_pass:
        reasons.append("stock_range_miss")
    if not fut_price_pass:
        reasons.append("fut_range_miss")
    if not spread_pass:
        reasons.append("spread_out_of_band")
    if not sync_pass:
        reasons.append("snapshot_unsynced")
    if not stock_volume_pass:
        reasons.append("stock_volume_miss")
    if not fut_volume_pass:
        reasons.append("fut_volume_miss")

    return {
        "status": "PLACE" if ready_to_place else "CHECK",
        "ready_to_place": ready_to_place,
        "manual_confirm_required": True,
        "pair": {
            "stock": stock,
            "future": future,
            "direction": direction,
        },
        "targets": {
            "spot_target": spot_target,
            "future_target_per_share": future_target,
            "spread_target": spread_target,
        },
        "order_price_bands": {
            "stock_buy_max": stock_buy_max,
            "stock_sell_min": stock_sell_min,
            "future_buy_max_per_share": fut_buy_max,
            "future_sell_min_per_share": fut_sell_min,
            "future_buy_max_contract": fut_buy_max * future_scale,
            "future_sell_min_contract": fut_sell_min * future_scale,
            "spread_min": spread_min,
            "spread_max": spread_max,
        },
        "volume_requirements": {
            "qty_fut_contracts": qty_fut,
            "qty_stock_shares": qty_stock,
            "participation_rate": participation_rate,
            "min_session_volume_stock": min_session_volume_stock,
            "min_session_volume_fut_contracts": min_session_volume_fut,
        },
        "gates": {
            "stock_price_pass": stock_price_pass,
            "fut_price_pass": fut_price_pass,
            "spread_pass": spread_pass,
            "sync_pass": sync_pass,
            "stock_volume_pass": stock_volume_pass,
            "fut_volume_pass": fut_volume_pass,
        },
        "hits": {
            "required": required_hits,
            "stock_price_hits": stock_price_hits,
            "fut_price_hits": fut_price_hits,
            "spread_hits": spread_hits,
            "sync_hits": sync_hits,
            "stock_volume_hits": stock_volume_hits,
            "fut_volume_hits": fut_volume_hits,
            "snapshots": len(snapshots_data),
        },
        "reasons": reasons,
        "last_snapshot": last_snapshot_view,
    }

