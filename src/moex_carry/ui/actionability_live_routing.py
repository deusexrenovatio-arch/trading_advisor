from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from typing import Mapping

from moex_carry.signals_delivery import parse_iso_utc, to_float
from moex_carry.ui.app_helpers_base import _extract_strategy_metadata

_FUT_MONTH_CODE_RE = re.compile(r"^([A-Za-z0-9]+?)[FGHJKMNQUVXZ]\d+$")

MINI_ROOT_TO_FULL_ROOT: dict[str, str] = {
    "BM": "BR",
    "GN": "GD",
    "NR": "NG",
    "RM": "RI",
    "S1": "SV",
}

DEFAULT_CLUSTER_BY_ROOT: dict[str, str] = {
    "BR": "energy",
    "NG": "energy",
    "GD": "metals",
    "SV": "metals",
    "PL": "metals",
    "PT": "metals",
    "RI": "indices",
    "MM": "indices",
}


def _metric_map(row: dict[str, object]) -> dict[str, object]:
    metrics = row.get("signal_metrics")
    return dict(metrics) if isinstance(metrics, dict) else {}


def _set_metric_map(row: dict[str, object], metrics: dict[str, object]) -> None:
    row["signal_metrics"] = metrics


def _dedup_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in result:
            continue
        result.append(text)
    return result


def extract_future_root(value: object) -> str:
    secid = str(value or "").strip().upper()
    matched = _FUT_MONTH_CODE_RE.match(secid)
    if matched:
        return str(matched.group(1)).upper()
    return secid


def preferred_live_root(value: object) -> str:
    root = extract_future_root(value)
    return MINI_ROOT_TO_FULL_ROOT.get(root, root)


def cluster_for_root(root: str) -> str | None:
    normalized = str(root or "").strip().upper()
    if not normalized:
        return None
    preferred = MINI_ROOT_TO_FULL_ROOT.get(normalized, normalized)
    return DEFAULT_CLUSTER_BY_ROOT.get(preferred)


def _pair_key(row: Mapping[str, object]) -> str:
    stock = str(row.get("stock") or "").strip().upper()
    future = str(row.get("future") or "").strip().upper()
    return f"{stock}|{future}"


def _position_state(row: Mapping[str, object]) -> str:
    raw = str(row.get("position_state") or "").strip().lower()
    if raw in {"flat", "open"}:
        return raw
    return "open" if bool(row.get("position_open")) else "flat"


def _strategy_stream(row: Mapping[str, object]) -> str | None:
    strategy_meta = _extract_strategy_metadata(row)
    return str(strategy_meta.get("strategy_stream") or "").strip().lower() or None


def _timestamp_sort_value(value: object) -> float:
    parsed = parse_iso_utc(value)
    if not isinstance(parsed, datetime):
        return float("-inf")
    return float(parsed.timestamp())


def _score_sort_value(row: Mapping[str, object]) -> float:
    parsed = to_float(row.get("signal_score"))
    if parsed is None:
        return float("-inf")
    return float(parsed)


def _cluster_cap(settings) -> int:
    max_positions = max(int(getattr(settings.risk_profile, "max_positions", 0) or 0), 0)
    exposure_pct = float(getattr(settings.risk_profile, "max_correlated_exposure_pct", 0.0) or 0.0)
    if max_positions <= 0 or exposure_pct <= 0:
        return 0
    return max(1, int(math.floor((max_positions * exposure_pct) / 100.0)))


def _merge_reason_list(metrics: dict[str, object], key: str, *reasons: str) -> None:
    current = metrics.get(key)
    values = [str(item) for item in current] if isinstance(current, list) else []
    values.extend(reasons)
    metrics[key] = _dedup_strings(values)


def _mark_source_review(row: dict[str, object], *, reason: str) -> None:
    metrics = _metric_map(row)
    metrics["source_freshness_status"] = "review"
    _merge_reason_list(metrics, "source_freshness_reasons", reason)
    _set_metric_map(row, metrics)


