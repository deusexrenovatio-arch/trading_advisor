from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from moex_carry.strategy.models import SignalDecision


@dataclass
class SpreadCarryState:
    position: Optional[str] = None
    entry_spread_pct_exec: Optional[float] = None
    entry_date: Optional[date] = None
    hold_days: int = 0


def step_spread_carry_alpha(
    state: SpreadCarryState,
    *,
    as_of: date,
    floor_pass: bool,
    liquidity_pass: bool,
    spread_pct_entry_exec: float,
    spread_pct_exit_exec: float,
    tp_net: float,
    sl_net: float,
    dte: int,
    min_dte_entry: int,
    close_buffer_days: int,
    h_max_days: int,
    entry_filter_ok: bool = True,
    direction: str = "cash_and_carry",
) -> SignalDecision:
    reasons: list[str] = []
    metrics = {
        "spread_pct_entry_exec": spread_pct_entry_exec,
        "spread_pct_exit_exec": spread_pct_exit_exec,
        "tp_net": tp_net,
        "sl_net": sl_net,
        "dte": dte,
        "hold_days": state.hold_days,
    }

    if state.position is None:
        if not floor_pass:
            reasons.append("floor_fail")
        if not liquidity_pass:
            reasons.append("liquidity_fail")
        if not entry_filter_ok:
            reasons.append("entry_filter_fail")
        if dte < min_dte_entry:
            reasons.append("dte_too_low")
        if floor_pass and liquidity_pass and entry_filter_ok and dte >= min_dte_entry:
            state.position = direction
            state.entry_spread_pct_exec = spread_pct_entry_exec
            state.entry_date = as_of
            state.hold_days = 0
            return SignalDecision(
                action="enter",
                direction=direction,
                score=0.0,
                reasons=["enter_ok"],
                metrics=metrics,
            )
        return SignalDecision(
            action="hold",
            direction=None,
            score=0.0,
            reasons=reasons or ["hold"],
            metrics=metrics,
        )

    state.hold_days += 1
    pnl_spread = spread_pct_exit_exec - (state.entry_spread_pct_exec or 0.0)
    metrics["pnl_spread_pct"] = pnl_spread
    metrics["hold_days"] = state.hold_days

    if pnl_spread >= tp_net:
        reasons.append("tp")
    elif pnl_spread <= -sl_net:
        reasons.append("sl")
    elif h_max_days > 0 and state.hold_days >= h_max_days:
        reasons.append("time")
    elif dte <= close_buffer_days:
        reasons.append("expiry")

    if reasons:
        state.position = None
        state.entry_spread_pct_exec = None
        state.entry_date = None
        state.hold_days = 0
        return SignalDecision(
            action="exit",
            direction=None,
            score=0.0,
            reasons=reasons,
            metrics=metrics,
        )

    return SignalDecision(
        action="hold",
        direction=None,
        score=0.0,
        reasons=["hold"],
        metrics=metrics,
    )
