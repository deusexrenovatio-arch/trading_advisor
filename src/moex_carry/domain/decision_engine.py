from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from moex_carry.domain.entities_v2 import SignalLifecycleState


DecisionActionType = Literal["APPROVE", "HOLD", "REJECT", "EXECUTE", "CLOSE"]

_DECISION_ACTION_ALIASES: dict[str, DecisionActionType] = {
    "APPROVE": "APPROVE",
    "ACK": "APPROVE",
    "HOLD": "HOLD",
    "REJECT": "REJECT",
    "EXECUTE": "EXECUTE",
    "ENTER": "EXECUTE",
    "CLOSE": "CLOSE",
    "EXIT": "CLOSE",
}


def derive_signal_lifecycle_state(
    action: object, *, position_open: bool = False
) -> SignalLifecycleState:
    normalized = str(action or "").strip().lower()
    if normalized in {"hold_pretrade", "check_pretrade"}:
        return "blocked"
    if normalized == "hold_open":
        return "hold_open"
    if normalized in {"ack", "acknowledged"}:
        return "acknowledged"
    if normalized == "enter":
        if bool(position_open):
            return "entered"
        return "ready"
    if normalized == "exit":
        if bool(position_open):
            return "exit_ready"
        return "closed"
    if normalized in {"reject", "rejected"}:
        return "rejected"
    return "candidate"


def build_signal_gate_results(
    *,
    signal_id: str,
    action: object,
    signal_metrics: object,
    pretrade_status: object,
    pretrade_reasons: object,
    stable_id: Callable[..., str],
) -> list[dict[str, object]]:
    normalized_action = str(action or "").strip().lower()
    metrics = signal_metrics if isinstance(signal_metrics, Mapping) else {}
    score_gate_raw = metrics.get("score_gate_pass")
    score_gate = None if score_gate_raw is None else bool(score_gate_raw)
    blocked_by_action = normalized_action in {"hold_pretrade", "check_pretrade"}
    normalized_pretrade_status = str(pretrade_status or "").strip().lower()
    pretrade_ready = not blocked_by_action
    if normalized_pretrade_status in {"pass", "place", "ready"}:
        pretrade_ready = True
    if normalized_pretrade_status in {"block", "hold", "check"}:
        pretrade_ready = False
    reasons = _coerce_reasons(pretrade_reasons) if not pretrade_ready else []
    return [
        {
            "gate_result_id": stable_id("gate", signal_id, "pretrade"),
            "gate_type": "pretrade",
            "status": "pass" if pretrade_ready else "block",
            "reasons": reasons,
        },
        {
            "gate_result_id": stable_id("gate", signal_id, "score_gate"),
            "gate_type": "score_gate",
            "status": "pass" if score_gate is not False else "block",
            "reasons": [] if score_gate is not False else ["score_gate_failed"],
        },
    ]


@dataclass
class DecisionActionRequest:
    action: DecisionActionType
    actor_id: str
    source: str
    reason_code: str | None
    comment: str | None
    idempotency_key: str | None


def parse_decision_action_request(
    payload: Mapping[str, Any],
    *,
    require_idempotency: bool = True,
) -> tuple[DecisionActionRequest | None, str | None]:
    action_raw = str(payload.get("action") or "").strip().upper()
    action = _DECISION_ACTION_ALIASES.get(action_raw)
    if action is None:
        return None, "action must be one of: APPROVE, HOLD, REJECT, EXECUTE, CLOSE"

    actor_id = str(payload.get("actor_id") or payload.get("actor") or "operator").strip()
    if not actor_id:
        actor_id = "operator"

    source = str(payload.get("source") or "ui").strip().lower()
    if source not in {"ui", "telegram", "system", "v1_adapter"}:
        source = "ui"

    reason_code_raw = payload.get("reason_code")
    reason_code = str(reason_code_raw).strip() if reason_code_raw is not None else None
    if reason_code == "":
        reason_code = None

    comment_raw = payload.get("comment")
    if comment_raw is None:
        comment_raw = payload.get("note")
    comment = str(comment_raw).strip() if comment_raw is not None else None
    if comment == "":
        comment = None

    idempotency_key_raw = payload.get("idempotency_key")
    idempotency_key = (
        str(idempotency_key_raw).strip() if idempotency_key_raw is not None else None
    )
    if idempotency_key == "":
        idempotency_key = None
    if require_idempotency and idempotency_key is None:
        return None, "idempotency_key is required"

    return (
        DecisionActionRequest(
            action=action,
            actor_id=actor_id,
            source=source,
            reason_code=reason_code,
            comment=comment,
            idempotency_key=idempotency_key,
        ),
        None,
    )


def build_decision_action_entries(
    *,
    decision_id: str,
    action_id: str,
    request_id: str,
    created_at: str,
    command: DecisionActionRequest,
    idempotency_key: str,
) -> tuple[dict[str, object], dict[str, object]]:
    action_lower = command.action.lower()
    action_entry: dict[str, object] = {
        "action_id": action_id,
        "decision_id": decision_id,
        "action": action_lower,
        "status": _operator_status(command.action),
        "actor": command.actor_id,
        "source": command.source,
        "reason_code": command.reason_code,
        "note": command.comment,
        "comment": command.comment,
        "idempotency_key": idempotency_key,
        "created_at": created_at,
    }
    execution_entry: dict[str, object] = {
        "decision_id": decision_id,
        "request_id": request_id,
        "action": action_lower,
        "status": _execution_status(command.action),
        "requested_at": created_at,
        "actor": command.actor_id,
        "source": command.source,
        "reason_code": command.reason_code,
        "note": command.comment,
        "idempotency_key": idempotency_key,
    }
    return action_entry, execution_entry


def _operator_status(action: DecisionActionType) -> str:
    if action == "APPROVE":
        return "approved"
    if action == "HOLD":
        return "on_hold"
    if action == "REJECT":
        return "rejected"
    if action == "EXECUTE":
        return "execute_requested"
    return "close_requested"


def _execution_status(action: DecisionActionType) -> str:
    if action == "APPROVE":
        return "approved"
    if action == "HOLD":
        return "on_hold"
    if action == "REJECT":
        return "rejected"
    if action == "EXECUTE":
        return "queued"
    return "close_queued"


def _coerce_reasons(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