def _mark_portfolio_block(
    row: dict[str, object],
    *,
    reason: str,
    limit: int | None = None,
    observed: int | None = None,
    detail_key: str | None = None,
    detail_value: object = None,
) -> None:
    metrics = _metric_map(row)
    metrics["portfolio_limit_status"] = "block"
    _merge_reason_list(metrics, "portfolio_limit_reasons", reason)
    context = metrics.get("portfolio_limit_context")
    context_map = dict(context) if isinstance(context, dict) else {}
    if limit is not None:
        context_map["limit"] = int(limit)
    if observed is not None:
        context_map["observed"] = int(observed)
    if detail_key:
        context_map[detail_key] = detail_value
    metrics["portfolio_limit_context"] = context_map
    _set_metric_map(row, metrics)


def _mark_portfolio_pass(
    row: dict[str, object],
    *,
    future_root: str,
    preferred_root_value: str,
    cluster: str | None,
) -> None:
    metrics = _metric_map(row)
    if not metrics.get("portfolio_limit_status"):
        metrics["portfolio_limit_status"] = "pass"
    context = metrics.get("portfolio_limit_context")
    context_map = dict(context) if isinstance(context, dict) else {}
    context_map["future_root"] = future_root
    context_map["preferred_root"] = preferred_root_value
    if cluster is not None:
        context_map["cluster"] = cluster
    metrics["portfolio_limit_context"] = context_map
    _set_metric_map(row, metrics)


def _annotate_runtime_adapter_sources(row: dict[str, object]) -> None:
    metrics = _metric_map(row)
    two_layer = metrics.get("two_layer")
    two_layer_map = dict(two_layer) if isinstance(two_layer, dict) else {}
    metadata = two_layer_map.get("metadata")
    metadata_map = dict(metadata) if isinstance(metadata, dict) else {}
    synthetic_history_events = int(round(to_float(metadata_map.get("synthetic_history_events")) or 0.0))
    historical_source_kind = str(
        two_layer_map.get("historical_source_kind")
        or ("synthetic" if synthetic_history_events > 0 else "")
    ).strip().lower() or None
    cost_source_kind = str(two_layer_map.get("cost_source_kind") or "").strip().lower() or None
    legacy_action = str(
        row.get("signal_action_legacy")
        or two_layer_map.get("legacy_action")
        or ""
    ).strip().lower()
    current_action = str(row.get("signal_action") or "").strip().lower()
    override_requested = bool(
        two_layer_map.get("override_requested")
        if "override_requested" in two_layer_map
        else two_layer_map.get("override_applied")
    )
    synthetic_promotion_blocked = bool(two_layer_map.get("synthetic_promotion_blocked"))
    if (
        not synthetic_promotion_blocked
        and override_requested
        and historical_source_kind == "synthetic"
        and current_action == "enter"
        and legacy_action
        and legacy_action != "enter"
    ):
        synthetic_promotion_blocked = True

    if historical_source_kind is not None:
        row["historical_source_kind"] = historical_source_kind
        metrics["historical_source_kind"] = historical_source_kind
    if cost_source_kind is not None:
        row["cost_source_kind"] = cost_source_kind
        metrics["cost_source_kind"] = cost_source_kind
    row["synthetic_promotion_blocked"] = synthetic_promotion_blocked
    if two_layer_map:
        two_layer_map["synthetic_promotion_blocked"] = synthetic_promotion_blocked
        if historical_source_kind is not None:
            two_layer_map["historical_source_kind"] = historical_source_kind
        if cost_source_kind is not None:
            two_layer_map["cost_source_kind"] = cost_source_kind
        metrics["two_layer"] = two_layer_map
    _set_metric_map(row, metrics)

    if synthetic_promotion_blocked and current_action == "enter":
        _mark_source_review(row, reason="synthetic_history_promotion_blocked")


