from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


EntityType = Literal["instrument", "pair", "portfolio"]
SignalLifecycleState = Literal[
    "candidate",
    "blocked",
    "ready",
    "acknowledged",
    "entered",
    "hold_open",
    "exit_ready",
    "closed",
    "rejected",
]


@dataclass
class EntityRef:
    entity_type: EntityType
    entity_id: str
    asset_id: str | None = None
    ticker: str | None = None


@dataclass
class GateResult:
    gate_result_id: str
    gate_type: str
    status: Literal["pass", "warn", "block"]
    reasons: list[str] = field(default_factory=list)


@dataclass
class SignalRef:
    signal_id: str
    entity_ref: EntityRef
    lifecycle_state: SignalLifecycleState
    gate_results: list[GateResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionActionV2:
    action_id: str
    decision_id: str
    source: Literal["ui", "telegram", "system"]
    actor: str
    note: str | None = None
    created_at: datetime | None = None


@dataclass
class ExecutionEventV2:
    execution_event_id: str
    action: Literal["ack", "enter", "exit", "hold_open"]
    order_id: str | None = None
    signal_id: str | None = None
    decision_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
