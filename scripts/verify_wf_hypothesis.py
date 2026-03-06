from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

DEFAULT_ENERGY_ROOTS = frozenset({"BR", "NG"})
DEFAULT_METALS_ROOTS = frozenset({"GD", "SV", "PL", "PT"})

_CONTRACT_ROOT_RE = re.compile(r"^(?P<root>[A-Za-z0-9]+?)[FGHJKMNQUVXZ]\d$")
_SIDE_SLOT_RE = re.compile(r"^(?P<side>[A-Za-z]+)@(?P<slot>\d{2}:\d{2})$")


@dataclass
class HypothesisFilters:
    include_setup_kinds: frozenset[str] = field(default_factory=frozenset)
    include_sides: frozenset[str] = field(default_factory=frozenset)
    include_slots: frozenset[str] = field(default_factory=frozenset)
    include_clusters: frozenset[str] = field(default_factory=frozenset)
    include_roots: frozenset[str] = field(default_factory=frozenset)
    include_instrument_ids: frozenset[str] = field(default_factory=frozenset)

    exclude_setup_kinds: frozenset[str] = field(default_factory=frozenset)
    exclude_sides: frozenset[str] = field(default_factory=frozenset)
    exclude_slots: frozenset[str] = field(default_factory=frozenset)
    exclude_clusters: frozenset[str] = field(default_factory=frozenset)
    exclude_roots: frozenset[str] = field(default_factory=frozenset)
    exclude_instrument_ids: frozenset[str] = field(default_factory=frozenset)
    exclude_side_slots: frozenset[tuple[str, str]] = field(default_factory=frozenset)

    energy_roots: frozenset[str] = field(default_factory=lambda: DEFAULT_ENERGY_ROOTS)
    metals_roots: frozenset[str] = field(default_factory=lambda: DEFAULT_METALS_ROOTS)


@dataclass
class HypothesisGates:
    min_setups_total: int | None = None
    min_filled_trades: int | None = None
    min_win_rate_net: float | None = None
    min_trades_per_week: float | None = None
    max_trades_per_week: float | None = None
    min_net_ticks_sum: float | None = None
    min_expectancy_net_ticks: float | None = None
    max_concentration_top_share: float | None = None


@dataclass(frozen=True)
class TapeRow:
    row: dict[str, Any]
    setup_kind: str
    side: str
    slot: str
    instrument_id: str
    root: str
    trade_date: date | None
    filled: bool
    outcome: str
    net_ticks: float
    gross_ticks: float


@dataclass(frozen=True)
class SignalTape:
    rows: list[TapeRow]
    all_mask: int
    setup_kind_masks: dict[str, int]
    side_masks: dict[str, int]
    slot_masks: dict[str, int]
    root_masks: dict[str, int]
    instrument_masks: dict[str, int]
    side_slot_masks: dict[tuple[str, str], int]


def _to_upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _to_lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.lower() in {"", "none", "nan", "null"}:
        return float(default)
    try:
        return float(text)
    except ValueError:
        return float(default)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return False


def _split_tokens(raw: str | None) -> list[str]:
    if raw is None:
        return []
    return [token.strip() for token in str(raw).split(",") if token.strip()]


def _split_many(values: Sequence[str] | None) -> list[str]:
    tokens: list[str] = []
    if not values:
        return tokens
    for raw in values:
        tokens.extend(_split_tokens(raw))
    return tokens


def _csv_upper_set(raw: str | None) -> frozenset[str]:
    return frozenset(_to_upper(token) for token in _split_tokens(raw))


def _csv_lower_set(raw: str | None) -> frozenset[str]:
    return frozenset(_to_lower(token) for token in _split_tokens(raw))


def _csv_slot_set(raw: str | None) -> frozenset[str]:
    values = frozenset(token for token in _split_tokens(raw) if re.match(r"^\d{2}:\d{2}$", token))
    return values


def _parse_side_slot_rules(values: Sequence[str] | None) -> frozenset[tuple[str, str]]:
    rules: set[tuple[str, str]] = set()
    for token in _split_many(values):
        match = _SIDE_SLOT_RE.match(token.strip())
        if match is None:
            raise ValueError(f"invalid_side_slot_rule:{token};expected=SIDE@HH:MM")
        side = _to_upper(match.group("side"))
        slot = match.group("slot")
        if side not in {"BUY", "SELL"}:
            raise ValueError(f"invalid_side_slot_side:{side};allowed=BUY|SELL")
        rules.add((side, slot))
    return frozenset(rules)