def apply_live_routing_guards(rows: list[dict[str, object]], *, settings) -> list[dict[str, object]]:
    payload = [dict(row) for row in rows if isinstance(row, dict)]
    if not payload:
        return payload

    max_positions = max(int(getattr(settings.risk_profile, "max_positions", 0) or 0), 0)
    max_contracts_per_instrument = max(
        int(getattr(settings.risk_profile, "max_contracts_per_instrument", 0) or 0),
        0,
    )
    cluster_cap = _cluster_cap(settings)

    open_pairs: set[str] = set()
    root_counts: Counter[str] = Counter()
    cluster_counts: Counter[str] = Counter()
    actual_roots_by_instrument: dict[str, set[str]] = {}

    for row in payload:
        _annotate_runtime_adapter_sources(row)
        future_root = extract_future_root(row.get("future"))
        preferred_root_value = preferred_live_root(row.get("future"))
        cluster = cluster_for_root(preferred_root_value)
        row["live_routing"] = {
            "future_root": future_root,
            "preferred_root": preferred_root_value,
            "cluster": cluster,
            "mini_root_suppressed": future_root in MINI_ROOT_TO_FULL_ROOT,
        }
        if _position_state(row) != "open":
            continue
        pair_key = _pair_key(row)
        if pair_key in open_pairs:
            continue
        open_pairs.add(pair_key)
        instrument_key = preferred_root_value or future_root or pair_key
        root_counts[instrument_key] += 1
        actual_roots_by_instrument.setdefault(instrument_key, set()).add(future_root)
        if cluster is not None:
            cluster_counts[cluster] += 1

    enter_candidates: list[dict[str, object]] = []
    for row in payload:
        if str(row.get("signal_action") or "").strip().lower() != "enter":
            continue
        if _position_state(row) == "open":
            continue
        enter_candidates.append(row)

    enter_candidates.sort(
        key=lambda row: (
            _score_sort_value(row),
            _timestamp_sort_value(row.get("timestamp") or row.get("snapshot_as_of")),
            _pair_key(row),
        ),
        reverse=True,
    )

    accepted_pairs: set[str] = set()
    accepted_enters = 0
    for row in enter_candidates:
        strategy_stream = _strategy_stream(row)
        future_root = extract_future_root(row.get("future"))
        preferred_root_value = preferred_live_root(row.get("future"))
        cluster = cluster_for_root(preferred_root_value)
        instrument_key = preferred_root_value or future_root or _pair_key(row)
        pair_key = _pair_key(row)

        if strategy_stream == "commodity_futures" and future_root in MINI_ROOT_TO_FULL_ROOT:
            _mark_portfolio_block(
                row,
                reason="no_mini_universe",
                detail_key="preferred_root",
                detail_value=preferred_root_value,
            )
            continue

        if bool(row.get("synthetic_promotion_blocked")):
            continue

        if pair_key in accepted_pairs:
            _mark_portfolio_block(row, reason="duplicate_pair_candidate", observed=1, limit=1)
            continue

        existing_roots = actual_roots_by_instrument.get(instrument_key, set())
        if existing_roots and any(root != future_root for root in existing_roots):
            _mark_portfolio_block(
                row,
                reason="mini_full_duplicate_live_routing",
                observed=len(existing_roots) + 1,
                limit=1,
                detail_key="existing_roots",
                detail_value=sorted(existing_roots),
            )
            continue

        projected_positions = len(open_pairs) + accepted_enters
        if max_positions > 0 and projected_positions >= max_positions:
            _mark_portfolio_block(
                row,
                reason="max_positions_live_routing",
                observed=projected_positions,
                limit=max_positions,
            )
            continue

        if max_contracts_per_instrument > 0 and root_counts[instrument_key] >= max_contracts_per_instrument:
            _mark_portfolio_block(
                row,
                reason="max_contracts_per_instrument_live_routing",
                observed=int(root_counts[instrument_key]),
                limit=max_contracts_per_instrument,
                detail_key="instrument_root",
                detail_value=instrument_key,
            )
            continue

        if cluster is not None and cluster_cap > 0 and cluster_counts[cluster] >= cluster_cap:
            _mark_portfolio_block(
                row,
                reason="max_correlated_exposure_live_routing",
                observed=int(cluster_counts[cluster]),
                limit=cluster_cap,
                detail_key="cluster",
                detail_value=cluster,
            )
            continue

        accepted_pairs.add(pair_key)
        accepted_enters += 1
        root_counts[instrument_key] += 1
        actual_roots_by_instrument.setdefault(instrument_key, set()).add(future_root)
        if cluster is not None:
            cluster_counts[cluster] += 1
        _mark_portfolio_pass(
            row,
            future_root=future_root,
            preferred_root_value=preferred_root_value,
            cluster=cluster,
        )

    return payload
