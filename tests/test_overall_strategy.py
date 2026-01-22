from moex_carry.strategy.overall_strategy import aggregate_strategy_signals
from moex_carry.strategy.strategy_signal import (
    RuleEvaluation,
    StrategyAllocation,
    StrategySignal,
)


def _signal(
    *,
    strategy_id: str,
    action: str,
    confidence: float = 0.5,
    strategy_type: str = "arbitrage",
    allocations: list[StrategyAllocation] | None = None,
    rules: list[RuleEvaluation] | None = None,
) -> StrategySignal:
    return StrategySignal(
        strategy_id=strategy_id,
        strategy_type=strategy_type,
        cadence="weekly",
        horizon="short",
        action=action,
        confidence=confidence,
        intent_allocations=allocations or [],
        rules_evaluated=rules or [],
    )


def test_aggregate_empty_signals():
    result = aggregate_strategy_signals([], {"arbitrage": 1.0}, min_confidence=0.2, max_signals=3)
    assert result.action == "hold"
    assert "no_eligible_signals" in result.warnings


def test_blocked_signal_from_rules():
    rules = [RuleEvaluation(rule_id="risk_gate", result=False, severity="block")]
    signal = _signal(strategy_id="spread_v1", action="enter", confidence=0.9, rules=rules)
    result = aggregate_strategy_signals([signal], {"arbitrage": 1.0}, min_confidence=0.2, max_signals=3)
    assert result.action == "hold"
    assert "spread_v1" in result.blocked_strategies
    assert any("rule_blocked" in reason for reason in result.reasons)


def test_exit_signal_has_priority():
    enter_signal = _signal(strategy_id="s1", action="enter", confidence=0.8)
    exit_signal = _signal(strategy_id="s2", action="exit", confidence=0.8)
    result = aggregate_strategy_signals(
        [enter_signal, exit_signal],
        {"arbitrage": 1.0},
        min_confidence=0.2,
        max_signals=3,
    )
    assert result.action == "exit"


def test_allocation_weighting():
    allocation = StrategyAllocation(instrument="SBER", side="long", target_weight=0.5)
    signal = _signal(
        strategy_id="spread_v1",
        action="enter",
        confidence=0.9,
        allocations=[allocation],
    )
    result = aggregate_strategy_signals(
        [signal],
        {"arbitrage": 0.5, "fundamental": 0.5},
        min_confidence=0.2,
        max_signals=3,
    )
    assert result.allocations
    assert result.allocations[0]["instrument"] == "SBER"
    assert abs(result.allocations[0]["target_weight"] - 0.25) < 1e-6
