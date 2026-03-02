from __future__ import annotations

import json
import hashlib
import logging
import math
import os
from pathlib import Path
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
from dash import Dash, Input, Output, State, dash_table, dcc, html
from flask import Flask, jsonify, request
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from moex_carry.config import AppSettings, resolve_paths
from moex_carry.contracts.strategy_test import BacktestRequest, ForwardTestRequest, HpoRequest
from moex_carry.backtest_v2.runtime import run_backtest_v2_cached, serialize_backtest_report
from moex_carry.data.moex_iss import MoexIssClient
from moex_carry.decision_log import load_jsonl
from moex_carry.domain.decision_engine import (
    build_decision_action_entries,
    parse_decision_action_request,
)
from moex_carry.domain.execution_policy import (
    evaluate_fail_closed_entry,
    select_auto_unwind_candidates,
)
from moex_carry.forward.runtime import load_forward_status, start_forward_run
from moex_carry.hpo.runtime import load_hpo_status, start_hpo_run
from moex_carry.logging import emit_api_log
from moex_carry.minute_ingest.runner import run_incremental_minute_ingest
from moex_carry.observability.runtime_metrics import ApiObservability
from moex_carry.parameter_specs import get_parameter_specs
from moex_carry.pipeline import build_spread_series, run_signal_cycle
from moex_carry.pretrade.delay_gate import run_delay_gate
from moex_carry.signals_ack import build_signal_fingerprint, parse_ack_note
from moex_carry.signals_delivery import parse_iso_utc, signal_delivery_state
from moex_carry.news import (
    build_signal_news_links,
    build_event_study_leakage_audit,
    compare_news_models,
    compute_event_fragmentation_report,
    rebuild_event_market_reactions,
    run_news_backtest,
    run_news_gate,
    summarize_event_study,
)
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_signal_execution_by_idempotency,
    load_event_market_reactions,
    load_decision_view_projection,
    upsert_decision_view_projection,
    load_active_signals,
    load_news_annotations,
    load_latest_signal_run,
    load_news_backtest_reports,
    load_news_event_items,
    load_news_events,
    load_news_impact_scores,
    load_news_items_by_ids,
    load_news_labels,
    load_news_gold_labels,
    load_news_llm_runs,
    load_news_model_eval_records,
    load_news_signal_links,
    load_news_unmatched_gold,
    load_open_executions,
    load_signal_executions,
    release_runtime_lease,
    renew_runtime_lease,
    load_signal_history,
    store_signal_history,
    store_signal_execution,
    store_signal_run,
    try_acquire_runtime_lease,
    upsert_news_annotations,
    upsert_news_backtest_report,
    upsert_news_signal_links,
)
from moex_carry.ui.app_helpers_base import (
    _append_jsonl,
    _latest_by_decision_id,
    _table_columns,
    _decision_columns,
    _prepare_decisions,
    _sanitize_value,
    _parse_bool,
    _coerce_bool,
    _default_require_score_gate_for_signals,
    _default_require_score_gate_for_top_pairs,
    _resolve_require_score_gate,
    _apply_score_gate_filter,
    _record_score_gate_pass,
    _parse_int,
    _parse_float,
    _bad_request,
    _is_iss_transport_error,
    _build_pretrade_fail_open_result,
    _df_to_records,
    _stringify_datetime_columns,
    _merge_signal_metrics,
    _build_execution_quality,
    _normalize_datetime,
    _normalize_execution_leg,
    _normalize_execution_action,
    _coerce_signal_action_request,
    _normalize_signal_action_source,
    _normalize_order_id,
    _stable_id,
    _build_pair_entity_ref,
    _build_signal_id_from_row,
    _derive_lifecycle_state,
    _derive_effective_signal_action,
    _build_gate_results_from_row,
    _normalize_gate_status,
    _coerce_string_list,
    _contains_reason_token,
    _normalize_evidence_item,
    _ACTIONABILITY_GATE_PRIORITIES,
)
from moex_carry.ui.app_helpers_base import SIGNAL_METRIC_CONTRACT_KEYS as _SIGNAL_METRIC_CONTRACT_KEYS
from moex_carry.ui.app_helpers_feed import (
    _parse_daily_time,
    _resolve_tz,
    _next_daily_run,
    _parse_date_bound,
    _parse_iso_datetime,
    _isoformat_utc,
    _load_news_bundle,
    _build_news_feed_events,
    _select_primary_model_score,
    _build_news_feed_events_from_event_layer,
    _future_scale_from_raw,
    _read_cache,
    _write_cache,
    _apply_query_filters,
    DECISION_STYLE,
)
from moex_carry.ui.app_helpers_news_bridge import build_silver_explain_payload
from moex_carry.ui.data import (
    load_backtest_summary,
    load_backtest_summary_with_source,
    load_decision_log,
    load_decision_view,
    load_projection_sources,
    load_signals,
    load_signals_with_source,
    load_top_pairs,
    load_top_pairs_with_source,
)
from moex_carry.ui.decision_actions import DecisionActionService
from moex_carry.ui.refresh_scheduler import SignalRefreshScheduler
from moex_carry.ui.routes_market_data import register_market_data_routes
from moex_carry.ui.routes_ops import register_ops_routes
from moex_carry.ui.routes_pretrade import register_pretrade_routes
from moex_carry.ui.routes_research import register_research_routes
from moex_carry.unified_runtime import (
    UnifiedMarketSnapshot,
    build_unified_market_snapshot,
    build_unified_spread_series,
    get_last_refresh_telemetry,
    list_unified_ingest_pairs,
    persist_snapshot_to_csv,
)


SIGNAL_METRIC_CONTRACT_KEYS = _SIGNAL_METRIC_CONTRACT_KEYS


BASE_TABLE_STYLE = {
    "style_table": {"overflowX": "auto", "border": "1px solid #e5e7eb"},
    "style_header": {
        "backgroundColor": "#f9fafb",
        "fontWeight": "600",
        "border": "1px solid #e5e7eb",
    },
    "style_cell": {
        "fontFamily": "Arial, sans-serif",
        "fontSize": "12px",
        "padding": "6px",
        "whiteSpace": "nowrap",
        "textOverflow": "ellipsis",
        "maxWidth": "180px",
        "border": "1px solid #f0f0f0",
    },
}


_CACHE_VERSION = "v5"
_V1_DEPRECATION_SUNSET_HTTP = "Wed, 01 Jul 2026 00:00:00 GMT"
_V1_DEPRECATION_SUNSET_DATE = "2026-07-01"
_DEFAULT_ENTRY_PRICE_TOLERANCE_PCT = 0.0015



def _derive_evidence_items_from_row(row: dict[str, object]) -> list[dict[str, object]]:
    metrics = row.get("signal_metrics")
    metric_map = metrics if isinstance(metrics, dict) else {}
    reasons = [str(item) for item in (row.get("signal_reasons") or []) if str(item).strip()]
    observed_at = row.get("timestamp")

    items: list[dict[str, object]] = []

    score_gate_pass = metric_map.get("score_gate_pass")
    if score_gate_pass is None:
        score_gate_pass = row.get("score_gate_pass")
    score_gate_bool = _parse_bool(score_gate_pass)
    if score_gate_bool is not None:
        items.append(
            {
                "source_key": "technical_score_gate",
                "source_kind": "technical",
                "stance": "support" if score_gate_bool else "oppose",
                "weight": 1.0,
                "confidence": _to_float(metric_map.get("score_exec_probability")),
                "severity": "medium" if not score_gate_bool else None,
                "observed_at": observed_at,
                "reason_codes": ["score_gate_pass" if score_gate_bool else "score_gate_fail"],
                "payload": {"score_gate_pass": bool(score_gate_bool)},
            }
        )

    gate_specs: tuple[tuple[str, str, str, str], ...] = (
        ("risk_gate_status", "risk", "risk_profile_gate", "risk_gate_reasons"),
        ("news_gate_action", "news", "news_geopolitics_gate", "news_gate_reasons"),
        ("liquidity_gate_status", "liquidity", "liquidity_gate", "liquidity_gate_reasons"),
        ("source_freshness_status", "other", "source_freshness_gate", "source_freshness_reasons"),
        ("portfolio_limit_status", "risk", "portfolio_limits_gate", "portfolio_limit_reasons"),
        ("venue_constraints_status", "other", "venue_constraints_gate", "venue_constraints_reasons"),
    )
    for status_key, source_kind, source_key, reasons_key in gate_specs:
        status = _normalize_gate_status(metric_map.get(status_key), default="unavailable")
        if status == "unavailable":
            continue
        reason_codes = _coerce_string_list(metric_map.get(reasons_key))
        payload = {"gate_status": status, "gate_id": source_key}
        if status == "block":
            payload["veto"] = True
        severity = None
        if status == "reduce":
            severity = "medium"
        elif status == "review":
            severity = "high"
        elif status == "block":
            severity = "critical"
        items.append(
            {
                "source_key": source_key,
                "source_kind": source_kind,
                "stance": "support" if status == "pass" else "oppose",
                "weight": 1.0,
                "observed_at": observed_at,
                "severity": severity,
                "reason_codes": reason_codes,
                "payload": payload,
            }
        )

    pretrade_status = str(
        metric_map.get("pretrade_status") or row.get("pretrade_status") or ""
    ).strip().lower()
    if pretrade_status:
        veto = pretrade_status in {"hold", "block"}
        stance = "support"
        severity = None
        if pretrade_status in {"check", "pending"}:
            stance = "oppose"
            severity = "medium"
        elif veto:
            stance = "oppose"
            severity = "critical"
        items.append(
            {
                "source_key": "execution_pretrade",
                "source_kind": "risk",
                "stance": stance,
                "weight": 1.0,
                "observed_at": observed_at,
                "severity": severity,
                "reason_codes": [f"pretrade_{pretrade_status}"],
                "payload": {
                    "pretrade_status": pretrade_status,
                    "veto": veto,
                },
            }
        )

    orderbook_pass = _parse_bool(metric_map.get("orderbook_pass"))
    if orderbook_pass is not None:
        reason_codes = _coerce_string_list(metric_map.get("orderbook_data_warnings"))
        if not reason_codes:
            reason_codes = ["orderbook_pass" if orderbook_pass else "orderbook_fail"]
        items.append(
            {
                "source_key": "liquidity_orderbook",
                "source_kind": "liquidity",
                "stance": "support" if orderbook_pass else "oppose",
                "weight": 1.0,
                "observed_at": observed_at,
                "severity": "high" if not orderbook_pass else None,
                "reason_codes": reason_codes,
                "payload": {"orderbook_pass": bool(orderbook_pass)},
            }
        )

    if _contains_reason_token(reasons, "news_veto", "geopolitical_veto"):
        items.append(
            {
                "source_key": "news_reason_veto",
                "source_kind": "news",
                "stance": "oppose",
                "weight": 1.0,
                "observed_at": observed_at,
                "severity": "critical",
                "reason_codes": ["reason_veto"],
                "payload": {"veto": True},
            }
        )

    if _contains_reason_token(reasons, "fundamental_support", "long_term_support"):
        items.append(
            {
                "source_key": "fundamental_support",
                "source_kind": "fundamental",
                "stance": "support",
                "weight": 1.0,
                "observed_at": observed_at,
                "reason_codes": ["fundamental_support"],
                "payload": {},
            }
        )
    if _contains_reason_token(reasons, "fundamental_veto", "fundamental_oppose"):
        items.append(
            {
                "source_key": "fundamental_oppose",
                "source_kind": "fundamental",
                "stance": "oppose",
                "weight": 1.0,
                "observed_at": observed_at,
                "severity": "high",
                "reason_codes": ["fundamental_oppose"],
                "payload": {},
            }
        )

    return items


