from __future__ import annotations

from datetime import tzinfo
from typing import Mapping

from moex_carry.integrations.telegram_strategy import strategy_label
from moex_carry.signals_delivery import parse_iso_utc, to_float


def _to_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _fmt_number(value: object, digits: int = 4) -> str:
    parsed = to_float(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.{digits}f}"


def _fmt_percent(value: object, digits: int = 2) -> str:
    parsed = to_float(value)
    if parsed is None:
        return "n/a"
    return f"{parsed * 100:.{digits}f}%"


def _fmt_timestamp(value: object, *, display_timezone: tzinfo, display_timezone_name: str) -> str:
    raw = str(value or "").strip()
    parsed = parse_iso_utc(raw)
    if parsed is None:
        return raw or "n/a"
    localized = parsed.astimezone(display_timezone)
    tz_label = localized.tzname() or display_timezone_name
    return f"{localized.strftime('%d.%m.%Y %H:%M')} {tz_label}"


def _entry_leg_action(*, direction: str, leg: str) -> str:
    if direction == "reverse":
        return "SELL акцию" if leg == "stock" else "BUY фьюч"
    return "BUY акцию" if leg == "stock" else "SELL фьюч"


def _exit_leg_action(*, direction: str, leg: str) -> str:
    if direction == "reverse":
        return "BUY акцию" if leg == "stock" else "SELL фьюч"
    return "SELL акцию" if leg == "stock" else "BUY фьюч"


