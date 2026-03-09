from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from moex_carry.config import AppSettings
from moex_carry.signal_engine.adapter import to_strategy_signal
from moex_carry.signal_engine.core.types import AlphaProposal, HistoricalOutcome, MarketRegimeFlags
from moex_carry.signal_engine.engine import CandidateEvaluation, evaluate_candidate
from moex_carry.signal_engine.cost.model_ticks import TickCostModelConfig
from moex_carry.signal_engine.gate.gate import GateConfig
from moex_carry.signal_engine.prob.empirical_dirichlet import DirichletDecayConfig
from moex_carry.strategy.strategy_signal import StrategySignal

RuntimeEvaluator = Callable[..., tuple[StrategySignal, CandidateEvaluation]]


def evaluate_proposal_to_strategy_signal(
    *,
    proposal: AlphaProposal,
    historical_outcomes: Sequence[HistoricalOutcome],
    as_of_ts: datetime,
    regime_flags: MarketRegimeFlags = MarketRegimeFlags(),
    spread_ticks_value: int | None = None,
    depth_lots: float | None = None,
    vacuum: bool = False,
    exit_return_ticks: float = 0.0,
    probability_config: DirichletDecayConfig = DirichletDecayConfig(),
    cost_config: TickCostModelConfig = TickCostModelConfig(),
    gate_config: GateConfig = GateConfig(),
    vol_regime: str | None = None,
) -> tuple[StrategySignal, CandidateEvaluation]:
    evaluation = evaluate_candidate(
        proposal=proposal,
        historical_outcomes=historical_outcomes,
        as_of_ts=as_of_ts,
        regime_flags=regime_flags,
        spread_ticks_value=spread_ticks_value,
        depth_lots=depth_lots,
        vacuum=vacuum,
        exit_return_ticks=exit_return_ticks,
        probability_config=probability_config,
        cost_config=cost_config,
        gate_config=gate_config,
        vol_regime=vol_regime,
    )
    signal = to_strategy_signal(proposal=proposal, engine_signal=evaluation.signal)
    return signal, evaluation


def _as_naive_datetime(value: object) -> datetime | None:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is not None:
            ts = ts.tz_convert(None)
        return ts.to_pydatetime().replace(tzinfo=None)
    if isinstance(ts, datetime):
        if ts.tzinfo is not None:
            return ts.astimezone(timezone.utc).replace(tzinfo=None)
        return ts
    return None


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _normalize_strategy_type(value: object, *, default: str = "arbitrage") -> str:
    raw = str(value or "").strip().lower()
    if raw in {"commodity_futures", "commodity", "futures"}:
        return "speculative"
    if raw in {"arbitrage", "speculative", "fundamental"}:
        return raw
    return default


def _strategy_stream_from_type(strategy_type: str) -> str:
    if strategy_type == "speculative":
        return "commodity_futures"
    return strategy_type


