from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from moex_carry.contracts.strategy_test import BacktestRequest


@dataclass
class ResolvedBacktestConfig:
    resolved_config: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def resolve_backtest_request(request: BacktestRequest) -> ResolvedBacktestConfig:
    warnings: list[str] = []
    cost_stress_mult = _coerce_float(request.test.cost_stress_mult, "cost_stress_mult", allow_none=True)
    if cost_stress_mult is None:
        cost_stress_mult = 1.0
    if cost_stress_mult <= 0:
        raise ValueError("cost_stress_mult must be > 0")

    _validate_request(request)

    resolved = request.model_dump(mode="python")
    resolved["test"]["cost_stress_mult"] = float(cost_stress_mult)

    auto_value = _compute_auto_dollarvol(request)
    resolved["liquidity"]["min_avg_dollarvol_stock"] = _resolve_auto_value(
        request.liquidity.min_avg_dollarvol_stock,
        auto_value,
        "liquidity.min_avg_dollarvol_stock",
        warnings,
    )
    resolved["liquidity"]["min_avg_dollarvol_fut"] = _resolve_auto_value(
        request.liquidity.min_avg_dollarvol_fut,
        auto_value,
        "liquidity.min_avg_dollarvol_fut",
        warnings,
    )

    _apply_cost_stress(resolved, cost_stress_mult)

    return ResolvedBacktestConfig(resolved_config=resolved, warnings=warnings)


def _coerce_float(value: Any, name: str, allow_none: bool = False) -> float | None:
    if value is None:
        return None if allow_none else 0.0
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"{name} must be a number")


def _is_auto(value: Any) -> bool:
    return isinstance(value, str) and value.upper() == "AUTO"


def _resolve_auto_value(
    value: Any,
    auto_default: float | None,
    label: str,
    warnings: list[str],
) -> float | None:
    if _is_auto(value):
        if auto_default is None or auto_default <= 0:
            warnings.append(f"{label}: AUTO resolved to 0.0 (missing inputs)")
            return 0.0
        resolved = float(auto_default)
        warnings.append(f"{label}: AUTO resolved to {resolved:.6g}")
        return resolved
    if value is None:
        return None
    return float(value)


def _compute_auto_dollarvol(request: BacktestRequest) -> float | None:
    liquidity = request.liquidity
    portfolio = request.portfolio
    universe = request.universe

    position_notional: float | None = None
    if portfolio.capital_allocated_per_trade is not None:
        position_notional = float(portfolio.capital_allocated_per_trade)
    elif portfolio.max_gross_notional is not None:
        position_notional = float(portfolio.max_gross_notional)
        if universe.max_pairs:
            position_notional = position_notional / max(int(universe.max_pairs), 1)
    elif portfolio.account_equity is not None:
        position_notional = float(portfolio.account_equity)

    participation_rate = liquidity.participation_rate
    max_days = liquidity.max_days_to_exit
    if (
        position_notional is None
        or participation_rate is None
        or max_days is None
        or participation_rate <= 0
        or max_days <= 0
    ):
        return None
    return float(position_notional) / (float(participation_rate) * float(max_days))


def _apply_cost_stress(resolved: dict[str, Any], mult: float) -> None:
    costs = resolved.get("costs", {})
    execution = resolved.get("execution", {})

    cost_fields = [
        "stock_commission_bps",
        "futures_commission_bps",
        "exchange_fee_bps",
        "fee_stock_per_share",
        "fee_stock_bps",
        "fee_fut_per_contract",
    ]
    for field in cost_fields:
        value = costs.get(field)
        if value is not None:
            costs[field] = float(value) * mult

    slippage_fields = [
        "half_spread_bps",
        "slip_stock_bps",
        "slip_fut_bps",
        "slip_fut_ticks",
    ]
    for field in slippage_fields:
        value = execution.get(field)
        if value is not None:
            execution[field] = float(value) * mult

    resolved["costs"] = costs
    resolved["execution"] = execution


