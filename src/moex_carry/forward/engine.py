from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Iterable, Mapping, Sequence

from moex_carry.domain.portfolio import Fill, Order, PortfolioState, SnapshotPerPair
from moex_carry.forward.broker import PaperBroker
from moex_carry.forward.interfaces import IMarketDataAdapter, IPaperBroker, IReporter, IStateStore
from moex_carry.forward.models import EquityPoint, ForwardAlert, ForwardState
from moex_carry.portfolio.contracts import RebalanceConfig
from moex_carry.portfolio.rebalance_controller import PortfolioRebalanceController, pair_key
from moex_carry.snapshot.builder import build_snapshot_universe

ALERT_DATA_STALE = "DATA_STALE"
ALERT_MISSING_QUOTES = "MISSING_QUOTES"
ALERT_SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
ALERT_DRAWDOWN_KILL = "DRAWDOWN_KILL"
ALERT_TURNOVER_SPIKE = "TURNOVER_SPIKE"


class ForwardStateError(RuntimeError):
    pass


@dataclass
class ForwardEngineConfig:
    initial_cash: float = 1_000_000.0
    max_drawdown_pct: float | None = 0.2
    max_spread_bps_stock: float | None = None
    max_spread_bps_fut: float | None = None
    turnover_spike_pct: float | None = None
    turnover_spike_notional: float | None = None
    max_data_lag_days: int | None = 0


class NullReporter:
    def daily_report(
        self,
        trading_day: date,
        portfolio: PortfolioState,
        equity: EquityPoint,
        snapshots: Sequence[SnapshotPerPair],
        alerts: Sequence[ForwardAlert],
    ) -> None:
        return None