def _bool_from_value(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _normalized_probabilities_from_row(row: Mapping[str, object]) -> tuple[float, float, float] | None:
    p_tp = _float_or_none(row.get("forecast_tp_probability"))
    if p_tp is None:
        p_tp = _float_or_none(row.get("p_hit_tp"))
    p_sl = _float_or_none(row.get("forecast_sl_probability"))
    if p_sl is None:
        p_sl = _float_or_none(row.get("p_hit_sl"))
    p_exit = _float_or_none(row.get("forecast_no_exit_probability"))
    if p_exit is None:
        p_exit = _float_or_none(row.get("p_exit"))

    if p_tp is None and p_sl is None and p_exit is None:
        return None

    tp = min(max(p_tp or 0.0, 0.0), 1.0)
    sl = min(max(p_sl or 0.0, 0.0), 1.0)
    if p_exit is None:
        p_exit = max(1.0 - tp - sl, 0.0)
    ex = min(max(p_exit, 0.0), 1.0)
    total = tp + sl + ex
    if total <= 0.0:
        return None
    return tp / total, sl / total, ex / total


def _row_n_effective(row: Mapping[str, object]) -> float:
    for key in ("forecast_n_effective", "forward_n_effective", "entry_signals", "trades_closed"):
        value = _float_or_none(row.get(key))
        if value is not None and value > 0:
            return value
    return 0.0


def _build_synthetic_historical_outcomes(
    row: Mapping[str, object],
    *,
    as_of_ts: datetime,
    max_events: int,
) -> list[HistoricalOutcome]:
    probabilities = _normalized_probabilities_from_row(row)
    if probabilities is None:
        return []

    n_effective = _row_n_effective(row)
    if n_effective <= 0:
        return []

    capped = max(min(int(round(n_effective)), max(max_events, 0)), 0)
    if capped <= 0:
        return []

    p_tp, p_sl, p_exit = probabilities
    weighted = {
        "TP": p_tp * capped,
        "SL": p_sl * capped,
        "EXIT": p_exit * capped,
    }
    counts = {label: int(value) for label, value in weighted.items()}
    remainder = capped - sum(counts.values())
    if remainder > 0:
        ranked_remainders = sorted(
            weighted.items(),
            key=lambda item: item[1] - int(item[1]),
            reverse=True,
        )
        for idx in range(remainder):
            label = ranked_remainders[idx % len(ranked_remainders)][0]
            counts[label] += 1

    outcomes: list[HistoricalOutcome] = []
    for _ in range(max(counts.get("TP", 0), 0)):
        outcomes.append(HistoricalOutcome(ts=as_of_ts, outcome="TP"))
    for _ in range(max(counts.get("SL", 0), 0)):
        outcomes.append(HistoricalOutcome(ts=as_of_ts, outcome="SL"))
    for _ in range(max(counts.get("EXIT", 0), 0)):
        outcomes.append(HistoricalOutcome(ts=as_of_ts, outcome="EXIT"))
    return outcomes


def _ticks_from_row(*, explicit: object, fallback_pct: float | None, default_value: int) -> int:
    explicit_value = _float_or_none(explicit)
    if explicit_value is not None and explicit_value > 0:
        return max(int(round(explicit_value)), 1)
    if fallback_pct is not None:
        converted = int(round(abs(fallback_pct) * 100.0))
        if converted > 0:
            return converted
    return max(int(default_value), 1)


def _depth_lots_from_row(row: Mapping[str, object]) -> float | None:
    depth_values: list[float] = []
    for key in ("stock_bid_depth", "stock_ask_depth", "fut_bid_depth", "fut_ask_depth"):
        value = _float_or_none(row.get(key))
        if value is not None and value > 0:
            depth_values.append(float(value))
    if not depth_values:
        return None
    return float(min(depth_values))


def _spread_ticks_from_row(row: Mapping[str, object]) -> int | None:
    for key in ("spread_ticks", "orderbook_spread_ticks"):
        value = _float_or_none(row.get(key))
        if value is not None:
            ticks = int(round(value))
            if ticks >= 0:
                return ticks
    signal_metrics = row.get("signal_metrics")
    if isinstance(signal_metrics, dict):
        value = _float_or_none(signal_metrics.get("spread_ticks"))
        if value is not None:
            ticks = int(round(value))
            if ticks >= 0:
                return ticks
    return None


def _regime_flags_from_row(row: Mapping[str, object]) -> MarketRegimeFlags:
    return MarketRegimeFlags(
        is_first_5m=_bool_from_value(row.get("is_first_5m")),
        is_last_5m=_bool_from_value(row.get("is_last_5m")),
        is_intraday_clearing_window=_bool_from_value(row.get("is_intraday_clearing_window")),
        is_evening_clearing_window=_bool_from_value(row.get("is_evening_clearing_window")),
    )


def _probability_config_from_settings(settings: AppSettings) -> DirichletDecayConfig:
    cfg = settings.signal_engine.probability
    alpha = list(cfg.dirichlet_alpha)
    alpha_tp = float(alpha[0]) if len(alpha) >= 1 else 1.0
    alpha_sl = float(alpha[1]) if len(alpha) >= 2 else 1.0
    alpha_exit = float(alpha[2]) if len(alpha) >= 3 else 1.0
    return DirichletDecayConfig(
        alpha_tp=alpha_tp,
        alpha_sl=alpha_sl,
        alpha_exit=alpha_exit,
        half_life_days=float(cfg.decay_half_life_days),
        tier_mid_threshold=float(cfg.tier_thresholds.mid),
        tier_high_threshold=float(cfg.tier_thresholds.high),
        probability_source=str(cfg.method or "dirichlet_decay_v1"),
    )


def _cost_config_from_settings(settings: AppSettings) -> TickCostModelConfig:
    cfg = settings.signal_engine.cost
    liquidity_cfg = cfg.liquidity_penalty
    return TickCostModelConfig(
        commission_ticks_per_side=float(cfg.commission_ticks_per_side),
        slippage_ticks_per_side=float(cfg.slippage_ticks_per_side),
        spread_half_ticks_fallback=float(cfg.spread_half_ticks_fallback),
        depth_ref_lots=float(liquidity_cfg.depth_ref_lots),
        max_penalty_ticks=float(liquidity_cfg.max_penalty_ticks),
        penalty_scale_ticks=1.0 if bool(liquidity_cfg.enable) else 0.0,
    )


def _gate_config_from_settings(settings: AppSettings) -> GateConfig:
    gate_cfg = settings.signal_engine.gate
    prob_cfg = settings.signal_engine.probability
    liquidity_cfg = settings.signal_engine.regimes.liquidity
    return GateConfig(
        forbid_windows_min=int(gate_cfg.forbid_windows_min),
        min_expected_return_ticks=float(gate_cfg.min_expected_return_ticks),
        max_spread_ticks=int(liquidity_cfg.max_spread_ticks),
        tier_mid_threshold=float(prob_cfg.tier_thresholds.mid),
        tier_high_threshold=float(prob_cfg.tier_thresholds.high),
    )


def _build_runtime_proposal_from_row(
    row: Mapping[str, object],
    *,
    as_of_ts: datetime,
    default_horizon_sec: int,
) -> AlphaProposal | None:
    stock = _str_or_none(row.get("stock"))
    future = _str_or_none(row.get("future"))
    if stock is None or future is None:
        return None

    raw_direction = str(row.get("signal_direction") or "").strip().lower()
    side = "SELL" if raw_direction == "reverse" else "BUY"
    parsed_entry_ts = _as_naive_datetime(row.get("snapshot_as_of"))
    if parsed_entry_ts is not None:
        entry_ts = parsed_entry_ts
    else:
        entry_ts = as_of_ts.astimezone(timezone.utc).replace(tzinfo=None)

    forecast_exit_days = _float_or_none(row.get("forecast_exit_days"))
    if forecast_exit_days is not None and forecast_exit_days > 0:
        horizon_sec = max(int(round(forecast_exit_days * 86_400.0)), 60)
    else:
        horizon_sec = max(int(default_horizon_sec), 60)

    tp_ticks = _ticks_from_row(
        explicit=row.get("tp_ticks"),
        fallback_pct=_float_or_none(row.get("tp_net")),
        default_value=2,
    )
    sl_ticks = _ticks_from_row(
        explicit=row.get("sl_ticks"),
        fallback_pct=_float_or_none(row.get("sl_net")),
        default_value=3,
    )

    features_snapshot = {
        "spread_pct": _float_or_none(row.get("spread_pct")),
        "legacy_signal_score": _float_or_none(row.get("signal_score")),
        "legacy_total_score": _float_or_none(row.get("total_score")),
    }
    features_snapshot = {
        key: value for key, value in features_snapshot.items() if value is not None
    }
    market_regime_snapshot: dict[str, Any] = {}
    source = _str_or_none(row.get("source"))
    if source is not None:
        market_regime_snapshot["source"] = source

    return AlphaProposal(
        strategy_id="spread_carry_runtime_v1",
        instrument_id=f"{stock}-{future}",
        side=side,  # type: ignore[arg-type]
        entry_ts=entry_ts,
        horizon_sec=horizon_sec,
        tp_ticks=tp_ticks,
        sl_ticks=sl_ticks,
        exit_rule={"type": "time_exit"},
        features_snapshot=features_snapshot,
        market_regime_snapshot=market_regime_snapshot,
    )


def _signal_direction_from_adapter_signal(signal: object) -> str | None:
    action = str(getattr(signal, "action", "")).strip().lower()
    if action != "enter":
        return None

    metadata = getattr(signal, "metadata", None)
    if isinstance(metadata, dict):
        engine_action = str(metadata.get("engine_action") or "").strip().upper()
        if engine_action == "SELL":
            return "reverse"
        if engine_action == "BUY":
            return "cash_and_carry"

    allocations = getattr(signal, "intent_allocations", [])
    if isinstance(allocations, list) and allocations:
        side = str(getattr(allocations[0], "side", "")).strip().lower()
        if side == "short":
            return "reverse"
        if side == "long":
            return "cash_and_carry"
    return "cash_and_carry"


def apply_runtime_adapter_to_frame(
    *,
    settings: AppSettings,
    ranked: pd.DataFrame,
    as_of_ts: datetime | None = None,
    evaluator: RuntimeEvaluator = evaluate_proposal_to_strategy_signal,
) -> pd.DataFrame:
    runtime_cfg = settings.signal_engine.runtime_adapter
    if not bool(runtime_cfg.enabled):
        return ranked
    if ranked is None or ranked.empty:
        return ranked

    adapted = ranked.copy()
    adapter_ts = as_of_ts or datetime.now(timezone.utc)
    probability_config = _probability_config_from_settings(settings)
    cost_config = _cost_config_from_settings(settings)
    gate_config = _gate_config_from_settings(settings)
    max_events = max(int(runtime_cfg.synthetic_history_cap), 0)
    default_horizon_sec = max(int(settings.signal_engine.strategies.micro_momo.horizon_min) * 60, 60)
    vacuum_cfg = settings.signal_engine.regimes.liquidity.vacuum
    vacuum_spread_ticks = int(vacuum_cfg.spread_ticks)
    vacuum_depth_lots = float(vacuum_cfg.depth_lots)
    override_signal_fields = bool(runtime_cfg.override_signal_fields)
    for column in (
        "signal_action_two_layer",
        "signal_direction_two_layer",
        "signal_score_two_layer",
        "signal_reasons_two_layer",
        "signal_metrics_two_layer",
        "signal_two_layer_error",
        "signal_action_legacy",
        "signal_direction_legacy",
        "signal_score_legacy",
        "signal_reasons_legacy",
    ):
        if column not in adapted.columns:
            adapted[column] = None

    for idx, row in adapted.iterrows():
        row_mapping = row.to_dict()
        proposal = _build_runtime_proposal_from_row(
            row_mapping,
            as_of_ts=adapter_ts,
            default_horizon_sec=default_horizon_sec,
        )
        if proposal is None:
            continue

        try:
            historical_outcomes = _build_synthetic_historical_outcomes(
                row_mapping,
                as_of_ts=adapter_ts,
                max_events=max_events,
            )
            spread_ticks_value = _spread_ticks_from_row(row_mapping)
            depth_lots = _depth_lots_from_row(row_mapping)
            vacuum = False
            if spread_ticks_value is not None and spread_ticks_value >= vacuum_spread_ticks:
                vacuum = True
            if depth_lots is not None and depth_lots <= vacuum_depth_lots:
                vacuum = True
            vol_regime = _str_or_none(row_mapping.get("vol_regime")) or _str_or_none(
                row_mapping.get("volatility_regime")
            )
            strategy_signal, evaluation = evaluator(
                proposal=proposal,
                historical_outcomes=historical_outcomes,
                as_of_ts=adapter_ts,
                regime_flags=_regime_flags_from_row(row_mapping),
                spread_ticks_value=spread_ticks_value,
                depth_lots=depth_lots,
                vacuum=vacuum,
                probability_config=probability_config,
                cost_config=cost_config,
                gate_config=gate_config,
                vol_regime=vol_regime,
            )
        except Exception as exc:  # pragma: no cover - defensive runtime path
            adapted.at[idx, "signal_two_layer_error"] = str(exc)
            continue

        two_layer_action = str(getattr(strategy_signal, "action", "hold")).strip().lower()
        if two_layer_action not in {"enter", "hold", "exit"}:
            two_layer_action = "hold"
        two_layer_direction = _signal_direction_from_adapter_signal(strategy_signal)

        reasons: list[str] = []
        warnings = getattr(strategy_signal, "warnings", [])
        if isinstance(warnings, list):
            reasons.extend(str(item) for item in warnings)
        rules = getattr(strategy_signal, "rules_evaluated", [])
        if isinstance(rules, list):
            reasons.extend(
                str(getattr(rule, "rule_id", "")).strip()
                for rule in rules
                if not getattr(rule, "result", True)
            )
        reason_list = [item for item in dict.fromkeys(reasons) if item]

        metadata = getattr(strategy_signal, "metadata", {})
        engine_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        forecast = getattr(evaluation, "forecast", None)
        if forecast is not None:
            engine_metadata.setdefault("p_tp", getattr(forecast, "p_tp", None))
            engine_metadata.setdefault("p_sl", getattr(forecast, "p_sl", None))
            engine_metadata.setdefault("p_exit", getattr(forecast, "p_exit", None))
            engine_metadata.setdefault("forecast_n_effective", getattr(forecast, "n_effective", None))
            engine_metadata.setdefault(
                "forecast_probability_source",
                getattr(forecast, "probability_source", None),
            )
        engine_metadata["synthetic_history_events"] = len(historical_outcomes)
        historical_source_kind = "synthetic" if historical_outcomes else "none"
        cost_source_kind = "pair_row_derived"
        legacy_action = str(row_mapping.get("signal_action") or "").strip().lower()
        synthetic_promotion_blocked = (
            bool(override_signal_fields)
            and historical_source_kind == "synthetic"
            and two_layer_action == "enter"
            and legacy_action != "enter"
        )
        if synthetic_promotion_blocked:
            reason_list = [item for item in dict.fromkeys([*reason_list, "synthetic_history_promotion_blocked"]) if item]
            engine_metadata["promotion_blocked_reason"] = "synthetic_history_cannot_promote_enter"

        expected_return = _float_or_none(getattr(strategy_signal, "expected_return", None))
        risk_estimate = _float_or_none(getattr(strategy_signal, "risk_estimate", None))
        confidence = _float_or_none(getattr(strategy_signal, "confidence", None)) or 0.0
        evaluation_cost = _float_or_none(getattr(evaluation, "cost_ticks", None))
        evaluation_expectancy = _float_or_none(getattr(evaluation, "expected_return_ticks", None))
        strategy_id = _str_or_none(getattr(strategy_signal, "strategy_id", None))
        strategy_type = _normalize_strategy_type(getattr(strategy_signal, "strategy_type", None))
        strategy_stream = _strategy_stream_from_type(strategy_type)

        two_layer_metrics: dict[str, object] = {
            "confidence": float(confidence),
            "expected_return_ticks": expected_return,
            "risk_ticks": risk_estimate,
            "cost_ticks": evaluation_cost,
            "expectancy_ticks_engine": evaluation_expectancy,
            "strategy_id": strategy_id,
            "strategy_type": strategy_type,
            "strategy_stream": strategy_stream,
            "legacy_action": legacy_action or None,
            "override_requested": bool(override_signal_fields),
            "override_applied": False,
            "historical_source_kind": historical_source_kind,
            "cost_source_kind": cost_source_kind,
            "synthetic_promotion_blocked": bool(synthetic_promotion_blocked),
            "metadata": engine_metadata,
        }

        adapted.at[idx, "signal_action_two_layer"] = two_layer_action
        adapted.at[idx, "signal_direction_two_layer"] = two_layer_direction
        adapted.at[idx, "signal_score_two_layer"] = float(confidence)
        adapted.at[idx, "signal_reasons_two_layer"] = reason_list
        adapted.at[idx, "signal_metrics_two_layer"] = two_layer_metrics

        current_metrics = row_mapping.get("signal_metrics")
        merged_metrics = dict(current_metrics) if isinstance(current_metrics, dict) else {}
        merged_metrics["two_layer"] = two_layer_metrics
        merged_metrics["strategy_id"] = strategy_id
        merged_metrics["strategy_type"] = strategy_type
        merged_metrics["strategy_stream"] = strategy_stream
        merged_metrics["historical_source_kind"] = historical_source_kind
        merged_metrics["cost_source_kind"] = cost_source_kind
        adapted.at[idx, "signal_metrics"] = merged_metrics

        if not override_signal_fields or synthetic_promotion_blocked:
            continue

        adapted.at[idx, "signal_action_legacy"] = row_mapping.get("signal_action")
        adapted.at[idx, "signal_direction_legacy"] = row_mapping.get("signal_direction")
        adapted.at[idx, "signal_score_legacy"] = _float_or_none(row_mapping.get("signal_score"))
        adapted.at[idx, "signal_reasons_legacy"] = row_mapping.get("signal_reasons")

        adapted.at[idx, "signal_action"] = two_layer_action
        adapted.at[idx, "signal_direction"] = two_layer_direction
        adapted.at[idx, "signal_score"] = float(confidence)
        adapted.at[idx, "signal_reasons"] = reason_list
        two_layer_metrics["override_applied"] = True
        adapted.at[idx, "signal_metrics_two_layer"] = two_layer_metrics
        merged_metrics["two_layer"] = two_layer_metrics
        adapted.at[idx, "signal_metrics"] = merged_metrics
        if "decision" in adapted.columns:
            adapted.at[idx, "decision"] = "ENTER_OK" if two_layer_action == "enter" else "HOLD"

    return adapted