def _extract_evidence_items(row: dict[str, object]) -> list[dict[str, object]]:
    metrics = row.get("signal_metrics")
    metric_map = metrics if isinstance(metrics, dict) else {}
    snapshot_as_of = row.get("timestamp")

    raw = row.get("evidence_items")
    if raw is None:
        raw = metric_map.get("evidence_items")

    items: list[dict[str, object]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            items.append(
                _normalize_evidence_item(
                    item,
                    snapshot_as_of=snapshot_as_of,
                )
            )

    existing_source_keys = {
        str(item.get("source_key") or "").strip()
        for item in items
        if isinstance(item, dict)
    }
    for item in _derive_evidence_items_from_row(row):
        if not isinstance(item, dict):
            continue
        normalized_item = _normalize_evidence_item(
            item,
            snapshot_as_of=snapshot_as_of,
            fallback_source_key_parts=(row.get("stock"), row.get("future"), row.get("run_id")),
        )
        source_key = str(normalized_item.get("source_key") or "").strip()
        if source_key and source_key in existing_source_keys:
            continue
        if source_key:
            existing_source_keys.add(source_key)
        items.append(normalized_item)

    return items


def _summarize_evidence_items(
    evidence_items: list[dict[str, object]],
    reasons: list[str],
) -> dict[str, object]:
    support_weight = 0.0
    oppose_weight = 0.0
    neutral_weight = 0.0
    veto_reasons: list[str] = []

    for item in evidence_items:
        stance = str(item.get("stance") or "neutral").strip().lower()
        weight = _to_float(item.get("weight"))
        if weight is None:
            weight = 1.0
        if stance == "support":
            support_weight += float(weight)
        elif stance == "oppose":
            oppose_weight += float(weight)
        else:
            neutral_weight += float(weight)
        payload = item.get("payload")
        item_veto = False
        if isinstance(payload, dict):
            item_veto = bool(payload.get("veto"))
        severity = str(item.get("severity") or "").strip().lower()
        if item_veto or severity == "critical":
            reason_codes = _coerce_string_list(item.get("reason_codes"))
            if reason_codes:
                veto_reasons.extend(reason_codes)
            else:
                veto_reasons.append(str(item.get("source_key") or "veto"))

    if _contains_reason_token(reasons, "news_veto", "geopolitical_veto", "risk_veto"):
        veto_reasons.append("reason_veto")

    total = support_weight + oppose_weight + neutral_weight
    if total > 0:
        conflict_score = min((2.0 * min(support_weight, oppose_weight)) / total, 1.0)
    else:
        conflict_score = 0.0

    return {
        "support_weight_total": float(support_weight),
        "oppose_weight_total": float(oppose_weight),
        "neutral_weight_total": float(neutral_weight),
        "conflict_score": float(conflict_score),
        "veto_active": bool(veto_reasons),
        "veto_reasons": veto_reasons,
    }


def _derive_actionability_gate_trace(
    row: dict[str, object],
    *,
    delivery: dict[str, object],
    evidence_summary: dict[str, object],
) -> list[dict[str, object]]:
    metrics = row.get("signal_metrics")
    metric_map = metrics if isinstance(metrics, dict) else {}
    reasons = [str(item) for item in (row.get("signal_reasons") or []) if str(item).strip()]
    effective_action = str(row.get("signal_action_effective") or row.get("signal_action") or "").strip().lower()

    trace: list[dict[str, object]] = []
    for gate_id, priority in _ACTIONABILITY_GATE_PRIORITIES:
        status = "pass"
        reason_codes: list[str] = []
        details: dict[str, object] = {}

        if gate_id == "risk_profile":
            raw_status = metric_map.get("risk_gate_status")
            if raw_status is None and _contains_reason_token(reasons, "risk_block", "risk_limit"):
                raw_status = "block"
            status = _normalize_gate_status(raw_status, default="pass")
            if status != "pass":
                reason_codes = _coerce_string_list(metric_map.get("risk_gate_reasons")) or ["risk_profile_gate"]
        elif gate_id == "news_geopolitics":
            raw_status = metric_map.get("news_gate_action")
            if raw_status is None and bool(evidence_summary.get("veto_active")):
                raw_status = "block"
            status = _normalize_gate_status(raw_status, default="pass")
            if status != "pass":
                reason_codes = _coerce_string_list(metric_map.get("news_gate_reasons"))
                if not reason_codes and bool(evidence_summary.get("veto_active")):
                    reason_codes = [str(item) for item in evidence_summary.get("veto_reasons") or []]
                if not reason_codes:
                    reason_codes = ["news_gate"]
        elif gate_id == "liquidity":
            raw_status = metric_map.get("liquidity_gate_status")
            if raw_status is None:
                orderbook_pass = _parse_bool(metric_map.get("orderbook_pass"))
                if orderbook_pass is False:
                    raw_status = "reduce"
            status = _normalize_gate_status(raw_status, default="pass")
            if status != "pass":
                reason_codes = _coerce_string_list(metric_map.get("liquidity_gate_reasons")) or [
                    "liquidity_gate",
                ]
        elif gate_id == "execution_feasibility":
            raw_status = metric_map.get("execution_gate_status")
            if raw_status is None:
                if effective_action == "hold_pretrade":
                    raw_status = "block"
                elif effective_action == "check_pretrade":
                    raw_status = "review"
                elif (
                    str(delivery.get("delivery_suppressed_reason") or "").strip().lower()
                    == "entry_out_of_range"
                ):
                    raw_status = "reduce"
            status = _normalize_gate_status(raw_status, default="pass")
            if status != "pass":
                reason_codes = _coerce_string_list(metric_map.get("execution_gate_reasons"))
                if not reason_codes and str(delivery.get("delivery_suppressed_reason") or "").strip().lower():
                    reason_codes = [str(delivery.get("delivery_suppressed_reason"))]
                if not reason_codes:
                    reason_codes = ["execution_gate"]
            details = {
                "entry_range_eligible": bool(delivery.get("entry_range_eligible")),
                "entry_signal_expired": bool(delivery.get("entry_signal_expired")),
            }
        elif gate_id == "source_freshness":
            raw_status = metric_map.get("source_freshness_status")
            status = _normalize_gate_status(raw_status, default="unavailable")
            if status != "pass":
                reason_codes = _coerce_string_list(metric_map.get("source_freshness_reasons"))
        elif gate_id == "portfolio_limits":
            raw_status = metric_map.get("portfolio_limit_status")
            status = _normalize_gate_status(raw_status, default="unavailable")
            if status != "pass":
                reason_codes = _coerce_string_list(metric_map.get("portfolio_limit_reasons"))
        elif gate_id == "venue_constraints":
            raw_status = metric_map.get("venue_constraints_status")
            status = _normalize_gate_status(raw_status, default="unavailable")
            if status != "pass":
                reason_codes = _coerce_string_list(metric_map.get("venue_constraints_reasons"))

        trace.append(
            {
                "gate_id": gate_id,
                "status": status,
                "priority": priority,
                "reason_codes": reason_codes,
                "details": details,
            }
        )
    return trace


def _resolve_policy_outcome(
    gate_trace: list[dict[str, object]],
    *,
    risk_scale_multiplier: float | None,
) -> dict[str, object]:
    ordered = sorted(gate_trace, key=lambda item: int(item.get("priority") or 999))

    def _first(status_value: str) -> dict[str, object] | None:
        for item in ordered:
            if str(item.get("status") or "").strip().lower() == status_value:
                return item
        return None

    selected = _first("block")
    final_status = "block" if selected is not None else "allow"
    if selected is None:
        selected = _first("review")
        if selected is not None:
            final_status = "review"
    if selected is None:
        selected = _first("reduce")
        if selected is not None:
            final_status = "reduce"
    if selected is None:
        selected = _first("pass")
        if selected is None and ordered:
            selected = ordered[0]

    selected_reason_codes = (
        [str(item) for item in (selected.get("reason_codes") or []) if str(item).strip()]
        if isinstance(selected, dict)
        else []
    )
    applied_gate_id = str(selected.get("gate_id") or "").strip() if isinstance(selected, dict) else None
    applied_priority = int(selected.get("priority") or 0) if isinstance(selected, dict) else None

    outcome: dict[str, object] = {
        "status": final_status,
        "reasons": selected_reason_codes,
        "blocking_gate": applied_gate_id if final_status == "block" else None,
        "precedence_version": "v1",
        "applied_gate_id": applied_gate_id or None,
        "applied_gate_priority": applied_priority,
        "manual_review_required": final_status == "review",
        "risk_scale_multiplier": (
            float(risk_scale_multiplier)
            if final_status == "reduce" and risk_scale_multiplier is not None
            else None
        ),
        "gate_trace": ordered,
    }
    return outcome


def _map_delivery_suppressed_reason_v2(reason: object) -> str | None:
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return None
    mapping = {
        "signal_used": "intent_consumed",
        "entry_expired": "intent_expired",
        "entry_out_of_range": "out_of_range",
        "unsupported_action": "unsupported_action",
    }
    return mapping.get(normalized, "not_actionable")


def _derive_intent_state_v2(row: dict[str, object], delivery: dict[str, object]) -> str:
    action = str(row.get("signal_action") or "").strip().lower()
    if action != "enter":
        return "none"
    if bool(row.get("signal_used")):
        return "consumed"
    if bool(delivery.get("entry_signal_expired")):
        return "expired"
    if not bool(delivery.get("entry_range_eligible")):
        return "out_of_range"
    return "active"


def _derive_delivery_state_v2(delivery: dict[str, object]) -> str:
    if bool(delivery.get("delivery_allowed")):
        return "not_sent"
    reason = str(delivery.get("delivery_suppressed_reason") or "").strip().lower()
    if reason == "entry_out_of_range":
        return "out_of_range_notified"
    if reason == "cooldown":
        return "cooldown"
    return "suppressed"


def _derive_actionability_state_v2(
    *,
    signal_action: str,
    policy_state: str,
    intent_state: str,
    position_state: str,
    execution_state: str,
    has_origin: bool,
) -> str:
    if policy_state == "block":
        return "blocked_entry"
    if signal_action == "exit":
        if position_state == "open" and policy_state in {"allow", "reduce"}:
            return "actionable_exit"
        return "inactive"
    if signal_action == "enter":
        if policy_state == "review":
            return "review_entry"
        if intent_state == "out_of_range" or execution_state == "out_of_range":
            return "enter_out_of_range"
        if intent_state == "active":
            if has_origin:
                return "actionable_enter_repriced"
            return "actionable_enter"
        if position_state == "open":
            return "hold_open"
        return "inactive"
    if position_state == "open":
        return "hold_open"
    return "inactive"


def _build_signal_actionability_projection(
    row: dict[str, object],
    *,
    callback_ttl_hours: int,
) -> dict[str, object]:
    signal_id = str(row.get("signal_id") or _build_signal_id_from_row(row))
    signal_action = str(row.get("signal_action") or "").strip().lower()
    position_state = str(row.get("position_state") or "flat").strip().lower()
    if position_state not in {"flat", "open"}:
        position_state = "open" if bool(row.get("position_open")) else "flat"

    signal_action_effective = _derive_effective_signal_action(row)
    delivery = signal_delivery_state(
        {**row, "signal_action_effective": signal_action_effective},
        callback_ttl_hours=callback_ttl_hours,
    )
    evidence_items = _extract_evidence_items(row)
    signal_reasons = [str(item) for item in (row.get("signal_reasons") or []) if str(item).strip()]
    evidence_summary = _summarize_evidence_items(evidence_items, signal_reasons)
    risk_scale_multiplier = _to_float(
        row.get("risk_scale_multiplier")
        if row.get("risk_scale_multiplier") is not None
        else (
            row.get("signal_metrics", {}).get("risk_scale_multiplier")
            if isinstance(row.get("signal_metrics"), dict)
            else None
        )
    )
    gate_trace = _derive_actionability_gate_trace(
        row,
        delivery=delivery,
        evidence_summary=evidence_summary,
    )
    policy_outcome = _resolve_policy_outcome(gate_trace, risk_scale_multiplier=risk_scale_multiplier)
    policy_state = str(policy_outcome.get("status") or "allow")
    intent_state = _derive_intent_state_v2(row, delivery)
    execution_state = "not_applicable"
    if signal_action == "enter":
        execution_state = "in_range" if bool(delivery.get("entry_range_eligible")) else "out_of_range"
    delivery_state = _derive_delivery_state_v2(delivery)
    source_conflict_state = "none"
    if bool(evidence_summary.get("veto_active")):
        source_conflict_state = "veto"
    else:
        conflict_score = _to_float(evidence_summary.get("conflict_score")) or 0.0
        if conflict_score >= 0.75:
            source_conflict_state = "high"
        elif conflict_score >= 0.4:
            source_conflict_state = "medium"
        elif conflict_score > 0:
            source_conflict_state = "low"

    has_origin = bool(row.get("signal_origin_run_id")) or bool(row.get("signal_origin_timestamp"))
    actionability_state = _derive_actionability_state_v2(
        signal_action=signal_action,
        policy_state=policy_state,
        intent_state=intent_state,
        position_state=position_state,
        execution_state=execution_state,
        has_origin=has_origin,
    )

    timestamp_raw = row.get("timestamp")
    signal_ts = parse_iso_utc(timestamp_raw)
    ttl_expires_at = None
    if signal_ts is not None:
        ttl_expires_at = (
            signal_ts + timedelta(hours=max(int(callback_ttl_hours or 72), 1))
        ).isoformat().replace("+00:00", "Z")

    delivery_action = str(delivery.get("delivery_action") or "").strip().lower()
    if delivery_action not in {"enter", "exit", "hold_open"}:
        delivery_action = "none"

    signal_fingerprint = str(row.get("signal_fingerprint") or "").strip()
    if not signal_fingerprint:
        signal_fingerprint = _stable_id(
            "fingerprint",
            row.get("run_id"),
            row.get("timestamp"),
            row.get("stock"),
            row.get("future"),
            signal_action,
            length=24,
        )

    intent_id = _stable_id("intent", signal_fingerprint, signal_id, length=24)
    intent_consumed = intent_state == "consumed"
    consumed_action = "ack" if intent_consumed else None
    if intent_consumed and _contains_reason_token(signal_reasons, "enter_used", "explicit_enter"):
        consumed_action = "enter"

    signal_metrics = row.get("signal_metrics") if isinstance(row.get("signal_metrics"), dict) else {}
    entry_plan = {
        "plan_revision": int(signal_metrics.get("plan_revision") or (1 if has_origin else 0)),
        "generated_at": row.get("timestamp"),
        "valid_until": ttl_expires_at,
        "direction": row.get("signal_direction"),
        "entry_price_min": _to_float(row.get("entry_stock_min")),
        "entry_price_max": _to_float(row.get("entry_stock_max")),
        "entry_spread_min": _to_float(row.get("entry_spread_min")),
        "entry_spread_max": _to_float(row.get("entry_spread_max")),
        "entry_spread_pct_min": _to_float(row.get("entry_spread_pct_min")),
        "entry_spread_pct_max": _to_float(row.get("entry_spread_pct_max")),
        "execution_window_sec": int(signal_metrics.get("execution_window_sec") or 0) or None,
    }

    entry_range_now = {
        "price_now": _to_float(row.get("spot_mid")),
        "spread_now": _to_float(row.get("spread_mid")),
        "spread_pct_now": _to_float(row.get("spread_pct")),
        "in_range": bool(delivery.get("entry_range_eligible")),
        "out_of_range_reasons": (
            ["entry_out_of_range"]
            if not bool(delivery.get("entry_range_eligible")) and signal_action == "enter"
            else []
        ),
    }

    projection: dict[str, object] = {
        "actionability_id": _stable_id("act", signal_id, signal_fingerprint, length=24),
        "signal_id": signal_id,
        "entity_ref": _build_pair_entity_ref(row.get("stock"), row.get("future")),
        "snapshot_as_of": row.get("timestamp"),
        "axes": {
            "policy_state": policy_state,
            "intent_state": intent_state,
            "position_state": position_state,
            "execution_state": execution_state,
            "delivery_state": delivery_state,
            "source_conflict_state": source_conflict_state,
        },
        "position_state": position_state,
        "actionability_state": actionability_state,
        "actionable_enter": actionability_state in {"actionable_enter", "actionable_enter_repriced"},
        "actionable_exit": actionability_state == "actionable_exit",
        "hold_required": position_state == "open",
        "intent": {
            "intent_id": intent_id,
            "source_signal_id": signal_id,
            "source_run_id": row.get("run_id"),
            "source_timestamp": row.get("timestamp"),
            "status": intent_state,
            "ttl_expires_at": ttl_expires_at,
            "consumed_by_action": consumed_action,
            "consumed_at": row.get("signal_used_at") if intent_consumed else None,
            "consumed_by": row.get("signal_used_by") if intent_consumed else None,
        },
        "entry_plan": entry_plan,
        "entry_range_now": entry_range_now,
        "delivery": {
            "delivery_action": delivery_action,
            "delivery_allowed": bool(delivery.get("delivery_allowed")),
            "delivery_suppressed_reason": _map_delivery_suppressed_reason_v2(
                delivery.get("delivery_suppressed_reason")
            ),
            "signal_fingerprint": signal_fingerprint,
            "out_of_range_notified": delivery_state == "out_of_range_notified",
            "last_notified_at": None,
        },
        "evidence_summary": evidence_summary,
        "evidence_items": evidence_items,
        "policy_outcome": policy_outcome,
        "reasons": signal_reasons,
        "signal_origin_run_id": row.get("signal_origin_run_id"),
        "signal_origin_timestamp": row.get("signal_origin_timestamp"),
        "metrics": signal_metrics,
        "run_id": row.get("run_id"),
        "timestamp": row.get("timestamp"),
        "stock": row.get("stock"),
        "future": row.get("future"),
        "signal_action": signal_action,
        "signal_direction": row.get("signal_direction"),
        "signal_score": row.get("signal_score"),
        "entry_stock_min": _to_float(row.get("entry_stock_min")),
        "entry_stock_max": _to_float(row.get("entry_stock_max")),
        "entry_future_min_per_share": _to_float(row.get("entry_future_min_per_share")),
        "entry_future_max_per_share": _to_float(row.get("entry_future_max_per_share")),
        "entry_spread_min": _to_float(row.get("entry_spread_min")),
        "entry_spread_max": _to_float(row.get("entry_spread_max")),
        "entry_spread_pct_min": _to_float(row.get("entry_spread_pct_min")),
        "entry_spread_pct_max": _to_float(row.get("entry_spread_pct_max")),
        "spot_mid": _to_float(row.get("spot_mid")),
        "future_mid": _to_float(row.get("future_mid")),
        "spread_mid": _to_float(row.get("spread_mid")),
        "spread_pct": _to_float(row.get("spread_pct")),
        "pretrade_status": row.get("pretrade_status"),
    }
    return projection


def _build_instrument_actionability_rows(
    pair_projection: dict[str, object],
) -> list[dict[str, object]]:
    stock = str(pair_projection.get("stock") or "").strip()
    future = str(pair_projection.get("future") or "").strip()
    if not stock and not future:
        return []

    row_list: list[tuple[str, str, str]] = []
    if stock:
        row_list.append(("stock", stock, "stock"))
    if future:
        row_list.append(("future", future, "future"))

    result: list[dict[str, object]] = []
    pair_id = f"{stock}__{future}" if stock and future else None
    pair_ref = _build_pair_entity_ref(stock, future) if stock and future else None
    for leg_key, secid, instrument_type in row_list:
        entry_plan = dict(pair_projection.get("entry_plan") or {})
        entry_range_now = dict(pair_projection.get("entry_range_now") or {})
        if leg_key == "stock":
            entry_plan["entry_price_min"] = _to_float(pair_projection.get("entry_stock_min"))
            entry_plan["entry_price_max"] = _to_float(pair_projection.get("entry_stock_max"))
            entry_range_now["price_now"] = _to_float(pair_projection.get("spot_mid"))
        else:
            entry_plan["entry_price_min"] = _to_float(pair_projection.get("entry_future_min_per_share"))
            entry_plan["entry_price_max"] = _to_float(pair_projection.get("entry_future_max_per_share"))
            entry_range_now["price_now"] = _to_float(pair_projection.get("future_mid"))

        instrument_row = dict(pair_projection)
        instrument_row["actionability_id"] = _stable_id(
            "act",
            pair_projection.get("actionability_id"),
            instrument_type,
            secid,
            length=24,
        )
        instrument_row["entity_ref"] = {
            "entity_type": "instrument",
            "entity_id": secid,
            "asset_id": secid,
            "ticker": secid,
        }
        instrument_row["instrument_type"] = instrument_type
        instrument_row["entry_plan"] = entry_plan
        instrument_row["entry_range_now"] = entry_range_now
        instrument_row["pair_id"] = pair_id
        instrument_row["pair_ref"] = pair_ref
        instrument_row["pair_stock"] = stock or None
        instrument_row["pair_future"] = future or None
        instrument_row["stock"] = None
        instrument_row["future"] = None
        result.append(instrument_row)
    return result


def _parse_pair_id(value: object) -> tuple[str, str] | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for sep in ("__", ":", "|", "/"):
        if sep not in raw:
            continue
        stock, future = raw.split(sep, 1)
        stock_value = stock.strip()
        future_value = future.strip()
        if stock_value and future_value:
            return stock_value, future_value
    return None


def _normalize_instrument_type(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"stock", "future"}:
        return normalized
    return None


def _extract_response_payload(result) -> tuple[object | None, int]:
    if isinstance(result, tuple):
        payload, status_code = result[0], int(result[1])
    else:
        payload, status_code = result, 200
    if hasattr(payload, "get_json"):
        data = payload.get_json(silent=True)
        return data, status_code
    return payload, status_code


def _parse_json_object(value: object) -> dict[str, object] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _parse_signal_action_note(note: object) -> dict[str, object] | None:
    payload = _parse_json_object(note)
    if not isinstance(payload, dict):
        return None
    kind = str(payload.get("kind") or "").strip()
    if kind not in {"signal_action_v1_adapter", "signal_action_v2"}:
        return None
    return payload


def _parse_ack_note_from_execution_note(note: object) -> dict[str, object] | None:
    direct = parse_ack_note(note)
    if direct is not None:
        return direct
    payload = _parse_signal_action_note(note)
    if payload is None:
        return None
    nested_note = payload.get("note")
    return parse_ack_note(nested_note)


def _deprecated_v1_successor_path(request_path: str) -> str | None:
    if request_path == "/api/top-pairs":
        return "/api/v2/top-pairs"
    if request_path == "/api/decision-view":
        return "/api/v2/decision-view"
    if request_path == "/api/pretrade/check":
        return "/api/v2/pretrade/check"
    if request_path == "/api/signals/active":
        return "/api/v2/signals/active"
    if request_path == "/api/signals/history":
        return "/api/v2/signals/history"
    if request_path == "/api/signals/executions":
        return "/api/v2/signals/executions"
    if request_path == "/api/signals/execute":
        return "/api/v2/signals/{signal_id}/actions"
    if request_path.startswith("/api/decisions/") and request_path.endswith("/action"):
        decision_id = request_path.removeprefix("/api/decisions/").removesuffix("/action")
        decision_id = decision_id.strip("/")
        if decision_id:
            return f"/api/v2/decisions/{decision_id}/actions"
    return None


def _signal_used_by_from_ack(note_payload: dict[str, object]) -> str | None:
    username = note_payload.get("telegram_username")
    if isinstance(username, str) and username.strip():
        return username.strip()
    user_id = note_payload.get("telegram_user_id")
    if isinstance(user_id, int):
        return str(user_id)
    return None


def _signal_used_by_from_action(note_payload: dict[str, object]) -> str | None:
    actor = note_payload.get("actor_id")
    if isinstance(actor, str) and actor.strip():
        return actor.strip()
    source = note_payload.get("source")
    if isinstance(source, str) and source.strip():
        return source.strip()
    return None


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _coalesce_float(record: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key not in record:
            continue
        parsed = _to_float(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _bounded_value_ok(*, current: float | None, lower: object, upper: object) -> bool:
    lower_value = _to_float(lower)
    upper_value = _to_float(upper)
    if lower_value is None and upper_value is None:
        return True
    if current is None:
        return False
    if lower_value is not None and upper_value is not None and lower_value > upper_value:
        lower_value, upper_value = upper_value, lower_value
    if lower_value is not None and current < lower_value:
        return False
    if upper_value is not None and current > upper_value:
        return False
    return True


def _resolve_entry_tolerance_from_settings(settings: AppSettings) -> float:
    raw = getattr(settings.spread_carry_alpha, "entry_price_tolerance_pct", _DEFAULT_ENTRY_PRICE_TOLERANCE_PCT)
    parsed = _to_float(raw)
    if parsed is None:
        parsed = _DEFAULT_ENTRY_PRICE_TOLERANCE_PCT
    return min(max(float(parsed), 0.0001), 0.05)


def _resolve_spread_tolerance_from_settings(settings: AppSettings) -> float:
    raw = getattr(settings.spread_carry_alpha, "entry_spread_tolerance_pct", None)
    parsed = _to_float(raw)
    if parsed is None:
        return _resolve_entry_tolerance_from_settings(settings)
    return min(max(float(parsed), 0.0001), 0.05)


def _build_dynamic_entry_plan(
    *,
    spot_mid: float | None,
    future_mid: float | None,
    spread_mid: float | None,
    spread_pct: float | None,
    tolerance: float,
    spread_tolerance: float | None = None,
) -> dict[str, float | None]:
    spread_tol = tolerance if spread_tolerance is None else min(max(float(spread_tolerance), 0.0001), 0.05)
    spot = float(spot_mid) if spot_mid is not None else None
    future = float(future_mid) if future_mid is not None else None
    spread_value = float(spread_mid) if spread_mid is not None else None
    spread_pct_value = float(spread_pct) if spread_pct is not None else None

    if spread_value is None and spread_pct_value is not None and spot is not None:
        spread_value = float(spread_pct_value * spot)
    if spread_pct_value is None and spread_value is not None and spot is not None and spot != 0:
        spread_pct_value = float(spread_value / spot)

    spread_band = None
    spread_pct_band = None
    if spread_value is not None:
        spread_band = float(max(abs(spread_value), 1.0) * spread_tol)
        if spot is not None and spot != 0:
            spread_pct_band = float(spread_band / abs(spot))
        elif spread_pct_value is not None:
            spread_pct_band = float(max(abs(spread_pct_value), 0.000001) * spread_tol)

    return {
        "entry_price_tolerance_pct": float(tolerance),
        "entry_spread_tolerance_pct": float(spread_tol),
        "entry_stock_min": float(spot * (1.0 - tolerance)) if spot is not None and spot > 0 else None,
        "entry_stock_max": float(spot * (1.0 + tolerance)) if spot is not None and spot > 0 else None,
        "entry_future_min_per_share": (
            float(future * (1.0 - tolerance)) if future is not None and future > 0 else None
        ),
        "entry_future_max_per_share": (
            float(future * (1.0 + tolerance)) if future is not None and future > 0 else None
        ),
        "entry_spread_min": (
            float(spread_value - spread_band)
            if spread_value is not None and spread_band is not None
            else None
        ),
        "entry_spread_max": (
            float(spread_value + spread_band)
            if spread_value is not None and spread_band is not None
            else None
        ),
        "entry_spread_pct_min": (
            float(spread_pct_value - spread_pct_band)
            if spread_pct_value is not None and spread_pct_band is not None
            else None
        ),
        "entry_spread_pct_max": (
            float(spread_pct_value + spread_pct_band)
            if spread_pct_value is not None and spread_pct_band is not None
            else None
        ),
    }


def _enrich_entry_plan_metrics(
    *,
    settings: AppSettings,
    current_metrics: dict[str, object] | None,
    fallback_metrics: dict[str, object] | None = None,
    force_rebuild: bool = False,
) -> dict[str, object]:
    merged: dict[str, object] = {}
    if isinstance(fallback_metrics, dict):
        merged.update(fallback_metrics)
    if isinstance(current_metrics, dict):
        merged.update(current_metrics)

    has_existing_plan = any(
        merged.get(key) is not None
        for key in (
            "entry_stock_min",
            "entry_stock_max",
            "entry_future_min_per_share",
            "entry_future_max_per_share",
            "entry_spread_min",
            "entry_spread_max",
            "entry_spread_pct_min",
            "entry_spread_pct_max",
        )
    )
    if has_existing_plan and not force_rebuild:
        return merged

    tolerance = _to_float(merged.get("entry_price_tolerance_pct"))
    if tolerance is None:
        tolerance = _resolve_entry_tolerance_from_settings(settings)
    tolerance = min(max(float(tolerance), 0.0001), 0.05)
    spread_tolerance = _to_float(merged.get("entry_spread_tolerance_pct"))
    if spread_tolerance is None:
        spread_tolerance = _resolve_spread_tolerance_from_settings(settings)
    spread_tolerance = min(max(float(spread_tolerance), 0.0001), 0.05)

    spot_mid = _coalesce_float(merged, ("spot_mid", "spot", "stock_mid", "stock_price", "stock_last_price"))
    future_mid = _coalesce_float(
        merged,
        ("future_mid", "future_price", "future_last_price"),
    )
    spread_mid = _coalesce_float(merged, ("spread_mid", "spread"))
    spread_pct = _coalesce_float(merged, ("spread_pct",))
    dynamic_plan = _build_dynamic_entry_plan(
        spot_mid=spot_mid,
        future_mid=future_mid,
        spread_mid=spread_mid,
        spread_pct=spread_pct,
        tolerance=tolerance,
        spread_tolerance=spread_tolerance,
    )
    merged.update(dynamic_plan)
    return merged


def _decrement_leg_bucket(open_legs: dict[str, int], preferred: str) -> None:
    if preferred in open_legs and int(open_legs.get(preferred, 0)) > 0:
        open_legs[preferred] = int(open_legs.get(preferred, 0)) - 1
        return
    if int(open_legs.get("other", 0)) > 0:
        open_legs["other"] = int(open_legs.get("other", 0)) - 1
        return
    if int(open_legs.get("stock", 0)) >= int(open_legs.get("future", 0)):
        if int(open_legs.get("stock", 0)) > 0:
            open_legs["stock"] = int(open_legs.get("stock", 0)) - 1
            return
        if int(open_legs.get("future", 0)) > 0:
            open_legs["future"] = int(open_legs.get("future", 0)) - 1
            return
    if int(open_legs.get("future", 0)) > 0:
        open_legs["future"] = int(open_legs.get("future", 0)) - 1
        return
    if int(open_legs.get("stock", 0)) > 0:
        open_legs["stock"] = int(open_legs.get("stock", 0)) - 1


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def create_app(settings: AppSettings) -> Dash:
    paths = resolve_paths(settings)
    server = Flask(__name__)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    decisions_dir = paths.data_dir / "decisions"
    actions_path = decisions_dir / "decision_actions.jsonl"
    executions_path = decisions_dir / "execution_requests.jsonl"
    logger = logging.getLogger(__name__)
    observability = ApiObservability(latency_window_size=1000)
    request_started_at_key = "moex.request_started_at"

    def _observe_request(endpoint_key: str, started_at: datetime, result):
        _, status_code = _extract_response_payload(result)
        duration_ms = max((datetime.now(timezone.utc) - started_at).total_seconds() * 1000.0, 0.0)
        observability.record_request(endpoint_key, status_code=status_code, duration_ms=duration_ms)
        return result

    def _mark_signal_action_events(result) -> None:
        payload, status_code = _extract_response_payload(result)
        if status_code == 409 and isinstance(payload, dict):
            if str(payload.get("error") or "").strip().lower() == "fail_closed_execution":
                observability.mark_event("execution_rejected_fail_closed")

    def _mark_pretrade_events(result) -> None:
        payload, status_code = _extract_response_payload(result)
        if status_code >= 500:
            observability.mark_event("pretrade_error")
            return
        if status_code >= 400 or not isinstance(payload, dict):
            return
        pretrade_status = str(payload.get("pretrade_status") or payload.get("status") or "").strip().lower()
        ready_to_place = _parse_bool(payload.get("ready_to_place"))
        if pretrade_status in {"block", "check", "pending"} or ready_to_place is False:
            observability.mark_event("pretrade_failure")
        degraded = _parse_bool(payload.get("degraded"))
        if degraded is True:
            observability.mark_event("pretrade_degraded")

    def _mark_auto_unwind_events(result) -> None:
        payload, status_code = _extract_response_payload(result)
        if status_code >= 500:
            observability.mark_event("auto_unwind_error")
            return
        if status_code >= 400 or not isinstance(payload, dict):
            return
        triggered_count = _parse_int(payload.get("triggered_count"), 0)
        blocked_count = _parse_int(payload.get("blocked_count"), 0)
        error_count = _parse_int(payload.get("error_count"), 0)
        if triggered_count > 0:
            observability.mark_event("auto_unwind_triggered", count=triggered_count)
        if blocked_count > 0:
            observability.mark_event("auto_unwind_blocked", count=blocked_count)
        if error_count > 0:
            observability.mark_event("auto_unwind_error", count=error_count)

    def _mark_news_feed_events(events: list[dict[str, object]]) -> None:
        if not events:
            return
        observability.mark_event("news_feed_events", count=len(events))
        high_count = sum(
            1
            for item in events
            if str(item.get("severity") or "").strip().lower() in {"high", "critical"}
        )
        if high_count > 0:
            observability.mark_event("news_feed_high_severity_events", count=high_count)

    def _mark_news_compare_events(model_id: str | None) -> None:
        observability.mark_event("news_compare_runs")
        winner = str(model_id or "").strip().lower()
        if winner in {"finbert", "nli"}:
            observability.mark_event(f"news_compare_win_{winner}")

    def _mark_signal_news_bridge_events(rows: list[dict[str, object]], link_count: int) -> None:
        if link_count > 0:
            observability.mark_event("news_signal_links", count=link_count)
        if not rows:
            return
        block_count = sum(
            1 for item in rows if str(item.get("news_gate_action") or "").strip().lower() == "block"
        )
        reduce_count = sum(
            1 for item in rows if str(item.get("news_gate_action") or "").strip().lower() == "reduce"
        )
        if block_count > 0:
            observability.mark_event("news_gate_block", count=block_count)
        if reduce_count > 0:
            observability.mark_event("news_gate_reduce", count=reduce_count)

    refresh_enabled = bool(settings.ui.signal_refresh_enabled)
    refresh_interval = int(settings.ui.signal_refresh_interval_sec or 0)
    refresh_daily_time = _parse_daily_time(settings.ui.signal_refresh_daily_time)
    refresh_tz = _resolve_tz(settings.ui.signal_refresh_timezone, settings.environment.timezone)
    refresh_mode = "daily" if refresh_daily_time else "interval"
    refresh_singleton = bool(getattr(settings.ui, "signal_refresh_singleton", True))
    refresh_lease_sec = max(int(getattr(settings.ui, "signal_refresh_lease_sec", 180) or 0), 30)
    refresh_lease_renew_sec = max(
        int(getattr(settings.ui, "signal_refresh_lease_renew_sec", 30) or 0),
        5,
    )
    refresh_lease_name = "signal_refresh_scheduler"
    refresh_scheduler_owner_id = f"pid-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    incremental_enabled = bool(getattr(settings.ui, "incremental_replay_enabled", True))
    refresh_durations_ms: list[float] = []
    refresh_state = {
        "enabled": refresh_enabled,
        "interval_sec": refresh_interval,
        "mode": refresh_mode,
        "daily_time": settings.ui.signal_refresh_daily_time,
        "timezone": settings.ui.signal_refresh_timezone or settings.environment.timezone,
        "incremental_enabled": incremental_enabled,
        "data_watermark_before": None,
        "data_watermark_after": None,
        "pairs_total": 0,
        "pairs_recomputed": 0,
        "pairs_reused": 0,
        "pairs_skipped": 0,
        "skip_reason": None,
        "ingest_lag_sec": None,
        "cache_hit_ratio": 0.0,
        "fallback_full_replay_count": 0,
        "refresh_duration_ms_p50": 0.0,
        "refresh_duration_ms_p95": 0.0,
        "staleness_age_sec": None,
        "status": "disabled",
        "last_started_at": None,
        "last_success_at": None,
        "last_error": None,
        "next_run_at": None,
        "scheduler_singleton": refresh_singleton,
        "scheduler_role": "follower" if refresh_singleton else "leader",
        "scheduler_owner_id": refresh_scheduler_owner_id,
    }
    refresh_lock = threading.Lock()
    refresh_stop = threading.Event()

    def _acquire_refresh_scheduler_lease() -> bool:
        with session_factory() as session:
            return bool(
                try_acquire_runtime_lease(
                    session,
                    lease_name=refresh_lease_name,
                    owner_id=refresh_scheduler_owner_id,
                    ttl_sec=refresh_lease_sec,
                )
            )

    def _renew_refresh_scheduler_lease() -> bool:
        with session_factory() as session:
            return bool(
                renew_runtime_lease(
                    session,
                    lease_name=refresh_lease_name,
                    owner_id=refresh_scheduler_owner_id,
                    ttl_sec=refresh_lease_sec,
                )
            )

    def _release_refresh_scheduler_lease() -> None:
        with session_factory() as session:
            release_runtime_lease(
                session,
                lease_name=refresh_lease_name,
                owner_id=refresh_scheduler_owner_id,
            )

    def _unified_ttl_sec() -> int:
        return max(int(getattr(settings.ui, "unified_snapshot_ttl_sec", 120) or 0), 1)

    def _resolved_unified_max_pairs(fallback: int | None = None) -> int | None:
        configured = settings.ui.signal_refresh_max_pairs
        if configured is not None and int(configured) > 0:
            return int(configured)
        if fallback is not None and int(fallback) > 0:
            return int(fallback)
        return None

    def _resolve_incremental_checkpoint_root() -> Path:
        configured = Path(str(getattr(settings.ui, "incremental_checkpoint_dir", "./data/state/incremental_replay")))
        if configured.is_absolute():
            return configured
        text = str(configured).replace("\\", "/")
        if text.startswith("./data/"):
            return paths.data_dir / text[len("./data/") :]
        if text.startswith("data/"):
            return paths.data_dir / text[len("data/") :]
        return paths.data_dir / configured

    def _percentile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        data = sorted(float(item) for item in values)
        if len(data) == 1:
            return data[0]
        rank = (len(data) - 1) * max(0.0, min(float(q), 100.0)) / 100.0
        lower = int(rank)
        upper = min(lower + 1, len(data) - 1)
        if lower == upper:
            return data[lower]
        weight = rank - lower
        return data[lower] * (1.0 - weight) + data[upper] * weight

    def _unified_snapshot(
        max_pairs: int | None,
        *,
        force: bool = False,
        ingest_cycle=None,
    ) -> UnifiedMarketSnapshot:
        return build_unified_market_snapshot(
            settings,
            paths.data_dir,
            force=force,
            ttl_sec=_unified_ttl_sec(),
            max_pairs=max_pairs,
            ingest_result_map=(ingest_cycle.pair_results if ingest_cycle is not None else None),
            global_data_watermark_before=(ingest_cycle.global_watermark_before if ingest_cycle is not None else None),
            global_data_watermark_after=(ingest_cycle.global_watermark_after if ingest_cycle is not None else None),
        )

    def _persist_unified_signal_run(max_pairs: int | None, *, force: bool, ingest_cycle=None) -> dict[str, object]:
        snapshot = _unified_snapshot(max_pairs=max_pairs, force=force, ingest_cycle=ingest_cycle)
        require_score_gate_signals = _default_require_score_gate_for_signals(settings)
        signals_all = snapshot.signals.copy()
        top_pairs = snapshot.top_pairs.copy()
        signals_actionable = _apply_score_gate_filter(
            signals_all.copy(),
            require_score_gate=require_score_gate_signals,
        )
        filtered_snapshot = UnifiedMarketSnapshot(
            created_at=snapshot.created_at,
            top_pairs=top_pairs,
            signals=signals_all,
            backtests=snapshot.backtests.copy(),
            warnings=list(snapshot.warnings),
            errors=list(snapshot.errors),
        )
        if settings.ui.signal_refresh_save_csv:
            persist_snapshot_to_csv(filtered_snapshot, paths.data_dir)
        run_id = f"signal-run-{uuid.uuid4().hex[:8]}"
        as_of = datetime.now(timezone.utc)
        params = {
            "max_pairs": max_pairs,
            "engine": "unified_minute_replay",
            "require_score_gate_signals": require_score_gate_signals,
            "require_score_gate_top_pairs": False,
            "signals_total": int(len(signals_all)),
            "signals_actionable": int(len(signals_actionable)),
            "warnings": list(snapshot.warnings),
            "errors": list(snapshot.errors),
        }
        records = signals_all.to_dict("records") if not signals_all.empty else []
        with session_factory() as session:
            store_signal_run(session, run_id, as_of, params)
            if records:
                store_signal_history(session, run_id, as_of, records)
        fallback_count = sum(1 for item in snapshot.warnings if ":fallback:" in str(item))
        return {
            "rows": int(len(signals_actionable)),
            "warnings": list(snapshot.warnings),
            "errors": list(snapshot.errors),
            "fallback_full_replay_count": int(fallback_count),
            "telemetry": get_last_refresh_telemetry(),
        }

    def _load_latest_unified_output(
        *,
        max_pairs: int | None,
        fresh: bool = False,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        preferred_engine = "unified"
        top_pairs = pd.DataFrame()
        signals = pd.DataFrame()
        backtests = pd.DataFrame()
        # Default path: serve the latest unified projection from dedicated engine outputs.
        if not fresh:
            top_pairs, top_pairs_source = load_top_pairs_with_source(
                paths.data_dir,
                preferred_engine=preferred_engine,
            )
            signals, signals_source = load_signals_with_source(
                paths.data_dir,
                preferred_engine=preferred_engine,
            )
            backtests, backtests_source = load_backtest_summary_with_source(
                paths.data_dir,
                preferred_engine=preferred_engine,
            )
            # In unified mode avoid silent mixed projections: fallback-to-legacy triggers recompute.
            if bool(top_pairs_source.get("fallback_to_legacy")):
                top_pairs = pd.DataFrame()
            if bool(signals_source.get("fallback_to_legacy")):
                signals = pd.DataFrame()
            if bool(backtests_source.get("fallback_to_legacy")):
                backtests = pd.DataFrame()
        if top_pairs.empty or signals.empty or backtests.empty:
            snapshot = _unified_snapshot(max_pairs=max_pairs, force=False)
            if top_pairs.empty:
                top_pairs = snapshot.top_pairs.copy()
            if signals.empty:
                signals = snapshot.signals.copy()
            if backtests.empty:
                backtests = snapshot.backtests.copy()
        return top_pairs, signals, backtests

    def _run_signal_refresh(trigger: str, force: bool = False) -> bool:
        if not refresh_enabled and trigger != "manual":
            refresh_state["status"] = "disabled"
            refresh_state["last_error"] = f"skip:{trigger}"
            return False
        if refresh_lock.locked():
            refresh_state["status"] = "busy"
            refresh_state["last_error"] = f"skip:{trigger}"
            return False
        with refresh_lock:
            started = datetime.now(timezone.utc)
            refresh_state["status"] = "running"
            refresh_state["last_started_at"] = _iso_now()
            refresh_state["last_error"] = None
            try:
                if settings.ui.use_unified_signal_engine:
                    max_pairs = _resolved_unified_max_pairs(settings.ui.signal_refresh_max_pairs)
                    ingest_cycle = None
                    if incremental_enabled and not force:
                        ingest_pairs = list_unified_ingest_pairs(
                            settings,
                            paths.data_dir,
                            max_pairs=max_pairs,
                        )
                        ingest_cycle = run_incremental_minute_ingest(
                            settings=settings,
                            data_dir=paths.data_dir,
                            checkpoint_root=_resolve_incremental_checkpoint_root(),
                            pairs=ingest_pairs,
                            overlap_minutes=max(int(getattr(settings.ui, "incremental_overlap_minutes", 180) or 0), 1),
                        )
                        refresh_state["data_watermark_before"] = ingest_cycle.global_watermark_before
                        refresh_state["data_watermark_after"] = ingest_cycle.global_watermark_after
                        lag_values = [
                            float(item.ingest_lag_sec)
                            for item in ingest_cycle.pair_results.values()
                            if item.ingest_lag_sec is not None
                        ]
                        refresh_state["ingest_lag_sec"] = max(lag_values) if lag_values else None
                        if ingest_cycle.degraded:
                            observability.mark_event("incremental_ingest_degraded")
                    refresh_payload = _persist_unified_signal_run(
                        max_pairs,
                        force=force,
                        ingest_cycle=ingest_cycle,
                    )
                    refresh_state["rows"] = int(refresh_payload.get("rows") or 0)
                    refresh_state["engine"] = "unified_minute_replay"
                    refresh_state["fallback_full_replay_count"] = int(
                        refresh_payload.get("fallback_full_replay_count") or 0
                    )
                    telemetry = refresh_payload.get("telemetry")
                    if isinstance(telemetry, dict):
                        refresh_state["incremental_enabled"] = bool(
                            telemetry.get("incremental_enabled", incremental_enabled)
                        )
                        refresh_state["data_watermark_before"] = telemetry.get("data_watermark_before")
                        refresh_state["data_watermark_after"] = telemetry.get("data_watermark_after")
                        refresh_state["pairs_total"] = int(telemetry.get("pairs_total") or 0)
                        refresh_state["pairs_recomputed"] = int(telemetry.get("pairs_recomputed") or 0)
                        refresh_state["pairs_reused"] = int(telemetry.get("pairs_reused") or 0)
                        refresh_state["pairs_skipped"] = int(telemetry.get("pairs_skipped") or 0)
                        refresh_state["skip_reason"] = telemetry.get("skip_reason")
                        pairs_total = max(int(refresh_state["pairs_total"]), 1)
                        refresh_state["cache_hit_ratio"] = float(refresh_state["pairs_reused"]) / float(pairs_total)
                        if refresh_state["skip_reason"]:
                            observability.mark_event(
                                f"refresh_skip_{str(refresh_state['skip_reason']).strip().lower()}",
                            )
                    if refresh_state["fallback_full_replay_count"] > 0:
                        observability.mark_event(
                            "incremental_full_fallback",
                            count=int(refresh_state["fallback_full_replay_count"]),
                        )
                    degraded_mode = bool(ingest_cycle is not None and ingest_cycle.degraded)
                    if degraded_mode:
                        refresh_state["status"] = "degraded"
                    else:
                        refresh_state["status"] = "ok"
                        refresh_state["last_success_at"] = _iso_now()
                else:
                    run_signal_cycle(
                        settings,
                        max_pairs=settings.ui.signal_refresh_max_pairs,
                        save_csv=settings.ui.signal_refresh_save_csv,
                    )
                    refresh_state["engine"] = "legacy_pipeline"
                    refresh_state["status"] = "ok"
                    refresh_state["last_success_at"] = _iso_now()
            except Exception as exc:
                refresh_state["last_error"] = str(exc)
                refresh_state["status"] = "error"
                logger.exception("Signal refresh failed")
                return False
            finally:
                duration_ms = max((datetime.now(timezone.utc) - started).total_seconds() * 1000.0, 0.0)
                refresh_durations_ms.append(duration_ms)
                if len(refresh_durations_ms) > 500:
                    del refresh_durations_ms[: len(refresh_durations_ms) - 500]
                refresh_state["refresh_duration_ms_p50"] = _percentile(refresh_durations_ms, 50.0)
                refresh_state["refresh_duration_ms_p95"] = _percentile(refresh_durations_ms, 95.0)
                if refresh_state.get("status") == "degraded":
                    last_success = pd.to_datetime(refresh_state.get("last_success_at"), errors="coerce")
                    if not pd.isna(last_success):
                        refresh_state["staleness_age_sec"] = max(
                            (datetime.now(timezone.utc) - last_success.to_pydatetime().replace(tzinfo=timezone.utc)).total_seconds(),
                            0.0,
                        )
                    else:
                        refresh_state["staleness_age_sec"] = None
                else:
                    refresh_state["staleness_age_sec"] = 0.0
        return True

    refresh_scheduler = SignalRefreshScheduler(
        enabled=refresh_enabled,
        refresh_interval_sec=refresh_interval,
        refresh_daily_time=refresh_daily_time,
        refresh_tz=refresh_tz,
        refresh_singleton=refresh_singleton,
        refresh_lease_sec=refresh_lease_sec,
        refresh_lease_renew_sec=refresh_lease_renew_sec,
        refresh_state=refresh_state,
        refresh_stop=refresh_stop,
        run_signal_refresh=_run_signal_refresh,
        acquire_lease=_acquire_refresh_scheduler_lease,
        renew_lease=_renew_refresh_scheduler_lease,
        release_lease=_release_refresh_scheduler_lease,
        next_daily_run=_next_daily_run,
        logger=logger,
        daily_time_label=settings.ui.signal_refresh_daily_time,
    )
    refresh_scheduler.start()

    api_request_id_key = "_api_v2_request_id"
    max_api_payload_bytes = int(getattr(settings.ui, "max_api_payload_bytes", 262144) or 262144)
    if max_api_payload_bytes <= 0:
        max_api_payload_bytes = 262144

    def _resolve_api_request_id() -> str:
        candidate = (
            request.headers.get("X-Request-Id")
            or request.headers.get("X-Request-ID")
            or request.headers.get("X-Correlation-Id")
            or request.headers.get("X-Correlation-ID")
        )
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
        return f"req-{uuid.uuid4().hex[:20]}"

    @server.before_request
    def _capture_request_started_at():
        request.environ[request_started_at_key] = datetime.now(timezone.utc).timestamp()
        if not request.path.startswith("/api/v2/"):
            return None

        request_id = _resolve_api_request_id()
        request.environ[api_request_id_key] = request_id
        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.content_length
            if content_length is not None and int(content_length) > max_api_payload_bytes:
                response = jsonify(
                    {
                        "error": "payload_too_large",
                        "message": (
                            "request payload exceeds max_api_payload_bytes "
                            f"({int(content_length)} > {max_api_payload_bytes})"
                        ),
                        "max_api_payload_bytes": max_api_payload_bytes,
                    }
                )
                response.status_code = 413
                response.headers["X-Request-Id"] = request_id
                return response
        return None

    @server.after_request
    def _cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, X-Request-Id, X-Request-ID, X-Correlation-Id, X-Correlation-ID"
        )
        response.headers["Access-Control-Expose-Headers"] = "X-Request-Id"

        successor = _deprecated_v1_successor_path(request.path)
        if successor is not None:
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = _V1_DEPRECATION_SUNSET_HTTP
            response.headers["X-API-Deprecated"] = "v1"
            response.headers["X-API-Sunset-Date"] = _V1_DEPRECATION_SUNSET_DATE
            warning_text = (
                f'299 - "Deprecated API v1 endpoint; migrate to {successor} '
                f'before {_V1_DEPRECATION_SUNSET_DATE}"'
            )
            response.headers["Warning"] = warning_text
            link_value = f'<{successor}>; rel="successor-version"'
            existing_link = response.headers.get("Link")
            response.headers["Link"] = (
                f"{existing_link}, {link_value}" if existing_link else link_value
            )

        if request.path.startswith("/api/v2/"):
            request_id = str(request.environ.get(api_request_id_key) or _resolve_api_request_id())
            response.headers["X-Request-Id"] = request_id
            try:
                started_value = request.environ.get(request_started_at_key)
                duration_ms = 0.0
                if started_value is not None:
                    duration_ms = max(
                        (datetime.now(timezone.utc).timestamp() - float(started_value)) * 1000.0,
                        0.0,
                    )
                emit_api_log(
                    logger,
                    component="api-v2",
                    path=request.path,
                    method=request.method,
                    status_code=response.status_code,
                    request_id=str(request_id),
                    duration_ms=duration_ms,
                )
            except Exception:
                logger.exception("Failed to emit structured API log")

        return response

    def _decision_exists(decision_id: str) -> bool:
        log_path = decisions_dir / "decision_log.jsonl"
        view_path = decisions_dir / "decision_view.jsonl"
        records = load_jsonl(log_path) if log_path.exists() else []
        if any(str(record.get("decision_id") or "") == decision_id for record in records):
            return True
        view_records = load_jsonl(view_path) if view_path.exists() else []
        return any(str(record.get("decision_id") or "") == decision_id for record in view_records)

    decision_action_service = DecisionActionService(
        actions_path=actions_path,
        executions_path=executions_path,
        decision_exists=_decision_exists,
        bad_request=_bad_request,
        stable_id=_stable_id,
        iso_now=_iso_now,
        append_jsonl=_append_jsonl,
        json_response=jsonify,
    )

    def _record_decision_action(
        decision_id: str,
        payload: dict[str, object],
        *,
        source_default: str,
        allowed_actions: set[str] | None = None,
        require_idempotency: bool = True,
    ):
        return decision_action_service.record(
            decision_id,
            payload,
            source_default=source_default,
            allowed_actions=allowed_actions,
            require_idempotency=require_idempotency,
        )

    @server.route("/api/signals/refresh-status", methods=["GET"])
    def signals_refresh_status_api():
        return jsonify(refresh_state)

    @server.route("/api/signals/refresh", methods=["POST"])
    def signals_refresh_api():
        if refresh_lock.locked():
            return jsonify({**refresh_state, "status": "busy"}), 409
        payload = request.get_json(silent=True)
        force_full = False
        if isinstance(payload, dict):
            force_full = bool(_parse_bool(payload.get("force_full")))
        elif request.args:
            force_full = bool(_parse_bool(request.args.get("force_full")))
        ok = _run_signal_refresh("manual", force=force_full)
        status_code = 200 if ok else 500
        return jsonify(refresh_state), status_code


    @server.route("/api/projections/source", methods=["GET"])
    def projection_source_api():
        preferred_engine = "unified" if settings.ui.use_unified_signal_engine else None
        payload = load_projection_sources(
            paths.data_dir,
            preferred_engine=preferred_engine,
        )
        payload["active_engine"] = "unified" if settings.ui.use_unified_signal_engine else "legacy"
        payload["unified_allow_legacy_fallback"] = bool(settings.ui.unified_allow_legacy_fallback)
        return jsonify(payload)

    @server.route("/api/decision-view", methods=["GET"])
    def decision_view_api():
        limit = max(_parse_int(request.args.get("limit"), 500), 0)

        def _load_decision_view_jsonl_rows() -> list[dict[str, object]]:
            view_path = paths.data_dir / "decisions" / "decision_view.jsonl"
            records = load_jsonl(view_path)
            df = pd.DataFrame(records)
            df = _apply_query_filters(df, request.args)
            df = df.sort_values("created_at", ascending=False) if not df.empty else df
            if limit > 0:
                df = df.head(limit)
            return _df_to_records(df)

        projection_source = "jsonl"
        if settings.ui.ff_db_projection_source:
            view_path = paths.data_dir / "decisions" / "decision_view.jsonl"
            jsonl_rows = load_jsonl(view_path) if view_path.exists() else []
            jsonl_rows = [row for row in jsonl_rows if isinstance(row, dict)]
            if jsonl_rows:
                with session_factory() as session:
                    upsert_decision_view_projection(session, jsonl_rows)
            with session_factory() as session:
                response_rows = load_decision_view_projection(
                    session,
                    limit=limit,
                    strategy_type=request.args.get("strategy_type"),
                    primary_instrument=request.args.get("primary_instrument"),
                    risk_state=request.args.get("risk_state"),
                    news_severity=request.args.get("news_severity"),
                    created_from=request.args.get("created_from"),
                    created_to=request.args.get("created_to"),
                )
            projection_source = "db"
        else:
            response_rows = _load_decision_view_jsonl_rows()

        action_records = load_jsonl(actions_path) if actions_path.exists() else []
        execution_records = load_jsonl(executions_path) if executions_path.exists() else []
        latest_actions = _latest_by_decision_id(action_records)
        latest_executions = _latest_by_decision_id(execution_records)
        for row in response_rows:
            decision_id = row.get("decision_id")
            if not decision_id:
                continue
            action = latest_actions.get(decision_id)
            if isinstance(action, dict):
                row["operator_action"] = {
                    "action_id": action.get("action_id"),
                    "action": action.get("action"),
                    "status": action.get("status"),
                    "actor": action.get("actor"),
                    "source": action.get("source"),
                    "reason_code": action.get("reason_code"),
                    "note": action.get("note"),
                    "comment": action.get("comment"),
                    "idempotency_key": action.get("idempotency_key"),
                    "created_at": action.get("created_at"),
                }
            execution = latest_executions.get(decision_id)
            if isinstance(execution, dict):
                row["execution_status"] = {
                    "request_id": execution.get("request_id"),
                    "action": execution.get("action"),
                    "status": execution.get("status"),
                    "requested_at": execution.get("requested_at"),
                    "executed_at": execution.get("executed_at"),
                    "actor": execution.get("actor"),
                    "source": execution.get("source"),
                    "reason_code": execution.get("reason_code"),
                    "note": execution.get("note"),
                    "idempotency_key": execution.get("idempotency_key"),
                }
            row["projection_source"] = projection_source
        return jsonify(response_rows)

    @server.route("/api/v2/decisions/view", methods=["GET"])
    @server.route("/api/v2/decision-view", methods=["GET"])
    def decision_view_v2_api():
        legacy = decision_view_api()
        rows, status_code = _extract_response_payload(legacy)
        if status_code >= 400:
            return legacy
        if not isinstance(rows, list):
            return jsonify([])
        projection_version = "v2.0"
        payload: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            decision_id = str(row.get("decision_id") or "").strip() or None
            primary = str(row.get("primary_instrument") or "").strip()
            operator_action = row.get("operator_action")
            execution_status = row.get("execution_status")
            operator_action = operator_action if isinstance(operator_action, dict) else {}
            execution_status = execution_status if isinstance(execution_status, dict) else {}
            entity_ref = {
                "entity_type": "instrument",
                "entity_id": primary,
                "ticker": primary or None,
            }
            decision_ref = {
                "decision_id": decision_id,
                "action_id": operator_action.get("action_id"),
                "latest_action": operator_action.get("action"),
                "latest_status": operator_action.get("status"),
                "actor_id": operator_action.get("actor"),
                "source": operator_action.get("source"),
                "idempotency_key": operator_action.get("idempotency_key"),
                "updated_at": operator_action.get("created_at"),
            }
            execution_ref = {
                "request_id": execution_status.get("request_id"),
                "action": execution_status.get("action"),
                "status": execution_status.get("status"),
                "requested_at": execution_status.get("requested_at"),
                "executed_at": execution_status.get("executed_at"),
                "actor_id": execution_status.get("actor"),
                "source": execution_status.get("source"),
                "reason_code": execution_status.get("reason_code"),
                "idempotency_key": execution_status.get("idempotency_key"),
            }
            enriched = dict(row)
            enriched["projection_version"] = projection_version
            enriched["decision_ref"] = decision_ref
            enriched["entity_ref"] = entity_ref
            enriched["execution_ref"] = execution_ref
            payload.append(enriched)
        return jsonify(payload)

    @server.route("/api/decision-log/<decision_id>", methods=["GET"])
    def decision_log_api(decision_id: str):
        log_path = paths.data_dir / "decisions" / "decision_log.jsonl"
        records = load_jsonl(log_path)
        for record in records:
            if record.get("decision_id") == decision_id:
                return jsonify(record)
        return jsonify({"error": "not_found"}), 404

    @server.route("/api/v2/news/feed", methods=["GET"])
    def news_feed_v2_api():
        started_at = datetime.now(timezone.utc)
        severity_filter = str(request.args.get("severity") or "").strip().lower()
        ticker_filter = str(request.args.get("ticker") or "").strip().upper()
        entity_filter = str(request.args.get("entity_id") or "").strip()
        from_raw = request.args.get("from")
        to_raw = request.args.get("to")
        from_ts = _parse_date_bound(from_raw, "start") if from_raw else None
        to_ts = _parse_date_bound(to_raw, "end") if to_raw else None
        if from_raw and from_ts is None:
            return _observe_request(
                "v2_news_feed",
                started_at,
                (jsonify({"error": "invalid_from"}), 400),
            )
        if to_raw and to_ts is None:
            return _observe_request(
                "v2_news_feed",
                started_at,
                (jsonify({"error": "invalid_to"}), 400),
            )

        limit = _parse_int(request.args.get("limit"), 200)
        preferred_models = [settings.news_models.primary_model] + list(settings.news_models.enabled_models)
        with session_factory() as session:
            events = _build_news_feed_events_from_event_layer(
                session,
                severity_filter=severity_filter or None,
                ticker_filter=ticker_filter or None,
                entity_filter=entity_filter or None,
                from_ts=from_ts,
                to_ts=to_ts,
                limit=limit,
                preferred_models=preferred_models,
            )
            if not events:
                bundle = _load_news_bundle(
                    session,
                    from_ts=from_ts,
                    to_ts=to_ts,
                    limit=max(limit, 200),
                    preferred_models=preferred_models,
                )
                events = _build_news_feed_events(
                    bundle=bundle,
                    severity_filter=severity_filter or None,
                    ticker_filter=ticker_filter or None,
                    entity_filter=entity_filter or None,
                    from_ts=from_ts,
                    to_ts=to_ts,
                )

        if not events:
            # Backward compatibility fallback while storage is warming up.
            log_path = paths.data_dir / "decisions" / "decision_log.jsonl"
            view_path = paths.data_dir / "decisions" / "decision_view.jsonl"
            log_records = load_jsonl(log_path)
            view_records = load_jsonl(view_path)
            view_by_decision = {
                str(item.get("decision_id") or ""): item for item in view_records if isinstance(item, dict)
            }
            for record in log_records:
                if not isinstance(record, dict):
                    continue
                decision_id = str(record.get("decision_id") or "").strip()
                created_at_raw = str(record.get("created_at") or "").strip()
                if not decision_id or not created_at_raw:
                    continue
                created_at_cmp = _parse_iso_datetime(created_at_raw)
                if created_at_cmp is None:
                    continue
                if from_ts and created_at_cmp < from_ts:
                    continue
                if to_ts and created_at_cmp > to_ts:
                    continue

                news_context = record.get("news_context")
                if not isinstance(news_context, dict):
                    continue
                severity = str(news_context.get("severity") or "low").strip().lower()
                if severity_filter and severity != severity_filter:
                    continue

                view_row = view_by_decision.get(decision_id, {})
                primary = str(view_row.get("primary_instrument") or "").strip()
                if ticker_filter and ticker_filter != primary.upper():
                    continue
                if entity_filter and entity_filter != primary:
                    continue

                summary = str(news_context.get("summary") or "news_signal").strip() or "news_signal"
                headline = str(news_context.get("headline") or summary).strip() or summary
                event_id = _stable_id(
                    "news",
                    decision_id,
                    created_at_raw,
                    severity,
                    headline,
                    summary,
                    length=20,
                )
                events.append(
                    {
                        "news_event_id": event_id,
                        "news_id": event_id,
                        "published_at": created_at_raw,
                        "ingested_at": created_at_raw,
                        "source": "decision_log",
                        "language": None,
                        "url": None,
                        "severity": severity,
                        "headline": headline,
                        "summary": summary,
                        "headline_count": int(news_context.get("headline_count") or 0),
                        "decision_ref": {"decision_id": decision_id},
                        "entity_links": [
                            {
                                "entity_type": "instrument",
                                "entity_id": primary,
                                "ticker": primary or None,
                            }
                        ],
                        "tags": [],
                        "model_scores": [],
                        "signal_refs": [],
                    }
                )

        events.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
        if limit > 0:
            events = events[:limit]
        _mark_news_feed_events(events)
        return _observe_request("v2_news_feed", started_at, jsonify(events))

    @server.route("/api/v2/events", methods=["GET"])
    def events_v2_api():
        started_at = datetime.now(timezone.utc)
        event_status = str(request.args.get("status") or "").strip().lower() or None
        from_raw = request.args.get("from")
        to_raw = request.args.get("to")
        from_ts = _parse_date_bound(from_raw, "start") if from_raw else None
        to_ts = _parse_date_bound(to_raw, "end") if to_raw else None
        if from_raw and from_ts is None:
            return _observe_request("v2_events", started_at, _bad_request("invalid_from"))
        if to_raw and to_ts is None:
            return _observe_request("v2_events", started_at, _bad_request("invalid_to"))
        limit = max(_parse_int(request.args.get("limit"), 200), 0)

        with session_factory() as session:
            events = load_news_events(
                session,
                event_status=event_status,
                published_from=_isoformat_utc(from_ts),
                published_to=_isoformat_utc(to_ts),
                limit=limit,
            )
            event_ids = [str(item.get("event_id") or "").strip() for item in events if item.get("event_id")]
            event_items = load_news_event_items(
                session,
                event_ids=event_ids,
                limit=max(len(event_ids) * 30, 1000),
            )

        item_count_by_event: dict[str, int] = {}
        first_news_by_event: dict[str, str] = {}
        for row in event_items:
            event_id = str(row.get("event_id") or "").strip()
            news_id = str(row.get("news_id") or "").strip()
            if not event_id:
                continue
            item_count_by_event[event_id] = int(item_count_by_event.get(event_id, 0)) + 1
            if news_id and event_id not in first_news_by_event:
                first_news_by_event[event_id] = news_id

        payload: list[dict[str, object]] = []
        for row in events:
            event_id = str(row.get("event_id") or "").strip()
            if not event_id:
                continue
            payload.append(
                {
                    "event_id": event_id,
                    "event_status": row.get("event_status"),
                    "event_first_published_at_utc": row.get("event_first_published_at_utc"),
                    "event_first_ingested_at_utc": row.get("event_first_ingested_at_utc"),
                    "event_last_published_at_utc": row.get("event_last_published_at_utc"),
                    "canonical_summary": row.get("canonical_summary"),
                    "canonical_mechanism": row.get("canonical_mechanism"),
                    "cluster_version": row.get("cluster_version"),
                    "news_count": int(item_count_by_event.get(event_id, 0)),
                    "primary_news_id": first_news_by_event.get(event_id),
                }
            )
        return _observe_request("v2_events", started_at, jsonify(payload))

    @server.route("/api/v2/events/fragmentation", methods=["GET"])
    def events_fragmentation_v2_api():
        started_at = datetime.now(timezone.utc)
        from_raw = request.args.get("from")
        to_raw = request.args.get("to")
        from_ts = _parse_date_bound(from_raw, "start") if from_raw else None
        to_ts = _parse_date_bound(to_raw, "end") if to_raw else None
        if from_raw and from_ts is None:
            return _observe_request("v2_events_fragmentation", started_at, _bad_request("invalid_from"))
        if to_raw and to_ts is None:
            return _observe_request("v2_events_fragmentation", started_at, _bad_request("invalid_to"))
        with session_factory() as session:
            payload = compute_event_fragmentation_report(
                session,
                published_from=from_ts,
                published_to=to_ts,
            )
        return _observe_request("v2_events_fragmentation", started_at, jsonify(payload))

    @server.route("/api/v2/events/<event_id>", methods=["GET"])
    def event_details_v2_api(event_id: str):
        started_at = datetime.now(timezone.utc)
        event_key = str(event_id or "").strip()
        if not event_key:
            return _observe_request("v2_event_details", started_at, _bad_request("event_id is required"))

        with session_factory() as session:
            event_rows = load_news_events(session, event_ids=[event_key], limit=1)
            if not event_rows:
                return _observe_request(
                    "v2_event_details",
                    started_at,
                    (jsonify({"error": "not_found", "event_id": event_key}), 404),
                )
            event_items = load_news_event_items(session, event_ids=[event_key], limit=500)
            news_ids = [str(row.get("news_id") or "").strip() for row in event_items if row.get("news_id")]
            news_rows = load_news_items_by_ids(session, news_ids)
            labels = load_news_labels(session, target_level="event", target_ids=[event_key], limit=200)
            llm_runs = load_news_llm_runs(session, target_level="event", target_id=event_key, limit=200)
            model_scores = load_news_impact_scores(
                session,
                target_level="event",
                target_ids=[event_key],
                limit=200,
            )
            signal_refs = load_news_signal_links(session, event_ids=[event_key], limit=500)
            reactions_preview = load_event_market_reactions(session, event_ids=[event_key], limit=200)

        payload = dict(event_rows[0])
        payload["news_items"] = news_rows
        payload["event_items"] = event_items
        payload["labels"] = labels
        payload["llm_runs"] = llm_runs
        payload["model_scores"] = model_scores
        payload["signal_refs"] = signal_refs
        payload["reactions_preview"] = reactions_preview
        return _observe_request("v2_event_details", started_at, jsonify(payload))

    @server.route("/api/v2/events/<event_id>/reaction", methods=["GET"])
    def event_reaction_v2_api(event_id: str):
        started_at = datetime.now(timezone.utc)
        event_key = str(event_id or "").strip()
        if not event_key:
            return _observe_request("v2_event_reaction", started_at, _bad_request("event_id is required"))
        instrument_id = str(request.args.get("instrument_id") or "").strip() or None
        window_id = str(request.args.get("window_id") or request.args.get("window") or "").strip() or None
        sampling_freq = str(request.args.get("sampling_freq") or "").strip() or None
        limit = max(_parse_int(request.args.get("limit"), 500), 0)

        with session_factory() as session:
            rows = load_event_market_reactions(
                session,
                event_ids=[event_key],
                instrument_id=instrument_id,
                window_id=window_id,
                sampling_freq=sampling_freq,
                limit=limit,
            )
        return _observe_request(
            "v2_event_reaction",
            started_at,
            jsonify(
                {
                    "event_id": event_key,
                    "instrument_id": instrument_id,
                    "window_id": window_id,
                    "sampling_freq": sampling_freq,
                    "rows": rows,
                }
            ),
        )

    @server.route("/api/v2/signals/top", methods=["GET"])
    def signals_top_v2_api():
        started_at = datetime.now(timezone.utc)
        commodity = str(request.args.get("commodity") or "").strip().upper() or None
        k = max(_parse_int(request.args.get("k"), 20), 1)
        from_raw = request.args.get("from")
        to_raw = request.args.get("to")
        from_ts = _parse_date_bound(from_raw, "start") if from_raw else None
        to_ts = _parse_date_bound(to_raw, "end") if to_raw else None
        if from_raw and from_ts is None:
            return _observe_request("v2_signals_top", started_at, _bad_request("invalid_from"))
        if to_raw and to_ts is None:
            return _observe_request("v2_signals_top", started_at, _bad_request("invalid_to"))

        preferred_models = [settings.news_models.primary_model] + list(settings.news_models.enabled_models)
        with session_factory() as session:
            feed_rows = _build_news_feed_events_from_event_layer(
                session,
                severity_filter=None,
                ticker_filter=commodity,
                entity_filter=None,
                from_ts=from_ts,
                to_ts=to_ts,
                limit=max(k * 20, 200),
                preferred_models=preferred_models,
            )
            if not feed_rows:
                bundle = _load_news_bundle(
                    session,
                    from_ts=from_ts,
                    to_ts=to_ts,
                    limit=max(k * 20, 200),
                    preferred_models=preferred_models,
                )
                feed_rows = _build_news_feed_events(
                    bundle=bundle,
                    severity_filter=None,
                    ticker_filter=commodity,
                    entity_filter=None,
                    from_ts=from_ts,
                    to_ts=to_ts,
                )

        ranked: list[dict[str, object]] = []
        for row in feed_rows:
            model_scores = row.get("model_scores")
            score = _select_primary_model_score(
                model_scores if isinstance(model_scores, list) else [],
                preferred_models,
            )
            impact_score = float(score.get("impact_score") or 0.0) if isinstance(score, dict) else 0.0
            ranked.append(
                {
                    "news_event_id": row.get("news_event_id"),
                    "published_at": row.get("published_at"),
                    "headline": row.get("headline"),
                    "summary": row.get("summary"),
                    "severity": row.get("severity"),
                    "entity_links": row.get("entity_links"),
                    "tags": row.get("tags"),
                    "impact_score": impact_score,
                    "direction": (score or {}).get("direction") if isinstance(score, dict) else None,
                    "confidence": max(
                        float((score or {}).get("prob_up") or 0.0),
                        float((score or {}).get("prob_down") or 0.0),
                        float((score or {}).get("prob_neutral") or 0.0),
                    )
                    if isinstance(score, dict)
                    else None,
                }
            )
        ranked.sort(key=lambda item: abs(float(item.get("impact_score") or 0.0)), reverse=True)
        return _observe_request("v2_signals_top", started_at, jsonify(ranked[:k]))

    @server.route("/api/v2/annotations", methods=["POST"])
    def annotations_v2_api():
        started_at = datetime.now(timezone.utc)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _observe_request("v2_annotations", started_at, _bad_request("payload must be object"))
        target_level = str(payload.get("target_level") or "").strip().lower()
        target_id = str(payload.get("target_id") or "").strip()
        if not target_level or not target_id:
            return _observe_request(
                "v2_annotations",
                started_at,
                _bad_request("target_level and target_id are required"),
            )
        row = {
            "annotation_id": payload.get("annotation_id"),
            "target_level": target_level,
            "target_id": target_id,
            "payload_json": payload.get("payload_json")
            if isinstance(payload.get("payload_json"), (dict, list))
            else payload.get("payload"),
            "author_id": payload.get("author_id"),
            "reason": payload.get("reason"),
            "version": payload.get("version") or "v1",
            "created_at": payload.get("created_at"),
        }
        with session_factory() as session:
            stored = upsert_news_annotations(session, [row])
            latest = load_news_annotations(
                session,
                target_level=target_level,
                target_id=target_id,
                limit=1,
            )
        return _observe_request(
            "v2_annotations",
            started_at,
            jsonify(
                {
                    "status": "ok",
                    "stored": stored,
                    "latest": latest[0] if latest else None,
                }
            ),
        )

    @server.route("/api/v2/models/versions", methods=["GET"])
    def models_versions_v2_api():
        started_at = datetime.now(timezone.utc)
        with session_factory() as session:
            score_rows = load_news_impact_scores(session, limit=5000)
            llm_runs = load_news_llm_runs(session, limit=5000)
        local_models: dict[str, set[str]] = {}
        for row in score_rows:
            model_id = str(row.get("model_id") or "").strip()
            model_version = str(row.get("model_version") or "").strip() or "unknown"
            if not model_id:
                continue
            local_models.setdefault(model_id, set()).add(model_version)
        llm_models: dict[str, dict[str, object]] = {}
        for row in llm_runs:
            provider = str(row.get("provider") or "").strip() or "unknown"
            model_id = str(row.get("model_id") or "").strip() or "unknown"
            key = f"{provider}:{model_id}"
            entry = llm_models.setdefault(
                key,
                {
                    "provider": provider,
                    "model_id": model_id,
                    "prompt_versions": set(),
                    "statuses": {},
                    "runs": 0,
                },
            )
            prompt_version = str(row.get("prompt_version") or "").strip()
            if prompt_version:
                entry["prompt_versions"].add(prompt_version)
            status = str(row.get("status") or "").strip() or "unknown"
            statuses = entry.get("statuses")
            if isinstance(statuses, dict):
                statuses[status] = int(statuses.get(status, 0)) + 1
            entry["runs"] = int(entry.get("runs", 0)) + 1

        llm_payload: list[dict[str, object]] = []
        for item in llm_models.values():
            prompt_versions = item.get("prompt_versions")
            llm_payload.append(
                {
                    "provider": item.get("provider"),
                    "model_id": item.get("model_id"),
                    "prompt_versions": sorted(prompt_versions) if isinstance(prompt_versions, set) else [],
                    "statuses": item.get("statuses"),
                    "runs": item.get("runs"),
                }
            )
        local_payload = [
            {"model_id": model_id, "versions": sorted(versions)}
            for model_id, versions in sorted(local_models.items())
        ]
        return _observe_request(
            "v2_models_versions",
            started_at,
            jsonify({"local_models": local_payload, "llm_models": llm_payload}),
        )

    @server.route("/api/v2/validation/summary", methods=["GET"])
    def validation_summary_v2_api():
        started_at = datetime.now(timezone.utc)
        with session_factory() as session:
            event_rows = load_news_events(session, limit=0)
            event_ids = [str(row.get("event_id") or "").strip() for row in event_rows if row.get("event_id")]
            event_item_rows = load_news_event_items(session, event_ids=event_ids, limit=0) if event_ids else []
            label_rows = load_news_labels(session, limit=0)
            score_rows = load_news_impact_scores(session, limit=0)
            reaction_rows = load_event_market_reactions(session, limit=0)
            llm_rows = load_news_llm_runs(session, limit=0)
            annotation_rows = load_news_annotations(session, limit=0)
            eval_rows = load_news_model_eval_records(session, limit=5000)
            unmatched_rows = load_news_unmatched_gold(session, limit=0)
            fragmentation_report = compute_event_fragmentation_report(session)

        event_status_counts: dict[str, int] = {}
        for row in event_rows:
            key = str(row.get("event_status") or "unknown").strip() or "unknown"
            event_status_counts[key] = int(event_status_counts.get(key, 0)) + 1

        label_source_counts: dict[str, int] = {}
        for row in label_rows:
            key = str(row.get("label_source") or "unknown").strip() or "unknown"
            label_source_counts[key] = int(label_source_counts.get(key, 0)) + 1

        model_counts: dict[str, int] = {}
        for row in score_rows:
            key = str(row.get("model_id") or "unknown").strip() or "unknown"
            model_counts[key] = int(model_counts.get(key, 0)) + 1

        llm_status_counts: dict[str, int] = {}
        for row in llm_rows:
            key = str(row.get("status") or "unknown").strip() or "unknown"
            llm_status_counts[key] = int(llm_status_counts.get(key, 0)) + 1

        promotion_state_counts: dict[str, int] = {}
        for row in eval_rows:
            key = str(row.get("promotion_state") or "unknown").strip() or "unknown"
            promotion_state_counts[key] = int(promotion_state_counts.get(key, 0)) + 1

        payload = {
            "events_total": len(event_rows),
            "event_items_total": len(event_item_rows),
            "event_status_counts": event_status_counts,
            "labels_total": len(label_rows),
            "label_source_counts": label_source_counts,
            "impact_scores_total": len(score_rows),
            "impact_model_counts": model_counts,
            "llm_runs_total": len(llm_rows),
            "llm_status_counts": llm_status_counts,
            "reactions_total": len(reaction_rows),
            "annotations_total": len(annotation_rows),
            "model_eval_records_total": len(eval_rows),
            "promotion_state_counts": promotion_state_counts,
            "unmatched_gold_total": len(unmatched_rows),
            "fragmentation": fragmentation_report,
        }
        return _observe_request("v2_validation_summary", started_at, jsonify(payload))

    @server.route("/api/v2/validation/event-study", methods=["GET"])
    def validation_event_study_v2_api():
        started_at = datetime.now(timezone.utc)
        commodity = str(request.args.get("commodity") or "").strip().upper()
        window_id = str(request.args.get("window_id") or request.args.get("window") or "").strip() or None
        sampling_freq = str(request.args.get("sampling_freq") or "").strip() or None
        event_time_mode = str(request.args.get("event_time_mode") or "published").strip().lower() or "published"
        if event_time_mode not in {"published", "ingested"}:
            return _observe_request("v2_validation_event_study", started_at, _bad_request("invalid_event_time_mode"))
        from_raw = request.args.get("from")
        to_raw = request.args.get("to")
        from_ts = _parse_date_bound(from_raw, "start") if from_raw else None
        to_ts = _parse_date_bound(to_raw, "end") if to_raw else None
        if from_raw and from_ts is None:
            return _observe_request("v2_validation_event_study", started_at, _bad_request("invalid_from"))
        if to_raw and to_ts is None:
            return _observe_request("v2_validation_event_study", started_at, _bad_request("invalid_to"))
        exclude_overlap = bool(_parse_bool(request.args.get("exclude_overlap")) or False)
        audit_leakage_raw = _parse_bool(request.args.get("audit_leakage"))
        audit_leakage = True if audit_leakage_raw is None else bool(audit_leakage_raw)
        rebuild_if_missing_param = _parse_bool(request.args.get("rebuild_if_missing"))
        rebuild_if_missing = True if rebuild_if_missing_param is None else bool(rebuild_if_missing_param)
        rebuild_max_events = max(_parse_int(request.args.get("rebuild_max_events"), 0), 0)
        estimation_lookback_days = max(_parse_int(request.args.get("estimation_lookback_days"), 7), 1)
        limit = max(_parse_int(request.args.get("limit"), 10000), 0)
        rebuild_report: dict[str, object] | None = None
        audit_event_rows: list[dict[str, object]] = []
        scoped_event_rows: list[dict[str, object]] = []
        with session_factory() as session:
            scoped_event_ids: set[str] | None = None
            if from_ts is not None or to_ts is not None:
                scoped_events = load_news_events(
                    session,
                    published_from=_isoformat_utc(from_ts),
                    published_to=_isoformat_utc(to_ts),
                    limit=0,
                )
                scoped_event_ids = {
                    str(row.get("event_id") or "").strip()
                    for row in scoped_events
                    if str(row.get("event_id") or "").strip()
                }
            reactions = load_event_market_reactions(
                session,
                window_id=window_id,
                sampling_freq=sampling_freq,
                limit=limit,
            )
            if rebuild_if_missing and not reactions:
                build = rebuild_event_market_reactions(
                    session,
                    published_from=from_ts,
                    published_to=to_ts,
                    window_ids=[window_id] if window_id else None,
                    sampling_freqs=[sampling_freq] if sampling_freq else ("1m", "5m", "15m"),
                    estimation_lookback_days=estimation_lookback_days,
                    max_events=rebuild_max_events,
                    event_time_mode=event_time_mode,
                )
                rebuild_report = {
                    "events_seen": build.events_seen,
                    "events_processed": build.events_processed,
                    "windows_processed": build.windows_processed,
                    "rows_upserted": build.rows_upserted,
                    "overlap_rows": build.overlap_rows,
                    "skipped_rows": build.skipped_rows,
                }
                reactions = load_event_market_reactions(
                    session,
                    window_id=window_id,
                    sampling_freq=sampling_freq,
                    limit=limit,
                )
            if commodity:
                reactions = [
                    row
                    for row in reactions
                    if commodity in str(row.get("instrument_id") or "").strip().upper()
                ]
            if scoped_event_ids is not None:
                reactions = [
                    row
                    for row in reactions
                    if str(row.get("event_id") or "").strip() in scoped_event_ids
                ]
            event_ids = sorted({str(row.get("event_id") or "").strip() for row in reactions if row.get("event_id")})
            label_rows = load_news_labels(
                session,
                target_level="event",
                target_ids=event_ids,
                limit=max(len(event_ids) * 2, 1000),
            )
            if event_ids:
                scoped_event_rows = load_news_events(
                    session,
                    event_ids=event_ids,
                    limit=max(len(event_ids) * 2, 1000),
                )
            if audit_leakage and event_ids:
                audit_event_rows = list(scoped_event_rows)
        summary_payload = summarize_event_study(
            reactions=reactions,
            labels=label_rows,
            events=scoped_event_rows,
            exclude_overlap=exclude_overlap,
        )
        leakage_audit = (
            build_event_study_leakage_audit(
                reactions=reactions,
                events=audit_event_rows,
                event_time_mode=event_time_mode,
            )
            if audit_leakage
            else None
        )
        payload = {
            "commodity": commodity or None,
            "window_id": window_id,
            "sampling_freq": sampling_freq,
            "event_time_mode": event_time_mode,
            "sample_count": int(summary_payload.get("sample_count") or 0),
            "sample_count_before_overlap_filter": int(
                summary_payload.get("sample_count_before_overlap_filter") or 0
            ),
            "excluded_overlap_count": int(summary_payload.get("excluded_overlap_count") or 0),
            "exclude_overlap": bool(summary_payload.get("exclude_overlap")),
            "car_summary_by_direction": summary_payload.get("car_summary_by_direction") or {},
            "car_summary_by_event_family": summary_payload.get("car_summary_by_event_family") or {},
            "car_summary_by_event_kind": summary_payload.get("car_summary_by_event_kind") or {},
            "fdr_method": summary_payload.get("fdr_method"),
            "leakage_audit": leakage_audit,
            "rebuild_report": rebuild_report,
        }
        return _observe_request("v2_validation_event_study", started_at, jsonify(payload))

    @server.route("/api/decisions/<decision_id>/action", methods=["GET", "POST"])
    def decision_action_api(decision_id: str):
        if not _decision_exists(decision_id):
            return jsonify({"error": "not_found"}), 404
        if request.method == "GET":
            action_records = load_jsonl(actions_path) if actions_path.exists() else []
            latest_actions = _latest_by_decision_id(action_records)
            execution_records = load_jsonl(executions_path) if executions_path.exists() else []
            latest_executions = _latest_by_decision_id(execution_records)
            action = latest_actions.get(decision_id)
            execution = latest_executions.get(decision_id)
            return jsonify(
                {
                    "decision_id": decision_id,
                    "operator_action": action or {},
                    "execution_status": execution or {},
                }
            )
        payload = request.get_json(silent=True)
        if payload is None:
            return _bad_request("invalid_json")
        if not isinstance(payload, dict):
            return _bad_request("payload must be object")
        adapter_payload: dict[str, object] = dict(payload)
        adapter_payload["source"] = "v1_adapter"
        adapter_payload["actor_id"] = payload.get("actor") or payload.get("actor_id")
        adapter_payload["comment"] = payload.get("note") or payload.get("comment")
        return _record_decision_action(
            decision_id,
            adapter_payload,
            source_default="v1_adapter",
            allowed_actions={"APPROVE", "REJECT"},
            require_idempotency=False,
        )

    @server.route("/api/v2/decisions/<decision_id>/actions", methods=["POST"])
    def decision_actions_v2_api(decision_id: str):
        payload = request.get_json(silent=True)
        if payload is None:
            return _bad_request("invalid_json")
        if not isinstance(payload, dict):
            return _bad_request("payload must be object")
        return _record_decision_action(
            decision_id,
            dict(payload),
            source_default="ui",
            allowed_actions={"APPROVE", "HOLD", "REJECT", "EXECUTE", "CLOSE"},
            require_idempotency=True,
        )

    @server.route("/api/params/specs", methods=["GET"])
    def params_specs_api():
        preset = request.args.get("preset")
        try:
            specs = get_parameter_specs(preset)
        except ValueError as exc:
            return jsonify({"error": "unknown_preset", "message": str(exc)}), 400
        return jsonify([spec.model_dump() for spec in specs])

    @server.route("/api/backtest/run", methods=["POST"])
    def backtest_run_api():
        payload = request.get_json(silent=True)
        if payload is None:
            return _bad_request("invalid_json")
        precompute = None
        compute_fill_quality = None
        request_payload = payload
        if isinstance(payload, dict):
            if "request" in payload:
                request_payload = payload.get("request")
                precompute = _parse_bool(payload.get("precompute"))
                compute_fill_quality = _parse_bool(payload.get("compute_fill_quality"))
            elif "precompute" in payload:
                precompute = _parse_bool(payload.get("precompute"))
                request_payload = dict(payload)
                request_payload.pop("precompute", None)
                compute_fill_quality = _parse_bool(payload.get("compute_fill_quality"))
                request_payload.pop("compute_fill_quality", None)
            elif "compute_fill_quality" in payload:
                compute_fill_quality = _parse_bool(payload.get("compute_fill_quality"))
                request_payload = dict(payload)
                request_payload.pop("compute_fill_quality", None)
        if not isinstance(request_payload, dict):
            return _bad_request("missing_request")
        try:
            backtest_request = BacktestRequest.model_validate(request_payload)
        except ValidationError as exc:
            return _bad_request("validation_error", details=exc.errors())
        if compute_fill_quality is None:
            compute_fill_quality = True
        try:
            report = run_backtest_v2_cached(
                backtest_request,
                paths.data_dir,
                precompute=precompute,
                compute_fill_quality=compute_fill_quality,
            )
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("Backtest v2 failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500
        return jsonify(serialize_backtest_report(report))

    @server.route("/api/forward/start", methods=["POST"])
    def forward_start_api():
        payload = request.get_json(silent=True) or {}
        request_payload = payload
        if isinstance(payload, dict) and "request" in payload:
            request_payload = payload.get("request") or {}
        if not isinstance(request_payload, dict):
            return _bad_request("missing_request")
        try:
            forward_request = ForwardTestRequest.model_validate(request_payload)
        except ValidationError as exc:
            return _bad_request("validation_error", details=exc.errors())
        try:
            run_info = start_forward_run(forward_request, paths.data_dir)
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("Forward start failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500
        return jsonify(run_info)

    @server.route("/api/forward/status", methods=["GET"])
    def forward_status_api():
        run_id = request.args.get("run_id")
        try:
            status = load_forward_status(paths.data_dir, run_id=run_id)
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("Forward status failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500
        return jsonify(status)

    @server.route("/api/hpo/run", methods=["POST"])
    def hpo_run_api():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _bad_request("invalid_json")
        precompute = _parse_bool(payload.get("precompute"))
        if precompute is None:
            precompute = True
        request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else payload
        if not isinstance(request_payload, dict):
            return _bad_request("missing_request")
        request_payload = {key: value for key, value in request_payload.items() if key != "precompute"}
        optimization = request_payload.get("optimization") if isinstance(request_payload, dict) else None
        max_trials_override = None
        if not (isinstance(optimization, dict) and "max_trials" in optimization):
            max_trials_override = 10
        try:
            hpo_request = HpoRequest.model_validate(request_payload)
        except ValidationError as exc:
            return _bad_request("validation_error", details=exc.errors())
        try:
            run_info = start_hpo_run(
                hpo_request,
                paths.data_dir,
                precompute=precompute,
                max_trials_override=max_trials_override,
            )
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("HPO run failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500
        return jsonify(run_info)

    @server.route("/api/hpo/status", methods=["GET"])
    def hpo_status_api():
        run_id = request.args.get("run_id")
        try:
            status = load_hpo_status(paths.data_dir, run_id=run_id)
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("HPO status failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500
        return jsonify(status)

    @server.route("/api/v2/research/news/backtest", methods=["GET"])
    def news_backtest_v2_api():
        started_at = datetime.now(timezone.utc)
        model_id = str(request.args.get("model_id") or settings.news_models.primary_model).strip()
        horizon = str(request.args.get("horizon") or "1d").strip().lower()
        target_mode = str(request.args.get("target_mode") or settings.news_models.target_mode_default).strip().lower()
        two_stage_for_v2_raw = _parse_bool(request.args.get("two_stage_for_v2"))
        two_stage_for_v2 = True if two_stage_for_v2_raw is None else bool(two_stage_for_v2_raw)
        utility_cost_per_trade = max(_parse_float(request.args.get("utility_cost_per_trade"), 0.00075), 0.0)
        utility_bootstrap_iters = max(_parse_int(request.args.get("utility_bootstrap_iters"), 2000), 0)
        epsilon = max(_parse_float(request.args.get("epsilon"), settings.news_models.epsilon_default), 0.0)
        folds = max(_parse_int(request.args.get("folds"), 5), 1)
        embargo_minutes = max(_parse_int(request.args.get("embargo_minutes"), 0), 0)
        walk_forward_raw = _parse_bool(request.args.get("walk_forward"))
        walk_forward = True if walk_forward_raw is None else bool(walk_forward_raw)
        calibration_mode = str(request.args.get("calibration_mode") or settings.news_models.calibration_mode).strip().lower()
        from_raw = request.args.get("from")
        to_raw = request.args.get("to")
        from_ts = _parse_date_bound(from_raw, "start") if from_raw else None
        to_ts = _parse_date_bound(to_raw, "end") if to_raw else None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if from_ts is None:
            from_ts = now - timedelta(days=90)
        if to_ts is None:
            to_ts = now
        if from_ts > to_ts:
            return _observe_request(
                "v2_news_backtest",
                started_at,
                _bad_request("from must be <= to"),
            )

        with session_factory() as session:
            report = run_news_backtest(
                session,
                model_id=model_id,
                horizon=horizon,
                period_from=from_ts,
                period_to=to_ts,
                epsilon=epsilon,
                folds=folds,
                embargo_minutes=embargo_minutes,
                walk_forward=walk_forward,
                calibration_mode=calibration_mode,
                calibration_min_train_samples=settings.news_models.calibration_min_train_samples,
                target_mode=target_mode,
                two_stage_for_v2=two_stage_for_v2,
                utility_cost_per_trade=utility_cost_per_trade,
                utility_bootstrap_iters=utility_bootstrap_iters,
            )
            run_id = _stable_id(
                "news-bt",
                model_id,
                horizon,
                from_ts.isoformat(),
                to_ts.isoformat(),
                datetime.now(timezone.utc).isoformat(),
                length=20,
            )
            upsert_news_backtest_report(
                session,
                {
                    "run_id": run_id,
                    "period_from": from_ts.isoformat() + "Z",
                    "period_to": to_ts.isoformat() + "Z",
                    "horizon": horizon,
                    "model_id": model_id,
                    "metrics_json": report,
                },
            )
        payload = dict(report)
        payload["run_id"] = run_id
        return _observe_request("v2_news_backtest", started_at, jsonify(payload))

    @server.route("/api/v2/research/news/models/compare", methods=["GET"])
    def news_models_compare_v2_api():
        started_at = datetime.now(timezone.utc)
        horizon = str(request.args.get("horizon") or "1d").strip().lower()
        target_mode = str(request.args.get("target_mode") or settings.news_models.target_mode_default).strip().lower()
        two_stage_for_v2_raw = _parse_bool(request.args.get("two_stage_for_v2"))
        two_stage_for_v2 = True if two_stage_for_v2_raw is None else bool(two_stage_for_v2_raw)
        utility_cost_per_trade = max(_parse_float(request.args.get("utility_cost_per_trade"), 0.00075), 0.0)
        utility_bootstrap_iters = max(_parse_int(request.args.get("utility_bootstrap_iters"), 2000), 0)
        promotion_utility_min_trades = max(_parse_int(request.args.get("promotion_utility_min_trades"), 30), 0)
        promotion_utility_max_drawdown = max(
            _parse_float(request.args.get("promotion_utility_max_drawdown"), 0.20),
            0.0,
        )
        epsilon = max(_parse_float(request.args.get("epsilon"), settings.news_models.epsilon_default), 0.0)
        folds = max(_parse_int(request.args.get("folds"), 5), 1)
        embargo_minutes = max(_parse_int(request.args.get("embargo_minutes"), 0), 0)
        walk_forward_raw = _parse_bool(request.args.get("walk_forward"))
        walk_forward = True if walk_forward_raw is None else bool(walk_forward_raw)
        calibration_mode = str(request.args.get("calibration_mode") or settings.news_models.calibration_mode).strip().lower()
        promotion_min_accuracy = _parse_float(
            request.args.get("promotion_min_accuracy"), settings.news_models.promotion_min_accuracy
        )
        promotion_min_coverage = _parse_float(
            request.args.get("promotion_min_coverage"), settings.news_models.promotion_min_coverage
        )
        promotion_max_brier = _parse_float(
            request.args.get("promotion_max_brier"), settings.news_models.promotion_max_brier
        )
        promotion_min_sample_count = max(
            _parse_int(request.args.get("promotion_min_sample_count"), settings.news_models.promotion_min_sample_count),
            0,
        )
        promotion_min_ticker_stability = _parse_float(
            request.args.get("promotion_min_ticker_stability"), settings.news_models.promotion_min_ticker_stability
        )
        from_raw = request.args.get("from")
        to_raw = request.args.get("to")
        models_raw = str(request.args.get("models") or "").strip()
        if models_raw:
            model_ids = [item.strip() for item in models_raw.split(",") if item.strip()]
        else:
            model_ids = [item for item in settings.news_models.enabled_models if item in {"finbert", "nli"}]
        if not model_ids:
            model_ids = ["finbert", "nli"]
        from_ts = _parse_date_bound(from_raw, "start") if from_raw else None
        to_ts = _parse_date_bound(to_raw, "end") if to_raw else None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if from_ts is None:
            from_ts = now - timedelta(days=90)
        if to_ts is None:
            to_ts = now
        if from_ts > to_ts:
            return _observe_request(
                "v2_news_compare",
                started_at,
                _bad_request("from must be <= to"),
            )

        with session_factory() as session:
            comparison = compare_news_models(
                session,
                model_ids=model_ids,
                horizon=horizon,
                period_from=from_ts,
                period_to=to_ts,
                epsilon=epsilon,
                folds=folds,
                embargo_minutes=embargo_minutes,
                walk_forward=walk_forward,
                calibration_mode=calibration_mode,
                calibration_min_train_samples=settings.news_models.calibration_min_train_samples,
                target_mode=target_mode,
                two_stage_for_v2=two_stage_for_v2,
                utility_cost_per_trade=utility_cost_per_trade,
                utility_bootstrap_iters=utility_bootstrap_iters,
                promotion_utility_min_trades=promotion_utility_min_trades,
                promotion_utility_max_drawdown=promotion_utility_max_drawdown,
                promotion_min_accuracy=promotion_min_accuracy,
                promotion_min_coverage=promotion_min_coverage,
                promotion_max_brier=promotion_max_brier,
                promotion_min_sample_count=promotion_min_sample_count,
                promotion_min_ticker_stability=promotion_min_ticker_stability,
            )
            reports = comparison.get("reports")
            if isinstance(reports, list):
                for report in reports:
                    if not isinstance(report, dict):
                        continue
                    report_model_id = str(report.get("model_id") or "").strip()
                    if not report_model_id:
                        continue
                    run_id = _stable_id(
                        "news-bt",
                        report_model_id,
                        horizon,
                        from_ts.isoformat(),
                        to_ts.isoformat(),
                        datetime.now(timezone.utc).isoformat(),
                        length=20,
                    )
                    upsert_news_backtest_report(
                        session,
                        {
                            "run_id": run_id,
                            "period_from": from_ts.isoformat() + "Z",
                            "period_to": to_ts.isoformat() + "Z",
                            "horizon": horizon,
                            "model_id": report_model_id,
                            "metrics_json": report,
                        },
                    )
            compare_run_id = _stable_id(
                "news-bt",
                "__compare__",
                horizon,
                from_ts.isoformat(),
                to_ts.isoformat(),
                str(comparison.get("audit", {}).get("comparison_hash") if isinstance(comparison.get("audit"), dict) else ""),
                datetime.now(timezone.utc).isoformat(),
                length=20,
            )
            upsert_news_backtest_report(
                session,
                {
                    "run_id": compare_run_id,
                    "period_from": from_ts.isoformat() + "Z",
                    "period_to": to_ts.isoformat() + "Z",
                    "horizon": horizon,
                    "model_id": "__compare__",
                    "metrics_json": comparison if isinstance(comparison, dict) else {},
                },
            )
            recent_reports = load_news_backtest_reports(session, horizon=horizon, limit=10)
        payload = dict(comparison)
        payload["recent_reports"] = recent_reports
        winner = payload.get("winner") if isinstance(payload.get("winner"), dict) else {}
        _mark_news_compare_events(str(winner.get("model_id") or ""))
        return _observe_request("v2_news_compare", started_at, jsonify(payload))
    @server.route("/api/v2/top-pairs", methods=["GET"])
    @server.route("/api/top-pairs", methods=["GET"])
    def top_pairs_api():
        all_pairs = request.args.get("all", "").lower() in {"1", "true", "yes"}
        fresh = request.args.get("fresh", "").lower() in {"1", "true", "yes"}
        require_score_gate = _resolve_require_score_gate(
            request.args.get("require_score_gate"),
            default=_default_require_score_gate_for_top_pairs(settings),
        )
        limit = int(request.args.get("limit", "500"))
        df = pd.DataFrame()
        if settings.ui.use_unified_signal_engine:
            try:
                max_pairs = None if all_pairs else _resolved_unified_max_pairs(limit)
                top_pairs, _, _ = _load_latest_unified_output(
                    max_pairs=max_pairs,
                    fresh=fresh,
                )
                df = top_pairs.copy()
            except Exception:
                logger.exception("Unified top-pairs failed")
                if not settings.ui.unified_allow_legacy_fallback:
                    return jsonify({"error": "server_error", "message": "unified_top_pairs_failed"}), 500
        if df.empty and settings.ui.unified_allow_legacy_fallback:
            df = load_top_pairs(paths.data_dir)
        df = _apply_score_gate_filter(df, require_score_gate=require_score_gate)
        if not df.empty and "signal_score_norm" not in df.columns:
            if {"zscore", "implied_rate_net", "required_rate"}.issubset(df.columns):
                z_entry = settings.strategy.z_entry
                implied_buffer = settings.strategy.implied_rate_buffer
                z_component = df["zscore"].abs() / z_entry if z_entry else 0.0
                rate_gap = (df["implied_rate_net"] - df["required_rate"]).abs()
                rate_component = rate_gap / implied_buffer if implied_buffer else 0.0
                df["signal_score_norm"] = 0.5 * (z_component + rate_component)
        if not all_pairs:
            df = df.head(max(limit, 0)) if limit else df
        records = [_merge_signal_metrics(record) for record in _df_to_records(df)]
        for record in records:
            record["execution_quality"] = _build_execution_quality(record)
        return jsonify(records)

    @server.route("/api/signals", methods=["GET"])
    def signals_api():
        df = pd.DataFrame()
        fresh = request.args.get("fresh", "").lower() in {"1", "true", "yes"}
        require_score_gate = _resolve_require_score_gate(
            request.args.get("require_score_gate"),
            default=_default_require_score_gate_for_signals(settings),
        )
        if settings.ui.use_unified_signal_engine:
            limit = int(request.args.get("limit", "500"))
            try:
                _, signals, _ = _load_latest_unified_output(
                    max_pairs=_resolved_unified_max_pairs(limit),
                    fresh=fresh,
                )
                df = signals.copy()
            except Exception:
                logger.exception("Unified signals failed")
                if not settings.ui.unified_allow_legacy_fallback:
                    return jsonify({"error": "server_error", "message": "unified_signals_failed"}), 500
        if df.empty and settings.ui.unified_allow_legacy_fallback:
            df = load_signals(paths.data_dir)
        df = _apply_score_gate_filter(df, require_score_gate=require_score_gate)
        limit = int(request.args.get("limit", "500"))
        df = df.head(max(limit, 0)) if limit else df
        records = [_merge_signal_metrics(record) for record in _df_to_records(df)]
        for record in records:
            record["execution_quality"] = _build_execution_quality(record)
        return jsonify(records)

    @server.route("/api/signals/active", methods=["GET"])
    def signals_active_api():
        require_score_gate = _resolve_require_score_gate(
            request.args.get("require_score_gate"),
            default=_default_require_score_gate_for_signals(settings),
        )
        with session_factory() as session:
            latest = load_latest_signal_run(session)
            if not latest:
                return jsonify([])
            rows = load_active_signals(session, latest.run_id)
            executions = load_open_executions(session)
            usage_by_fingerprint: dict[str, dict[str, object]] = {}
            pair_trade_timestamps: dict[tuple[str, str], list[datetime]] = {}
            position_state: dict[tuple[str, str], dict[str, object]] = {}

            def _register_usage(
                fingerprint: str,
                *,
                used_at: datetime,
                used_by: str | None,
            ) -> None:
                existing = usage_by_fingerprint.get(fingerprint)
                existing_ts_raw = existing.get("timestamp") if isinstance(existing, dict) else None
                existing_ts = (
                    _normalize_datetime(existing_ts_raw)
                    if isinstance(existing_ts_raw, datetime)
                    else None
                )
                if existing_ts is None or used_at >= existing_ts:
                    usage_by_fingerprint[fingerprint] = {
                        "timestamp": used_at,
                        "used_by": used_by,
                    }

            for exec_row in sorted(executions, key=lambda item: item.timestamp):
                if not isinstance(exec_row.timestamp, datetime):
                    continue
                exec_ts = _normalize_datetime(exec_row.timestamp)
                key = (exec_row.stock_secid, exec_row.future_secid)
                state = position_state.setdefault(
                    key,
                    {
                        "enter_count": 0,
                        "exit_count": 0,
                        "net_executions": 0,
                        "last_execution_at": None,
                        "direction": None,
                        "open_legs": {"stock": 0, "future": 0, "other": 0},
                        "enter_orders": set(),
                        "exit_orders": set(),
                        "order_legs": {},
                    },
                )
                action = _normalize_execution_action(exec_row.action)
                if action == "ack":
                    ack_note = _parse_ack_note_from_execution_note(exec_row.note)
                    if isinstance(ack_note, dict):
                        fingerprint_raw = ack_note.get("fingerprint")
                        if isinstance(fingerprint_raw, str) and fingerprint_raw.strip():
                            _register_usage(
                                fingerprint_raw.strip(),
                                used_at=exec_ts,
                                used_by=_signal_used_by_from_ack(ack_note),
                            )
                    action_note = _parse_signal_action_note(exec_row.note)
                    if isinstance(action_note, dict):
                        fingerprint_raw = action_note.get("fingerprint")
                        source = str(action_note.get("source") or "").strip().lower()
                        if (
                            isinstance(fingerprint_raw, str)
                            and fingerprint_raw.strip()
                            and source in {"ui", "telegram", "v1_adapter"}
                        ):
                            _register_usage(
                                fingerprint_raw.strip(),
                                used_at=exec_ts,
                                used_by=_signal_used_by_from_action(action_note),
                            )
                    continue

                action_note = _parse_signal_action_note(exec_row.note)
                if isinstance(action_note, dict):
                    fingerprint_raw = action_note.get("fingerprint")
                    requested_action = str(action_note.get("requested_action") or "").strip().lower()
                    source = str(action_note.get("source") or "").strip().lower()
                    if (
                        isinstance(fingerprint_raw, str)
                        and fingerprint_raw.strip()
                        and requested_action in {"enter", "ack"}
                        and source in {"ui", "telegram", "v1_adapter"}
                    ):
                        _register_usage(
                            fingerprint_raw.strip(),
                            used_at=exec_ts,
                            used_by=_signal_used_by_from_action(action_note),
                        )

                if action not in {"enter", "exit"}:
                    continue
                pair_trade_timestamps.setdefault(key, []).append(exec_ts)
                leg = _normalize_execution_leg(exec_row.side)
                order_id = _normalize_order_id(getattr(exec_row, "order_id", None))
                if order_id is None:
                    order_id = f"legacy-{exec_row.id}"

                open_legs_raw = state.get("open_legs")
                if isinstance(open_legs_raw, dict):
                    open_legs = {
                        "stock": int(open_legs_raw.get("stock", 0) or 0),
                        "future": int(open_legs_raw.get("future", 0) or 0),
                        "other": int(open_legs_raw.get("other", 0) or 0),
                    }
                else:
                    open_legs = {"stock": 0, "future": 0, "other": 0}

                order_legs_raw = state.get("order_legs")
                order_legs: dict[tuple[str, str], set[str]]
                if isinstance(order_legs_raw, dict):
                    order_legs = {}
                    for order_key, value in order_legs_raw.items():
                        if (
                            isinstance(order_key, tuple)
                            and len(order_key) == 2
                            and isinstance(order_key[0], str)
                            and isinstance(order_key[1], str)
                            and isinstance(value, set)
                        ):
                            order_legs[order_key] = set(str(item) for item in value)
                else:
                    order_legs = {}
                group_key = (action, order_id)
                group_legs = order_legs.setdefault(group_key, set())
                group_legs.add(leg)
                state["order_legs"] = order_legs

                enter_orders_raw = state.get("enter_orders")
                enter_orders = set(enter_orders_raw) if isinstance(enter_orders_raw, set) else set()
                exit_orders_raw = state.get("exit_orders")
                exit_orders = set(exit_orders_raw) if isinstance(exit_orders_raw, set) else set()

                if action == "enter":
                    state["enter_count"] = int(state["enter_count"]) + 1
                    state["net_executions"] = int(state["net_executions"]) + 1
                    open_legs[leg] = int(open_legs.get(leg, 0)) + 1
                    enter_orders.add(order_id)
                elif action == "exit":
                    state["exit_count"] = int(state["exit_count"]) + 1
                    state["net_executions"] = max(int(state["net_executions"]) - 1, 0)
                    _decrement_leg_bucket(open_legs, leg)
                    exit_orders.add(order_id)
                state["open_legs"] = open_legs
                state["enter_orders"] = enter_orders
                state["exit_orders"] = exit_orders
                state["open_leg_total"] = int(open_legs["stock"] + open_legs["future"] + open_legs["other"])
                state["open_leg_imbalance"] = int(open_legs["stock"]) != int(open_legs["future"])
                state["last_execution_at"] = exec_ts
                if exec_row.direction is not None:
                    state["direction"] = exec_row.direction

            def _signal_usage_fields(
                *,
                run_id: str,
                timestamp: str,
                stock: str,
                future: str,
                signal_action: str,
                signal_fingerprint: str | None = None,
            ) -> dict[str, object]:
                fingerprint = str(signal_fingerprint or "").strip()
                if not fingerprint:
                    fingerprint = build_signal_fingerprint(
                        run_id=run_id,
                        timestamp=timestamp,
                        stock=stock,
                        future=future,
                        signal_action=signal_action,
                    )
                usage_entry = usage_by_fingerprint.get(fingerprint)
                if not isinstance(usage_entry, dict):
                    return {
                        "signal_used": False,
                        "signal_used_at": None,
                        "signal_used_by": None,
                        "signal_details_pending": False,
                    }
                usage_ts_raw = usage_entry.get("timestamp")
                usage_ts = _normalize_datetime(usage_ts_raw) if isinstance(usage_ts_raw, datetime) else None
                has_trade_after_usage = False
                if usage_ts is not None:
                    trades = pair_trade_timestamps.get((stock, future), [])
                    has_trade_after_usage = any(trade_ts > usage_ts for trade_ts in trades)
                return {
                    "signal_used": True,
                    "signal_used_at": usage_ts.isoformat() if usage_ts is not None else None,
                    "signal_used_by": usage_entry.get("used_by"),
                    "signal_details_pending": not has_trade_after_usage,
                }

            for state in position_state.values():
                enter_orders = state.get("enter_orders")
                exit_orders = state.get("exit_orders")
                order_legs = state.get("order_legs")
                enter_order_count = len(enter_orders) if isinstance(enter_orders, set) else 0
                exit_order_count = len(exit_orders) if isinstance(exit_orders, set) else 0
                linked_two_leg_orders = 0
                partial_leg_orders = 0
                if isinstance(order_legs, dict):
                    for legs in order_legs.values():
                        if not isinstance(legs, set):
                            continue
                        normalized_legs = {str(leg) for leg in legs}
                        dual_leg = "stock" in normalized_legs and "future" in normalized_legs
                        single_leg = (
                            ("stock" in normalized_legs) ^ ("future" in normalized_legs)
                        )
                        if dual_leg:
                            linked_two_leg_orders += 1
                        elif single_leg:
                            partial_leg_orders += 1
                state["enter_order_count"] = enter_order_count
                state["exit_order_count"] = exit_order_count
                state["net_orders"] = max(enter_order_count - exit_order_count, 0)
                state["linked_two_leg_orders"] = linked_two_leg_orders
                state["partial_leg_orders"] = partial_leg_orders

            open_pairs = {
                key for key, state in position_state.items() if int(state.get("open_leg_total") or 0) > 0
            }
            entry_intent_ttl_hours = max(
                int(getattr(settings.ui, "signal_entry_intent_ttl_hours", 72) or 72),
                1,
            )
            latest_as_of = getattr(latest, "as_of", None)
            latest_as_of_dt = (
                _normalize_datetime(latest_as_of) if isinstance(latest_as_of, datetime) else None
            )
            cutoff_anchor = (
                latest_as_of_dt
                if latest_as_of_dt is not None
                else datetime.now(timezone.utc).astimezone(timezone.utc).replace(tzinfo=None)
            )
            entry_intent_cutoff = cutoff_anchor - timedelta(hours=entry_intent_ttl_hours)
            latest_entry_intent_by_pair: dict[tuple[str, str], object] = {}
            pairs_for_intent_lookup = set(open_pairs)
            for row in rows:
                pairs_for_intent_lookup.add((row.stock_secid, row.future_secid))
            for stock, future in sorted(pairs_for_intent_lookup):
                enter_rows = load_signal_history(
                    session,
                    from_ts=entry_intent_cutoff,
                    limit=20,
                    stock=stock,
                    future=future,
                    action="enter",
                )
                for enter_row in enter_rows:
                    if isinstance(getattr(enter_row, "timestamp", None), datetime):
                        latest_entry_intent_by_pair[(stock, future)] = enter_row
                        break
            rows_by_pair = {(row.stock_secid, row.future_secid): row for row in rows}
            actionable: list[dict[str, object]] = []
            for row in rows:
                key = (row.stock_secid, row.future_secid)
                state = position_state.get(key, {})
                is_open = key in open_pairs
                open_legs_raw = state.get("open_legs")
                open_legs = (
                    open_legs_raw
                    if isinstance(open_legs_raw, dict)
                    else {"stock": 0, "future": 0, "other": 0}
                )
                row_action = str(row.action or "").strip().lower()
                if row_action == "enter":
                    action = "enter"
                elif row_action == "exit":
                    if not is_open:
                        continue
                    action = "exit"
                elif row_action not in {"enter", "exit"}:
                    action = "hold_open" if is_open else "hold_flat"
                else:
                    continue
                signal_run_id = row.run_id
                signal_timestamp = row.timestamp.isoformat()
                signal_direction = row.direction
                signal_score = row.score
                signal_reasons = list(row.reasons) if isinstance(row.reasons, list) else []
                current_metrics = row.metrics if isinstance(row.metrics, dict) else {}
                fallback_metrics: dict[str, object] | None = None
                pending_intent_promoted = False
                repriced_from_hold_flat = False
                entry_intent_consumed = False
                signal_fingerprint = build_signal_fingerprint(
                    run_id=signal_run_id,
                    timestamp=signal_timestamp,
                    stock=row.stock_secid,
                    future=row.future_secid,
                    signal_action=action,
                )
                usage_fields = _signal_usage_fields(
                    run_id=signal_run_id,
                    timestamp=signal_timestamp,
                    stock=row.stock_secid,
                    future=row.future_secid,
                    signal_action=action,
                    signal_fingerprint=signal_fingerprint,
                )
                entry_intent_row = latest_entry_intent_by_pair.get(key)
                if (
                    action in {"hold_open", "hold_flat"}
                    and entry_intent_row is not None
                    and isinstance(getattr(entry_intent_row, "timestamp", None), datetime)
                ):
                    intent_run_id = str(entry_intent_row.run_id)
                    intent_timestamp = entry_intent_row.timestamp.isoformat()
                    intent_fingerprint = build_signal_fingerprint(
                        run_id=intent_run_id,
                        timestamp=intent_timestamp,
                        stock=row.stock_secid,
                        future=row.future_secid,
                        signal_action="enter",
                    )
                    intent_usage = _signal_usage_fields(
                        run_id=intent_run_id,
                        timestamp=intent_timestamp,
                        stock=row.stock_secid,
                        future=row.future_secid,
                        signal_action="enter",
                        signal_fingerprint=intent_fingerprint,
                    )
                    if bool(intent_usage.get("signal_used")):
                        entry_intent_consumed = True
                    else:
                        pending_intent_promoted = True
                        action = "enter"
                        signal_fingerprint = intent_fingerprint
                        usage_fields = intent_usage
                        signal_score = float(entry_intent_row.score or signal_score or 0.0)
                        fallback_metrics = (
                            entry_intent_row.metrics if isinstance(entry_intent_row.metrics, dict) else None
                        )
                        if signal_direction is None:
                            signal_direction = entry_intent_row.direction
                        if "pending_entry_intent_active" not in signal_reasons:
                            signal_reasons.append("pending_entry_intent_active")
                if action == "hold_flat" and entry_intent_consumed:
                    continue
                if action == "hold_flat":
                    action = "enter"
                    repriced_from_hold_flat = True
                    signal_fingerprint = build_signal_fingerprint(
                        run_id=signal_run_id,
                        timestamp=signal_timestamp,
                        stock=row.stock_secid,
                        future=row.future_secid,
                        signal_action=action,
                    )
                    usage_fields = _signal_usage_fields(
                        run_id=signal_run_id,
                        timestamp=signal_timestamp,
                        stock=row.stock_secid,
                        future=row.future_secid,
                        signal_action=action,
                        signal_fingerprint=signal_fingerprint,
                    )
                    if "repriced_from_hold_flat" not in signal_reasons:
                        signal_reasons.append("repriced_from_hold_flat")
                if (
                    action == "enter"
                    and not is_open
                    and repriced_from_hold_flat
                    and bool(usage_fields.get("signal_used"))
                ):
                    continue
                signal_metrics = _enrich_entry_plan_metrics(
                    settings=settings,
                    current_metrics=current_metrics,
                    fallback_metrics=fallback_metrics,
                    force_rebuild=(pending_intent_promoted or repriced_from_hold_flat),
                )
                if (
                    pending_intent_promoted
                    and not is_open
                    and entry_intent_row is not None
                    and isinstance(entry_intent_row.metrics, dict)
                    and entry_intent_row.metrics.get("score_gate_pass") is not None
                ):
                    signal_metrics["score_gate_pass"] = bool(entry_intent_row.metrics.get("score_gate_pass"))
                payload = {
                    "run_id": signal_run_id,
                    "timestamp": signal_timestamp,
                    "stock": row.stock_secid,
                    "future": row.future_secid,
                    "signal_fingerprint": signal_fingerprint,
                    "signal_action": action,
                    "signal_direction": signal_direction,
                    "signal_score": signal_score,
                    "signal_reasons": signal_reasons,
                    "signal_metrics": signal_metrics,
                    "position_open": is_open,
                    "position_state": "open" if is_open else "flat",
                    "position_enter_count": int(state.get("enter_count") or 0),
                    "position_exit_count": int(state.get("exit_count") or 0),
                    "position_net_executions": int(state.get("net_executions") or 0),
                    "position_enter_order_count": int(state.get("enter_order_count") or 0),
                    "position_exit_order_count": int(state.get("exit_order_count") or 0),
                    "position_net_orders": int(state.get("net_orders") or 0),
                    "position_linked_two_leg_orders": int(state.get("linked_two_leg_orders") or 0),
                    "position_partial_leg_orders": int(state.get("partial_leg_orders") or 0),
                    "position_open_stock_legs": int(open_legs.get("stock") or 0),
                    "position_open_future_legs": int(open_legs.get("future") or 0),
                    "position_open_other_legs": int(open_legs.get("other") or 0),
                    "position_open_leg_total": int(state.get("open_leg_total") or 0),
                    "position_leg_imbalance": bool(state.get("open_leg_imbalance")),
                    "position_last_execution_at": (
                        state["last_execution_at"].isoformat()
                        if isinstance(state.get("last_execution_at"), datetime)
                        else None
                    ),
                    **usage_fields,
                }
                if pending_intent_promoted and entry_intent_row is not None:
                    payload["signal_origin_run_id"] = entry_intent_row.run_id
                    payload["signal_origin_timestamp"] = entry_intent_row.timestamp.isoformat()
                actionable.append(_merge_signal_metrics(payload))

            missing_open_pairs = open_pairs.difference(rows_by_pair.keys())
            for stock, future in sorted(missing_open_pairs):
                state = position_state.get((stock, future), {})
                open_legs_raw = state.get("open_legs")
                open_legs = (
                    open_legs_raw
                    if isinstance(open_legs_raw, dict)
                    else {"stock": 0, "future": 0, "other": 0}
                )
                last_execution_at = state.get("last_execution_at")
                if isinstance(last_execution_at, datetime):
                    timestamp_value = last_execution_at.isoformat()
                else:
                    timestamp_value = latest.as_of.isoformat()
                action = "hold_open"
                signal_direction = state.get("direction")
                signal_score = 0.0
                signal_reasons: list[str] = ["position_open_no_active_signal"]
                signal_metrics: dict[str, object] = {}
                signal_fingerprint = build_signal_fingerprint(
                    run_id=latest.run_id,
                    timestamp=timestamp_value,
                    stock=stock,
                    future=future,
                    signal_action=action,
                )
                usage_fields = _signal_usage_fields(
                    run_id=latest.run_id,
                    timestamp=timestamp_value,
                    stock=stock,
                    future=future,
                    signal_action=action,
                    signal_fingerprint=signal_fingerprint,
                )
                entry_intent_row = latest_entry_intent_by_pair.get((stock, future))
                pending_intent_promoted = False
                if (
                    entry_intent_row is not None
                    and isinstance(getattr(entry_intent_row, "timestamp", None), datetime)
                ):
                    intent_run_id = str(entry_intent_row.run_id)
                    intent_timestamp = entry_intent_row.timestamp.isoformat()
                    intent_fingerprint = build_signal_fingerprint(
                        run_id=intent_run_id,
                        timestamp=intent_timestamp,
                        stock=stock,
                        future=future,
                        signal_action="enter",
                    )
                    intent_usage = _signal_usage_fields(
                        run_id=intent_run_id,
                        timestamp=intent_timestamp,
                        stock=stock,
                        future=future,
                        signal_action="enter",
                        signal_fingerprint=intent_fingerprint,
                    )
                    if not bool(intent_usage.get("signal_used")):
                        pending_intent_promoted = True
                        action = "enter"
                        signal_fingerprint = intent_fingerprint
                        usage_fields = intent_usage
                        signal_score = float(entry_intent_row.score or 0.0)
                        signal_direction = entry_intent_row.direction or signal_direction
                        signal_reasons = (
                            list(entry_intent_row.reasons)
                            if isinstance(entry_intent_row.reasons, list)
                            else []
                        )
                        if "pending_entry_intent_active" not in signal_reasons:
                            signal_reasons.append("pending_entry_intent_active")
                        signal_metrics = _enrich_entry_plan_metrics(
                            settings=settings,
                            current_metrics=None,
                            fallback_metrics=(
                                entry_intent_row.metrics
                                if isinstance(entry_intent_row.metrics, dict)
                                else None
                            ),
                            force_rebuild=False,
                        )
                payload = {
                    "run_id": latest.run_id,
                    "timestamp": timestamp_value,
                    "stock": stock,
                    "future": future,
                    "signal_fingerprint": signal_fingerprint,
                    "signal_action": action,
                    "signal_direction": signal_direction,
                    "signal_score": signal_score,
                    "signal_reasons": signal_reasons,
                    "signal_metrics": signal_metrics,
                    "position_open": True,
                    "position_state": "open",
                    "position_enter_count": int(state.get("enter_count") or 0),
                    "position_exit_count": int(state.get("exit_count") or 0),
                    "position_net_executions": int(state.get("net_executions") or 0),
                    "position_enter_order_count": int(state.get("enter_order_count") or 0),
                    "position_exit_order_count": int(state.get("exit_order_count") or 0),
                    "position_net_orders": int(state.get("net_orders") or 0),
                    "position_linked_two_leg_orders": int(state.get("linked_two_leg_orders") or 0),
                    "position_partial_leg_orders": int(state.get("partial_leg_orders") or 0),
                    "position_open_stock_legs": int(open_legs.get("stock") or 0),
                    "position_open_future_legs": int(open_legs.get("future") or 0),
                    "position_open_other_legs": int(open_legs.get("other") or 0),
                    "position_open_leg_total": int(state.get("open_leg_total") or 0),
                    "position_leg_imbalance": bool(state.get("open_leg_imbalance")),
                    "position_last_execution_at": (
                        last_execution_at.isoformat() if isinstance(last_execution_at, datetime) else None
                    ),
                    **usage_fields,
                }
                if pending_intent_promoted and entry_intent_row is not None:
                    payload["signal_origin_run_id"] = entry_intent_row.run_id
                    payload["signal_origin_timestamp"] = entry_intent_row.timestamp.isoformat()
                actionable.append(_merge_signal_metrics(payload))

            callback_ttl_hours = int(getattr(settings.telegram, "callback_ttl_hours", 72) or 72)
            for row in actionable:
                delivery = signal_delivery_state(
                    row,
                    callback_ttl_hours=callback_ttl_hours,
                )
                row["delivery_action"] = delivery.get("delivery_action")
                row["delivery_allowed"] = bool(delivery.get("delivery_allowed"))
                row["delivery_suppressed_reason"] = delivery.get("delivery_suppressed_reason")
                row["entry_signal_expired"] = bool(delivery.get("entry_signal_expired"))
                row["entry_range_eligible"] = bool(delivery.get("entry_range_eligible"))

            if require_score_gate:
                actionable = [
                    row
                    for row in actionable
                    if bool(row.get("position_open")) or _record_score_gate_pass(row)
                ]

            actionable.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
            actionable.sort(key=lambda item: 0 if bool(item.get("position_open")) else 1)
            return jsonify(actionable)

    @server.route("/api/v2/signals/active", methods=["GET"])
    def signals_active_v2_api():
        started_at = datetime.now(timezone.utc)
        legacy = signals_active_api()
        rows, status_code = _extract_response_payload(legacy)
        if status_code >= 400:
            return _observe_request("v2_signals_active", started_at, legacy)
        if not isinstance(rows, list):
            return _observe_request("v2_signals_active", started_at, jsonify([]))

        events_by_ticker: dict[str, list[dict[str, object]]] = {}
        preferred_models = [settings.news_models.primary_model] + list(settings.news_models.enabled_models)
        if settings.ui.ff_news_bridge_enabled:
            lookback_start = datetime.now(timezone.utc) - timedelta(
                minutes=max(settings.news_filter.lookback_minutes, 1)
            )
            with session_factory() as session:
                feed_rows = _build_news_feed_events_from_event_layer(
                    session,
                    severity_filter=None,
                    ticker_filter=None,
                    entity_filter=None,
                    from_ts=_normalize_datetime(lookback_start),
                    to_ts=None,
                    limit=1000,
                    preferred_models=preferred_models,
                )
                if not feed_rows:
                    bundle = _load_news_bundle(
                        session,
                        from_ts=_normalize_datetime(lookback_start),
                        to_ts=None,
                        limit=1000,
                        preferred_models=preferred_models,
                    )
                    feed_rows = _build_news_feed_events(
                        bundle=bundle,
                        severity_filter=None,
                        ticker_filter=None,
                        entity_filter=None,
                        from_ts=_normalize_datetime(lookback_start),
                        to_ts=None,
                    )
            for event in feed_rows:
                if not isinstance(event, dict):
                    continue
                for entity in event.get("entity_links", []):
                    if not isinstance(entity, dict):
                        continue
                    ticker = str(entity.get("ticker") or entity.get("entity_id") or "").strip().upper()
                    if not ticker:
                        continue
                    events_by_ticker.setdefault(ticker, []).append(event)
        payload: list[dict[str, object]] = []
        bridge_links_to_store: list[dict[str, object]] = []
        silver_label_cache: dict[str, dict[str, object] | None] = {}

        def _build_news_score_payload(events: list[dict[str, object]]) -> dict[str, object]:
            if not events:
                return {
                    "direction": "neutral",
                    "direction_score": 0.0,
                    "p_move": 0.0,
                    "p_up": 0.0,
                    "p_down": 0.0,
                    "p_neutral": 1.0,
                    "p_up_given_move": 0.5,
                    "confidence": 0.0,
                    "matched_news_count": 0,
                    "scored_news_count": 0,
                }

            weighted_up = 0.0
            weighted_down = 0.0
            weighted_neutral = 0.0
            total_weight = 0.0
            scored_news_count = 0

            for event in events:
                news_id = str(event.get("news_id") or "").strip()
                if not news_id:
                    continue
                score_row = score_by_news.get(news_id)
                if not isinstance(score_row, dict):
                    continue
                prob_up = max(0.0, min(1.0, float(score_row.get("prob_up") or 0.0)))
                prob_down = max(0.0, min(1.0, float(score_row.get("prob_down") or 0.0)))
                prob_neutral = max(0.0, min(1.0, float(score_row.get("prob_neutral") or 0.0)))
                prob_total = prob_up + prob_down + prob_neutral
                if prob_total <= 0.0:
                    continue
                prob_up /= prob_total
                prob_down /= prob_total
                prob_neutral /= prob_total
                impact_score = max(0.0, float(score_row.get("impact_score") or 0.0))
                weight = max(impact_score, 0.05)
                weighted_up += prob_up * weight
                weighted_down += prob_down * weight
                weighted_neutral += prob_neutral * weight
                total_weight += weight
                scored_news_count += 1

            if total_weight <= 0.0:
                return {
                    "direction": "neutral",
                    "direction_score": 0.0,
                    "p_move": 0.0,
                    "p_up": 0.0,
                    "p_down": 0.0,
                    "p_neutral": 1.0,
                    "p_up_given_move": 0.5,
                    "confidence": 0.0,
                    "matched_news_count": len(events),
                    "scored_news_count": 0,
                }

            p_up = max(0.0, min(1.0, weighted_up / total_weight))
            p_down = max(0.0, min(1.0, weighted_down / total_weight))
            p_neutral = max(0.0, min(1.0, weighted_neutral / total_weight))
            prob_total = p_up + p_down + p_neutral
            if prob_total > 0.0:
                p_up /= prob_total
                p_down /= prob_total
                p_neutral /= prob_total

            p_move = max(0.0, min(1.0, 1.0 - p_neutral))
            directional_mass = p_up + p_down
            p_up_given_move = p_up / directional_mass if directional_mass > 0.0 else 0.5
            confidence = p_move * max(p_up_given_move, 1.0 - p_up_given_move)
            direction_score = p_up - p_down
            if p_move < 0.5:
                direction = "neutral"
            elif p_up > p_down:
                direction = "up"
            elif p_down > p_up:
                direction = "down"
            else:
                direction = "neutral"

            return {
                "direction": direction,
                "direction_score": round(direction_score, 6),
                "p_move": round(p_move, 6),
                "p_up": round(p_up, 6),
                "p_down": round(p_down, 6),
                "p_neutral": round(p_neutral, 6),
                "p_up_given_move": round(p_up_given_move, 6),
                "confidence": round(confidence, 6),
                "matched_news_count": len(events),
                "scored_news_count": scored_news_count,
            }

        def _load_silver_labels(event_ids: list[str]) -> dict[str, dict[str, object] | None]:
            normalized_ids = [str(item or "").strip() for item in event_ids if str(item or "").strip()]
            if not normalized_ids:
                return {}
            missing_ids = [event_id for event_id in normalized_ids if event_id not in silver_label_cache]
            if missing_ids:
                with session_factory() as session:
                    rows = load_news_gold_labels(
                        session,
                        target_type="event",
                        target_ids=missing_ids,
                        source="auto_target_v2",
                        quality="silver",
                        limit=max(len(missing_ids) * 5, 500),
                    )
                latest_by_event: dict[str, dict[str, object]] = {}
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    event_id = str(row.get("target_id") or "").strip()
                    if not event_id or event_id in latest_by_event:
                        continue
                    latest_by_event[event_id] = row
                for event_id in missing_ids:
                    silver_label_cache[event_id] = latest_by_event.get(event_id)
            return {event_id: silver_label_cache.get(event_id) for event_id in normalized_ids}

        for row in rows:
            if not isinstance(row, dict):
                continue
            signal_id = _build_signal_id_from_row(row)
            lifecycle_state = _derive_lifecycle_state(row)
            signal_action_effective = _derive_effective_signal_action(row)
            delivery = signal_delivery_state(
                {**row, "signal_action_effective": signal_action_effective},
                callback_ttl_hours=int(getattr(settings.telegram, "callback_ttl_hours", 72) or 72),
            )
            entity_ref = _build_pair_entity_ref(row.get("stock"), row.get("future"))
            gate_results = _build_gate_results_from_row(row, signal_id)
            execution_ref = {
                "position_open": bool(row.get("position_open")),
                "position_state": row.get("position_state"),
                "last_execution_at": row.get("position_last_execution_at"),
                "open_leg_total": int(row.get("position_open_leg_total") or 0),
                "net_orders": int(row.get("position_net_orders") or 0),
            }

            matched_events: list[dict[str, object]] = []
            if settings.ui.ff_news_bridge_enabled:
                candidate_tickers = {
                    str(row.get("stock") or "").strip().upper(),
                    str(row.get("future") or "").strip().upper(),
                }
                seen_news_ids: set[str] = set()
                for ticker in candidate_tickers:
                    if not ticker:
                        continue
                    for event in events_by_ticker.get(ticker, []):
                        if not isinstance(event, dict):
                            continue
                        news_id = str(event.get("news_id") or "").strip()
                        if not news_id or news_id in seen_news_ids:
                            continue
                        seen_news_ids.add(news_id)
                        matched_events.append(event)
                matched_events.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)

            gate_rows = [
                {
                    "news_id": event.get("news_id"),
                    "title": event.get("headline"),
                    "content": event.get("summary"),
                    "published_at": event.get("published_at"),
                    "source": event.get("source"),
                }
                for event in matched_events
            ]
            score_by_news: dict[str, dict[str, object]] = {}
            for event in matched_events:
                news_id = str(event.get("news_id") or "").strip()
                if not news_id:
                    continue
                model_scores = event.get("model_scores")
                selected_score: dict[str, object] | None = None
                if isinstance(model_scores, list):
                    selected_score = _select_primary_model_score(model_scores, preferred_models)
                if selected_score is not None:
                    score_by_news[news_id] = selected_score
            gate_result = run_news_gate(
                gate_rows,
                score_by_news=score_by_news,
                lookback_minutes=settings.news_filter.lookback_minutes,
                block_severity_threshold=settings.news_filter.block_severity_threshold,
                reduce_severity_threshold=settings.news_filter.reduce_severity_threshold,
                allowed_sources=settings.news_filter.sources,
                enforce_source_allowlist=settings.news_filter.enforce_source_allowlist,
            )
            gate_matched_news_ids = {
                str(item.item_id or "").strip()
                for item in gate_result.matched_items
                if str(item.item_id or "").strip()
            }
            gate_matched_events = [
                event
                for event in matched_events
                if str(event.get("news_id") or "").strip() in gate_matched_news_ids
            ]
            matched_event_ids = [
                str(event.get("news_event_id") or "").strip()
                for event in gate_matched_events
                if str(event.get("news_event_id") or "").strip()
            ]
            latest_published_at = (
                str(gate_matched_events[0].get("published_at") or "")
                if gate_matched_events
                else None
            )
            news_score = _build_news_score_payload(gate_matched_events)
            silver_explain = build_silver_explain_payload(
                gate_matched_events,
                news_score,
                _load_silver_labels(matched_event_ids),
                preview_limit=10,
            )
            if (
                settings.ui.ff_news_bridge_enabled
                and settings.ui.ff_news_bridge_persist_links_on_read
                and gate_matched_events
            ):
                bridge_links_to_store.extend(
                    build_signal_news_links(
                        signal_id=signal_id,
                        decision_id=None,
                        matched_news_refs=[
                            {
                                "news_id": str(event.get("news_id") or "").strip(),
                                "event_id": str(event.get("news_event_id") or "").strip(),
                            }
                            for event in gate_matched_events
                        ],
                        gate_action=gate_result.action,
                        link_type="used_in_decision",
                        lookback_minutes=settings.news_filter.lookback_minutes,
                        source="runtime",
                    )
                )
            enriched_row = dict(row)
            enriched_row.update(
                {
                    "signal_id": signal_id,
                    "entity_ref": entity_ref,
                    "lifecycle_state": lifecycle_state,
                    "signal_action_effective": signal_action_effective,
                    "news_ref": {
                        "total_events": len(gate_matched_events),
                        "latest_published_at": latest_published_at,
                    },
                    "news_gate_action": gate_result.action if gate_matched_events else "allow",
                    "matched_news_event_ids": matched_event_ids,
                    "event_ids_used": matched_event_ids,
                    "news_severity": gate_result.highest_severity if gate_matched_events else "low",
                    "news_score": news_score,
                    "silver_explain": silver_explain,
                    "gate_results": gate_results,
                    "decision_ref": {"decision_id": None},
                    "execution_ref": execution_ref,
                    "delivery_action": delivery.get("delivery_action"),
                    "delivery_allowed": bool(delivery.get("delivery_allowed")),
                    "delivery_suppressed_reason": delivery.get("delivery_suppressed_reason"),
                    "entry_signal_expired": bool(delivery.get("entry_signal_expired")),
                    "entry_range_eligible": bool(delivery.get("entry_range_eligible")),
                }
            )
            payload.append(enriched_row)
        created_links_count = 0
        if bridge_links_to_store:
            dedup_links: dict[str, dict[str, object]] = {}
            for row in bridge_links_to_store:
                key = "|".join(
                    [
                        str(row.get("news_id") or ""),
                        str(row.get("event_id") or ""),
                        str(row.get("signal_id") or ""),
                        str(row.get("link_type") or ""),
                        str(row.get("window_start") or ""),
                    ]
                )
                dedup_links[key] = row
            created_links_count = len(dedup_links)
            with session_factory() as session:
                upsert_news_signal_links(session, dedup_links.values())
        _mark_signal_news_bridge_events(payload, created_links_count)
        return _observe_request("v2_signals_active", started_at, jsonify(payload))

    def _collect_signal_actionability_rows() -> tuple[list[dict[str, object]], int]:
        legacy = signals_active_v2_api()
        rows, status_code = _extract_response_payload(legacy)
        if status_code >= 400:
            return [], status_code
        if not isinstance(rows, list):
            return [], 200

        callback_ttl_hours = int(getattr(settings.telegram, "callback_ttl_hours", 72) or 72)
        payload: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            payload.append(
                _build_signal_actionability_projection(
                    row,
                    callback_ttl_hours=callback_ttl_hours,
                )
            )
        payload.sort(key=lambda item: str(item.get("snapshot_as_of") or ""), reverse=True)
        payload.sort(key=lambda item: 0 if str(item.get("position_state") or "") == "open" else 1)
        return payload, 200

    @server.route("/api/v2/signals/actionability", methods=["GET"])
    def signals_actionability_v2_api():
        rows, status_code = _collect_signal_actionability_rows()
        if status_code >= 400:
            return jsonify([])

        entity_type = str(request.args.get("entity_type") or "").strip().lower()
        if entity_type not in {"", "pair", "instrument"}:
            return _bad_request("entity_type must be one of: pair, instrument")
        instrument_type_filter = str(request.args.get("instrument_type") or "").strip().lower()
        if instrument_type_filter not in {"", "stock", "future"}:
            return _bad_request("instrument_type must be one of: stock, future")
        include_non_actionable = _coerce_bool(
            request.args.get("include_non_actionable"),
            default=False,
        )
        limit = max(_parse_int(request.args.get("limit"), 500), 0)

        projected: list[dict[str, object]] = []
        for row in rows:
            if entity_type in {"", "pair"}:
                projected.append(dict(row))
            if entity_type in {"", "instrument"}:
                projected.extend(_build_instrument_actionability_rows(row))

        if instrument_type_filter:
            projected = [
                row
                for row in projected
                if str(row.get("instrument_type") or "").strip().lower() == instrument_type_filter
            ]

        if not include_non_actionable:
            projected = [
                row
                for row in projected
                if str(row.get("actionability_state") or "").strip().lower()
                in {"actionable_enter", "actionable_enter_repriced", "actionable_exit", "hold_open"}
                or bool(row.get("hold_required"))
            ]

        if limit > 0:
            projected = projected[:limit]
        return jsonify(projected)

    @server.route("/api/v2/pairs/actionability", methods=["GET"])
    def pairs_actionability_v2_api():
        include_non_actionable = _coerce_bool(
            request.args.get("include_non_actionable"),
            default=False,
        )
        include_open_holds = _coerce_bool(
            request.args.get("include_open_holds"),
            default=True,
        )
        limit = max(_parse_int(request.args.get("limit"), 500), 0)

        rows, status_code = _collect_signal_actionability_rows()
        if status_code >= 400:
            return jsonify([])

        projected: list[dict[str, object]] = []
        for row in rows:
            state = str(row.get("actionability_state") or "").strip().lower()
            if not include_non_actionable and state not in {
                "actionable_enter",
                "actionable_enter_repriced",
                "actionable_exit",
                "hold_open",
            }:
                continue
            if not include_open_holds and state == "hold_open":
                continue

            pair_id = f"{str(row.get('stock') or '').strip()}__{str(row.get('future') or '').strip()}"
            pair_row = {
                "pair_id": pair_id,
                "stock": row.get("stock"),
                "future": row.get("future"),
                "entity_ref": row.get("entity_ref"),
                "snapshot_as_of": row.get("snapshot_as_of"),
                "axes": row.get("axes"),
                "position_state": row.get("position_state"),
                "actionability_state": row.get("actionability_state"),
                "actionable_enter": bool(row.get("actionable_enter")),
                "actionable_exit": bool(row.get("actionable_exit")),
                "hold_required": bool(row.get("hold_required")),
                "intent": row.get("intent"),
                "entry_plan": {
                    "plan_revision": (row.get("entry_plan") or {}).get("plan_revision")
                    if isinstance(row.get("entry_plan"), dict)
                    else None,
                    "generated_at": (row.get("entry_plan") or {}).get("generated_at")
                    if isinstance(row.get("entry_plan"), dict)
                    else None,
                    "valid_until": (row.get("entry_plan") or {}).get("valid_until")
                    if isinstance(row.get("entry_plan"), dict)
                    else None,
                    "direction": (row.get("entry_plan") or {}).get("direction")
                    if isinstance(row.get("entry_plan"), dict)
                    else None,
                    "entry_stock_min": row.get("entry_stock_min"),
                    "entry_stock_max": row.get("entry_stock_max"),
                    "entry_future_min_per_share": row.get("entry_future_min_per_share"),
                    "entry_future_max_per_share": row.get("entry_future_max_per_share"),
                    "entry_spread_min": row.get("entry_spread_min"),
                    "entry_spread_max": row.get("entry_spread_max"),
                    "entry_spread_pct_min": row.get("entry_spread_pct_min"),
                    "entry_spread_pct_max": row.get("entry_spread_pct_max"),
                },
                "entry_range_now": {
                    "stock_now": row.get("spot_mid"),
                    "future_now": row.get("future_mid"),
                    "spread_now": row.get("spread_mid"),
                    "spread_pct_now": row.get("spread_pct"),
                    "in_range": bool((row.get("entry_range_now") or {}).get("in_range"))
                    if isinstance(row.get("entry_range_now"), dict)
                    else False,
                    "out_of_range_reasons": (
                        (row.get("entry_range_now") or {}).get("out_of_range_reasons") or []
                    )
                    if isinstance(row.get("entry_range_now"), dict)
                    else [],
                },
                "delivery": row.get("delivery"),
                "evidence_summary": row.get("evidence_summary"),
                "evidence_items": row.get("evidence_items"),
                "policy_outcome": row.get("policy_outcome"),
                "reasons": row.get("reasons") or [],
                "signal_origin_run_id": row.get("signal_origin_run_id"),
                "signal_origin_timestamp": row.get("signal_origin_timestamp"),
                "metrics": row.get("metrics") or {},
                "signal_id": row.get("signal_id"),
            }
            projected.append(pair_row)

        if limit > 0:
            projected = projected[:limit]
        return jsonify(projected)

    def _normalize_entity_action_result(
        result,
        *,
        entity_ref: dict[str, object],
        intent_id: str | None,
        signal_id_hint: str | None = None,
        extra_fields: dict[str, object] | None = None,
    ):
        payload, status_code = _extract_response_payload(result)
        if not isinstance(payload, dict):
            return result
        fail_closed_payload = payload.get("fail_closed")
        fail_closed = False
        if isinstance(fail_closed_payload, dict):
            fail_closed = bool(fail_closed_payload.get("enabled"))
        response_payload = {
            "status": payload.get("status", "ok"),
            "action": payload.get("action"),
            "entity_ref": entity_ref,
            "intent_id": intent_id,
            "signal_id": payload.get("signal_id") or signal_id_hint,
            "fail_closed": fail_closed,
            "request_id": payload.get("execution_event_id") or payload.get("action_id"),
            "recorded_at": payload.get("created_at"),
            "message": payload.get("message"),
        }
        if isinstance(extra_fields, dict):
            response_payload.update(extra_fields)
        if status_code >= 400:
            return jsonify(response_payload), status_code
        return jsonify(response_payload), status_code

    def _find_pair_projection(stock: str, future: str) -> dict[str, object] | None:
        rows, _ = _collect_signal_actionability_rows()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("stock") or "").strip() != stock:
                continue
            if str(row.get("future") or "").strip() != future:
                continue
            return row
        return None

    def _resolve_instrument_pair_context(
        *,
        entity_id: str,
        payload: dict[str, object],
    ) -> tuple[dict[str, object] | None, str | None]:
        requested_type = _normalize_instrument_type(payload.get("instrument_type"))
        requested_pair = _parse_pair_id(payload.get("pair_id"))
        requested_stock = str(payload.get("stock") or "").strip()
        requested_future = str(payload.get("future") or "").strip()
        if not requested_pair and requested_stock and requested_future:
            requested_pair = (requested_stock, requested_future)

        rows, _ = _collect_signal_actionability_rows()
        candidates: list[tuple[dict[str, object], str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            stock = str(row.get("stock") or "").strip()
            future = str(row.get("future") or "").strip()
            if not stock or not future:
                continue
            inferred_type: str | None = None
            if entity_id == stock:
                inferred_type = "stock"
            elif entity_id == future:
                inferred_type = "future"
            if inferred_type is None:
                continue
            if requested_type is not None and requested_type != inferred_type:
                continue
            if requested_pair is not None and (stock, future) != requested_pair:
                continue
            candidates.append((row, inferred_type))

        if not candidates:
            return None, None
        if len(candidates) > 1:
            return {"_ambiguous_pairs": [f"{item[0].get('stock')}__{item[0].get('future')}" for item in candidates]}, None
        selected_row, selected_type = candidates[0]
        return selected_row, selected_type

    def _record_pair_entity_action(
        stock: str,
        future: str,
        payload: dict[str, object],
        *,
        entity_ref_override: dict[str, object] | None = None,
        extra_fields: dict[str, object] | None = None,
    ):
        signal_id_hint = str(payload.get("signal_id") or "").strip() or None
        intent_id = str(payload.get("intent_id") or "").strip() or None
        projection = _find_pair_projection(stock, future)
        current_intent_id = None
        if isinstance(projection, dict):
            intent_payload = projection.get("intent")
            if isinstance(intent_payload, dict):
                current_intent_id = str(intent_payload.get("intent_id") or "").strip() or None
            if signal_id_hint is None:
                signal_id_hint = str(projection.get("signal_id") or "").strip() or None

        if intent_id is not None and intent_id != "":
            if not current_intent_id:
                return (
                    jsonify(
                        {
                            "status": "blocked",
                            "action": payload.get("action"),
                            "entity_ref": entity_ref_override or _build_pair_entity_ref(stock, future),
                            "intent_id": intent_id,
                            "signal_id": signal_id_hint,
                            "fail_closed": bool(settings.ui.ff_fail_closed_execution),
                            "request_id": None,
                            "recorded_at": _iso_now(),
                            "message": "intent_not_active",
                            "error": "intent_mismatch",
                        }
                    ),
                    409,
                )
            if intent_id != current_intent_id:
                return (
                    jsonify(
                        {
                            "status": "blocked",
                            "action": payload.get("action"),
                            "entity_ref": entity_ref_override or _build_pair_entity_ref(stock, future),
                            "intent_id": intent_id,
                            "signal_id": signal_id_hint,
                            "fail_closed": bool(settings.ui.ff_fail_closed_execution),
                            "request_id": None,
                            "recorded_at": _iso_now(),
                            "message": "intent_superseded_or_stale",
                            "error": "intent_mismatch",
                            "current_intent_id": current_intent_id,
                        }
                    ),
                    409,
                )

        action_payload = dict(payload)
        action_payload["stock"] = stock
        action_payload["future"] = future
        if signal_id_hint is not None:
            action_payload["signal_id"] = signal_id_hint
        result = _record_signal_action(
            signal_id=signal_id_hint,
            payload=action_payload,
            source_default="ui",
            legacy_mode=False,
        )
        return _normalize_entity_action_result(
            result,
            entity_ref=entity_ref_override or _build_pair_entity_ref(stock, future),
            intent_id=intent_id,
            signal_id_hint=signal_id_hint,
            extra_fields=extra_fields,
        )

    @server.route("/api/v2/entities/<entity_type>/<path:entity_id>/signals/actions", methods=["POST"])
    def entity_signals_actions_v2_api(entity_type: str, entity_id: str):
        payload = request.get_json(silent=True)
        if payload is None or not isinstance(payload, dict):
            return _bad_request("invalid_json")
        normalized_entity_type = str(entity_type or "").strip().lower()
        if normalized_entity_type not in {"pair", "instrument"}:
            return _bad_request("entity_type must be one of: pair, instrument")
        if normalized_entity_type == "pair":
            pair = _parse_pair_id(entity_id)
            if pair is None:
                return _bad_request("pair entity_id must be STOCK__FUTURE or STOCK:FUTURE")
            stock, future = pair
            return _record_pair_entity_action(stock, future, dict(payload))

        intent_id = str(payload.get("intent_id") or "").strip() or None
        action = str(payload.get("action") or "").strip().lower()
        if action not in {"ack", "enter", "exit", "hold"}:
            return _bad_request("action must be one of: ack, enter, exit, hold")
        instrument_id = str(entity_id).strip()
        if not instrument_id:
            return _bad_request("entity_id is required for instrument")

        resolved_row, resolved_type = _resolve_instrument_pair_context(
            entity_id=instrument_id,
            payload=dict(payload),
        )
        if isinstance(resolved_row, dict) and "_ambiguous_pairs" in resolved_row:
            return (
                jsonify(
                    {
                        "status": "blocked",
                        "action": action,
                        "entity_ref": {
                            "entity_type": "instrument",
                            "entity_id": instrument_id,
                            "asset_id": instrument_id or None,
                            "ticker": instrument_id or None,
                        },
                        "intent_id": intent_id,
                        "signal_id": None,
                        "fail_closed": bool(settings.ui.ff_fail_closed_execution),
                        "request_id": None,
                        "recorded_at": _iso_now(),
                        "message": "instrument_entity_is_ambiguous_use_pair_id",
                        "error": "ambiguous_instrument_entity",
                        "candidate_pairs": resolved_row.get("_ambiguous_pairs"),
                    }
                ),
                409,
            )
        if not isinstance(resolved_row, dict):
            return (
                jsonify(
                    {
                        "status": "not_found",
                        "action": action,
                        "entity_ref": {
                            "entity_type": "instrument",
                            "entity_id": instrument_id,
                            "asset_id": instrument_id or None,
                            "ticker": instrument_id or None,
                        },
                        "intent_id": intent_id,
                        "signal_id": None,
                        "fail_closed": bool(settings.ui.ff_fail_closed_execution),
                        "request_id": None,
                        "recorded_at": _iso_now(),
                        "message": "instrument_entity_has_no_active_pair_context",
                    }
                ),
                404,
            )

        stock = str(resolved_row.get("stock") or "").strip()
        future = str(resolved_row.get("future") or "").strip()
        if not stock or not future:
            return _bad_request("instrument resolution failed")
        pair_id = f"{stock}__{future}"
        instrument_ref = {
            "entity_type": "instrument",
            "entity_id": instrument_id,
            "asset_id": instrument_id or None,
            "ticker": instrument_id or None,
        }
        return _record_pair_entity_action(
            stock,
            future,
            dict(payload),
            entity_ref_override=instrument_ref,
            extra_fields={
                "pair_ref": _build_pair_entity_ref(stock, future),
                "pair_id": pair_id,
                "instrument_type": resolved_type,
            },
        )

    @server.route("/api/v2/pairs/<pair_id>/actions", methods=["POST"])
    def pair_actions_v2_api(pair_id: str):
        payload = request.get_json(silent=True)
        if payload is None or not isinstance(payload, dict):
            return _bad_request("invalid_json")
        pair = _parse_pair_id(pair_id)
        if pair is None:
            return _bad_request("pair_id must be STOCK__FUTURE or STOCK:FUTURE")
        stock, future = pair
        result = _record_pair_entity_action(stock, future, dict(payload))
        response_payload, status_code = _extract_response_payload(result)
        if not isinstance(response_payload, dict):
            return result
        pair_response = dict(response_payload)
        pair_response["pair_id"] = f"{stock}__{future}"
        return jsonify(pair_response), status_code

    def _record_signal_action(
        signal_id: str | None,
        payload: dict[str, object],
        *,
        source_default: str,
        legacy_mode: bool = False,
    ):
        action_pair = _coerce_signal_action_request(payload.get("action"), legacy_mode=legacy_mode)
        if action_pair is None:
            if legacy_mode:
                return _bad_request("action must be one of: enter, exit, hold_open")
            return _bad_request("action must be one of: ack, enter, exit, hold")
        requested_action, execution_action = action_pair

        source = _normalize_signal_action_source(payload.get("source"), default=source_default)
        actor_id = str(payload.get("actor_id") or payload.get("actor") or "operator").strip() or "operator"
        reason_code_raw = payload.get("reason_code")
        reason_code = str(reason_code_raw).strip() if reason_code_raw is not None else None
        if reason_code == "":
            reason_code = None
        fail_closed_override = bool(_parse_bool(payload.get("fail_closed_override")))
        override_reason_raw = payload.get("override_reason")
        override_reason = (
            str(override_reason_raw).strip() if override_reason_raw is not None else (reason_code or None)
        )
        if override_reason == "":
            override_reason = None
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not idempotency_key:
            return _bad_request("idempotency_key is required")

        signal_row = None
        active_rows_cache: list[dict[str, object]] | None = None

        def _load_active_rows_for_lookup() -> list[dict[str, object]]:
            nonlocal active_rows_cache
            if active_rows_cache is not None:
                return active_rows_cache
            legacy = signals_active_api()
            rows, status_code = _extract_response_payload(legacy)
            if status_code >= 400 or not isinstance(rows, list):
                active_rows_cache = []
            else:
                active_rows_cache = [row for row in rows if isinstance(row, dict)]
            return active_rows_cache

        if signal_id:
            for row in _load_active_rows_for_lookup():
                if _build_signal_id_from_row(row) == signal_id:
                    signal_row = row
                    break

        stock = str(payload.get("stock") or (signal_row or {}).get("stock") or "").strip()
        future = str(payload.get("future") or (signal_row or {}).get("future") or "").strip()
        if signal_row is None and stock and future:
            for row in _load_active_rows_for_lookup():
                if str(row.get("stock") or "").strip() != stock:
                    continue
                if str(row.get("future") or "").strip() != future:
                    continue
                row_action = str(row.get("signal_action") or "").strip().lower()
                if row_action == requested_action:
                    signal_row = row
                    break
                if signal_row is None:
                    signal_row = row
        stock = str(payload.get("stock") or (signal_row or {}).get("stock") or "").strip()
        future = str(payload.get("future") or (signal_row or {}).get("future") or "").strip()
        if not stock or not future:
            message = "signal_id is unknown in active set" if signal_id else "stock and future are required"
            return jsonify({"error": "not_found", "message": message}), 404
        direction = payload.get("direction") or (signal_row or {}).get("signal_direction")
        signal_id_resolved = signal_id or _stable_id("sig", stock, future, requested_action)

        signal_run_id = str((signal_row or {}).get("run_id") or "").strip()
        signal_timestamp = str((signal_row or {}).get("timestamp") or "").strip()
        signal_action_for_fingerprint = str((signal_row or {}).get("signal_action") or "").strip().lower()
        if not signal_action_for_fingerprint:
            signal_action_for_fingerprint = requested_action
        signal_fingerprint = str((signal_row or {}).get("signal_fingerprint") or "").strip() or None
        if signal_run_id and signal_timestamp and signal_action_for_fingerprint:
            if signal_fingerprint is None:
                signal_fingerprint = build_signal_fingerprint(
                    run_id=signal_run_id,
                    timestamp=signal_timestamp,
                    stock=stock,
                    future=future,
                    signal_action=signal_action_for_fingerprint,
                )

        pretrade_payload = payload.get("pretrade")
        pretrade_status_hint = payload.get("pretrade_status")
        pretrade_degraded_hint = _parse_bool(payload.get("pretrade_degraded"))
        if isinstance(pretrade_payload, dict):
            if pretrade_status_hint is None:
                pretrade_status_hint = pretrade_payload.get("pretrade_status") or pretrade_payload.get("status")
            if pretrade_degraded_hint is None:
                pretrade_degraded_hint = _parse_bool(pretrade_payload.get("degraded"))

        fail_closed = evaluate_fail_closed_entry(
            enabled=bool(settings.ui.ff_fail_closed_execution),
            requested_action=requested_action,
            signal_row=signal_row if isinstance(signal_row, dict) else None,
            source=source,
            override=fail_closed_override,
            override_reason=override_reason,
            pretrade_status=pretrade_status_hint,
            pretrade_degraded=pretrade_degraded_hint,
        )
        if fail_closed.status == "block":
            return (
                jsonify(
                    {
                        "status": "blocked",
                        "error": "fail_closed_execution",
                        "signal_id": signal_id_resolved,
                        "entity_ref": _build_pair_entity_ref(stock, future),
                        "action": requested_action,
                        "reason_code": fail_closed.reason_code,
                        "message": fail_closed.message,
                        "fail_closed": {
                            "enabled": bool(settings.ui.ff_fail_closed_execution),
                            "status": fail_closed.status,
                            "reason_code": fail_closed.reason_code,
                        },
                    }
                ),
                409,
            )

        side = payload.get("side")
        order_id = _normalize_order_id(payload.get("order_id"))
        if order_id is None and execution_action in {"enter", "exit", "hold_open"}:
            leg = _normalize_execution_leg(side)
            if leg in {"stock", "future"}:
                order_id = f"{stock}-{future}-{execution_action}-{uuid.uuid4().hex[:10]}"

        note_payload: dict[str, object] = {
            "kind": "signal_action_v1_adapter" if legacy_mode else "signal_action_v2",
            "signal_id": signal_id_resolved,
            "source": source,
            "actor_id": actor_id,
            "idempotency_key": idempotency_key,
            "requested_action": requested_action,
        }
        if signal_fingerprint is not None:
            note_payload["fingerprint"] = signal_fingerprint
        if signal_run_id:
            note_payload["signal_run_id"] = signal_run_id
        if signal_timestamp:
            note_payload["signal_timestamp"] = signal_timestamp
        if signal_action_for_fingerprint:
            note_payload["signal_action"] = signal_action_for_fingerprint
        if reason_code is not None:
            note_payload["reason_code"] = reason_code
        if fail_closed.status == "override":
            note_payload["fail_closed_override"] = True
            note_payload["fail_closed_reason"] = fail_closed.reason_code
        operator_note = payload.get("note") or payload.get("comment")
        operator_note_value = str(operator_note).strip() if operator_note is not None else None
        if operator_note_value:
            note_payload["note"] = operator_note_value
            ack_note = parse_ack_note(operator_note_value)
            if isinstance(ack_note, dict):
                ack_fingerprint = str(ack_note.get("fingerprint") or "").strip()
                if ack_fingerprint and "fingerprint" not in note_payload:
                    note_payload["fingerprint"] = ack_fingerprint
        note = json.dumps(note_payload, ensure_ascii=False, separators=(",", ":"))

        now = datetime.now(timezone.utc)
        action_id = f"act-{uuid.uuid4().hex[:12]}"

        def _duplicate_signal_action_response(row) -> tuple[object, int] | object:
            return jsonify(
                {
                    "status": "duplicate",
                    "action_id": f"act-{row.id}",
                    "signal_id": signal_id_resolved,
                    "entity_ref": _build_pair_entity_ref(stock, future),
                    "execution_event_id": f"exec-{row.id}",
                    "action": requested_action,
                    "idempotency_key": idempotency_key,
                    "order_id": row.order_id,
                    "fail_closed": {
                        "enabled": bool(settings.ui.ff_fail_closed_execution),
                        "status": fail_closed.status,
                        "reason_code": fail_closed.reason_code,
                    },
                }
            )

        with session_factory() as session:
            existing = load_signal_execution_by_idempotency(
                session,
                stock=stock,
                future=future,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return _duplicate_signal_action_response(existing)

            status = payload.get("status")
            if status is None:
                status = "acknowledged" if requested_action == "ack" else "recorded"
            try:
                store_signal_execution(
                    session,
                    now,
                    {
                        "stock": stock,
                        "future": future,
                        "direction": direction,
                        "action": execution_action,
                        "price": payload.get("price"),
                        "quantity": payload.get("quantity"),
                        "side": side,
                        "order_id": order_id,
                        "idempotency_key": idempotency_key,
                        "status": status,
                        "note": note,
                    },
                )
            except IntegrityError:
                session.rollback()
                existing = load_signal_execution_by_idempotency(
                    session,
                    stock=stock,
                    future=future,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    return _duplicate_signal_action_response(existing)
                raise

        return jsonify(
            {
                "status": "ok",
                "action_id": action_id,
                "signal_id": signal_id_resolved,
                "entity_ref": _build_pair_entity_ref(stock, future),
                "execution_event_id": _stable_id(
                    "exec",
                    signal_id_resolved,
                    idempotency_key,
                    requested_action,
                    now.isoformat(),
                    length=20,
                ),
                "action": requested_action,
                "source": source,
                "actor_id": actor_id,
                "idempotency_key": idempotency_key,
                "stored_action": execution_action,
                "order_id": order_id,
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "fail_closed": {
                    "enabled": bool(settings.ui.ff_fail_closed_execution),
                    "status": fail_closed.status,
                    "reason_code": fail_closed.reason_code,
                },
            }
        )

    @server.route("/api/v2/signals/<signal_id>/actions", methods=["POST"])
    def signals_actions_v2_api(signal_id: str):
        started_at = datetime.now(timezone.utc)
        payload = request.get_json(silent=True)
        if payload is None or not isinstance(payload, dict):
            return _observe_request("v2_signals_actions", started_at, _bad_request("invalid_json"))
        result = _record_signal_action(
            signal_id,
            dict(payload),
            source_default="ui",
            legacy_mode=False,
        )
        _mark_signal_action_events(result)
        return _observe_request("v2_signals_actions", started_at, result)

    @server.route("/api/v2/policies/auto-unwind/run", methods=["POST"])
    def auto_unwind_run_v2_api():
        started_at = datetime.now(timezone.utc)

        def _finish(result):
            _mark_auto_unwind_events(result)
            return _observe_request("v2_auto_unwind_run", started_at, result)

        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return _finish(_bad_request("payload must be object"))

        timeout_default = max(int(getattr(settings.ui, "auto_unwind_timeout_sec", 600) or 600), 0)
        timeout_sec = max(_parse_int(payload.get("timeout_sec"), timeout_default), 0)
        dry_run_raw = _parse_bool(payload.get("dry_run"))
        dry_run = bool(dry_run_raw) if dry_run_raw is not None else False
        actor_id = str(payload.get("actor_id") or "system:auto-unwind").strip() or "system:auto-unwind"

        now_utc = datetime.now(timezone.utc)
        now_override = payload.get("now_utc")
        if now_override is not None and str(now_override).strip():
            try:
                parsed_now = datetime.fromisoformat(str(now_override).strip().replace("Z", "+00:00"))
            except ValueError:
                return _finish(_bad_request("now_utc must be ISO-8601 datetime"))
            now_utc = (
                parsed_now.replace(tzinfo=timezone.utc)
                if parsed_now.tzinfo is None
                else parsed_now.astimezone(timezone.utc)
            )

        active = signals_active_api()
        rows, status_code = _extract_response_payload(active)
        if status_code >= 400:
            return _finish(active)
        rows_list: list[dict[str, object]] = []
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    rows_list.append(row)

        candidates = select_auto_unwind_candidates(rows_list, timeout_sec=timeout_sec, now_utc=now_utc)
        rows_by_pair: dict[tuple[str, str], dict[str, object]] = {
            (str(row.get("stock") or "").strip(), str(row.get("future") or "").strip()): row
            for row in rows_list
        }
        candidate_payload: list[dict[str, object]] = []
        for candidate in candidates:
            pair_key = (candidate.stock, candidate.future)
            row = rows_by_pair.get(pair_key)
            signal_id_value: str | None = None
            if isinstance(row, dict):
                signal_id_value = _build_signal_id_from_row(row)
            candidate_payload.append(
                {
                    "signal_id": signal_id_value,
                    "stock": candidate.stock,
                    "future": candidate.future,
                    "direction": candidate.direction,
                    "last_execution_at": candidate.last_execution_at,
                    "age_sec": candidate.age_sec,
                    "open_leg_total": candidate.open_leg_total,
                    "open_stock_legs": candidate.open_stock_legs,
                    "open_future_legs": candidate.open_future_legs,
                    "reason_code": "LEG_IMBALANCE_TIMEOUT",
                }
            )

        if dry_run:
            return _finish(
                jsonify(
                    {
                        "status": "dry_run",
                        "policy": "auto_unwind_leg_imbalance_timeout",
                        "evaluated_at": now_utc.isoformat().replace("+00:00", "Z"),
                        "timeout_sec": timeout_sec,
                        "candidate_count": len(candidate_payload),
                        "candidates": candidate_payload,
                    }
                )
            )

        triggered: list[dict[str, object]] = []
        duplicates: list[dict[str, object]] = []
        blocked: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []

        for candidate in candidates:
            action_payload: dict[str, object] = {
                "action": "exit",
                "stock": candidate.stock,
                "future": candidate.future,
                "direction": candidate.direction,
                "source": "system",
                "actor_id": actor_id,
                "reason_code": "LEG_IMBALANCE_TIMEOUT",
                "comment": f"auto_unwind_after_{candidate.age_sec}s",
                "status": "policy_submitted",
                "idempotency_key": (
                    f"auto-unwind:{candidate.stock}:{candidate.future}:{candidate.last_execution_at}"
                ),
            }
            result = _record_signal_action(
                signal_id=None,
                payload=action_payload,
                source_default="system",
                legacy_mode=False,
            )
            result_payload, result_status = _extract_response_payload(result)
            item = {
                "stock": candidate.stock,
                "future": candidate.future,
                "age_sec": candidate.age_sec,
                "last_execution_at": candidate.last_execution_at,
            }

            if isinstance(result_payload, dict):
                item["action_status"] = result_payload.get("status")
                item["action_id"] = result_payload.get("action_id")
                item["execution_event_id"] = result_payload.get("execution_event_id")
                item["reason_code"] = result_payload.get("reason_code")
                item["message"] = result_payload.get("message")
            else:
                item["action_status"] = "unknown"
                item["message"] = "non_json_response"

            if result_status >= 500:
                errors.append(item)
                continue
            action_status = str(item.get("action_status") or "").strip().lower()
            if action_status == "ok":
                triggered.append(item)
            elif action_status == "duplicate":
                duplicates.append(item)
            elif action_status == "blocked":
                blocked.append(item)
            else:
                errors.append(item)

        status = "ok" if not errors else "partial_error"
        return _finish(
            jsonify(
                {
                    "status": status,
                    "policy": "auto_unwind_leg_imbalance_timeout",
                    "evaluated_at": now_utc.isoformat().replace("+00:00", "Z"),
                    "timeout_sec": timeout_sec,
                    "candidate_count": len(candidate_payload),
                    "triggered_count": len(triggered),
                    "duplicate_count": len(duplicates),
                    "blocked_count": len(blocked),
                    "error_count": len(errors),
                    "candidates": candidate_payload,
                    "triggered": triggered,
                    "duplicates": duplicates,
                    "blocked": blocked,
                    "errors": errors,
                }
            )
        )

    register_ops_routes(
        server,
        session_factory=session_factory,
        load_latest_signal_run_fn=load_latest_signal_run,
        logger=logger,
        refresh_state=refresh_state,
        iso_now=_iso_now,
        observe_request=_observe_request,
        observability=observability,
    )

    register_market_data_routes(
        server,
        settings=settings,
        paths=paths,
        logger=logger,
        session_factory=session_factory,
        cache_version=_CACHE_VERSION,
        parse_date_bound=_parse_date_bound,
        merge_signal_metrics=_merge_signal_metrics,
        bad_request=_bad_request,
        extract_response_payload=_extract_response_payload,
        record_signal_action=_record_signal_action,
        normalize_execution_action=_normalize_execution_action,
        load_signal_history_fn=load_signal_history,
        load_signal_executions_fn=load_signal_executions,
        load_backtest_summary_fn=load_backtest_summary,
        load_latest_unified_output=_load_latest_unified_output,
        resolved_unified_max_pairs=_resolved_unified_max_pairs,
        df_to_records=_df_to_records,
        parse_int=_parse_int,
        signals_active_api=signals_active_api,
        derive_lifecycle_state=_derive_lifecycle_state,
        build_pair_entity_ref=_build_pair_entity_ref,
        build_signal_id_from_row=_build_signal_id_from_row,
        iso_now=_iso_now,
        append_jsonl=_append_jsonl,
        stringify_datetime_columns=_stringify_datetime_columns,
        read_cache=_read_cache,
        write_cache=_write_cache,
        unified_ttl_sec=_unified_ttl_sec,
        build_unified_spread_series_fn=build_unified_spread_series,
        get_build_spread_series=lambda: build_spread_series,
    )

    register_pretrade_routes(
        server,
        settings=settings,
        paths=paths,
        logger=logger,
        parse_float=_parse_float,
        parse_int=_parse_int,
        future_scale_from_raw=_future_scale_from_raw,
        bad_request=_bad_request,
        sanitize_value=_sanitize_value,
        build_pretrade_fail_open_result=_build_pretrade_fail_open_result,
        is_iss_transport_error=_is_iss_transport_error,
        get_moex_client_cls=lambda: MoexIssClient,
        get_run_delay_gate=lambda: run_delay_gate,
        observe_request=_observe_request,
        mark_pretrade_events=_mark_pretrade_events,
    )

    register_research_routes(
        server=server,
        paths=paths,
        logger=logger,
        bad_request=_bad_request,
        parse_bool=_parse_bool,
        run_backtest_v2_cached_fn=lambda *args, **kwargs: run_backtest_v2_cached(*args, **kwargs),
        serialize_backtest_report_fn=lambda report: serialize_backtest_report(report),
        start_hpo_run_fn=lambda *args, **kwargs: start_hpo_run(*args, **kwargs),
        load_hpo_status_fn=lambda *args, **kwargs: load_hpo_status(*args, **kwargs),
    )

    app = Dash(__name__, server=server, url_base_pathname="/dash/")
    app.layout = html.Div(
        [
            html.H2("MOEX Carry Dashboard"),
            dcc.Interval(id="refresh", interval=60_000, n_intervals=0),
            dcc.Tabs(
                [
                    dcc.Tab(
                        label="Top pairs",
                        children=[
                            dash_table.DataTable(
                                id="top_pairs_table",
                                data=[],
                                columns=[],
                                page_size=15,
                                **BASE_TABLE_STYLE,
                            )
                        ],
                    ),
                    dcc.Tab(
                        label="Signals",
                        children=[
                            dash_table.DataTable(
                                id="signals_table",
                                data=[],
                                columns=[],
                                page_size=15,
                                **BASE_TABLE_STYLE,
                            )
                        ],
                    ),
                    dcc.Tab(
                        label="Backtests",
                        children=[
                            dash_table.DataTable(
                                id="backtest_table",
                                data=[],
                                columns=[],
                                page_size=10,
                                **BASE_TABLE_STYLE,
                            )
                        ],
                    ),
                    dcc.Tab(
                        label="Decisions",
                        children=[
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Label("Strategy"),
                                            dcc.Dropdown(id="decision_filter_strategy", clearable=True),
                                        ],
                                        style={"width": "20%", "display": "inline-block"},
                                    ),
                                    html.Div(
                                        [
                                            html.Label("Instrument"),
                                            dcc.Dropdown(id="decision_filter_instrument", clearable=True),
                                        ],
                                        style={"width": "20%", "display": "inline-block", "marginLeft": "10px"},
                                    ),
                                    html.Div(
                                        [
                                            html.Label("Risk state"),
                                            dcc.Dropdown(id="decision_filter_risk", clearable=True),
                                        ],
                                        style={"width": "20%", "display": "inline-block", "marginLeft": "10px"},
                                    ),
                                    html.Div(
                                        [
                                            html.Label("News severity"),
                                            dcc.Dropdown(id="decision_filter_news", clearable=True),
                                        ],
                                        style={"width": "20%", "display": "inline-block", "marginLeft": "10px"},
                                    ),
                                ],
                                style={"marginBottom": "12px"},
                            ),
                            dash_table.DataTable(
                                id="decision_table",
                                data=[],
                                columns=_decision_columns(),
                                page_size=12,
                                row_selectable="single",
                                filter_action="native",
                                sort_action="native",
                                style_data_conditional=DECISION_STYLE,
                                **BASE_TABLE_STYLE,
                            ),
                            html.H4("Decision details"),
                            html.Pre(
                                id="decision_detail",
                                style={
                                    "whiteSpace": "pre-wrap",
                                    "backgroundColor": "#f9fafb",
                                    "border": "1px solid #e5e7eb",
                                    "padding": "8px",
                                    "fontFamily": "Consolas, monospace",
                                    "fontSize": "12px",
                                },
                            ),
                        ],
                    ),
                ]
            ),
        ]
    )

    @app.callback(
        Output("top_pairs_table", "data"),
        Output("top_pairs_table", "columns"),
        Output("signals_table", "data"),
        Output("signals_table", "columns"),
        Output("backtest_table", "data"),
        Output("backtest_table", "columns"),
        Input("refresh", "n_intervals"),
    )
    def _refresh(_):
        if settings.ui.use_unified_signal_engine:
            try:
                top_pairs, signals, backtest = _load_latest_unified_output(
                    max_pairs=_resolved_unified_max_pairs(settings.ui.signal_refresh_max_pairs),
                    fresh=False,
                )
                top_pairs = _apply_score_gate_filter(
                    top_pairs.copy(),
                    require_score_gate=_default_require_score_gate_for_top_pairs(settings),
                )
                signals = _apply_score_gate_filter(
                    signals.copy(),
                    require_score_gate=_default_require_score_gate_for_signals(settings),
                )
                backtest = backtest.copy()
            except Exception:
                logger.exception("Unified Dash refresh failed")
                top_pairs = pd.DataFrame()
                signals = pd.DataFrame()
                backtest = pd.DataFrame()
            if settings.ui.unified_allow_legacy_fallback:
                if top_pairs.empty:
                    top_pairs = load_top_pairs(paths.data_dir)
                if signals.empty:
                    signals = load_signals(paths.data_dir)
                if backtest.empty:
                    backtest = load_backtest_summary(paths.data_dir)
        else:
            top_pairs = load_top_pairs(paths.data_dir)
            signals = load_signals(paths.data_dir)
            backtest = load_backtest_summary(paths.data_dir)
        return (
            top_pairs.to_dict("records"),
            _table_columns(top_pairs),
            signals.to_dict("records"),
            _table_columns(signals),
            backtest.to_dict("records"),
            _table_columns(backtest),
        )

    @app.callback(
        Output("decision_table", "data"),
        Output("decision_table", "columns"),
        Output("decision_filter_strategy", "options"),
        Output("decision_filter_instrument", "options"),
        Output("decision_filter_risk", "options"),
        Output("decision_filter_news", "options"),
        Input("refresh", "n_intervals"),
        Input("decision_filter_strategy", "value"),
        Input("decision_filter_instrument", "value"),
        Input("decision_filter_risk", "value"),
        Input("decision_filter_news", "value"),
    )
    def _refresh_decisions(_, strategy_value, instrument_value, risk_value, news_value):
        decisions = load_decision_view(paths.data_dir)
        if decisions.empty:
            return [], _decision_columns(), [], [], [], []
        decisions = _prepare_decisions(decisions)
        filters = {
            "strategy_type": strategy_value,
            "primary_instrument": instrument_value,
            "risk_state": risk_value,
            "news_severity": news_value,
        }
        filtered = decisions
        for column, value in filters.items():
            if value:
                filtered = filtered[filtered[column] == value]
        strategy_options = [{"label": value, "value": value} for value in sorted(decisions["strategy_type"].unique())]
        instrument_options = [
            {"label": value, "value": value}
            for value in sorted(decisions["primary_instrument"].fillna("").unique())
            if value
        ]
        risk_options = [{"label": value, "value": value} for value in sorted(decisions["risk_state"].unique())]
        news_options = [{"label": value, "value": value} for value in sorted(decisions["news_severity"].unique())]
        return (
            filtered.to_dict("records"),
            _decision_columns(),
            strategy_options,
            instrument_options,
            risk_options,
            news_options,
        )

    @app.callback(
        Output("decision_detail", "children"),
        Input("decision_table", "selected_rows"),
        State("decision_table", "data"),
    )
    def _show_decision_detail(selected_rows, rows):
        if not selected_rows or not rows:
            return "Select a decision row to inspect the full decision_log."
        row = rows[selected_rows[0]]
        decision_id = row.get("decision_id")
        logs = load_decision_log(paths.data_dir)
        if logs.empty or not decision_id:
            return "Decision log entry not found."
        match = logs[logs["decision_id"] == decision_id]
        if match.empty:
            return "Decision log entry not found."
        entry = match.iloc[0].to_dict()
        return json.dumps(entry, ensure_ascii=False, indent=2)

    return app


def run_ui(settings: AppSettings) -> None:
    app = create_app(settings)
    app.run(host=settings.ui.host, port=settings.ui.port, debug=False)