class ForwardTestEngine:
    def __init__(
        self,
        *,
        market_data: IMarketDataAdapter,
        state_store: IStateStore,
        resolved_config: Mapping[str, Any],
        rebalance_config: RebalanceConfig,
        broker: IPaperBroker | None = None,
        reporter: IReporter | None = None,
        engine_config: ForwardEngineConfig | None = None,
    ) -> None:
        self._market_data = market_data
        self._state_store = state_store
        self._resolved_config = resolved_config
        self._rebalance_config = rebalance_config
        self._broker = broker or PaperBroker()
        self._reporter = reporter or NullReporter()
        self._engine_config = engine_config or ForwardEngineConfig()
        self._rebalance_controller = PortfolioRebalanceController()
        self._state: ForwardState | None = None
        self._config_hash = self._compute_config_hash()

    @property
    def state(self) -> ForwardState | None:
        return self._state

    def run_eod(self, trading_day: date) -> list[Order]:
        state = self._load_state()
        snapshot_input = self._market_data.get_eod_snapshot(trading_day)
        snapshots = self._build_snapshots(trading_day, snapshot_input)
        alerts = self._collect_snapshot_alerts(trading_day, snapshot_input, snapshots)

        rebalance_result = self._rebalance_controller.rebalance(
            snapshots,
            state.portfolio,
            self._rebalance_config,
        )
        orders = rebalance_result.orders
        self._enrich_orders_metadata(orders, snapshots)
        submitted = self._broker.submit_orders(orders, state.portfolio, self._as_datetime(trading_day))
        state.portfolio.open_orders = list(submitted)
        state.portfolio.as_of = self._as_datetime(trading_day)
        state.last_eod_day = trading_day
        state.metadata["last_rebalance_warnings"] = list(rebalance_result.warnings)

        turnover_alert = self._check_turnover_spike(rebalance_result.turnover_estimate_notional, state)
        if turnover_alert:
            alerts.append(turnover_alert)
        self._persist_alerts(alerts)
        self._state_store.save(state)
        return list(submitted)

    def run_open(self, trading_day: date) -> list[Fill]:
        state = self._load_state()
        open_orders = list(state.portfolio.open_orders)
        if not open_orders:
            return []
        snapshot_input = self._market_data.get_open_snapshot(trading_day)
        snapshots = self._build_snapshots(trading_day, snapshot_input)
        alerts = self._collect_snapshot_alerts(trading_day, snapshot_input, snapshots)

        fills = self._broker.simulate_fills(open_orders, snapshots, self._as_datetime(trading_day))
        applied = self._broker.apply_fills(fills, state.portfolio, self._as_datetime(trading_day))
        if len(applied) < len(open_orders):
            missing = [order.order_id for order in open_orders if order.order_id not in {f.order_id for f in applied}]
            if missing:
                alerts.append(
                    ForwardAlert(
                        code=ALERT_MISSING_QUOTES,
                        as_of=self._as_datetime(trading_day),
                        message="Missing prices for some orders at open.",
                        metadata={"order_ids": missing},
                    )
                )

        for fill in applied:
            self._state_store.append_trade(fill)
        state.last_open_day = trading_day
        state.portfolio.as_of = self._as_datetime(trading_day)
        self._persist_alerts(alerts)
        self._state_store.save(state)
        return list(applied)

    def run_after_close(self, trading_day: date) -> EquityPoint:
        state = self._load_state()
        snapshot_input = self._market_data.get_eod_snapshot(trading_day)
        snapshots = self._build_snapshots(trading_day, snapshot_input)
        alerts = self._collect_snapshot_alerts(trading_day, snapshot_input, snapshots)

        equity_point, mtm_alerts = self._mark_to_market(trading_day, state, snapshots)
        alerts.extend(mtm_alerts)
        state.last_after_close_day = trading_day
        self._state_store.append_equity(equity_point)
        self._persist_alerts(alerts)
        self._state_store.save(state)
        self._reporter.daily_report(trading_day, state.portfolio, equity_point, snapshots, alerts)
        return equity_point

    def _load_state(self) -> ForwardState:
        if self._state is not None:
            return self._state
        state = self._state_store.load()
        if state is None:
            now = datetime.now(timezone.utc)
            portfolio = PortfolioState(as_of=now, cash=self._engine_config.initial_cash, equity=self._engine_config.initial_cash)
            state = ForwardState(config_hash=self._config_hash, portfolio=portfolio)
            state.metadata["equity_high_watermark"] = float(self._engine_config.initial_cash)
            self._state_store.save(state)
        elif state.config_hash != self._config_hash:
            raise ForwardStateError("Forward state config_hash mismatch; restart required.")
        self._state = state
        return state

    def _compute_config_hash(self) -> str:
        payload = {
            "resolved_config": self._resolved_config,
            "rebalance_config": self._dump_rebalance_config(),
            "engine_config": asdict(self._engine_config),
        }
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _dump_rebalance_config(self) -> dict[str, Any]:
        if hasattr(self._rebalance_config, "model_dump"):
            return self._rebalance_config.model_dump(mode="python")
        if hasattr(self._rebalance_config, "dict"):
            return self._rebalance_config.dict()
        return dict(self._rebalance_config)

    def _build_snapshots(
        self,
        trading_day: date,
        snapshot_input,
    ) -> list[SnapshotPerPair]:
        snapshots = build_snapshot_universe(
            trading_day,
            snapshot_input.pairs,
            snapshot_input.stock_bars,
            snapshot_input.fut_bars,
            snapshot_input.dividends,
            snapshot_input.key_rates,
            self._resolved_config,
            events=snapshot_input.events,
        )
        pair_map = {pair_key(p.stock_secid, p.future_secid): p for p in snapshot_input.pairs}
        for snapshot in snapshots:
            pair_id = pair_key(snapshot.stock_secid, snapshot.future_secid)
            pair = pair_map.get(pair_id)
            if pair is None:
                continue
            if snapshot.metadata is None:
                snapshot.metadata = {}
            if pair.multiplier is not None and snapshot.metadata.get("multiplier") is None:
                snapshot.metadata["multiplier"] = pair.multiplier
            if pair.tick_size is not None and snapshot.metadata.get("tick_size") is None:
                snapshot.metadata["tick_size"] = pair.tick_size
        return snapshots

    def _collect_snapshot_alerts(
        self,
        trading_day: date,
        snapshot_input,
        snapshots: Sequence[SnapshotPerPair],
    ) -> list[ForwardAlert]:
        alerts: list[ForwardAlert] = []
        as_of_dt = self._as_datetime(trading_day)
        if self._is_data_stale(trading_day, snapshot_input):
            alerts.append(
                ForwardAlert(
                    code=ALERT_DATA_STALE,
                    as_of=as_of_dt,
                    message="Market data snapshot is stale.",
                    metadata={"snapshot_day": snapshot_input.as_of.isoformat()},
                )
            )

        missing_pairs: list[str] = []
        spread_pairs: list[dict[str, Any]] = []
        for snapshot in snapshots:
            pair_id = pair_key(snapshot.stock_secid, snapshot.future_secid)
            warnings = snapshot.events.warnings if snapshot.events else []
            if any(warning.startswith("missing_") or warning.startswith("execution_prices_error") for warning in warnings):
                missing_pairs.append(pair_id)
            if self._is_spread_too_wide(snapshot):
                spread_pairs.append(
                    {
                        "pair_id": pair_id,
                        "spread_bps_stock": snapshot.lq.spread_bps_stock,
                        "spread_bps_fut": snapshot.lq.spread_bps_fut,
                    }
                )

        if missing_pairs:
            alerts.append(
                ForwardAlert(
                    code=ALERT_MISSING_QUOTES,
                    as_of=as_of_dt,
                    message="Missing quotes for one or more pairs.",
                    metadata={"pairs": missing_pairs},
                )
            )
        if spread_pairs:
            alerts.append(
                ForwardAlert(
                    code=ALERT_SPREAD_TOO_WIDE,
                    as_of=as_of_dt,
                    message="Spread exceeded configured threshold.",
                    metadata={"pairs": spread_pairs},
                )
            )
        return alerts

    def _is_data_stale(self, trading_day: date, snapshot_input) -> bool:
        max_lag = self._engine_config.max_data_lag_days
        if max_lag is None:
            return False
        if max_lag < 0:
            return False
        lag_days = (trading_day - snapshot_input.as_of).days
        return lag_days > max_lag

    def _is_spread_too_wide(self, snapshot: SnapshotPerPair) -> bool:
        max_stock = self._engine_config.max_spread_bps_stock
        max_fut = self._engine_config.max_spread_bps_fut
        if max_stock is not None and snapshot.lq.spread_bps_stock is not None:
            if snapshot.lq.spread_bps_stock > max_stock:
                return True
        if max_fut is not None and snapshot.lq.spread_bps_fut is not None:
            if snapshot.lq.spread_bps_fut > max_fut:
                return True
        return False

    def _check_turnover_spike(self, turnover: float, state: ForwardState) -> ForwardAlert | None:
        if turnover is None:
            return None
        if self._engine_config.turnover_spike_notional is not None:
            threshold = self._engine_config.turnover_spike_notional
        elif self._engine_config.turnover_spike_pct is not None:
            equity = state.portfolio.equity if state.portfolio.equity is not None else state.portfolio.cash
            threshold = float(equity or 0.0) * self._engine_config.turnover_spike_pct
        else:
            return None
        if turnover > threshold:
            return ForwardAlert(
                code=ALERT_TURNOVER_SPIKE,
                as_of=state.portfolio.as_of,
                message="Turnover spike exceeded threshold.",
                metadata={"turnover": turnover, "threshold": threshold},
            )
        return None

    def _mark_to_market(
        self,
        trading_day: date,
        state: ForwardState,
        snapshots: Sequence[SnapshotPerPair],
    ) -> tuple[EquityPoint, list[ForwardAlert]]:
        snapshot_map = {pair_key(s.stock_secid, s.future_secid): s for s in snapshots}
        equity = float(state.portfolio.cash)
        for pos in state.portfolio.positions:
            pair_id = pair_key(pos.pair.stock_secid, pos.pair.future_secid)
            snapshot = snapshot_map.get(pair_id)
            if snapshot is None:
                continue
            stock_price = snapshot.spot_close or snapshot.spot_mid
            fut_price = snapshot.future_close or snapshot.future_mid
            if stock_price is not None:
                pos.mark_price_stock = float(stock_price)
                equity += pos.quantity_stock * float(stock_price)
            if fut_price is not None and pos.entry_price_fut is not None:
                multiplier = float(pos.pair.multiplier) if pos.pair.multiplier else 1.0
                fut_pnl = (float(fut_price) - float(pos.entry_price_fut)) * pos.quantity_fut * multiplier
                equity += fut_pnl
            unrealized = 0.0
            if stock_price is not None and pos.entry_price_stock is not None:
                unrealized += (float(stock_price) - float(pos.entry_price_stock)) * pos.quantity_stock
            if fut_price is not None and pos.entry_price_fut is not None:
                multiplier = float(pos.pair.multiplier) if pos.pair.multiplier else 1.0
                unrealized += (float(fut_price) - float(pos.entry_price_fut)) * pos.quantity_fut * multiplier
            pos.unrealized_pnl = unrealized

        state.portfolio.equity = equity
        state.portfolio.as_of = self._as_datetime(trading_day)
        high = float(state.metadata.get("equity_high_watermark", equity))
        if equity > high:
            high = equity
        state.metadata["equity_high_watermark"] = high
        drawdown = (equity / high) - 1.0 if high else 0.0
        alerts: list[ForwardAlert] = []
        if self._engine_config.max_drawdown_pct is not None and drawdown <= -self._engine_config.max_drawdown_pct:
            alerts.append(
                ForwardAlert(
                    code=ALERT_DRAWDOWN_KILL,
                    as_of=self._as_datetime(trading_day),
                    message="Drawdown threshold breached.",
                    metadata={"drawdown_pct": drawdown},
                )
            )
        return EquityPoint(
            as_of=self._as_datetime(trading_day),
            equity=equity,
            cash=state.portfolio.cash,
            drawdown_pct=drawdown,
        ), alerts

    def _persist_alerts(self, alerts: Iterable[ForwardAlert]) -> None:
        for alert in alerts:
            self._state_store.append_alert(alert)

    def _enrich_orders_metadata(self, orders: Sequence[Order], snapshots: Sequence[SnapshotPerPair]) -> None:
        snapshot_map = {pair_key(s.stock_secid, s.future_secid): s for s in snapshots}
        for order in orders:
            meta = order.metadata or {}
            pair_id = meta.get("pair_id")
            snapshot = snapshot_map.get(pair_id) if pair_id else None
            if snapshot is not None:
                meta.setdefault("pair_stock", snapshot.stock_secid)
                meta.setdefault("pair_future", snapshot.future_secid)
                multiplier = snapshot.metadata.get("multiplier") if snapshot.metadata else None
                meta.setdefault("multiplier", multiplier)
                if snapshot.expiry is not None:
                    meta.setdefault("expiry", snapshot.expiry.isoformat())
            order.metadata = meta

    def _as_datetime(self, trading_day: date) -> datetime:
        return datetime.combine(trading_day, time.min).replace(tzinfo=timezone.utc)
