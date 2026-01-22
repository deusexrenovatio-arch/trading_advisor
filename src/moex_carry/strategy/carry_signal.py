from __future__ import annotations

from moex_carry.strategy.models import SignalDecision


def carry_signal(implied_rate_net: float, required_rate: float, buffer: float) -> SignalDecision:
    if implied_rate_net >= required_rate + buffer:
        return SignalDecision(
            action="enter",
            direction="cash_and_carry",
            score=implied_rate_net - required_rate,
            reasons=["implied_rate_above_required"],
            metrics={"implied_rate_net": implied_rate_net, "required_rate": required_rate},
        )
    if implied_rate_net <= required_rate - buffer:
        return SignalDecision(
            action="enter",
            direction="reverse",
            score=required_rate - implied_rate_net,
            reasons=["implied_rate_below_required"],
            metrics={"implied_rate_net": implied_rate_net, "required_rate": required_rate},
        )
    return SignalDecision(
        action="hold",
        direction=None,
        score=0.0,
        reasons=["implied_rate_neutral"],
        metrics={"implied_rate_net": implied_rate_net, "required_rate": required_rate},
    )
