from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Optional


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_schema(filename: str) -> dict[str, Any]:
    path = _repo_root() / "contracts" / filename
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_required(data: Any, schema: dict[str, Any], path: str = "") -> list[str]:
    errors: list[str] = []
    schema_type = schema.get("type")
    if schema_type == "object":
        required = schema.get("required", [])
        for key in required:
            if not isinstance(data, dict) or key not in data:
                errors.append(f"{path}.{key}".strip("."))
        properties = schema.get("properties", {})
        if isinstance(data, dict):
            if schema.get("additionalProperties") is False:
                for key in data:
                    if key not in properties:
                        errors.append(f"{path}.{key}".strip("."))
            for key, value in data.items():
                if key in properties:
                    errors.extend(
                        _validate_required(value, properties[key], path=f"{path}.{key}".strip("."))
                    )
    if schema_type == "array" and isinstance(data, list):
        items_schema = schema.get("items")
        if items_schema:
            for idx, item in enumerate(data):
                errors.extend(_validate_required(item, items_schema, path=f"{path}[{idx}]"))
    return errors


def validate_decision_log(entry: dict[str, Any]) -> list[str]:
    schema = _load_schema("decision-log.schema.json")
    return _validate_required(entry, schema)


def validate_decision_view(entry: dict[str, Any]) -> list[str]:
    schema = _load_schema("decision-view.schema.json")
    return _validate_required(entry, schema)