def format_signal_message(
    row: Mapping[str, object],
    *,
    display_timezone: tzinfo,
    display_timezone_name: str,
) -> str:
    delivery_payload = row.get("delivery")
    delivery_action = (
        str(delivery_payload.get("delivery_action") or "").strip().lower()
        if isinstance(delivery_payload, Mapping)
        else ""
    )
    action_raw = str(row.get("signal_action") or delivery_action).strip().lower()
    action_label = {
        "enter": "🟢 ENTER",
        "exit": "🔴 EXIT",
        "hold_open": "🟡 HOLD_OPEN",
    }.get(action_raw, f"⚪ {action_raw.upper() or 'UNKNOWN'}")

    entry_plan = row.get("entry_plan")
    entry_plan_map = entry_plan if isinstance(entry_plan, Mapping) else {}
    entry_range_now = row.get("entry_range_now")
    entry_range_map = entry_range_now if isinstance(entry_range_now, Mapping) else {}
    metrics = row.get("signal_metrics")
    metrics_map = metrics if isinstance(metrics, Mapping) else {}

    direction_raw = str(row.get("signal_direction") or "").strip().lower()
    if not direction_raw:
        direction_raw = str(entry_plan_map.get("direction") or "").strip().lower()
    direction_label = {
        "cash_and_carry": "Cash-and-carry",
        "reverse": "Reverse",
        "neutral": "Neutral",
    }.get(direction_raw, direction_raw or "n/a")

    stock = str(row.get("stock") or "").strip() or "N/A"
    future = str(row.get("future") or "").strip() or "N/A"
    timestamp = _fmt_timestamp(
        row.get("timestamp") or row.get("snapshot_as_of"),
        display_timezone=display_timezone,
        display_timezone_name=display_timezone_name,
    )
    strategy_stream_raw = str(
        row.get("strategy_stream") or row.get("strategy_type") or ""
    ).strip().lower()
    strategy_stream_raw = "commodity_futures" if strategy_stream_raw == "speculative" else strategy_stream_raw
    strategy_label_text = strategy_label(strategy_stream_raw)

    entry_stock_min = row.get("entry_stock_min")
    entry_stock_max = row.get("entry_stock_max")
    if entry_stock_min is None:
        entry_stock_min = entry_plan_map.get("entry_stock_min")
    if entry_stock_max is None:
        entry_stock_max = entry_plan_map.get("entry_stock_max")
    if entry_stock_min is None:
        entry_stock_min = entry_plan_map.get("entry_price_min")
    if entry_stock_max is None:
        entry_stock_max = entry_plan_map.get("entry_price_max")

    entry_future_min = row.get("entry_future_min_per_share")
    entry_future_max = row.get("entry_future_max_per_share")
    if entry_future_min is None:
        entry_future_min = entry_plan_map.get("entry_future_min_per_share")
    if entry_future_max is None:
        entry_future_max = entry_plan_map.get("entry_future_max_per_share")

    entry_spread_min = row.get("entry_spread_min")
    entry_spread_max = row.get("entry_spread_max")
    if entry_spread_min is None:
        entry_spread_min = entry_plan_map.get("entry_spread_min")
    if entry_spread_max is None:
        entry_spread_max = entry_plan_map.get("entry_spread_max")

    entry_spread_pct_min = row.get("entry_spread_pct_min")
    entry_spread_pct_max = row.get("entry_spread_pct_max")
    if entry_spread_pct_min is None:
        entry_spread_pct_min = entry_plan_map.get("entry_spread_pct_min")
    if entry_spread_pct_max is None:
        entry_spread_pct_max = entry_plan_map.get("entry_spread_pct_max")

    current_spread_pct = row.get("spread_pct")
    if current_spread_pct is None:
        current_spread_pct = entry_range_map.get("spread_pct_now")
    tp = row.get("tp_spread_pct_level")
    if tp is None:
        tp = metrics_map.get("tp_spread_pct_level")
    sl = row.get("sl_spread_pct_level")
    if sl is None:
        sl = metrics_map.get("sl_spread_pct_level")
    forecast_days = row.get("forecast_exit_days")
    if forecast_days is None:
        forecast_days = metrics_map.get("forecast_exit_days")
    forecast_tp_probability = row.get("forecast_tp_probability")
    if forecast_tp_probability is None:
        forecast_tp_probability = metrics_map.get("forecast_tp_probability")
    forecast_sl_probability = row.get("forecast_sl_probability")
    if forecast_sl_probability is None:
        forecast_sl_probability = metrics_map.get("forecast_sl_probability")
    forecast_model = str(row.get("forecast_model") or metrics_map.get("forecast_model") or "").strip()
    score = row.get("signal_score")
    if score is None:
        score = metrics_map.get("total_score")

    seq_entry_enabled = _to_bool(row.get("sequential_entry_enabled"))
    if seq_entry_enabled is None:
        seq_entry_enabled = _to_bool(metrics_map.get("sequential_entry_enabled"))
    entry_protocol_raw = str(
        row.get("entry_execution_protocol")
        or metrics_map.get("entry_execution_protocol")
        or ""
    ).strip().lower()
    if not entry_protocol_raw:
        entry_protocol_raw = "sequential" if seq_entry_enabled else "atomic"
    seq_entry_first_leg = str(
        row.get("sequential_entry_first_leg")
        or metrics_map.get("sequential_entry_first_leg")
        or "future"
    ).strip().lower()
    if seq_entry_first_leg not in {"stock", "future"}:
        seq_entry_first_leg = "future"
    seq_entry_second_leg_wait = row.get("sequential_entry_second_leg_max_wait_minutes")
    if seq_entry_second_leg_wait is None:
        seq_entry_second_leg_wait = metrics_map.get("sequential_entry_second_leg_max_wait_minutes")
    seq_entry_unwind_penalty = row.get("sequential_entry_unwind_penalty_bps")
    if seq_entry_unwind_penalty is None:
        seq_entry_unwind_penalty = metrics_map.get("sequential_entry_unwind_penalty_bps")

    seq_exit_enabled = _to_bool(row.get("sequential_exit_enabled"))
    if seq_exit_enabled is None:
        seq_exit_enabled = _to_bool(metrics_map.get("sequential_exit_enabled"))
    exit_protocol_raw = str(
        row.get("exit_execution_protocol")
        or metrics_map.get("exit_execution_protocol")
        or ""
    ).strip().lower()
    if not exit_protocol_raw:
        exit_protocol_raw = "sequential" if seq_exit_enabled else "atomic"
    seq_exit_first_leg = str(
        row.get("sequential_exit_first_leg")
        or metrics_map.get("sequential_exit_first_leg")
        or "future"
    ).strip().lower()
    if seq_exit_first_leg not in {"stock", "future"}:
        seq_exit_first_leg = "future"
    seq_exit_second_leg_wait = row.get("sequential_exit_second_leg_max_wait_minutes")
    if seq_exit_second_leg_wait is None:
        seq_exit_second_leg_wait = metrics_map.get("sequential_exit_second_leg_max_wait_minutes")
    seq_exit_force_penalty = row.get("sequential_exit_force_penalty_bps")
    if seq_exit_force_penalty is None:
        seq_exit_force_penalty = metrics_map.get("sequential_exit_force_penalty_bps")

    lines = [
        "📣 Новый сигнал",
        action_label,
        f"📈 Пара: {stock}/{future}",
        f"🧩 Стратегия: {strategy_label_text}",
        f"🧭 Направление: {direction_label}",
        f"⭐ Score: {_fmt_number(score)}",
        f"⏱ Время: {timestamp}",
    ]

    has_entry_plan = any(
        value is not None
        for value in (
            entry_stock_min,
            entry_stock_max,
            entry_future_min,
            entry_future_max,
            entry_spread_min,
            entry_spread_max,
            entry_spread_pct_min,
            entry_spread_pct_max,
        )
    )
    if has_entry_plan:
        lines.append("📍 План входа")
        if entry_stock_min is not None or entry_stock_max is not None:
            lines.append(f"• {stock}: {_fmt_number(entry_stock_min)} .. {_fmt_number(entry_stock_max)}")
        if entry_future_min is not None or entry_future_max is not None:
            lines.append(
                f"• {future}: {_fmt_number(entry_future_min)} .. {_fmt_number(entry_future_max)}"
            )
        if entry_spread_min is not None or entry_spread_max is not None:
            lines.append(
                f"• Допустимый spread: {_fmt_number(entry_spread_min)} .. {_fmt_number(entry_spread_max)}"
            )
        if entry_spread_pct_min is not None or entry_spread_pct_max is not None:
            lines.append(
                "• Допустимый spread (%): "
                f"{_fmt_percent(entry_spread_pct_min)} .. {_fmt_percent(entry_spread_pct_max)}"
            )
        if current_spread_pct is not None:
            lines.append(f"• Текущий spread (%): {_fmt_percent(current_spread_pct)}")

    if entry_protocol_raw == "sequential":
        second_leg = "stock" if seq_entry_first_leg == "future" else "future"
        lines.append(
            "• Протокол входа: staged "
            f"({_entry_leg_action(direction=direction_raw, leg=seq_entry_first_leg)} -> "
            f"{_entry_leg_action(direction=direction_raw, leg=second_leg)})"
        )
        lines.append(
            f"• Макс. разрыв между ногами: {int(to_float(seq_entry_second_leg_wait) or 0)} мин"
        )
        lines.append(
            "• Если 2-я нога не встала: unwind 1-й "
            f"(penalty {(to_float(seq_entry_unwind_penalty) or 0.0):.2f} bps)"
        )
    else:
        lines.append("• Протокол входа: atomic (обе ноги одновременно)")

    if tp is not None or sl is not None:
        lines.append(f"• TP/SL spread: {_fmt_percent(tp)} / {_fmt_percent(sl)}")
    if exit_protocol_raw == "sequential":
        second_leg = "stock" if seq_exit_first_leg == "future" else "future"
        lines.append(
            "• Протокол выхода: staged "
            f"({_exit_leg_action(direction=direction_raw, leg=seq_exit_first_leg)} -> "
            f"{_exit_leg_action(direction=direction_raw, leg=second_leg)})"
        )
        lines.append(
            "• Макс. разрыв между ногами (выход): "
            f"{int(to_float(seq_exit_second_leg_wait) or 0)} мин"
        )
        lines.append(
            "• Если 2-я нога не встала: force-close 2-й "
            f"(penalty {(to_float(seq_exit_force_penalty) or 0.0):.2f} bps)"
        )
    else:
        lines.append("• Протокол выхода: atomic (обе ноги одновременно)")
    if forecast_tp_probability is not None or forecast_sl_probability is not None:
        lines.append(
            "• Forecast TP/SL prob: "
            f"{_fmt_percent(forecast_tp_probability)} / {_fmt_percent(forecast_sl_probability)}"
        )
    if forecast_days is not None:
        if forecast_model:
            lines.append(f"• Прогноз выхода: {forecast_days} дн ({forecast_model})")
        else:
            lines.append(f"• Прогноз выхода: {forecast_days} дн")

    execution_contract = row.get("execution_contract")
    contract_map = execution_contract if isinstance(execution_contract, Mapping) else {}
    baseline_id = str(row.get("baseline_id") or contract_map.get("baseline_id") or "").strip()
    signal_expire_ts = row.get("signal_expire_ts") or contract_map.get("signal_expire_ts")
    if baseline_id:
        lines.append(f"• Baseline: {baseline_id}")
    if signal_expire_ts:
        lines.append(
            "• Сигнал валиден до: "
            f"{_fmt_timestamp(signal_expire_ts, display_timezone=display_timezone, display_timezone_name=display_timezone_name)}"
        )
    entry_order_type = str(contract_map.get("entry_order_type") or "").strip().upper()
    if entry_order_type:
        lines.append(
            "• H4A вход: "
            f"{entry_order_type} +{int(to_float(contract_map.get('entry_improve_ticks')) or 0)} тик"
        )
    fallback_minutes = int(to_float(contract_map.get("entry_fallback_after_minutes")) or 0)
    fallback_slip = int(to_float(contract_map.get("entry_fallback_slip_ticks")) or 0)
    if fallback_minutes > 0:
        lines.append(
            f"• Fallback: через {fallback_minutes} мин -> marketable ({fallback_slip} неблаг. тик)"
        )
    break_even_rr = to_float(contract_map.get("break_even_rr"))
    break_even_buffer = int(to_float(contract_map.get("break_even_buffer_ticks")) or 0)
    if break_even_rr is not None:
        lines.append(
            f"• Break-even: после {break_even_rr:.2f}R, буфер {break_even_buffer} тика"
        )
    trail_activation_rr = to_float(contract_map.get("trail_activation_rr"))
    trail_offset_ticks = int(to_float(contract_map.get("trail_offset_ticks")) or 0)
    if trail_activation_rr is not None:
        lines.append(
            f"• Trailing: после {trail_activation_rr:.2f}R, offset {trail_offset_ticks} тика"
        )
    time_stop_minutes = int(to_float(contract_map.get("time_stop_minutes")) or 0)
    if time_stop_minutes > 0:
        lines.append(f"• Time stop: {time_stop_minutes} минут от fill")
    same_bar_policy = str(contract_map.get("same_bar_policy") or "").strip()
    same_bar_source = str(contract_map.get("same_bar_policy_source") or "").strip()
    if same_bar_policy:
        lines.append(
            f"• Same-bar policy: {same_bar_policy} ({same_bar_source or 'simulator'})"
        )

    lines.append("")
    lines.append("Нажмите кнопку ниже, если только просмотрели сигнал.")
    lines.append("Факт выставления заявки и фактический fill фиксируйте отдельно.")
    return "\n".join(lines)