def _validate_request(request: BacktestRequest) -> None:
    test_cfg = request.test
    strategy = request.strategy
    liquidity = request.liquidity
    allocation = request.allocation
    rebalance = request.rebalance
    portfolio = request.portfolio

    if test_cfg.start_date and test_cfg.end_date and test_cfg.start_date > test_cfg.end_date:
        raise ValueError("test.start_date must be <= test.end_date")

    w_floor = float(strategy.w_floor)
    w_alpha = float(strategy.w_alpha)
    if abs((w_floor + w_alpha) - 1.0) > 1e-6:
        raise ValueError("strategy.w_floor + strategy.w_alpha must equal 1.0")

    _require_range(liquidity.participation_rate, "liquidity.participation_rate", min_value=0.0, max_value=1.0)
    _require_positive(liquidity.participation_rate, "liquidity.participation_rate", allow_zero=False)
    _require_range(strategy.w_floor, "strategy.w_floor", min_value=0.0, max_value=1.0)
    _require_range(strategy.w_alpha, "strategy.w_alpha", min_value=0.0, max_value=1.0)
    _require_positive(strategy.w_liq, "strategy.w_liq", allow_zero=True, allow_none=True)
    _require_positive(strategy.w_event, "strategy.w_event", allow_zero=True, allow_none=True)
    _require_positive(strategy.k_event, "strategy.k_event", allow_zero=True, allow_none=True)
    _require_range(strategy.TP_pct, "strategy.TP_pct", min_value=0.0, max_value=1.0)
    _require_range(strategy.SL_pct, "strategy.SL_pct", min_value=0.0, max_value=1.0)
    _require_range(allocation.min_trade_weight, "allocation.min_trade_weight", min_value=0.0, max_value=1.0)
    _require_range(rebalance.threshold_pct, "rebalance.threshold_pct", min_value=0.0, max_value=1.0)
    _require_range(allocation.max_turnover_pct, "allocation.max_turnover_pct", min_value=0.0, max_value=1.0)

    _require_positive(portfolio.margin_proxy, "portfolio.margin_proxy", allow_zero=False)
    _require_positive(strategy.H_max_days, "strategy.H_max_days", allow_zero=False)
    _require_positive(strategy.z_window, "strategy.z_window", allow_zero=False)
    _require_positive(strategy.min_DTE_entry, "strategy.min_DTE_entry", allow_zero=False)
    _require_positive(strategy.close_buffer_days, "strategy.close_buffer_days", allow_zero=True)
    _require_positive(strategy.roll_trigger_days, "strategy.roll_trigger_days", allow_zero=True)
    _require_positive(liquidity.max_days_to_exit, "liquidity.max_days_to_exit", allow_zero=False, allow_none=True)
    _require_positive(portfolio.max_contracts_per_pair, "portfolio.max_contracts_per_pair", allow_zero=False, allow_none=True)
    _require_positive(portfolio.account_equity, "portfolio.account_equity", allow_zero=False, allow_none=True)

    _validate_min_max_pairs(request.model_dump(mode="python"))


def _require_positive(
    value: Any,
    name: str,
    *,
    allow_zero: bool,
    allow_none: bool = False,
) -> None:
    if value is None:
        if allow_none:
            return
        raise ValueError(f"{name} must be set")
    numeric = float(value)
    if allow_zero and numeric < 0:
        raise ValueError(f"{name} must be >= 0")
    if not allow_zero and numeric <= 0:
        raise ValueError(f"{name} must be > 0")


def _require_range(
    value: Any,
    name: str,
    *,
    min_value: float,
    max_value: float,
) -> None:
    if value is None:
        raise ValueError(f"{name} must be set")
    numeric = float(value)
    if numeric < min_value or numeric > max_value:
        raise ValueError(f"{name} must be between {min_value} and {max_value}")


def _validate_min_max_pairs(config: dict[str, Any], path: str = "") -> None:
    if not isinstance(config, dict):
        return
    for key, value in config.items():
        if isinstance(value, dict):
            _validate_min_max_pairs(value, path=f"{path}{key}.")
    for key, value in config.items():
        if not isinstance(key, str) or not key.startswith("min_"):
            continue
        max_key = f"max_{key[4:]}"
        if max_key not in config:
            continue
        min_value = config.get(key)
        max_value = config.get(max_key)
        if min_value is None or max_value is None:
            continue
        if float(min_value) > float(max_value):
            raise ValueError(f"{path}{key} must be <= {path}{max_key}")
