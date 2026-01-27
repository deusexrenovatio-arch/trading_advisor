from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from moex_carry.domain.portfolio import Fill, Order, PairSpec, PortfolioState, PositionState
from moex_carry.forward.models import EquityPoint, ForwardAlert, ForwardState


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _serialize_date(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def _normalize_metadata(value: Any) -> Any:
    if isinstance(value, datetime):
        return _serialize_datetime(value)
    if isinstance(value, date):
        return _serialize_date(value)
    if isinstance(value, dict):
        return {str(key): _normalize_metadata(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_normalize_metadata(item) for item in value]
    return value


def _pair_to_dict(pair: PairSpec) -> dict[str, Any]:
    return {
        "stock_secid": pair.stock_secid,
        "future_secid": pair.future_secid,
        "expiry": _serialize_date(pair.expiry),
        "lot_size": pair.lot_size,
        "multiplier": pair.multiplier,
        "tick_size": pair.tick_size,
        "currency": pair.currency,
        "metadata": _normalize_metadata(pair.metadata),
    }


def _pair_from_dict(data: dict[str, Any]) -> PairSpec:
    return PairSpec(
        stock_secid=data["stock_secid"],
        future_secid=data["future_secid"],
        expiry=_parse_date(data.get("expiry")),
        lot_size=data.get("lot_size"),
        multiplier=data.get("multiplier"),
        tick_size=data.get("tick_size"),
        currency=data.get("currency", "RUB"),
        metadata=data.get("metadata") or {},
    )


def _position_to_dict(position: PositionState) -> dict[str, Any]:
    return {
        "pair": _pair_to_dict(position.pair),
        "direction": position.direction,
        "quantity_stock": position.quantity_stock,
        "quantity_fut": position.quantity_fut,
        "entry_date": _serialize_date(position.entry_date),
        "entry_price_stock": position.entry_price_stock,
        "entry_price_fut": position.entry_price_fut,
        "mark_price_stock": position.mark_price_stock,
        "mark_price_fut": position.mark_price_fut,
        "unrealized_pnl": position.unrealized_pnl,
        "realized_pnl": position.realized_pnl,
        "state": position.state,
        "metadata": _normalize_metadata(position.metadata),
        "entry_spread_exec_pct": position.entry_spread_exec_pct,
        "liq_fail_streak": position.liq_fail_streak,
        "drop_rank_streak": position.drop_rank_streak,
        "trail_peak_spread_pct": position.trail_peak_spread_pct,
    }


def _position_from_dict(data: dict[str, Any]) -> PositionState:
    return PositionState(
        pair=_pair_from_dict(data["pair"]),
        direction=data.get("direction", "cash_and_carry"),
        quantity_stock=float(data.get("quantity_stock", 0.0)),
        quantity_fut=float(data.get("quantity_fut", 0.0)),
        entry_date=_parse_date(data.get("entry_date")),
        entry_price_stock=data.get("entry_price_stock"),
        entry_price_fut=data.get("entry_price_fut"),
        mark_price_stock=data.get("mark_price_stock"),
        mark_price_fut=data.get("mark_price_fut"),
        unrealized_pnl=data.get("unrealized_pnl"),
        realized_pnl=data.get("realized_pnl"),
        state=data.get("state", "open"),
        metadata=data.get("metadata") or {},
        entry_spread_exec_pct=data.get("entry_spread_exec_pct"),
        liq_fail_streak=int(data.get("liq_fail_streak", 0)),
        drop_rank_streak=int(data.get("drop_rank_streak", 0)),
        trail_peak_spread_pct=data.get("trail_peak_spread_pct"),
    )


def _order_to_dict(order: Order) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "instrument": order.instrument,
        "side": order.side,
        "order_type": order.order_type,
        "quantity": order.quantity,
        "price": order.price,
        "status": order.status,
        "created_at": _serialize_datetime(order.created_at),
        "metadata": _normalize_metadata(order.metadata),
    }


def _order_from_dict(data: dict[str, Any]) -> Order:
    return Order(
        order_id=data["order_id"],
        instrument=data["instrument"],
        side=data.get("side", "buy"),
        order_type=data.get("order_type", "market"),
        quantity=float(data.get("quantity", 0.0)),
        price=data.get("price"),
        status=data.get("status", "new"),
        created_at=_parse_datetime(data.get("created_at")),
        metadata=data.get("metadata") or {},
    )


def _fill_to_dict(fill: Fill) -> dict[str, Any]:
    return {
        "fill_id": fill.fill_id,
        "order_id": fill.order_id,
        "instrument": fill.instrument,
        "side": fill.side,
        "quantity": fill.quantity,
        "price": fill.price,
        "fee": fill.fee,
        "filled_at": _serialize_datetime(fill.filled_at),
        "metadata": _normalize_metadata(fill.metadata),
    }


def _fill_from_dict(data: dict[str, Any]) -> Fill:
    return Fill(
        fill_id=data["fill_id"],
        order_id=data["order_id"],
        instrument=data["instrument"],
        side=data.get("side", "buy"),
        quantity=float(data.get("quantity", 0.0)),
        price=float(data.get("price", 0.0)),
        fee=data.get("fee"),
        filled_at=_parse_datetime(data.get("filled_at")),
        metadata=data.get("metadata") or {},
    )


def _portfolio_to_dict(portfolio: PortfolioState) -> dict[str, Any]:
    return {
        "as_of": _serialize_datetime(portfolio.as_of),
        "cash": portfolio.cash,
        "equity": portfolio.equity,
        "margin_used": portfolio.margin_used,
        "positions": [_position_to_dict(pos) for pos in portfolio.positions],
        "open_orders": [_order_to_dict(order) for order in portfolio.open_orders],
        "fills": [_fill_to_dict(fill) for fill in portfolio.fills],
        "metadata": _normalize_metadata(portfolio.metadata),
    }


def _portfolio_from_dict(data: dict[str, Any]) -> PortfolioState:
    return PortfolioState(
        as_of=_parse_datetime(data.get("as_of")) or datetime.now(timezone.utc),
        cash=float(data.get("cash", 0.0)),
        equity=data.get("equity"),
        margin_used=data.get("margin_used"),
        positions=[_position_from_dict(item) for item in data.get("positions", [])],
        open_orders=[_order_from_dict(item) for item in data.get("open_orders", [])],
        fills=[_fill_from_dict(item) for item in data.get("fills", [])],
        metadata=data.get("metadata") or {},
    )


def _state_to_dict(state: ForwardState) -> dict[str, Any]:
    return {
        "config_hash": state.config_hash,
        "portfolio": _portfolio_to_dict(state.portfolio),
        "last_eod_day": _serialize_date(state.last_eod_day),
        "last_open_day": _serialize_date(state.last_open_day),
        "last_after_close_day": _serialize_date(state.last_after_close_day),
        "metadata": _normalize_metadata(state.metadata),
    }


def _state_from_dict(data: dict[str, Any]) -> ForwardState:
    return ForwardState(
        config_hash=data["config_hash"],
        portfolio=_portfolio_from_dict(data.get("portfolio") or {}),
        last_eod_day=_parse_date(data.get("last_eod_day")),
        last_open_day=_parse_date(data.get("last_open_day")),
        last_after_close_day=_parse_date(data.get("last_after_close_day")),
        metadata=data.get("metadata") or {},
    )


def _write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


class JsonStateStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.base_dir / "state.json"
        self.trades_path = self.base_dir / "trades.jsonl"
        self.equity_path = self.base_dir / "equity.jsonl"
        self.alerts_path = self.base_dir / "alerts.jsonl"

    def load(self) -> ForwardState | None:
        if not self.state_path.exists():
            return None
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        return _state_from_dict(data)

    def save(self, state: ForwardState) -> None:
        payload = _state_to_dict(state)
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_trade(self, fill: Fill) -> None:
        _write_jsonl(self.trades_path, _fill_to_dict(fill))

    def append_equity(self, point: EquityPoint) -> None:
        payload = asdict(point)
        payload["as_of"] = _serialize_datetime(point.as_of)
        payload["metadata"] = _normalize_metadata(point.metadata)
        _write_jsonl(self.equity_path, payload)

    def append_alert(self, alert: ForwardAlert) -> None:
        payload = asdict(alert)
        payload["as_of"] = _serialize_datetime(alert.as_of)
        payload["metadata"] = _normalize_metadata(alert.metadata)
        _write_jsonl(self.alerts_path, payload)