def _isoformat(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def build_snapshot(
    source: str,
    instrument: str,
    as_of: date | datetime,
    payload: bytes,
    uri: Optional[str] = None,
    query: Optional[str] = None,
    is_cached: Optional[bool] = None,
) -> dict[str, Any]:
    if isinstance(as_of, date) and not isinstance(as_of, datetime):
        as_of_dt = datetime.combine(as_of, time.min).replace(tzinfo=timezone.utc)
    else:
        as_of_dt = as_of if isinstance(as_of, datetime) else datetime.now(timezone.utc)
    hash_value = hashlib.sha256(payload).hexdigest()
    source_slug = "iss" if source == "MOEX_ISS" else source.lower()
    snapshot_id = f"snap-{source_slug}-{instrument}-{as_of_dt:%Y%m%d%H%M}-{hash_value[:8]}"
    snapshot = {
        "source": source,
        "snapshot_id": snapshot_id,
        "as_of": _isoformat(as_of_dt),
        "hash": hash_value,
    }
    if uri:
        snapshot["uri"] = uri
    if query:
        snapshot["query"] = query
    if is_cached is not None:
        snapshot["is_cached"] = is_cached
    return snapshot


def build_decision_view(decision_log: dict[str, Any]) -> dict[str, Any]:
    strategies = decision_log.get("strategies", [])
    if len(strategies) == 1:
        strategy_type = strategies[0].get("type", "mixed")
    else:
        strategy_type = "mixed"
    primary_instrument = ""
    allocations = decision_log.get("portfolio_proposal", {}).get("allocations", [])
    if allocations:
        primary_instrument = allocations[0].get("instrument", "")
    news_severity = "low"
    news_summary: dict[str, Any] | None = None
    news_context = decision_log.get("news_context") or {}
    if isinstance(news_context, dict):
        news_severity = news_context.get("severity", news_severity)
        gate_action_raw = str(news_context.get("gate_action") or news_context.get("summary") or "").strip().lower()
        gate_action = gate_action_raw if gate_action_raw in {"allow", "reduce", "block"} else None
        news_summary = {
            "gate_action": gate_action,
            "headline_count": int(news_context.get("headline_count") or 0),
            "model_selected": news_context.get("model_selected"),
            "news_event_ids": news_context.get("news_event_ids") or [],
        }
        if gate_action is None:
            news_summary.pop("gate_action", None)
    decision = decision_log.get("decision", {})
    risk_state = decision.get("risk_state", "green")
    reasons = decision.get("reasons", [])
    risk_summary = "Risk checks passed."
    if risk_state != "green" and reasons:
        risk_summary = f"Risk issues: {', '.join(reasons)}"
    cost_model = decision_log.get("cost_model", {})
    cost_summary = {
        "round_trip_cost": cost_model.get("round_trip_cost", 0.0),
        "break_even_ticks": cost_model.get("break_even_ticks", 0.0),
    }
    if "break_even_points" in cost_model:
        cost_summary["break_even_points"] = cost_model["break_even_points"]
    key_features = decision_log.get("feature_set", {}).get("features", [])
    links = {
        "decision_log": decision_log.get("decision_id", ""),
        "input_snapshots": [
            snapshot.get("snapshot_id")
            for snapshot in decision_log.get("input_snapshots", [])
            if isinstance(snapshot, dict) and snapshot.get("snapshot_id")
        ],
    }
    aggregation_summary: dict[str, Any] | None = None
    aggregation = decision_log.get("aggregation")
    if isinstance(aggregation, dict):
        aggregation_summary = {
            "action": aggregation.get("action", "hold"),
            "score": aggregation.get("score", 0.0),
            "strategies": aggregation.get("used_strategies", []),
            "blocked_strategies": aggregation.get("blocked_strategies", []),
        }
    proposal_summary: dict[str, Any] | None = None
    proposal = decision_log.get("proposal")
    if isinstance(proposal, dict):
        proposal_summary = {
            "type": proposal.get("type"),
            "cadence": proposal.get("cadence"),
            "effective_date": proposal.get("effective_date"),
            "summary": proposal.get("summary"),
        }
    basket_summary = None
    basket_allocations = decision_log.get("basket_allocations")
    if isinstance(basket_allocations, dict):
        basket_summary = {
            "current": basket_allocations.get("current", []),
            "target": basket_allocations.get("target", []),
            "delta": basket_allocations.get("delta", []),
        }
    operator_action = decision_log.get("operator_action")
    execution_request = decision_log.get("execution_request")
    execution_status = None
    if isinstance(execution_request, dict):
        execution_status = {
            "status": execution_request.get("status"),
            "requested_at": execution_request.get("requested_at"),
            "executed_at": execution_request.get("executed_at"),
        }
    view = {
        "schema_version": decision_log.get("schema_version", "1.0.0"),
        "decision_view_id": decision_log.get("decision_view_id", ""),
        "decision_id": decision_log.get("decision_id", ""),
        "created_at": decision_log.get("created_at", ""),
        "strategy_type": strategy_type,
        "primary_instrument": primary_instrument,
        "action": decision.get("action", "hold"),
        "risk_state": risk_state,
        "risk_summary": risk_summary,
        "news_severity": news_severity,
        "cost_summary": cost_summary,
        "key_features": key_features,
        "allocations": allocations,
        "backtest_metrics": decision_log.get("backtest_metrics", {}),
        "links": links,
    }
    if news_summary is not None:
        view["news_summary"] = news_summary
    if aggregation_summary:
        view["aggregation_summary"] = aggregation_summary
    if proposal_summary and proposal_summary.get("type"):
        view["proposal_summary"] = proposal_summary
    if basket_summary:
        view["basket_summary"] = basket_summary
    if isinstance(operator_action, dict) and operator_action:
        view["operator_action"] = operator_action
    if execution_status:
        view["execution_status"] = execution_status
    return view


class DecisionLogStore:
    def __init__(
        self,
        data_dir: Path,
        *,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.base_dir = data_dir / "decisions"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.base_dir / "decision_log.jsonl"
        self.view_path = self.base_dir / "decision_view.jsonl"
        self._session_factory = session_factory

    def append(self, decision_log: dict[str, Any], decision_view: dict[str, Any]) -> None:
        log_errors = validate_decision_log(decision_log)
        view_errors = validate_decision_view(decision_view)
        if log_errors:
            raise ValueError(f"decision_log schema validation failed: {log_errors}")
        if view_errors:
            raise ValueError(f"decision_view schema validation failed: {view_errors}")
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(decision_log, ensure_ascii=False) + "\n")
        with self.view_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(decision_view, ensure_ascii=False) + "\n")
        if self._session_factory is None:
            return
        from moex_carry.storage.repositories import upsert_decision_view_projection

        with self._session_factory() as session:
            upsert_decision_view_projection(session, [decision_view])


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records
