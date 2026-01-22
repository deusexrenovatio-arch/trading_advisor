from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

StrategyType = Literal["fundamental", "speculative", "arbitrage"]
SignalAction = Literal["enter", "exit", "hold"]
AllocationSide = Literal["long", "short", "flat"]
RuleSeverity = Literal["info", "warn", "block"]


@dataclass
class StrategyAllocation:
    instrument: str
    side: AllocationSide
    target_weight: float | None = None
    quantity: float | None = None


@dataclass
class RuleEvaluation:
    rule_id: str
    result: bool
    severity: RuleSeverity = "info"
    description: str | None = None


@dataclass
class StrategySignal:
    strategy_id: str
    strategy_type: StrategyType
    cadence: str
    horizon: str
    action: SignalAction
    confidence: float
    expected_return: float | None = None
    risk_estimate: float | None = None
    liquidity_score: float | None = None
    instruments: list[str] = field(default_factory=list)
    intent_allocations: list[StrategyAllocation] = field(default_factory=list)
    rules_evaluated: list[RuleEvaluation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
