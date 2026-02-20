from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from moex_carry.backtest_v2.engine import build_rebalance_config
from moex_carry.backtest_v2.runtime import build_universe_from_request
from moex_carry.config_resolver import resolve_backtest_request
from moex_carry.contracts.strategy_test import ForwardTestRequest
from moex_carry.data.history_store import HistoryDataStore
from moex_carry.forward.engine import ForwardEngineConfig, ForwardTestEngine
from moex_carry.forward.interfaces import IMarketDataAdapter
from moex_carry.forward.models import MarketSnapshotInput
from moex_carry.forward.store import JsonStateStore, _state_to_dict


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_last_jsonl(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    lines = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                lines.append(line)
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return None


def _as_date(value: datetime | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(timezone.utc).date()


class HistoryMarketDataAdapter(IMarketDataAdapter):
    def __init__(self, data_store: HistoryDataStore) -> None:
        self._data_store = data_store
        self._pairs = list(data_store.pairs)
        self._stock_secids = {pair.stock_secid for pair in self._pairs}
        self._fut_secids = {pair.future_secid for pair in self._pairs}
        self._calendar = list(data_store.get_calendar(date.min, date.max))
        self._calendar.sort()

    def get_eod_snapshot(self, trading_day: date) -> MarketSnapshotInput:
        stock_bars = self._data_store.get_stock_bars(trading_day, self._stock_secids)
        fut_bars = self._data_store.get_fut_bars(trading_day, self._fut_secids)
        return MarketSnapshotInput(
            as_of=trading_day,
            pairs=list(self._pairs),
            stock_bars={bar.secid: bar for bar in stock_bars},
            fut_bars={bar.secid: bar for bar in fut_bars},
            dividends=self._data_store.get_dividends(),
            key_rates=self._data_store.get_key_rates(),
            events=self._data_store.get_events(),
            timestamp=datetime.now(timezone.utc),
        )

    def get_open_snapshot(self, trading_day: date) -> MarketSnapshotInput:
        stock_bars = self._data_store.get_stock_bars(trading_day, self._stock_secids)
        fut_bars = self._data_store.get_fut_bars(trading_day, self._fut_secids)
        stock_bars = self._data_store.bars_for_open(stock_bars)
        fut_bars = self._data_store.bars_for_open(fut_bars)
        return MarketSnapshotInput(
            as_of=trading_day,
            pairs=list(self._pairs),
            stock_bars={bar.secid: bar for bar in stock_bars},
            fut_bars={bar.secid: bar for bar in fut_bars},
            dividends=self._data_store.get_dividends(),
            key_rates=self._data_store.get_key_rates(),
            events=self._data_store.get_events(),
            timestamp=datetime.now(timezone.utc),
        )

    def get_trading_day(self, as_of: datetime | None = None) -> date:
        if not self._calendar:
            return _as_date(as_of)
        target = _as_date(as_of)
        if target in self._calendar:
            return target
        past = [day for day in self._calendar if day <= target]
        if past:
            return past[-1]
        return self._calendar[0]

    def get_next_trading_day(self, trading_day: date) -> date:
        if not self._calendar:
            return trading_day
        for day in self._calendar:
            if day > trading_day:
                return day
        return trading_day

    def is_market_closed(self, as_of: datetime | None = None) -> bool:
        if not self._calendar:
            return False
        target = _as_date(as_of)
        return target not in self._calendar


def _run_dir(data_dir: Path, run_id: str) -> Path:
    return Path(data_dir) / "forward" / "runs" / run_id


def _active_run_path(data_dir: Path) -> Path:
    return Path(data_dir) / "forward" / "active_run.json"


def _write_active_run(data_dir: Path, run_id: str, created_at: str) -> None:
    path = _active_run_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"run_id": run_id, "created_at": created_at}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_active_run(data_dir: Path) -> str | None:
    path = _active_run_path(data_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    run_id = payload.get("run_id")
    return str(run_id) if run_id else None


def start_forward_run(
    request: ForwardTestRequest,
    data_dir: Path,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_backtest_request(request)
    universe = build_universe_from_request(request, data_dir)
    data_store = HistoryDataStore(
        data_dir,
        universe,
        start_date=request.test.start_date,
        end_date=request.test.end_date,
    )
    adapter = HistoryMarketDataAdapter(data_store)
    rebalance_config = build_rebalance_config(resolved.resolved_config)
    initial_cash = request.portfolio.account_equity or ForwardEngineConfig().initial_cash
    engine_config = ForwardEngineConfig(initial_cash=float(initial_cash or 1_000_000.0))

    run_id = run_id or f"fwd-{uuid.uuid4().hex[:10]}"
    run_dir = _run_dir(data_dir, run_id)
    state_store = JsonStateStore(run_dir)
    engine = ForwardTestEngine(
        market_data=adapter,
        state_store=state_store,
        resolved_config=resolved.resolved_config,
        rebalance_config=rebalance_config,
        engine_config=engine_config,
    )
    state = engine._load_state()
    created_at = _iso_now()
    run_info = {
        "run_id": run_id,
        "status": "initialized",
        "created_at": created_at,
        "config_hash": state.config_hash,
        "warnings": list(resolved.warnings),
        "state": _state_to_dict(state),
    }
    metadata = {
        "run_id": run_id,
        "created_at": created_at,
        "config_hash": state.config_hash,
        "request": request.model_dump(mode="python"),
        "resolved_config": resolved.resolved_config,
        "warnings": list(resolved.warnings),
        "engine_config": asdict(engine_config),
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    _write_active_run(data_dir, run_id, created_at)
    return run_info


def load_forward_status(
    data_dir: Path,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    if run_id is None:
        run_id = _load_active_run(data_dir)
    if not run_id:
        raise ValueError("no_active_run")
    run_dir = _run_dir(data_dir, run_id)
    if not run_dir.exists():
        raise ValueError("run_not_found")
    state_store = JsonStateStore(run_dir)
    state = state_store.load()
    if state is None:
        raise ValueError("state_not_found")
    status = {
        "run_id": run_id,
        "status": "ready",
        "state": _state_to_dict(state),
        "last_trade": _read_last_jsonl(state_store.trades_path),
        "last_equity": _read_last_jsonl(state_store.equity_path),
        "last_alert": _read_last_jsonl(state_store.alerts_path),
    }
    run_meta_path = run_dir / "run.json"
    if run_meta_path.exists():
        try:
            status["run_meta"] = json.loads(run_meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return status
