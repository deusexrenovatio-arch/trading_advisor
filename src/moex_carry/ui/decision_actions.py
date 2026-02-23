from __future__ import annotations

from pathlib import Path
from typing import Callable
import uuid

from moex_carry.decision_log import load_jsonl
from moex_carry.domain.decision_engine import (
    build_decision_action_entries,
    parse_decision_action_request,
)


class DecisionActionService:
    def __init__(
        self,
        *,
        actions_path: Path,
        executions_path: Path,
        decision_exists: Callable[[str], bool],
        bad_request: Callable[[str], object],
        stable_id: Callable[..., str],
        iso_now: Callable[[], str],
        append_jsonl: Callable[[Path, dict[str, object]], None],
        json_response: Callable[[dict[str, object]], object],
    ) -> None:
        self.actions_path = actions_path
        self.executions_path = executions_path
        self.decision_exists = decision_exists
        self.bad_request = bad_request
        self.stable_id = stable_id
        self.iso_now = iso_now
        self.append_jsonl = append_jsonl
        self.json_response = json_response

    def record(
        self,
        decision_id: str,
        payload: dict[str, object],
        *,
        source_default: str,
        allowed_actions: set[str] | None = None,
        require_idempotency: bool = True,
    ):
        if not self.decision_exists(decision_id):
            return self.json_response({"error": "not_found"}), 404
        command, error = parse_decision_action_request(
            payload,
            require_idempotency=require_idempotency,
        )
        if error is not None or command is None:
            return self.bad_request(error or "invalid_action")
        if allowed_actions is not None and command.action not in allowed_actions:
            allowed = ", ".join(sorted(allowed_actions))
            return self.bad_request(f"action must be one of: {allowed}")

        if not command.source:
            command.source = source_default
        idempotency_key = command.idempotency_key or f"idem-{uuid.uuid4().hex[:12]}"

        action_records = load_jsonl(self.actions_path) if self.actions_path.exists() else []
        execution_records = load_jsonl(self.executions_path) if self.executions_path.exists() else []
        for item in action_records:
            if str(item.get("decision_id") or "") != decision_id:
                continue
            existing_key = str(item.get("idempotency_key") or "").strip()
            if existing_key and existing_key == idempotency_key:
                execution_match = None
                for execution_item in execution_records:
                    if not isinstance(execution_item, dict):
                        continue
                    if str(execution_item.get("decision_id") or "") != decision_id:
                        continue
                    execution_key = str(execution_item.get("idempotency_key") or "").strip()
                    if execution_key and execution_key == idempotency_key:
                        execution_match = execution_item
                        break
                decision_ref = {
                    "decision_id": decision_id,
                    "action_id": item.get("action_id"),
                    "latest_action": item.get("action"),
                    "latest_status": item.get("status"),
                    "actor_id": item.get("actor"),
                    "source": item.get("source"),
                    "idempotency_key": item.get("idempotency_key"),
                    "updated_at": item.get("created_at"),
                }
                execution_ref = {
                    "request_id": execution_match.get("request_id")
                    if isinstance(execution_match, dict)
                    else None,
                    "action": execution_match.get("action")
                    if isinstance(execution_match, dict)
                    else None,
                    "status": execution_match.get("status")
                    if isinstance(execution_match, dict)
                    else None,
                    "requested_at": execution_match.get("requested_at")
                    if isinstance(execution_match, dict)
                    else None,
                    "executed_at": execution_match.get("executed_at")
                    if isinstance(execution_match, dict)
                    else None,
                    "actor_id": execution_match.get("actor")
                    if isinstance(execution_match, dict)
                    else None,
                    "source": execution_match.get("source")
                    if isinstance(execution_match, dict)
                    else None,
                    "reason_code": execution_match.get("reason_code")
                    if isinstance(execution_match, dict)
                    else None,
                    "idempotency_key": execution_match.get("idempotency_key")
                    if isinstance(execution_match, dict)
                    else None,
                }
                return self.json_response(
                    {
                        "status": "duplicate",
                        "decision_id": decision_id,
                        "action_id": item.get("action_id"),
                        "idempotency_key": idempotency_key,
                        "operator_action": item,
                        "execution_status": execution_match or {},
                        "decision_ref": decision_ref,
                        "execution_ref": execution_ref,
                    }
                )

        created_at = self.iso_now()
        action_id = self.stable_id(
            "dact", decision_id, command.action, idempotency_key, created_at, length=20
        )
        request_id = self.stable_id(
            "dreq", decision_id, command.action, idempotency_key, created_at, length=20
        )
        action_entry, execution_entry = build_decision_action_entries(
            decision_id=decision_id,
            action_id=action_id,
            request_id=request_id,
            created_at=created_at,
            command=command,
            idempotency_key=idempotency_key,
        )
        self.append_jsonl(self.actions_path, action_entry)
        self.append_jsonl(self.executions_path, execution_entry)

        return self.json_response(
            {
                "status": "ok",
                "decision_id": decision_id,
                "action_id": action_id,
                "idempotency_key": idempotency_key,
                "operator_action": action_entry,
                "execution_status": execution_entry,
                "decision_ref": {
                    "decision_id": decision_id,
                    "action_id": action_entry.get("action_id"),
                    "latest_action": action_entry.get("action"),
                    "latest_status": action_entry.get("status"),
                    "actor_id": action_entry.get("actor"),
                    "source": action_entry.get("source"),
                    "idempotency_key": action_entry.get("idempotency_key"),
                    "updated_at": action_entry.get("created_at"),
                },
                "execution_ref": {
                    "request_id": execution_entry.get("request_id"),
                    "action": execution_entry.get("action"),
                    "status": execution_entry.get("status"),
                    "requested_at": execution_entry.get("requested_at"),
                    "executed_at": execution_entry.get("executed_at"),
                    "actor_id": execution_entry.get("actor"),
                    "source": execution_entry.get("source"),
                    "reason_code": execution_entry.get("reason_code"),
                    "idempotency_key": execution_entry.get("idempotency_key"),
                },
            }
        )
