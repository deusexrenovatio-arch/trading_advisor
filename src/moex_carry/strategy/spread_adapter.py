from __future__ import annotations

from typing import Any, Iterable, Mapping

from moex_carry.strategy.strategy_signal import (
    AllocationSide,
    RuleEvaluation,
    RuleSeverity,
    SignalAction,
    StrategyAllocation,
    StrategySignal,
    StrategyType,
)

_ALLOWED_TYPES: set[StrategyType] = {"fundamental", "speculative", "arbitrage"}
_ALLOWED_ACTIONS: set[SignalAction] = {"enter", "exit", "hold"}
_ALLOWED_SIDES: set[AllocationSide] = {"long", "short", "flat"}
_ALLOWED_SEVERITIES: set[RuleSeverity] = {"info", "warn", "block"}


def normalize_spread_payload(payload: Mapping[str, Any]) -> StrategySignal | None:
    strategy_id = str(payload.get("strategy_id", "")).strip()
    if not strategy_id:
        return None

    raw_type = str(payload.get("strategy_type", "arbitrage")).strip()
    strategy_type: StrategyType = raw_type if raw_type in _ALLOWED_TYPES else "arbitrage"

    raw_action = str(payload.get("action", "hold")).strip()
    action: SignalAction = raw_action if raw_action in _ALLOWED_ACTIONS else "hold"

    cadence = str(payload.get("cadence", "unspecified"))
    horizon = str(payload.get("horizon", "unspecified"))
    confidence = _to_float(payload.get("confidence"), default=0.0)

    return StrategySignal(
        strategy_id=strategy_id,
        strategy_type=strategy_type,
        cadence=cadence,
        horizon=horizon,
        action=action,
        confidence=confidence,
        expected_return=_to_float(payload.get("expected_return")),
        risk_estimate=_to_float(payload.get("risk_estimate")),
        liquidity_score=_to_float(payload.get("liquidity_score")),
        instruments=_to_str_list(payload.get("instruments")),
        intent_allocations=_parse_allocations(payload.get("intent_allocations")),
        rules_evaluated=_parse_rules(payload.get("rules_evaluated")),
        warnings=_to_str_list(payload.get("warnings")),
        metadata=_to_dict(payload.get("metadata")),
    )


def load_spread_signals(raw_payloads: Iterable[Mapping[str, Any]] | None = None) -> list[StrategySignal]:
    if not raw_payloads:
        return []
    signals: list[StrategySignal] = []
    for payload in raw_payloads:
        signal = normalize_spread_payload(payload)
        if signal:
            signals.append(signal)
    return signals


def _parse_allocations(raw: Any) -> list[StrategyAllocation]:
    if not isinstance(raw, list):
        return []
    allocations: list[StrategyAllocation] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        instrument = str(item.get("instrument", "")).strip()
        if not instrument:
            continue
        raw_side = str(item.get("side", "flat")).strip()
        side: AllocationSide = raw_side if raw_side in _ALLOWED_SIDES else "flat"
        allocations.append(
            StrategyAllocation(
                instrument=instrument,
                side=side,
                target_weight=_to_float(item.get("target_weight")),
                quantity=_to_float(item.get("quantity")),
            )
        )
    return allocations


def _parse_rules(raw: Any) -> list[RuleEvaluation]:
    if not isinstance(raw, list):
        return []
    rules: list[RuleEvaluation] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        rule_id = str(item.get("rule_id", "")).strip()
        if not rule_id:
            continue
        result = bool(item.get("result"))
        raw_severity = str(item.get("severity", "info")).strip()
        severity: RuleSeverity = raw_severity if raw_severity in _ALLOWED_SEVERITIES else "info"
        rules.append(
            RuleEvaluation(
                rule_id=rule_id,
                result=result,
                severity=severity,
                description=_to_optional_str(item.get("description")),
            )
        )
    return rules


def _to_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return []


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}