def _parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text or text.lower() == "none":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _slot_from_ts(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "none":
        return "UNKNOWN"
    try:
        return datetime.fromisoformat(text).strftime("%H:%M")
    except ValueError:
        match = re.search(r"T(?P<slot>\d{2}:\d{2})", text)
        if match is not None:
            return match.group("slot")
    return "UNKNOWN"


def _instrument_root(instrument_id: str) -> str:
    secid = _to_upper(instrument_id)
    matched = _CONTRACT_ROOT_RE.match(secid)
    if matched is not None:
        return _to_upper(matched.group("root"))
    return secid


def _cluster_for_root(root: str, *, filters: HypothesisFilters) -> str:
    if root in filters.energy_roots:
        return "energy"
    if root in filters.metals_roots:
        return "metals"
    return "other"


def _bucket_template(*, include_gross: bool = False) -> dict[str, float]:
    payload = {
        "count": 0.0,
        "net_ticks_sum": 0.0,
        "win_count": 0.0,
        "tp_count": 0.0,
        "sl_count": 0.0,
        "exit_count": 0.0,
    }
    if include_gross:
        payload["gross_ticks_sum"] = 0.0
        payload["abs_gross_ticks_sum"] = 0.0
    return payload


def _update_bucket(
    bucket: dict[str, float],
    *,
    net_ticks: float,
    gross_ticks: float,
    outcome: str,
) -> None:
    bucket["count"] += 1.0
    bucket["net_ticks_sum"] += float(net_ticks)
    if "gross_ticks_sum" in bucket:
        bucket["gross_ticks_sum"] += float(gross_ticks)
    if "abs_gross_ticks_sum" in bucket:
        bucket["abs_gross_ticks_sum"] += abs(float(gross_ticks))
    if net_ticks > 0.0:
        bucket["win_count"] += 1.0
    if outcome == "TP":
        bucket["tp_count"] += 1.0
    elif outcome == "SL":
        bucket["sl_count"] += 1.0
    elif outcome == "EXIT":
        bucket["exit_count"] += 1.0


def _finalize_bucket(slot: dict[str, float]) -> dict[str, Any]:
    count = int(slot["count"])
    net_sum = float(slot["net_ticks_sum"])
    gross_sum = float(slot.get("gross_ticks_sum", 0.0))
    payload = {
        "count": count,
        "net_ticks_sum": net_sum,
        "win_count": int(slot["win_count"]),
        "tp_count": int(slot["tp_count"]),
        "sl_count": int(slot["sl_count"]),
        "exit_count": int(slot["exit_count"]),
        "expectancy_net_ticks": float(net_sum / float(count)) if count > 0 else 0.0,
        "win_rate_net": float(slot["win_count"] / float(count)) if count > 0 else 0.0,
        "tp_rate": float(slot["tp_count"] / float(count)) if count > 0 else 0.0,
        "sl_rate": float(slot["sl_count"] / float(count)) if count > 0 else 0.0,
        "exit_rate": float(slot["exit_count"] / float(count)) if count > 0 else 0.0,
    }
    if "gross_ticks_sum" in slot:
        payload["gross_ticks_sum"] = gross_sum
        payload["abs_gross_ticks_sum"] = float(slot.get("abs_gross_ticks_sum", 0.0))
    return payload


def _resolve_report_period(report: dict[str, Any]) -> tuple[date | None, date | None]:
    period = report.get("period")
    if isinstance(period, dict):
        start = _parse_iso_date(period.get("start_date"))
        end = _parse_iso_date(period.get("end_date"))
        if start is not None and end is not None and end >= start:
            return start, end
    start = _parse_iso_date(report.get("period_start") or report.get("start_date"))
    end = _parse_iso_date(report.get("period_end") or report.get("end_date"))
    if start is not None and end is not None and end >= start:
        return start, end
    return None, None


def _resolve_filtered_period(selected_rows: list[dict[str, Any]]) -> tuple[date | None, date | None]:
    dates: list[date] = []
    for row in selected_rows:
        trade_date = _parse_iso_date(row["row"].get("trade_date"))
        if trade_date is not None:
            dates.append(trade_date)
    if not dates:
        return None, None
    return min(dates), max(dates)


def _trades_per_week(*, filled_trades: int, period_start: date | None, period_end: date | None) -> float:
    if period_start is None or period_end is None:
        return 0.0
    days = (period_end - period_start).days + 1
    if days <= 0:
        return 0.0
    return float(max(int(filled_trades), 0) * 7.0 / float(days))


def _summary_concentration(by_instrument: dict[str, dict[str, Any]]) -> tuple[float, float]:
    abs_nets = [abs(float(slot.get("net_ticks_sum", 0.0))) for slot in by_instrument.values()]
    total_abs = float(sum(abs_nets))
    if total_abs <= 0.0:
        return 0.0, 0.0
    shares = [value / total_abs for value in abs_nets if value > 0.0]
    if not shares:
        return 0.0, 0.0
    top_share = float(max(shares))
    hhi = float(sum(share * share for share in shares))
    return top_share, hhi


def _summary_concentration_from_net_sums(net_sums: dict[str, float]) -> tuple[float, float]:
    abs_nets = [abs(float(value)) for value in net_sums.values()]
    total_abs = float(sum(abs_nets))
    if total_abs <= 0.0:
        return 0.0, 0.0
    shares = [value / total_abs for value in abs_nets if value > 0.0]
    if not shares:
        return 0.0, 0.0
    top_share = float(max(shares))
    hhi = float(sum(share * share for share in shares))
    return top_share, hhi


def _add_mask(index: dict[str | tuple[str, str], int], key: str | tuple[str, str], bit: int) -> None:
    index[key] = int(index.get(key, 0) | int(bit))


def _mask_union(index: dict[str | tuple[str, str], int], keys: Sequence[str | tuple[str, str]]) -> int:
    mask = 0
    for key in keys:
        mask |= int(index.get(key, 0))
    return int(mask)


def _iter_mask_indices(mask: int):
    remaining = int(mask)
    while remaining:
        lsb = remaining & -remaining
        yield int(lsb.bit_length() - 1)
        remaining ^= lsb


def _compile_signal_tape(planned_signals: list[dict[str, Any]]) -> SignalTape:
    rows: list[TapeRow] = []
    setup_kind_masks: dict[str, int] = {}
    side_masks: dict[str, int] = {}
    slot_masks: dict[str, int] = {}
    root_masks: dict[str, int] = {}
    instrument_masks: dict[str, int] = {}
    side_slot_masks: dict[tuple[str, str], int] = {}
    for raw in planned_signals:
        if not isinstance(raw, dict):
            continue
        idx = len(rows)
        bit = int(1 << idx)
        setup_kind = _to_upper(raw.get("setup_kind")) or "UNKNOWN"
        side = _to_upper(raw.get("side")) or "UNKNOWN"
        slot = _slot_from_ts(raw.get("as_of_ts"))
        instrument_id = _to_upper(raw.get("instrument_id")) or "UNKNOWN"
        root = _instrument_root(instrument_id)
        trade_date = _parse_iso_date(raw.get("trade_date"))
        filled = _to_bool(raw.get("simulated_filled"))
        outcome = _to_upper(raw.get("simulated_outcome")) or "UNKNOWN"
        net_ticks = _to_float(raw.get("simulated_net_ticks"), 0.0)
        gross_ticks = _to_float(raw.get("simulated_gross_ticks"), 0.0)
        rows.append(
            TapeRow(
                row=raw,
                setup_kind=setup_kind,
                side=side,
                slot=slot,
                instrument_id=instrument_id,
                root=root,
                trade_date=trade_date,
                filled=filled,
                outcome=outcome,
                net_ticks=float(net_ticks),
                gross_ticks=float(gross_ticks),
            )
        )
        _add_mask(setup_kind_masks, setup_kind, bit)
        _add_mask(side_masks, side, bit)
        _add_mask(slot_masks, slot, bit)
        _add_mask(root_masks, root, bit)
        _add_mask(instrument_masks, instrument_id, bit)
        _add_mask(side_slot_masks, (side, slot), bit)
    all_mask = int((1 << len(rows)) - 1) if rows else 0
    return SignalTape(
        rows=rows,
        all_mask=all_mask,
        setup_kind_masks=setup_kind_masks,
        side_masks=side_masks,
        slot_masks=slot_masks,
        root_masks=root_masks,
        instrument_masks=instrument_masks,
        side_slot_masks=side_slot_masks,
    )


def _cluster_masks_for_filters(
    tape: SignalTape,
    *,
    filters: HypothesisFilters,
) -> dict[str, int]:
    energy_roots = {root for root in filters.energy_roots}
    metals_roots = {root for root in filters.metals_roots if root not in energy_roots}
    energy_mask = _mask_union(tape.root_masks, sorted(energy_roots))
    metals_mask = _mask_union(tape.root_masks, sorted(metals_roots))
    other_mask = int(tape.all_mask & ~(energy_mask | metals_mask))
    return {
        "energy": int(energy_mask),
        "metals": int(metals_mask),
        "other": int(other_mask),
    }


def _select_mask_from_tape(
    tape: SignalTape,
    *,
    filters: HypothesisFilters,
    collect_rejected_by_reason: bool = True,
) -> tuple[int, dict[str, int]]:
    selected = int(tape.all_mask)
    rejected_by_reason: dict[str, int] = {}
    cluster_masks = _cluster_masks_for_filters(tape, filters=filters)

    def _apply_include(reason: str, allowed_mask: int) -> None:
        nonlocal selected
        rejected_mask = int(selected & ~int(allowed_mask))
        if bool(collect_rejected_by_reason) and rejected_mask:
            rejected_by_reason[reason] = int(rejected_mask.bit_count())
        selected = int(selected & int(allowed_mask))

    def _apply_exclude(reason: str, denied_mask: int) -> None:
        nonlocal selected
        rejected_mask = int(selected & int(denied_mask))
        if bool(collect_rejected_by_reason) and rejected_mask:
            rejected_by_reason[reason] = int(rejected_mask.bit_count())
        selected = int(selected & ~int(denied_mask))

    if filters.include_setup_kinds:
        _apply_include(
            "include_setup_kinds",
            _mask_union(tape.setup_kind_masks, sorted(filters.include_setup_kinds)),
        )
    if filters.include_sides:
        _apply_include("include_sides", _mask_union(tape.side_masks, sorted(filters.include_sides)))
    if filters.include_slots:
        _apply_include("include_slots", _mask_union(tape.slot_masks, sorted(filters.include_slots)))
    if filters.include_clusters:
        include_mask = 0
        for cluster in sorted(filters.include_clusters):
            include_mask |= int(cluster_masks.get(cluster, 0))
        _apply_include("include_clusters", int(include_mask))
    if filters.include_roots:
        _apply_include("include_roots", _mask_union(tape.root_masks, sorted(filters.include_roots)))
    if filters.include_instrument_ids:
        _apply_include(
            "include_instrument_ids",
            _mask_union(tape.instrument_masks, sorted(filters.include_instrument_ids)),
        )
    if filters.exclude_setup_kinds:
        _apply_exclude(
            "exclude_setup_kinds",
            _mask_union(tape.setup_kind_masks, sorted(filters.exclude_setup_kinds)),
        )
    if filters.exclude_sides:
        _apply_exclude("exclude_sides", _mask_union(tape.side_masks, sorted(filters.exclude_sides)))
    if filters.exclude_slots:
        _apply_exclude("exclude_slots", _mask_union(tape.slot_masks, sorted(filters.exclude_slots)))
    if filters.exclude_clusters:
        exclude_mask = 0
        for cluster in sorted(filters.exclude_clusters):
            exclude_mask |= int(cluster_masks.get(cluster, 0))
        _apply_exclude("exclude_clusters", int(exclude_mask))
    if filters.exclude_roots:
        _apply_exclude("exclude_roots", _mask_union(tape.root_masks, sorted(filters.exclude_roots)))
    if filters.exclude_instrument_ids:
        _apply_exclude(
            "exclude_instrument_ids",
            _mask_union(tape.instrument_masks, sorted(filters.exclude_instrument_ids)),
        )
    if filters.exclude_side_slots:
        _apply_exclude(
            "exclude_side_slots",
            _mask_union(tape.side_slot_masks, sorted(filters.exclude_side_slots)),
        )
    return int(selected & tape.all_mask), rejected_by_reason


def _resolve_filtered_period_from_mask(tape: SignalTape, selected_mask: int) -> tuple[date | None, date | None]:
    min_date: date | None = None
    max_date: date | None = None
    for idx in _iter_mask_indices(selected_mask):
        trade_date = tape.rows[idx].trade_date
        if trade_date is None:
            continue
        if min_date is None or trade_date < min_date:
            min_date = trade_date
        if max_date is None or trade_date > max_date:
            max_date = trade_date
    return min_date, max_date


def _summarize_selection_from_mask(
    tape: SignalTape,
    *,
    selected_mask: int,
    period_start: date | None,
    period_end: date | None,
    filters: HypothesisFilters,
    include_breakdowns: bool = True,
) -> dict[str, Any]:
    setups_total = int(selected_mask.bit_count())
    # Keep scan proportional to selected rows only.
    filled_indices = [idx for idx in _iter_mask_indices(selected_mask) if tape.rows[idx].filled]
    filled_count = int(len(filled_indices))
    tp_count = 0
    sl_count = 0
    exit_count = 0
    win_count = 0
    net_sum = 0.0
    gross_sum = 0.0
    by_kind: dict[str, dict[str, float]] = {}
    by_instrument: dict[str, dict[str, float]] = {}
    by_slot: dict[str, dict[str, float]] = {}
    by_cluster: dict[str, dict[str, float]] = {}
    by_side: dict[str, dict[str, float]] = {}
    by_instrument_net: dict[str, float] = {}
    energy_roots = {root for root in filters.energy_roots}
    metals_roots = {root for root in filters.metals_roots if root not in energy_roots}
    for idx in filled_indices:
        item = tape.rows[idx]
        outcome = item.outcome
        net_ticks = float(item.net_ticks)
        gross_ticks = float(item.gross_ticks)
        cluster = "other"
        if item.root in energy_roots:
            cluster = "energy"
        elif item.root in metals_roots:
            cluster = "metals"
        net_sum += net_ticks
        gross_sum += gross_ticks
        by_instrument_net[item.instrument_id] = float(by_instrument_net.get(item.instrument_id, 0.0) + net_ticks)
        if outcome == "TP":
            tp_count += 1
        elif outcome == "SL":
            sl_count += 1
        elif outcome == "EXIT":
            exit_count += 1
        if net_ticks > 0.0:
            win_count += 1
        if not bool(include_breakdowns):
            continue
        _update_bucket(
            by_kind.setdefault(item.setup_kind, _bucket_template()),
            net_ticks=net_ticks,
            gross_ticks=gross_ticks,
            outcome=outcome,
        )
        _update_bucket(
            by_instrument.setdefault(item.instrument_id, _bucket_template(include_gross=True)),
            net_ticks=net_ticks,
            gross_ticks=gross_ticks,
            outcome=outcome,
        )
        _update_bucket(
            by_slot.setdefault(item.slot, _bucket_template()),
            net_ticks=net_ticks,
            gross_ticks=gross_ticks,
            outcome=outcome,
        )
        _update_bucket(
            by_cluster.setdefault(cluster, _bucket_template()),
            net_ticks=net_ticks,
            gross_ticks=gross_ticks,
            outcome=outcome,
        )
        _update_bucket(
            by_side.setdefault(item.side, _bucket_template()),
            net_ticks=net_ticks,
            gross_ticks=gross_ticks,
            outcome=outcome,
        )
    if bool(include_breakdowns):
        finalized_by_kind = {key: _finalize_bucket(slot) for key, slot in sorted(by_kind.items())}
        finalized_by_instrument = {key: _finalize_bucket(slot) for key, slot in sorted(by_instrument.items())}
        finalized_by_slot = {key: _finalize_bucket(slot) for key, slot in sorted(by_slot.items())}
        finalized_by_cluster = {key: _finalize_bucket(slot) for key, slot in sorted(by_cluster.items())}
        finalized_by_side = {key: _finalize_bucket(slot) for key, slot in sorted(by_side.items())}
    else:
        finalized_by_kind = {}
        finalized_by_instrument = {}
        finalized_by_slot = {}
        finalized_by_cluster = {}
        finalized_by_side = {}
    top_share, hhi = _summary_concentration_from_net_sums(by_instrument_net)
    expectancy = float(net_sum / float(filled_count)) if filled_count > 0 else 0.0
    fill_rate = float(filled_count / float(setups_total)) if setups_total > 0 else 0.0
    tp_rate = float(tp_count / float(filled_count)) if filled_count > 0 else 0.0
    sl_rate = float(sl_count / float(filled_count)) if filled_count > 0 else 0.0
    exit_rate = float(exit_count / float(filled_count)) if filled_count > 0 else 0.0
    win_rate = float(win_count / float(filled_count)) if filled_count > 0 else 0.0
    trades_per_week = _trades_per_week(
        filled_trades=filled_count,
        period_start=period_start,
        period_end=period_end,
    )
    return {
        "setups_total": setups_total,
        "filled_trades": filled_count,
        "fill_rate": float(fill_rate),
        "tp_rate": float(tp_rate),
        "sl_rate": float(sl_rate),
        "exit_rate": float(exit_rate),
        "win_rate_net": float(win_rate),
        "expectancy_net_ticks": float(expectancy),
        "gross_ticks_sum": float(gross_sum),
        "net_ticks_sum": float(net_sum),
        "trades_per_week": float(trades_per_week),
        "period_start": period_start.isoformat() if period_start is not None else None,
        "period_end": period_end.isoformat() if period_end is not None else None,
        "concentration_top_share": float(top_share),
        "concentration_hhi": float(hhi),
        "by_setup_kind": finalized_by_kind,
        "by_instrument": finalized_by_instrument,
        "by_slot": finalized_by_slot,
        "by_cluster": finalized_by_cluster,
        "by_side": finalized_by_side,
    }


def _select_rows(
    planned_signals: list[dict[str, Any]],
    *,
    filters: HypothesisFilters,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    selected_rows: list[dict[str, Any]] = []
    rejected_by_reason: dict[str, int] = {}
    for row in planned_signals:
        setup_kind = _to_upper(row.get("setup_kind"))
        side = _to_upper(row.get("side"))
        slot = _slot_from_ts(row.get("as_of_ts"))
        instrument_id = _to_upper(row.get("instrument_id"))
        root = _instrument_root(instrument_id)
        cluster = _cluster_for_root(root, filters=filters)

        reason: str | None = None
        if filters.include_setup_kinds and setup_kind not in filters.include_setup_kinds:
            reason = "include_setup_kinds"
        elif filters.include_sides and side not in filters.include_sides:
            reason = "include_sides"
        elif filters.include_slots and slot not in filters.include_slots:
            reason = "include_slots"
        elif filters.include_clusters and cluster not in filters.include_clusters:
            reason = "include_clusters"
        elif filters.include_roots and root not in filters.include_roots:
            reason = "include_roots"
        elif filters.include_instrument_ids and instrument_id not in filters.include_instrument_ids:
            reason = "include_instrument_ids"
        elif filters.exclude_setup_kinds and setup_kind in filters.exclude_setup_kinds:
            reason = "exclude_setup_kinds"
        elif filters.exclude_sides and side in filters.exclude_sides:
            reason = "exclude_sides"
        elif filters.exclude_slots and slot in filters.exclude_slots:
            reason = "exclude_slots"
        elif filters.exclude_clusters and cluster in filters.exclude_clusters:
            reason = "exclude_clusters"
        elif filters.exclude_roots and root in filters.exclude_roots:
            reason = "exclude_roots"
        elif filters.exclude_instrument_ids and instrument_id in filters.exclude_instrument_ids:
            reason = "exclude_instrument_ids"
        elif filters.exclude_side_slots and (side, slot) in filters.exclude_side_slots:
            reason = "exclude_side_slots"

        if reason is not None:
            rejected_by_reason[reason] = int(rejected_by_reason.get(reason, 0) + 1)
            continue

        selected_rows.append(
            {
                "row": row,
                "setup_kind": setup_kind or "UNKNOWN",
                "side": side or "UNKNOWN",
                "slot": slot,
                "instrument_id": instrument_id,
                "root": root,
                "cluster": cluster,
            }
        )
    return selected_rows, rejected_by_reason


def _summarize_selection(
    selected_rows: list[dict[str, Any]],
    *,
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    setups_total = int(len(selected_rows))
    filled_rows = [row for row in selected_rows if _to_bool(row["row"].get("simulated_filled"))]

    filled_count = int(len(filled_rows))
    tp_count = 0
    sl_count = 0
    exit_count = 0
    win_count = 0
    net_sum = 0.0
    gross_sum = 0.0

    by_kind: dict[str, dict[str, float]] = {}
    by_instrument: dict[str, dict[str, float]] = {}
    by_slot: dict[str, dict[str, float]] = {}
    by_cluster: dict[str, dict[str, float]] = {}
    by_side: dict[str, dict[str, float]] = {}

    for item in filled_rows:
        row = item["row"]
        outcome = _to_upper(row.get("simulated_outcome"))
        net_ticks = _to_float(row.get("simulated_net_ticks"), 0.0)
        gross_ticks = _to_float(row.get("simulated_gross_ticks"), 0.0)
        kind = item["setup_kind"]
        instrument_id = item["instrument_id"]
        slot = item["slot"]
        cluster = item["cluster"]
        side = item["side"]

        net_sum += float(net_ticks)
        gross_sum += float(gross_ticks)
        if outcome == "TP":
            tp_count += 1
        elif outcome == "SL":
            sl_count += 1
        elif outcome == "EXIT":
            exit_count += 1
        if net_ticks > 0.0:
            win_count += 1

        _update_bucket(
            by_kind.setdefault(kind, _bucket_template()),
            net_ticks=net_ticks,
            gross_ticks=gross_ticks,
            outcome=outcome,
        )
        _update_bucket(
            by_instrument.setdefault(
                instrument_id,
                _bucket_template(include_gross=True),
            ),
            net_ticks=net_ticks,
            gross_ticks=gross_ticks,
            outcome=outcome,
        )
        _update_bucket(
            by_slot.setdefault(slot, _bucket_template()),
            net_ticks=net_ticks,
            gross_ticks=gross_ticks,
            outcome=outcome,
        )
        _update_bucket(
            by_cluster.setdefault(cluster, _bucket_template()),
            net_ticks=net_ticks,
            gross_ticks=gross_ticks,
            outcome=outcome,
        )
        _update_bucket(
            by_side.setdefault(side, _bucket_template()),
            net_ticks=net_ticks,
            gross_ticks=gross_ticks,
            outcome=outcome,
        )

    finalized_by_kind = {key: _finalize_bucket(slot) for key, slot in sorted(by_kind.items())}
    finalized_by_instrument = {key: _finalize_bucket(slot) for key, slot in sorted(by_instrument.items())}
    finalized_by_slot = {key: _finalize_bucket(slot) for key, slot in sorted(by_slot.items())}
    finalized_by_cluster = {key: _finalize_bucket(slot) for key, slot in sorted(by_cluster.items())}
    finalized_by_side = {key: _finalize_bucket(slot) for key, slot in sorted(by_side.items())}

    top_share, hhi = _summary_concentration(finalized_by_instrument)
    expectancy = float(net_sum / float(filled_count)) if filled_count > 0 else 0.0
    fill_rate = float(filled_count / float(setups_total)) if setups_total > 0 else 0.0
    tp_rate = float(tp_count / float(filled_count)) if filled_count > 0 else 0.0
    sl_rate = float(sl_count / float(filled_count)) if filled_count > 0 else 0.0
    exit_rate = float(exit_count / float(filled_count)) if filled_count > 0 else 0.0
    win_rate = float(win_count / float(filled_count)) if filled_count > 0 else 0.0
    trades_per_week = _trades_per_week(
        filled_trades=filled_count,
        period_start=period_start,
        period_end=period_end,
    )

    return {
        "setups_total": setups_total,
        "filled_trades": filled_count,
        "fill_rate": float(fill_rate),
        "tp_rate": float(tp_rate),
        "sl_rate": float(sl_rate),
        "exit_rate": float(exit_rate),
        "win_rate_net": float(win_rate),
        "expectancy_net_ticks": float(expectancy),
        "gross_ticks_sum": float(gross_sum),
        "net_ticks_sum": float(net_sum),
        "trades_per_week": float(trades_per_week),
        "period_start": period_start.isoformat() if period_start is not None else None,
        "period_end": period_end.isoformat() if period_end is not None else None,
        "concentration_top_share": float(top_share),
        "concentration_hhi": float(hhi),
        "by_setup_kind": finalized_by_kind,
        "by_instrument": finalized_by_instrument,
        "by_slot": finalized_by_slot,
        "by_cluster": finalized_by_cluster,
        "by_side": finalized_by_side,
    }


def _gate_check(
    *,
    check_id: str,
    actual: float,
    expected: float,
    operator: str,
) -> dict[str, Any]:
    if operator == ">=":
        passed = float(actual) >= float(expected)
    elif operator == "<=":
        passed = float(actual) <= float(expected)
    else:
        raise ValueError(f"unsupported_operator:{operator}")
    return {
        "id": check_id,
        "passed": bool(passed),
        "actual": float(actual),
        "expected": float(expected),
        "operator": operator,
    }


def _evaluate_gates(summary: dict[str, Any], *, gates: HypothesisGates) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    if gates.min_setups_total is not None:
        checks.append(
            _gate_check(
                check_id="min_setups_total",
                actual=float(summary.get("setups_total", 0)),
                expected=float(gates.min_setups_total),
                operator=">=",
            )
        )
    if gates.min_filled_trades is not None:
        checks.append(
            _gate_check(
                check_id="min_filled_trades",
                actual=float(summary.get("filled_trades", 0)),
                expected=float(gates.min_filled_trades),
                operator=">=",
            )
        )
    if gates.min_win_rate_net is not None:
        checks.append(
            _gate_check(
                check_id="min_win_rate_net",
                actual=float(summary.get("win_rate_net", 0.0)),
                expected=float(gates.min_win_rate_net),
                operator=">=",
            )
        )
    if gates.min_trades_per_week is not None:
        checks.append(
            _gate_check(
                check_id="min_trades_per_week",
                actual=float(summary.get("trades_per_week", 0.0)),
                expected=float(gates.min_trades_per_week),
                operator=">=",
            )
        )
    if gates.max_trades_per_week is not None:
        checks.append(
            _gate_check(
                check_id="max_trades_per_week",
                actual=float(summary.get("trades_per_week", 0.0)),
                expected=float(gates.max_trades_per_week),
                operator="<=",
            )
        )
    if gates.min_net_ticks_sum is not None:
        checks.append(
            _gate_check(
                check_id="min_net_ticks_sum",
                actual=float(summary.get("net_ticks_sum", 0.0)),
                expected=float(gates.min_net_ticks_sum),
                operator=">=",
            )
        )
    if gates.min_expectancy_net_ticks is not None:
        checks.append(
            _gate_check(
                check_id="min_expectancy_net_ticks",
                actual=float(summary.get("expectancy_net_ticks", 0.0)),
                expected=float(gates.min_expectancy_net_ticks),
                operator=">=",
            )
        )
    if gates.max_concentration_top_share is not None:
        checks.append(
            _gate_check(
                check_id="max_concentration_top_share",
                actual=float(summary.get("concentration_top_share", 0.0)),
                expected=float(gates.max_concentration_top_share),
                operator="<=",
            )
        )
    passed = all(bool(item.get("passed", False)) for item in checks) if checks else True
    return {
        "passed": bool(passed),
        "checks": checks,
    }


def _with_gate_profile(gates: HypothesisGates, profile: str | None) -> HypothesisGates:
    if not profile:
        return gates
    if profile == "stage_go":
        defaults = {
            "min_win_rate_net": 0.70,
            "min_trades_per_week": 1.50,
            "min_net_ticks_sum": 0.0,
            "max_concentration_top_share": 0.50,
        }
    elif profile == "final_go":
        defaults = {
            "min_win_rate_net": 0.75,
            "min_trades_per_week": 2.00,
            "min_net_ticks_sum": 0.0,
            "max_concentration_top_share": 0.35,
        }
    else:
        raise ValueError(f"unknown_gate_profile:{profile}")
    for key, value in defaults.items():
        if getattr(gates, key) is None:
            setattr(gates, key, value)
    return gates


def build_hypothesis_report(
    *,
    report: dict[str, Any],
    filters: HypothesisFilters,
    gates: HypothesisGates,
    gate_profile: str | None = None,
    tpw_period_scope: str = "report",
    source_report_path: str | None = None,
    use_signal_tape: bool = True,
    precompiled_tape: SignalTape | None = None,
    collect_rejected_by_reason: bool = True,
    include_breakdowns: bool = True,
) -> dict[str, Any]:
    planned = report.get("planned_signals")
    if not isinstance(planned, list):
        raise ValueError("report_missing_planned_signals")
    planned_rows = [row for row in planned if isinstance(row, dict)]
    period_report = _resolve_report_period(report)
    if bool(use_signal_tape):
        tape = precompiled_tape if precompiled_tape is not None else _compile_signal_tape(planned_rows)
        selected_mask, rejected_by_reason = _select_mask_from_tape(
            tape,
            filters=filters,
            collect_rejected_by_reason=collect_rejected_by_reason,
        )
        selected_rows_count = int(selected_mask.bit_count())
        rejected_rows_count = int(len(tape.rows) - selected_rows_count)
        period_filtered = _resolve_filtered_period_from_mask(tape, selected_mask)
    else:
        selected_rows, rejected_by_reason = _select_rows(planned_rows, filters=filters)
        selected_rows_count = int(len(selected_rows))
        rejected_rows_count = int(len(planned_rows) - selected_rows_count)
        period_filtered = _resolve_filtered_period(selected_rows)

    if tpw_period_scope == "filtered":
        period_start, period_end = period_filtered if period_filtered != (None, None) else period_report
        period_source = "filtered" if period_filtered != (None, None) else "report"
    else:
        period_start, period_end = period_report if period_report != (None, None) else period_filtered
        period_source = "report" if period_report != (None, None) else "filtered"

    if bool(use_signal_tape):
        summary = _summarize_selection_from_mask(
            tape,
            selected_mask=selected_mask,
            period_start=period_start,
            period_end=period_end,
            filters=filters,
            include_breakdowns=include_breakdowns,
        )
    else:
        summary = _summarize_selection(
            selected_rows,
            period_start=period_start,
            period_end=period_end,
        )
    resolved_gates = _with_gate_profile(gates, gate_profile)
    acceptance = _evaluate_gates(summary, gates=resolved_gates)

    filters_payload = {
        "include_setup_kinds": sorted(filters.include_setup_kinds),
        "include_sides": sorted(filters.include_sides),
        "include_slots": sorted(filters.include_slots),
        "include_clusters": sorted(filters.include_clusters),
        "include_roots": sorted(filters.include_roots),
        "include_instrument_ids": sorted(filters.include_instrument_ids),
        "exclude_setup_kinds": sorted(filters.exclude_setup_kinds),
        "exclude_sides": sorted(filters.exclude_sides),
        "exclude_slots": sorted(filters.exclude_slots),
        "exclude_clusters": sorted(filters.exclude_clusters),
        "exclude_roots": sorted(filters.exclude_roots),
        "exclude_instrument_ids": sorted(filters.exclude_instrument_ids),
        "exclude_side_slots": [f"{side}@{slot}" for side, slot in sorted(filters.exclude_side_slots)],
        "energy_roots": sorted(filters.energy_roots),
        "metals_roots": sorted(filters.metals_roots),
    }
    gates_payload = {
        "min_setups_total": resolved_gates.min_setups_total,
        "min_filled_trades": resolved_gates.min_filled_trades,
        "min_win_rate_net": resolved_gates.min_win_rate_net,
        "min_trades_per_week": resolved_gates.min_trades_per_week,
        "max_trades_per_week": resolved_gates.max_trades_per_week,
        "min_net_ticks_sum": resolved_gates.min_net_ticks_sum,
        "min_expectancy_net_ticks": resolved_gates.min_expectancy_net_ticks,
        "max_concentration_top_share": resolved_gates.max_concentration_top_share,
    }

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_report_path": source_report_path,
        "source_planned_signals_total": int(len(planned_rows)),
        "selection": {
            "selected_rows": int(selected_rows_count),
            "rejected_rows": int(rejected_rows_count),
            "rejected_by_reason": rejected_by_reason if collect_rejected_by_reason else {},
            "filters": filters_payload,
            "tpw_period_scope": tpw_period_scope,
            "tpw_period_source": period_source,
            "engine": "tape" if bool(use_signal_tape) else "legacy",
        },
        "summary": summary,
        "gates_config": gates_payload,
        "acceptance": acceptance,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify WF hypothesis on planned_signals with deterministic filters and pass/fail gates.",
    )
    parser.add_argument("--in-json", required=True, help="Path to walk-forward report JSON with planned_signals.")
    parser.add_argument("--out-json", default=None, help="Optional output path for verification report JSON.")

    parser.add_argument("--include-setup-kinds", default=None, help="Comma-separated setup kinds.")
    parser.add_argument("--include-sides", default=None, help="Comma-separated sides (BUY,SELL).")
    parser.add_argument("--include-slots", default=None, help="Comma-separated decision slots (HH:MM).")
    parser.add_argument("--include-clusters", default=None, help="Comma-separated clusters (energy,metals,other).")
    parser.add_argument("--include-roots", default=None, help="Comma-separated instrument roots.")
    parser.add_argument("--include-instrument-ids", default=None, help="Comma-separated instrument ids.")

    parser.add_argument("--exclude-setup-kinds", default=None, help="Comma-separated setup kinds.")
    parser.add_argument("--exclude-sides", default=None, help="Comma-separated sides.")
    parser.add_argument("--exclude-slots", default=None, help="Comma-separated slots.")
    parser.add_argument("--exclude-clusters", default=None, help="Comma-separated clusters.")
    parser.add_argument("--exclude-roots", default=None, help="Comma-separated roots.")
    parser.add_argument("--exclude-instrument-ids", default=None, help="Comma-separated instrument ids.")
    parser.add_argument(
        "--exclude-side-slot",
        action="append",
        default=[],
        help="Exclude SIDE@HH:MM; may be passed multiple times or comma-separated.",
    )

    parser.add_argument("--cluster-energy-roots", default="BR,NG", help="Energy cluster roots.")
    parser.add_argument("--cluster-metals-roots", default="GD,SV,PL,PT", help="Metals cluster roots.")
    parser.add_argument(
        "--tpw-period-scope",
        choices=("report", "filtered"),
        default="report",
        help="How to compute trades/week denominator.",
    )

    parser.add_argument("--gate-profile", choices=("stage_go", "final_go"), default=None)
    parser.add_argument("--gate-min-setups-total", type=int, default=None)
    parser.add_argument("--gate-min-filled-trades", type=int, default=None)
    parser.add_argument("--gate-min-winrate-net", type=float, default=None)
    parser.add_argument("--gate-min-trades-per-week", type=float, default=None)
    parser.add_argument("--gate-max-trades-per-week", type=float, default=None)
    parser.add_argument("--gate-min-net-ticks-sum", type=float, default=None)
    parser.add_argument("--gate-min-expectancy-net-ticks", type=float, default=None)
    parser.add_argument("--gate-max-concentration-top-share", type=float, default=None)
    parser.add_argument(
        "--engine",
        choices=("tape", "legacy"),
        default="tape",
        help="Selection engine. 'tape' is optimized for repeated hypothesis checks.",
    )
    parser.add_argument(
        "--lite-summary",
        action="store_true",
        help="Skip heavy breakdown dictionaries (by_*); keep scalar metrics and gates.",
    )
    parser.add_argument(
        "--no-rejected-reasons",
        action="store_true",
        help="Do not compute per-reason rejection counts.",
    )
    parser.add_argument("--quiet", action="store_true", help="Do not print summary lines.")
    return parser.parse_args(argv)


def _build_filters(args: argparse.Namespace) -> HypothesisFilters:
    return HypothesisFilters(
        include_setup_kinds=_csv_upper_set(args.include_setup_kinds),
        include_sides=_csv_upper_set(args.include_sides),
        include_slots=_csv_slot_set(args.include_slots),
        include_clusters=_csv_lower_set(args.include_clusters),
        include_roots=_csv_upper_set(args.include_roots),
        include_instrument_ids=_csv_upper_set(args.include_instrument_ids),
        exclude_setup_kinds=_csv_upper_set(args.exclude_setup_kinds),
        exclude_sides=_csv_upper_set(args.exclude_sides),
        exclude_slots=_csv_slot_set(args.exclude_slots),
        exclude_clusters=_csv_lower_set(args.exclude_clusters),
        exclude_roots=_csv_upper_set(args.exclude_roots),
        exclude_instrument_ids=_csv_upper_set(args.exclude_instrument_ids),
        exclude_side_slots=_parse_side_slot_rules(args.exclude_side_slot),
        energy_roots=_csv_upper_set(args.cluster_energy_roots),
        metals_roots=_csv_upper_set(args.cluster_metals_roots),
    )


def _build_gates(args: argparse.Namespace) -> HypothesisGates:
    return HypothesisGates(
        min_setups_total=args.gate_min_setups_total,
        min_filled_trades=args.gate_min_filled_trades,
        min_win_rate_net=args.gate_min_winrate_net,
        min_trades_per_week=args.gate_min_trades_per_week,
        max_trades_per_week=args.gate_max_trades_per_week,
        min_net_ticks_sum=args.gate_min_net_ticks_sum,
        min_expectancy_net_ticks=args.gate_min_expectancy_net_ticks,
        max_concentration_top_share=args.gate_max_concentration_top_share,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    in_path = Path(args.in_json)
    payload = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("report_json_root_must_be_object")

    report = build_hypothesis_report(
        report=payload,
        filters=_build_filters(args),
        gates=_build_gates(args),
        gate_profile=args.gate_profile,
        tpw_period_scope=str(args.tpw_period_scope),
        source_report_path=str(in_path),
        use_signal_tape=(str(args.engine).strip().lower() == "tape"),
        collect_rejected_by_reason=not bool(args.no_rejected_reasons),
        include_breakdowns=not bool(args.lite_summary),
    )

    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("report_path", str(out_path))

    if not args.quiet:
        summary = report["summary"]
        acceptance = report["acceptance"]
        print("selected_rows", int(report["selection"]["selected_rows"]))
        print("filled_trades", int(summary["filled_trades"]))
        print("win_rate_net", round(float(summary["win_rate_net"]), 6))
        print("trades_per_week", round(float(summary["trades_per_week"]), 6))
        print("net_ticks_sum", round(float(summary["net_ticks_sum"]), 6))
        print("concentration_top_share", round(float(summary["concentration_top_share"]), 6))
        print("acceptance_passed", bool(acceptance["passed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
