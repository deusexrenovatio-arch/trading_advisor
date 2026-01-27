from __future__ import annotations

import hashlib
import json
import math
import threading
from collections import OrderedDict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from moex_carry.backtest_v2 import BacktestPrecomputed, BacktestReport, precompute_backtest_data, run_backtest_v2
from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.data.history_store import HistoryDataStore
from moex_carry.domain.models import ContractSpec, Instrument
from moex_carry.domain.portfolio import PairSpec
from moex_carry.portfolio.rebalance_controller import pair_key
from moex_carry.selection.universe import build_pair_mappings

_PRECOMPUTE_CACHE: "OrderedDict[str, BacktestPrecomputed]" = OrderedDict()
_PRECOMPUTE_LOCK = threading.Lock()
_PRECOMPUTE_CACHE_MAX = 4


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_get(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row.get(key)
        lower_key = key.lower()
        if lower_key in row:
            return row.get(lower_key)
        upper_key = key.upper()
        if upper_key in row:
            return row.get(upper_key)
    return None


def _parse_contract_specs(futures_df: pd.DataFrame) -> list[ContractSpec]:
    specs: list[ContractSpec] = []
    if futures_df.empty:
        return specs
    for row in futures_df.to_dict("records"):
        secid = _row_get(row, "SECID")
        asset = _row_get(row, "ASSETCODE")
        if not secid or not asset:
            continue
        expiry_raw = _row_get(row, "LASTTRADEDATE", "LASTTRADINGDAY")
        expiry = pd.to_datetime(expiry_raw, errors="coerce").date() if expiry_raw else None
        if not expiry:
            continue
        lot_raw = _row_get(row, "LOTVOLUME", "LOTSIZE", "LOT") or 1
        multiplier_raw = _row_get(row, "MULTIPLIER") or 1
        price_step_raw = _row_get(row, "MINSTEP") or 1
        specs.append(
            ContractSpec(
                secid=str(secid),
                asset_code=str(asset),
                expiry=expiry,
                lot_size=float(lot_raw),
                price_step=float(price_step_raw),
                multiplier=float(multiplier_raw),
            )
        )
    return specs


def _parse_instruments(shares_df: pd.DataFrame) -> list[Instrument]:
    instruments: list[Instrument] = []
    if shares_df.empty:
        return instruments
    for row in shares_df.to_dict("records"):
        secid = _row_get(row, "SECID")
        if not secid:
            continue
        instruments.append(
            Instrument(
                secid=str(secid),
                name=str(_row_get(row, "SHORTNAME", "SECNAME") or secid),
                instrument_type="stock",
                currency=str(_row_get(row, "CURRENCYID") or "RUB"),
                board=_row_get(row, "BOARDID"),
            )
        )
    return instruments


def _normalize_symbols(values: Iterable[str]) -> set[str]:
    cleaned: set[str] = set()
    for value in values:
        if not value:
            continue
        cleaned.add(str(value).strip().upper())
    return cleaned


def _parse_pair_ids(values: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for raw in values:
        if not raw:
            continue
        value = str(raw).strip()
        if not value:
            continue
        stock = None
        future = None
        for sep in ("|", "/", ":"):
            if sep in value:
                stock, future = value.split(sep, 1)
                break
        if stock is None or future is None:
            continue
        stock = stock.strip().upper()
        future = future.strip().upper()
        if stock and future:
            result.add(pair_key(stock, future))
    return result


def build_universe_from_request(request: BacktestRequest, data_dir: Path) -> list[PairSpec]:
    raw_dir = Path(data_dir) / "raw"
    shares_path = raw_dir / "shares.csv"
    futures_path = raw_dir / "futures.csv"
    if not shares_path.exists() or not futures_path.exists():
        missing = [str(path) for path in (shares_path, futures_path) if not path.exists()]
        raise ValueError(f"Missing raw data: {', '.join(missing)}")

    shares_df = pd.read_csv(shares_path)
    futures_df = pd.read_csv(futures_path)
    instruments = _parse_instruments(shares_df)
    futures_specs = _parse_contract_specs(futures_df)
    if not instruments or not futures_specs:
        raise ValueError("Unable to build universe from raw shares/futures data")

    mappings = build_pair_mappings(instruments, futures_specs)
    include_stocks = _normalize_symbols(request.universe.include_stocks)
    include_futures = _normalize_symbols(request.universe.include_futures)
    allowed_months = set(request.universe.allowed_expiry_months or [])
    allowed_years = set(request.universe.allowed_expiry_years or [])
    allowed_pairs = _parse_pair_ids(request.universe.pair_ids)

    filtered: list[PairSpec] = []
    spec_map = {spec.secid: spec for spec in futures_specs}
    for mapping in mappings:
        stock = mapping.stock_secid.upper()
        future = mapping.future_secid.upper()
        if include_stocks and stock not in include_stocks:
            continue
        if include_futures and future not in include_futures:
            continue
        if allowed_months and mapping.expiry.month not in allowed_months:
            continue
        if allowed_years and mapping.expiry.year not in allowed_years:
            continue
        if allowed_pairs and pair_key(stock, future) not in allowed_pairs:
            continue
        spec = spec_map.get(mapping.future_secid)
        if spec is None:
            continue
        filtered.append(
            PairSpec(
                stock_secid=stock,
                future_secid=future,
                expiry=mapping.expiry,
                lot_size=spec.lot_size,
                multiplier=spec.multiplier,
                tick_size=spec.price_step,
                metadata={"pair_id": pair_key(stock, future)},
            )
        )

    if not filtered:
        raise ValueError("Universe filter returned zero pairs")

    filtered.sort(key=lambda item: (item.expiry or date.max, item.stock_secid, item.future_secid))
    max_pairs = request.universe.max_pairs
    if max_pairs is not None and max_pairs > 0:
        filtered = filtered[: max_pairs]
    return filtered


def _cache_key(request: BacktestRequest, universe: Iterable[PairSpec], data_dir: Path) -> str:
    payload = {
        "request": request.model_dump(mode="python"),
        "universe": [
            {
                "stock": pair.stock_secid,
                "future": pair.future_secid,
                "expiry": pair.expiry.isoformat() if pair.expiry else None,
                "lot_size": pair.lot_size,
                "multiplier": pair.multiplier,
                "tick_size": pair.tick_size,
            }
            for pair in universe
        ],
        "data_dir": str(data_dir),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _get_precomputed(
    request: BacktestRequest,
    universe: list[PairSpec],
    data_store: HistoryDataStore,
) -> BacktestPrecomputed:
    cache_key = _cache_key(request, universe, data_store.data_dir)
    with _PRECOMPUTE_LOCK:
        cached = _PRECOMPUTE_CACHE.get(cache_key)
        if cached is not None:
            _PRECOMPUTE_CACHE.move_to_end(cache_key)
            return cached
    precomputed = precompute_backtest_data(request, universe, data_store)
    with _PRECOMPUTE_LOCK:
        _PRECOMPUTE_CACHE[cache_key] = precomputed
        if len(_PRECOMPUTE_CACHE) > _PRECOMPUTE_CACHE_MAX:
            _PRECOMPUTE_CACHE.popitem(last=False)
    return precomputed


def run_backtest_v2_cached(
    request: BacktestRequest,
    data_dir: Path,
    *,
    precompute: bool | None = None,
) -> BacktestReport:
    universe = build_universe_from_request(request, data_dir)
    data_store = HistoryDataStore(
        data_dir,
        universe,
        start_date=request.test.start_date,
        end_date=request.test.end_date,
    )
    precomputed = None
    if precompute is not False:
        precomputed = _get_precomputed(request, universe, data_store)
    return run_backtest_v2(
        request=request,
        universe=universe,
        data_store=data_store,
        precomputed=precomputed,
    )


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or not math.isfinite(value):
            return None
    if isinstance(value, dict):
        return {key: _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def _serialize_config(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return value


def serialize_backtest_report(report: BacktestReport) -> dict[str, Any]:
    trades = [
        {
            "pair_id": trade.pair_id,
            "stock_secid": trade.stock_secid,
            "future_secid": trade.future_secid,
            "direction": trade.direction,
            "entry_date": trade.entry_date.isoformat(),
            "exit_date": trade.exit_date.isoformat(),
            "entry_price_stock": trade.entry_price_stock,
            "entry_price_fut": trade.entry_price_fut,
            "exit_price_stock": trade.exit_price_stock,
            "exit_price_fut": trade.exit_price_fut,
            "quantity_stock": trade.quantity_stock,
            "quantity_fut": trade.quantity_fut,
            "pnl": trade.pnl,
            "hold_days": trade.hold_days,
            "exit_reason": trade.exit_reason,
        }
        for trade in report.trades
    ]
    equity_curve = [
        {
            "date": point.date.isoformat(),
            "equity": point.equity,
            "cash": point.cash,
            "drawdown": point.drawdown,
            "turnover": point.turnover,
            "positions": point.positions,
        }
        for point in report.equity_curve
    ]
    payload = {
        "summary_metrics": report.summary_metrics,
        "equity_curve": equity_curve,
        "trades": trades,
        "resolved_config": _serialize_config(report.resolved_config),
        "warnings": list(report.warnings),
    }
    return _sanitize_value(payload)
