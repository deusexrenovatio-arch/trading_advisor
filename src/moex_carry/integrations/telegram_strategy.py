from __future__ import annotations

from typing import Any


def normalize_strategy_type(value: object) -> str | None:
    raw = str(value or "").strip().lower()
    aliases = {
        "commodity": "speculative",
        "commodity_futures": "speculative",
        "futures": "speculative",
    }
    normalized = aliases.get(raw, raw)
    if normalized in {"arbitrage", "speculative", "fundamental"}:
        return normalized
    return None


def normalize_strategy_stream(value: object) -> str | None:
    raw = str(value or "").strip().lower()
    if raw == "speculative":
        return "commodity_futures"
    if raw in {"arbitrage", "commodity_futures", "fundamental"}:
        return raw
    return None


def resolve_strategy_metadata(row: dict[str, object]) -> tuple[str | None, str, str]:
    metrics = row.get("signal_metrics")
    metrics_map = metrics if isinstance(metrics, dict) else {}
    nested_two_layer = metrics_map.get("two_layer")
    nested_map = nested_two_layer if isinstance(nested_two_layer, dict) else {}

    strategy_type = normalize_strategy_type(row.get("strategy_type"))
    if strategy_type is None:
        strategy_type = normalize_strategy_type(metrics_map.get("strategy_type"))
    if strategy_type is None:
        strategy_type = normalize_strategy_type(nested_map.get("strategy_type"))
    if strategy_type is None:
        strategy_type = "arbitrage"

    strategy_stream = normalize_strategy_stream(row.get("strategy_stream"))
    if strategy_stream is None:
        strategy_stream = normalize_strategy_stream(metrics_map.get("strategy_stream"))
    if strategy_stream is None:
        strategy_stream = normalize_strategy_stream(nested_map.get("strategy_stream"))
    if strategy_stream is None:
        strategy_stream = "commodity_futures" if strategy_type == "speculative" else strategy_type

    strategy_id_raw: Any = row.get("strategy_id")
    strategy_id = str(strategy_id_raw).strip() if strategy_id_raw is not None else ""
    if not strategy_id:
        strategy_id_raw = metrics_map.get("strategy_id")
        strategy_id = str(strategy_id_raw).strip() if strategy_id_raw is not None else ""
    if not strategy_id:
        strategy_id_raw = nested_map.get("strategy_id")
        strategy_id = str(strategy_id_raw).strip() if strategy_id_raw is not None else ""
    return (strategy_id or None, strategy_type, strategy_stream)


def strategy_label(strategy_stream: str) -> str:
    return {
        "arbitrage": "Арбитраж",
        "commodity_futures": "Товарные фьючерсы",
        "fundamental": "Фундаментальная",
    }.get(strategy_stream, strategy_stream or "n/a")
