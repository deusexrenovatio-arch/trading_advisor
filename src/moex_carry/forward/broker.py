from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence

from moex_carry.domain.portfolio import Fill, Order, PairSpec, PortfolioState, PositionState, SnapshotPerPair
from moex_carry.portfolio.rebalance_controller import pair_key

def _price_from_snapshot(order: Order, snapshot: SnapshotPerPair) -> float | None:
    side = order.side.lower()
    instrument = order.instrument
    if instrument == snapshot.stock_secid:
        bid = snapshot.spot_bid
        ask = snapshot.spot_ask
        mid = snapshot.spot_mid
        open_price = snapshot.spot_open
        close_price = snapshot.spot_close
    else:
        bid = snapshot.future_bid
        ask = snapshot.future_ask
        mid = snapshot.future_mid
        open_price = snapshot.future_open
        close_price = snapshot.future_close

    if side == "buy":
        return ask or mid or open_price or close_price or bid
    return bid or mid or open_price or close_price or ask


class PaperBroker:
    def submit_orders(
        self,
        orders: Sequence[Order],
        portfolio: PortfolioState,
        as_of: datetime,
    ) -> list[Order]:
        submitted: list[Order] = []
        for order in orders:
            if order.created_at is None:
                order.created_at = as_of
            if order.status == "new":
                order.status = "submitted"
            submitted.append(order)
        portfolio.open_orders = list(submitted)
        return list(submitted)

    def simulate_fills(
        self,
        orders: Sequence[Order],
        snapshots: Sequence[SnapshotPerPair],
        as_of: datetime,
    ) -> list[Fill]:
        snapshot_map: dict[str, SnapshotPerPair] = {}
        for snapshot in snapshots:
            snapshot_map[snapshot.stock_secid] = snapshot
            snapshot_map[snapshot.future_secid] = snapshot

        fills: list[Fill] = []
        for idx, order in enumerate(orders, start=1):
            snapshot = snapshot_map.get(order.instrument)
            if snapshot is None:
                continue
            price = _price_from_snapshot(order, snapshot)
            if price is None:
                continue
            fill_id = f"fill-{order.order_id}-{idx:04d}"
            fills.append(
                Fill(
                    fill_id=fill_id,
                    order_id=order.order_id,
                    instrument=order.instrument,
                    side=order.side,
                    quantity=float(order.quantity),
                    price=float(price),
                    fee=order.metadata.get("fee") if order.metadata else None,
                    filled_at=as_of,
                    metadata=dict(order.metadata) if order.metadata else {},
                )
            )
        return fills

    def apply_fills(
        self,
        fills: Sequence[Fill],
        portfolio: PortfolioState,
        as_of: datetime,
    ) -> list[Fill]:
        if not fills:
            return []

        open_orders = {order.order_id: order for order in portfolio.open_orders}
        positions_map: dict[str, PositionState] = {
            pair_key(pos.pair.stock_secid, pos.pair.future_secid): pos for pos in portfolio.positions
        }

        for fill in fills:
            order = open_orders.get(fill.order_id)
            if order is not None:
                order.status = "filled"
            pair_id = fill.metadata.get("pair_id") if fill.metadata else None
            pair = self._pair_from_fill(fill, pair_id, positions_map)
            if pair is None:
                continue
            if pair_id is None:
                pair_id = pair_key(pair.stock_secid, pair.future_secid)
            position = positions_map.get(pair_id)
            if position is None:
                position = PositionState(
                    pair=pair,
                    direction="cash_and_carry",
                    quantity_stock=0.0,
                    quantity_fut=0.0,
                    entry_date=None,
                    entry_price_stock=None,
                    entry_price_fut=None,
                    mark_price_stock=None,
                    mark_price_fut=None,
                    unrealized_pnl=None,
                    realized_pnl=0.0,
                )
                positions_map[pair_id] = position

            if fill.instrument == pair.stock_secid:
                self._apply_leg_fill(
                    position,
                    leg="stock",
                    delta_qty=self._signed_qty(fill),
                    price=fill.price,
                    as_of=as_of,
                    multiplier=1.0,
                )
                portfolio.cash -= self._signed_qty(fill) * fill.price
            else:
                multiplier = float(pair.multiplier) if pair.multiplier else 1.0
                self._apply_leg_fill(
                    position,
                    leg="future",
                    delta_qty=self._signed_qty(fill),
                    price=fill.price,
                    as_of=as_of,
                    multiplier=multiplier,
                )

            position.direction = self._resolve_direction(position)

        portfolio.positions = list(positions_map.values())
        portfolio.open_orders = [
            order for order in portfolio.open_orders if order.order_id not in {fill.order_id for fill in fills}
        ]
        portfolio.fills.extend(list(fills))
        portfolio.as_of = as_of
        return list(fills)

    def _signed_qty(self, fill: Fill) -> float:
        return float(fill.quantity) if fill.side.lower() == "buy" else -float(fill.quantity)

    def _apply_leg_fill(
        self,
        position: PositionState,
        *,
        leg: str,
        delta_qty: float,
        price: float,
        as_of: datetime,
        multiplier: float,
    ) -> None:
        if leg == "stock":
            current_qty = position.quantity_stock
            entry_price = position.entry_price_stock
        else:
            current_qty = position.quantity_fut
            entry_price = position.entry_price_fut

        new_qty = current_qty + delta_qty
        realized_delta = self._realized_pnl_delta(current_qty, delta_qty, entry_price, price, multiplier)
        entry_price = self._update_entry_price(current_qty, entry_price, delta_qty, price)
        if realized_delta is not None:
            position.realized_pnl = (position.realized_pnl or 0.0) + realized_delta

        if leg == "stock":
            position.quantity_stock = new_qty
            position.entry_price_stock = entry_price
        else:
            position.quantity_fut = new_qty
            position.entry_price_fut = entry_price

        if position.entry_date is None and new_qty != 0:
            position.entry_date = as_of.date()
        if new_qty == 0:
            if leg == "stock":
                position.entry_price_stock = None
            else:
                position.entry_price_fut = None

    def _update_entry_price(
        self,
        current_qty: float,
        entry_price: float | None,
        delta_qty: float,
        fill_price: float,
    ) -> float | None:
        new_qty = current_qty + delta_qty
        if new_qty == 0:
            return None
        if entry_price is None or current_qty == 0:
            return fill_price
        if current_qty * delta_qty > 0:
            total_qty = abs(current_qty) + abs(delta_qty)
            if total_qty == 0:
                return fill_price
            return (abs(current_qty) * entry_price + abs(delta_qty) * fill_price) / total_qty
        if abs(delta_qty) > abs(current_qty):
            return fill_price
        return entry_price

    def _realized_pnl_delta(
        self,
        current_qty: float,
        delta_qty: float,
        entry_price: float | None,
        fill_price: float,
        multiplier: float,
    ) -> float | None:
        if entry_price is None:
            return None
        if current_qty == 0 or current_qty * delta_qty >= 0:
            return None
        closed_qty = min(abs(delta_qty), abs(current_qty))
        if closed_qty == 0:
            return None
        direction = 1.0 if current_qty > 0 else -1.0
        return (fill_price - entry_price) * closed_qty * direction * multiplier

    def _resolve_direction(self, position: PositionState) -> str:
        if position.quantity_stock >= 0 and position.quantity_fut <= 0:
            return "cash_and_carry"
        return "reverse"

    def _pair_from_fill(
        self,
        fill: Fill,
        pair_id: str | None,
        positions_map: Mapping[str, PositionState],
    ) -> PairSpec | None:
        if pair_id and pair_id in positions_map:
            return positions_map[pair_id].pair
        if pair_id:
            stock = fill.metadata.get("pair_stock") if fill.metadata else None
            future = fill.metadata.get("pair_future") if fill.metadata else None
            if stock and future:
                multiplier = fill.metadata.get("multiplier") if fill.metadata else None
                expiry = fill.metadata.get("expiry") if fill.metadata else None
                if isinstance(expiry, str):
                    try:
                        expiry = datetime.fromisoformat(expiry).date()
                    except ValueError:
                        expiry = None
                return PairSpec(
                    stock_secid=str(stock),
                    future_secid=str(future),
                    multiplier=float(multiplier) if multiplier is not None else None,
                    expiry=expiry,
                    metadata={"pair_id": pair_id},
                )
        for pos in positions_map.values():
            if fill.instrument in {pos.pair.stock_secid, pos.pair.future_secid}:
                return pos.pair
        return None
