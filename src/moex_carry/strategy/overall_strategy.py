from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from moex_carry.strategy.strategy_signal import (
    RuleEvaluation,
    SignalAction,
    StrategyAllocation,
    StrategySignal,
)


@dataclass
class AggregationResult:
    action: SignalAction
    score: float
    allocations: list[dict[str, object]]
    reasons: list[str]
    warnings: list[str]
    blocked_strategies: list[str]
    used_strategies: list[str]
    weights: dict[str, float]


def aggregate_strategy_signals(
    signals: Sequence[StrategySignal],
    weights: Mapping[str, float],
    min_confidence: float,
    max_signals: int,
) -> AggregationResult:
    normalized_weights = _normalize_weights(weights)
    blocked: list[str] = []
    used: list[str] = []
    reasons: list[str] = []
    warnings: list[str] = []

    candidates: list[StrategySignal] = []
    for signal in signals:
        weight = normalized_weights.get(signal.strategy_type, 0.0)
        if weight <= 0:
            blocked.append(signal.strategy_id)
            reasons.append(f"{signal.strategy_id}:weight_zero")
            continue
        block_reason = _block_reason(signal, min_confidence)
        if block_reason:
            blocked.append(signal.strategy_id)
            reasons.append(f"{signal.strategy_id}:{block_reason}")
            continue
        candidates.append(signal)

    ranked = sorted(
        candidates,
        key=lambda item: _signal_score(item, normalized_weights),
        reverse=True,
    )
    if max_signals > 0:
        ranked = ranked[:max_signals]

    used = [signal.strategy_id for signal in ranked]
    action = _aggregate_action(ranked)
    allocations = _merge_allocations(ranked, normalized_weights)
    score = sum(_signal_score(signal, normalized_weights) for signal in ranked)
    if not ranked:
        warnings.append("no_eligible_signals")

    return AggregationResult(
        action=action,
        score=score,
        allocations=allocations,
        reasons=reasons,
        warnings=warnings,
        blocked_strategies=blocked,
        used_strategies=used,
        weights=normalized_weights,
    )


def strategy_signal_to_dict(signal: StrategySignal) -> dict[str, object]:
    payload: dict[str, object] = {
        "strategy_id": signal.strategy_id,
        "strategy_type": signal.strategy_type,
        "cadence": signal.cadence,
        "horizon": signal.horizon,
        "action": signal.action,
        "confidence": signal.confidence,
        "instruments": list(signal.instruments),
        "intent_allocations": [
            _allocation_to_dict(alloc) for alloc in signal.intent_allocations
        ],
        "rules_evaluated": [_rule_to_dict(rule) for rule in signal.rules_evaluated],
        "warnings": list(signal.warnings),
    }
    if signal.expected_return is not None:
        payload["expected_return"] = signal.expected_return
    if signal.risk_estimate is not None:
        payload["risk_estimate"] = signal.risk_estimate
    if signal.liquidity_score is not None:
        payload["liquidity_score"] = signal.liquidity_score
    if signal.metadata:
        payload["metadata"] = dict(signal.metadata)
    return payload


def _allocation_to_dict(allocation: StrategyAllocation) -> dict[str, object]:
    payload: dict[str, object] = {
        "instrument": allocation.instrument,
        "side": allocation.side,
    }
    if allocation.target_weight is not None:
        payload["target_weight"] = allocation.target_weight
    if allocation.quantity is not None:
        payload["quantity"] = allocation.quantity
    return payload


def _rule_to_dict(rule: RuleEvaluation) -> dict[str, object]:
    payload: dict[str, object] = {
        "rule_id": rule.rule_id,
        "result": rule.result,
        "severity": rule.severity,
    }
    if rule.description:
        payload["description"] = rule.description
    return payload


def _normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    raw = {key: float(value) for key, value in weights.items() if value is not None}
    total = sum(value for value in raw.values() if value > 0)
    if total <= 0:
        return {"fundamental": 1 / 3, "speculative": 1 / 3, "arbitrage": 1 / 3}
    return {key: value / total for key, value in raw.items() if value > 0}


def _block_reason(signal: StrategySignal, min_confidence: float) -> str | None:
    if signal.confidence < min_confidence:
        return "low_confidence"
    if _has_blocking_rule(signal.rules_evaluated):
        return "rule_blocked"
    return None


def _has_blocking_rule(rules: Iterable[RuleEvaluation]) -> bool:
    for rule in rules:
        if rule.severity == "block" and rule.result is False:
            return True
    return False


def _signal_score(signal: StrategySignal, weights: Mapping[str, float]) -> float:
    weight = weights.get(signal.strategy_type, 0.0)
    base = signal.confidence
    if signal.expected_return is not None:
        base *= signal.expected_return
    return weight * base


def _aggregate_action(signals: Sequence[StrategySignal]) -> SignalAction:
    if any(signal.action == "exit" for signal in signals):
        return "exit"
    if any(signal.action == "enter" for signal in signals):
        return "enter"
    return "hold"


def _merge_allocations(
    signals: Sequence[StrategySignal],
    weights: Mapping[str, float],
) -> list[dict[str, object]]:
    merged: dict[tuple[str, str], dict[str, object]] = {}
    for signal in signals:
        weight = weights.get(signal.strategy_type, 0.0)
        for alloc in signal.intent_allocations:
            if weight <= 0:
                continue
            key = (alloc.instrument, alloc.side)
            entry = merged.setdefault(
                key,
                {
                    "instrument": alloc.instrument,
                    "side": alloc.side,
                    "target_weight": None,
                    "quantity": None,
                    "rationale": [],
                },
            )
            if alloc.target_weight is not None:
                current = entry["target_weight"] or 0.0
                entry["target_weight"] = current + alloc.target_weight * weight
            if alloc.quantity is not None:
                current_qty = entry["quantity"] or 0.0
                entry["quantity"] = current_qty + alloc.quantity * weight
            rationale = entry["rationale"]
            if isinstance(rationale, list):
                rationale.append(signal.strategy_id)
    allocations: list[dict[str, object]] = []
    for entry in merged.values():
        if not entry.get("rationale"):
            entry.pop("rationale", None)
        else:
            entry["rationale"] = ", ".join(entry["rationale"])
        if entry.get("target_weight") is None:
            entry.pop("target_weight", None)
        if entry.get("quantity") is None:
            entry.pop("quantity", None)
        allocations.append(entry)
    return allocations
