from __future__ import annotations

from typing import Sequence

from moex_carry.strategy.carry_signal import carry_signal
from moex_carry.strategy.event_filters import apply_event_filters
from moex_carry.strategy.models import SignalDecision
from moex_carry.strategy.stat_signal import stat_signal


def build_portfolio_proposal(
    signal_action: str,
    signal_direction: str | None,
    stock_secid: str,
    future_secid: str,
    weight: float = 0.5,
) -> dict[str, list[dict[str, object]]]:
    allocations: list[dict[str, object]] = []
    if signal_action == "enter":
        if signal_direction == "cash_and_carry":
            allocations = [
                {"instrument": stock_secid, "side": "long", "target_weight": weight},
                {"instrument": future_secid, "side": "short", "target_weight": weight},
            ]
        elif signal_direction == "reverse":
            allocations = [
                {"instrument": stock_secid, "side": "short", "target_weight": weight},
                {"instrument": future_secid, "side": "long", "target_weight": weight},
            ]
    return {"allocations": allocations}


def generate_signal(
    spread_series: Sequence[float],
    implied_rate_net: float,
    required_rate: float,
    days_to_expiry: int,
    days_to_exdiv: int,
    z_window: int,
    z_min_window: int,
    z_entry: float,
    z_exit: float,
    implied_rate_buffer: float,
    min_days_to_expiry: int,
    min_days_to_exdiv: int,
) -> SignalDecision:
    event_filter = apply_event_filters(
        days_to_expiry, days_to_exdiv, min_days_to_expiry, min_days_to_exdiv
    )
    if not event_filter.allowed:
        return SignalDecision(
            action="hold",
            direction=None,
            score=0.0,
            reasons=["event_filter_blocked", *event_filter.reasons],
            metrics={},
        )

    stat_decision = stat_signal(spread_series, z_window, z_entry, z_exit, min_window=z_min_window)
    carry_decision = carry_signal(implied_rate_net, required_rate, implied_rate_buffer)

    reasons = list(set(stat_decision.reasons + carry_decision.reasons))
    metrics = {**stat_decision.metrics, **carry_decision.metrics}

    if stat_decision.action == "enter" and carry_decision.action == "enter":
        if stat_decision.direction == carry_decision.direction:
            return SignalDecision(
                action="enter",
                direction=stat_decision.direction,
                score=(stat_decision.score + carry_decision.score) / 2,
                reasons=reasons,
                metrics=metrics,
            )
        return SignalDecision(
            action="hold",
            direction=None,
            score=0.0,
            reasons=reasons + ["direction_conflict"],
            metrics=metrics,
        )

    if stat_decision.action == "exit":
        return SignalDecision(
            action="exit",
            direction=None,
            score=stat_decision.score,
            reasons=reasons,
            metrics=metrics,
        )

    if stat_decision.action == "enter" or carry_decision.action == "enter":
        missing = []
        if stat_decision.action != "enter":
            missing.append("stat_not_confirmed")
        if carry_decision.action != "enter":
            missing.append("carry_not_confirmed")
        return SignalDecision(
            action="hold",
            direction=None,
            score=0.0,
            reasons=reasons + missing,
            metrics=metrics,
        )

    return SignalDecision(
        action="hold",
        direction=None,
        score=0.0,
        reasons=reasons,
        metrics=metrics,
    )
