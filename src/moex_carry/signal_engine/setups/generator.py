from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from moex_carry.signal_engine.core.calendar import MarketCalendar
from moex_carry.signal_engine.core.math_utils import round_half_away_from_zero
from moex_carry.signal_engine.core.types import (
    Candle,
    Direction,
    ExecutionParams,
    Level,
    LiquidityState,
    OrderIntent,
    OrderType,
    RegimeState,
    Setup,
    Side,
    TrendState,
)
from moex_carry.signal_engine.execution.engine import ExecutionEngine
from moex_carry.signal_engine.setups.extended_families import (
    generate_ema_pullback_limit,
    generate_orb_breakout,
    generate_vwap_pullback_limit,
)
from moex_carry.signal_engine.setups.volatility_compression_family import (
    generate_volatility_compression_breakout,
)


class SetupGenerator:
    def __init__(self, cfg: dict, execution_engine: ExecutionEngine | None = None):
        self.cfg = cfg or {}
        self.execution_engine = execution_engine or ExecutionEngine({})
        self._rejection_trace: list[dict[str, Any]] = []

    def _reset_rejection_trace(self) -> None:
        self._rejection_trace = []

    def _record_rejection(
        self,
        *,
        setup_kind: str,
        rule: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "setup_kind": str(setup_kind).strip().upper() or "UNKNOWN",
            "rule": str(rule).strip().lower() or "unspecified",
        }
        if details:
            normalized = {
                str(key): _trace_scalar(value)
                for key, value in details.items()
                if value is not None
            }
            if normalized:
                payload["details"] = normalized
        self._rejection_trace.append(payload)

    def _reject(self, *, setup_kind: str, rule: str, **details: Any) -> None:
        self._record_rejection(setup_kind=setup_kind, rule=rule, details=details or None)
        return None

    def consume_rejection_trace(self) -> list[dict[str, Any]]:
        rows = list(self._rejection_trace)
        self._rejection_trace = []
        return rows

    def generate(
        self,
        as_of_ts: datetime,
        instrument_id: str,
        last_price_ticks: int,
        regime: RegimeState,
        levels_d1: list[Level],
        levels_h1: list[Level],
        exec_params: ExecutionParams,
        calendar: MarketCalendar,
        m5: list[Candle] | None = None,
    ) -> list[Setup]:
        self._reset_rejection_trace()
        if regime.daily_trend_state != TrendState.TREND:
            self._reject(
                setup_kind="ALL",
                rule="daily_trend_not_trend",
                daily_trend_state=str(regime.daily_trend_state.value),
            )
            return []
        if regime.daily_dir == Direction.NEUTRAL:
            self._reject(setup_kind="ALL", rule="daily_dir_neutral")
            return []
        if not regime.h1_alignment:
            self._reject(setup_kind="ALL", rule="h1_not_aligned")
            return []
        if regime.liquidity_state == LiquidityState.VACUUM:
            self._reject(setup_kind="ALL", rule="liquidity_vacuum")
            return []
        if calendar.forbid_new_position(as_of_ts):
            self._reject(setup_kind="ALL", rule="calendar_forbid_new_position")
            return []
        if self._eligibility_filter_enabled():
            cost_ticks = self._estimated_round_trip_cost_ticks()
            min_h1_mult = _safe_non_negative_float(self.cfg.get("min_atr_h1_cost_mult"), 6.0)
            min_d1_mult = _safe_non_negative_float(self.cfg.get("min_atr_d1_cost_mult"), 12.0)
            min_h1_ticks = max(round_half_away_from_zero(min_h1_mult * cost_ticks), 1)
            min_d1_ticks = max(round_half_away_from_zero(min_d1_mult * cost_ticks), 1)
            if int(regime.h1_atr_ticks) < int(min_h1_ticks):
                self._reject(
                    setup_kind="ALL",
                    rule="eligibility_h1_atr_below_min",
                    h1_atr_ticks=int(regime.h1_atr_ticks),
                    min_h1_ticks=int(min_h1_ticks),
                )
                return []
            if int(regime.daily_atr_ticks) < int(min_d1_ticks):
                self._reject(
                    setup_kind="ALL",
                    rule="eligibility_d1_atr_below_min",
                    daily_atr_ticks=int(regime.daily_atr_ticks),
                    min_d1_ticks=int(min_d1_ticks),
                )
                return []

        setups: list[Setup] = []
        m5_rows = m5 or []
        if self._setup_kind_enabled("BOX_BREAKOUT", default_enabled=True):
            s1 = self._generate_box_breakout(
                as_of_ts=as_of_ts,
                instrument_id=instrument_id,
                regime=regime,
                levels_d1=levels_d1,
                levels_h1=levels_h1,
                exec_params=exec_params,
                calendar=calendar,
                m5=m5_rows,
            )
            if s1 is not None:
                setups.append(s1)
        if self._setup_kind_enabled("PULLBACK_LIMIT", default_enabled=True):
            s2 = self._generate_pullback_limit(
                as_of_ts=as_of_ts,
                instrument_id=instrument_id,
                last_price_ticks=int(last_price_ticks),
                regime=regime,
                levels_d1=levels_d1,
                exec_params=exec_params,
                calendar=calendar,
                m5=m5_rows,
            )
            if s2 is not None:
                setups.append(s2)
        if self._setup_kind_enabled("ORB_BREAKOUT", default_enabled=False):
            s3 = generate_orb_breakout(
                self,
                as_of_ts=as_of_ts,
                instrument_id=instrument_id,
                last_price_ticks=int(last_price_ticks),
                regime=regime,
                levels_d1=levels_d1,
                exec_params=exec_params,
                calendar=calendar,
                m5=m5_rows,
            )
            if s3 is not None:
                setups.append(s3)
        if self._setup_kind_enabled("EMA_PULLBACK_LIMIT", default_enabled=False):
            s4 = generate_ema_pullback_limit(
                self,
                as_of_ts=as_of_ts,
                instrument_id=instrument_id,
                last_price_ticks=int(last_price_ticks),
                regime=regime,
                levels_d1=levels_d1,
                levels_h1=levels_h1,
                exec_params=exec_params,
                calendar=calendar,
                m5=m5_rows,
            )
            if s4 is not None:
                setups.append(s4)
        if self._setup_kind_enabled("VWAP_PULLBACK_LIMIT", default_enabled=False):
            s5 = generate_vwap_pullback_limit(
                self,
                as_of_ts=as_of_ts,
                instrument_id=instrument_id,
                last_price_ticks=int(last_price_ticks),
                regime=regime,
                levels_d1=levels_d1,
                exec_params=exec_params,
                calendar=calendar,
                m5=m5_rows,
            )
            if s5 is not None:
                setups.append(s5)
        if self._setup_kind_enabled("VOLATILITY_COMPRESSION_BREAKOUT", default_enabled=False):
            s6 = generate_volatility_compression_breakout(
                self,
                as_of_ts=as_of_ts,
                instrument_id=instrument_id,
                last_price_ticks=int(last_price_ticks),
                regime=regime,
                levels_d1=levels_d1,
                exec_params=exec_params,
                calendar=calendar,
                m5=m5_rows,
            )
            if s6 is not None:
                setups.append(s6)

        max_setups = max(int(self.cfg.get("max_setups_per_instrument", 2)), 0)
        if max_setups <= 0:
            self._reject(
                setup_kind="ALL",
                rule="max_setups_per_instrument_non_positive",
                max_setups_per_instrument=int(max_setups),
            )
            return []
        ranked = sorted(
            setups,
            key=lambda item: (int(item.risk_ticks), abs(item.tp_order.price_ticks - item.entry_order.price_ticks)),
        )
        return ranked[:max_setups]

    def _setup_kind_enabled(self, setup_kind: str, *, default_enabled: bool) -> bool:
        kind = str(setup_kind).strip().upper()
        if not kind:
            return bool(default_enabled)
        allowed = _normalize_setup_kind_tokens(self.cfg.get("enabled_setup_kinds"))
        if allowed and kind not in allowed:
            return False
        disabled = _normalize_setup_kind_tokens(self.cfg.get("disabled_setup_kinds"))
        if kind in disabled:
            return False
        if kind == "BOX_BREAKOUT":
            return bool(self.cfg.get("enable_box_breakout", default_enabled))
        if kind == "PULLBACK_LIMIT":
            return bool(self.cfg.get("enable_pullback_limit", default_enabled))
        if kind == "ORB_BREAKOUT":
            return bool(self.cfg.get("enable_orb_breakout", default_enabled))
        if kind == "EMA_PULLBACK_LIMIT":
            return bool(self.cfg.get("enable_ema_pullback", default_enabled))
        if kind == "VWAP_PULLBACK_LIMIT":
            return bool(self.cfg.get("enable_vwap_pullback", default_enabled))
        if kind == "VOLATILITY_COMPRESSION_BREAKOUT":
            return bool(self.cfg.get("enable_volatility_compression_breakout", default_enabled))
        return bool(default_enabled)

    def _cost_gate_metrics(self, *, reward_gross_ticks: int, risk_gross_ticks: int) -> dict[str, float | bool]:
        cost_ticks = self._estimated_round_trip_cost_ticks()
        min_reward_net = _safe_non_negative_float(self.cfg.get("min_reward_net_ticks"), 2.0)
        min_rr_net = _safe_non_negative_float(self.cfg.get("min_rr_net"), 1.1)
        min_reward_gross_default = max(2.0 * cost_ticks, 0.0)
        min_reward_gross = _safe_non_negative_float(
            self.cfg.get("min_reward_gross_ticks"),
            min_reward_gross_default,
        )
        reward_gross = float(max(int(reward_gross_ticks), 0))
        risk_gross = float(max(int(risk_gross_ticks), 0))
        reward_net = reward_gross - cost_ticks
        risk_net = risk_gross + cost_ticks
        rr_net = reward_net / risk_net if risk_net > 0.0 else 0.0
        is_pass = bool(
            reward_gross >= min_reward_gross
            and reward_net >= min_reward_net
            and rr_net >= min_rr_net
        )
        return {
            "pass": is_pass,
            "estimated_round_trip_cost_ticks": float(cost_ticks),
            "reward_gross_ticks": float(reward_gross),
            "risk_gross_ticks": float(risk_gross),
            "reward_net_ticks": float(reward_net),
            "risk_net_ticks": float(risk_net),
            "rr_net": float(rr_net),
            "min_reward_gross_ticks": float(min_reward_gross),
            "min_reward_net_ticks": float(min_reward_net),
            "min_rr_net": float(min_rr_net),
        }

    def _estimated_round_trip_cost_ticks(self) -> float:
        return _safe_non_negative_float(self.cfg.get("estimated_round_trip_cost_ticks"), 5.0)

    def _cost_gate_enabled(self) -> bool:
        return bool(self.cfg.get("enable_cost_net_gate", True))

    def _eligibility_filter_enabled(self) -> bool:
        return bool(self.cfg.get("enable_eligibility_filter", True))

    def _min_target_return_pct(self) -> float:
        return _safe_non_negative_float(self.cfg.get("min_target_return_pct"), 0.5)

    def _stop_model(self) -> str:
        return str(self.cfg.get("stop_model", "structure")).strip().lower()

    def _stop_lookback_bars(self) -> int:
        return max(int(self.cfg.get("stop_lookback_bars", 24)), 1)

    def _stop_volume_quantile(self) -> float:
        quantile = float(self.cfg.get("stop_volume_quantile", 0.75))
        return min(max(quantile, 0.0), 1.0)

    def _entry_range_half_width_ticks(self) -> int:
        return max(int(self.cfg.get("entry_range_half_width_ticks", 0)), 0)

    def _entry_ttl_minutes(self) -> int:
        return max(int(self.cfg.get("entry_ttl_minutes", 0) or 0), 0)

    def _stop_limit_fallback_to_market_min(self) -> int:
        return max(int(self.cfg.get("stop_limit_fallback_to_market_min", 0) or 0), 0)

    def _stop_limit_fallback_slip_ticks(self) -> int:
        return max(int(self.cfg.get("stop_limit_fallback_slip_ticks", 1) or 1), 0)

    def _time_stop_minutes(self) -> int:
        return max(int(self.cfg.get("time_stop_minutes", 0) or 0), 0)

    def _entry_range_ticks(
        self,
        *,
        entry_ticks: int,
        order_type: OrderType,
        side: Side,
        limit_ticks: int | None = None,
    ) -> tuple[int, int]:
        if order_type == OrderType.STOP_LIMIT and limit_ticks is not None:
            low = min(int(entry_ticks), int(limit_ticks))
            high = max(int(entry_ticks), int(limit_ticks))
            return int(low), int(high)
        half = self._entry_range_half_width_ticks()
        if half <= 0:
            return int(entry_ticks), int(entry_ticks)
        low = int(entry_ticks) - int(half)
        high = int(entry_ticks) + int(half)
        if side == Side.BUY:
            return int(low), int(high)
        return int(low), int(high)

    def _volatility_stop_ticks(
        self,
        *,
        side: Side,
        entry_ticks: int,
        regime: RegimeState,
        exec_params: ExecutionParams,
    ) -> int:
        sl_mult = float(self.cfg.get("sl_atr_mult", 0.8))
        atr_ref_ticks = max(int(regime.h1_atr_ticks), int(exec_params.m5_atr_ticks), 1)
        delta = max(round_half_away_from_zero(sl_mult * float(atr_ref_ticks)), 1)
        return int(entry_ticks - delta if side == Side.BUY else entry_ticks + delta)

    def _choose_stop_ticks(
        self,
        *,
        side: Side,
        entry_ticks: int,
        regime: RegimeState,
        exec_params: ExecutionParams,
        m5: list[Candle],
    ) -> tuple[int, str]:
        model = self._stop_model()
        if model == "volatility":
            return self._volatility_stop_ticks(
                side=side,
                entry_ticks=entry_ticks,
                regime=regime,
                exec_params=exec_params,
            ), "volatility"
        if model == "local_extreme":
            stop_ticks = self.execution_engine.choose_stop_from_local_extreme(
                m5=m5,
                side=side,
                entry_ticks=int(entry_ticks),
                buffer_ticks=max(int(exec_params.buffer_ticks), 1),
                lookback_bars=self._stop_lookback_bars(),
            )
            return int(stop_ticks), "local_extreme"
        if model == "volume_extreme":
            stop_ticks = self.execution_engine.choose_stop_from_volume_extreme(
                m5=m5,
                side=side,
                entry_ticks=int(entry_ticks),
                buffer_ticks=max(int(exec_params.buffer_ticks), 1),
                lookback_bars=self._stop_lookback_bars(),
                volume_quantile=self._stop_volume_quantile(),
            )
            return int(stop_ticks), "volume_extreme"
        stop_ticks = self.execution_engine.choose_stop_from_m5_structure(
            m5=m5,
            side=side,
            entry_ticks=int(entry_ticks),
            buffer_ticks=max(int(exec_params.buffer_ticks), 1),
        )
        return int(stop_ticks), "structure"

    def _generate_box_breakout(
        self,
        *,
        as_of_ts: datetime,
        instrument_id: str,
        regime: RegimeState,
        levels_d1: list[Level],
        levels_h1: list[Level],
        exec_params: ExecutionParams,
        calendar: MarketCalendar,
        m5: list[Candle],
    ) -> Setup | None:
        if bool(self.cfg.get("require_vol_not_low", True)) and regime.daily_vol_state.value == "LOW":
            return self._reject(
                setup_kind="BOX_BREAKOUT",
                rule="daily_vol_low",
                daily_vol_state=str(regime.daily_vol_state.value),
            )

        box_h = _find_level(levels_h1, "BOX_H")
        box_l = _find_level(levels_h1, "BOX_L")
        if regime.daily_dir == Direction.UP:
            if box_h is None:
                return self._reject(setup_kind="BOX_BREAKOUT", rule="missing_box_h")
            side = Side.BUY
            entry_stop_ticks = int(box_h.price_ticks) + int(exec_params.buffer_ticks)
            limit_ticks = entry_stop_ticks + int(exec_params.limit_slip_ticks)
        elif regime.daily_dir == Direction.DOWN:
            if box_l is None:
                return self._reject(setup_kind="BOX_BREAKOUT", rule="missing_box_l")
            side = Side.SELL
            entry_stop_ticks = int(box_l.price_ticks) - int(exec_params.buffer_ticks)
            limit_ticks = entry_stop_ticks - int(exec_params.limit_slip_ticks)
        else:
            return self._reject(setup_kind="BOX_BREAKOUT", rule="daily_dir_neutral")

        sl_ticks, stop_model = self._choose_stop_ticks(
            side=side,
            entry_ticks=entry_stop_ticks,
            regime=regime,
            exec_params=exec_params,
            m5=m5,
        )
        if side == Side.BUY and int(sl_ticks) >= int(entry_stop_ticks):
            sl_ticks = self._volatility_stop_ticks(
                side=side,
                entry_ticks=entry_stop_ticks,
                regime=regime,
                exec_params=exec_params,
            )
            stop_model = "volatility_fallback"
        if side == Side.SELL and int(sl_ticks) <= int(entry_stop_ticks):
            sl_ticks = self._volatility_stop_ticks(
                side=side,
                entry_ticks=entry_stop_ticks,
                regime=regime,
                exec_params=exec_params,
            )
            stop_model = "volatility_fallback"
        risk_ticks = abs(int(entry_stop_ticks) - int(sl_ticks))
        if risk_ticks <= 0:
            return self._reject(
                setup_kind="BOX_BREAKOUT",
                rule="non_positive_risk_ticks",
                risk_ticks=int(risk_ticks),
            )
        max_risk_atr_mult = float(self.cfg.get("max_risk_atr_mult", 1.2))
        if regime.h1_atr_ticks > 0:
            max_risk = max(round_half_away_from_zero(max_risk_atr_mult * float(regime.h1_atr_ticks)), 1)
            if risk_ticks > max_risk:
                return self._reject(
                    setup_kind="BOX_BREAKOUT",
                    rule="risk_above_max_atr_mult",
                    risk_ticks=int(risk_ticks),
                    max_risk_ticks=int(max_risk),
                )

        min_target_ticks = int(self.cfg.get("min_target_ticks", 3))
        tp_ticks = self.execution_engine.choose_tp_from_levels(
            side=side,
            entry_ticks=entry_stop_ticks,
            candidate_levels=levels_d1,
            min_target_ticks=min_target_ticks,
        )
        if tp_ticks is None:
            rr_default = float(self.cfg.get("rr_default", 1.6))
            delta = max(round_half_away_from_zero(rr_default * float(risk_ticks)), min_target_ticks)
            tp_ticks = entry_stop_ticks + delta if side == Side.BUY else entry_stop_ticks - delta
        target_return_pct = _potential_return_pct(entry_stop_ticks, tp_ticks)
        if float(target_return_pct) < float(self._min_target_return_pct()):
            return self._reject(
                setup_kind="BOX_BREAKOUT",
                rule="target_return_pct_below_min",
                target_return_pct=float(target_return_pct),
                min_target_return_pct=float(self._min_target_return_pct()),
            )

        cost_gate = self._cost_gate_metrics(
            reward_gross_ticks=abs(int(tp_ticks) - int(entry_stop_ticks)),
            risk_gross_ticks=int(risk_ticks),
        )
        if self._cost_gate_enabled() and not bool(cost_gate.get("pass")):
            return self._reject(
                setup_kind="BOX_BREAKOUT",
                rule="cost_gate_blocked",
                reward_net_ticks=float(cost_gate.get("reward_net_ticks", 0.0)),
                min_reward_net_ticks=float(cost_gate.get("min_reward_net_ticks", 0.0)),
                rr_net=float(cost_gate.get("rr_net", 0.0)),
                min_rr_net=float(cost_gate.get("min_rr_net", 0.0)),
            )

        expiry_policy = str(self.cfg.get("entry_expiry_policy", "EOD_BEFORE_EVENING_CLEARING"))
        expiry_ts = calendar.recommended_entry_expiry(as_of_ts, expiry_policy)
        ttl_minutes = self._entry_ttl_minutes()
        if ttl_minutes > 0:
            expiry_ts = min(expiry_ts, as_of_ts + timedelta(minutes=ttl_minutes))
        entry_range_low, entry_range_high = self._entry_range_ticks(
            entry_ticks=entry_stop_ticks,
            order_type=OrderType.STOP_LIMIT,
            side=side,
            limit_ticks=limit_ticks,
        )
        setup_id = f"{instrument_id}:BOX_BREAKOUT:{side.value}:{entry_stop_ticks}"
        entry_level = box_h if side == Side.BUY else box_l
        if entry_level is None:
            return self._reject(setup_kind="BOX_BREAKOUT", rule="entry_level_missing")
        return Setup(
            setup_id=setup_id,
            side=side,
            entry_level=entry_level,
            entry_order=OrderIntent(
                order_type=OrderType.STOP_LIMIT,
                side=side,
                price_ticks=entry_stop_ticks,
                qty_lots=max(int(self.cfg.get("qty_lots", 1)), 1),
                tif=str(self.cfg.get("entry_tif", "GTT")),
                price_range_low_ticks=int(entry_range_low),
                price_range_high_ticks=int(entry_range_high),
                activate_from_ts=None,
                expire_ts=expiry_ts,
                link_group=setup_id,
                meta={
                    "limit_price_ticks": int(limit_ticks),
                    "setup_kind": "BOX_BREAKOUT",
                    "cost_gate": cost_gate,
                    "target_return_pct": float(target_return_pct),
                    "stop_model": str(stop_model),
                    "entry_range_low_ticks": int(entry_range_low),
                    "entry_range_high_ticks": int(entry_range_high),
                    "stop_limit_fallback_to_market_min": int(self._stop_limit_fallback_to_market_min()),
                    "stop_limit_fallback_slip_ticks": int(self._stop_limit_fallback_slip_ticks()),
                    "time_stop_minutes": int(self._time_stop_minutes()),
                },
            ),
            sl_order=OrderIntent(
                order_type=OrderType.STOP,
                side=Side.SELL if side == Side.BUY else Side.BUY,
                price_ticks=int(sl_ticks),
                qty_lots=max(int(self.cfg.get("qty_lots", 1)), 1),
                tif="GTC",
                activate_from_ts=None,
                expire_ts=None,
                link_group=setup_id,
                meta={"setup_kind": "BOX_BREAKOUT", "stop_model": str(stop_model)},
            ),
            tp_order=OrderIntent(
                order_type=OrderType.LIMIT,
                side=Side.SELL if side == Side.BUY else Side.BUY,
                price_ticks=int(tp_ticks),
                qty_lots=max(int(self.cfg.get("qty_lots", 1)), 1),
                tif="GTC",
                activate_from_ts=None,
                expire_ts=None,
                link_group=setup_id,
                meta={"setup_kind": "BOX_BREAKOUT"},
            ),
            horizon=str(self.cfg.get("horizon", "EOD")),
            rationale=[
                "trend_first",
                "h1_box_breakout",
                f"daily_dir_{regime.daily_dir.value.lower()}",
            ],
            risk_ticks=int(risk_ticks),
        )

    def _generate_pullback_limit(
        self,
        *,
        as_of_ts: datetime,
        instrument_id: str,
        last_price_ticks: int,
        regime: RegimeState,
        levels_d1: list[Level],
        exec_params: ExecutionParams,
        calendar: MarketCalendar,
        m5: list[Candle],
    ) -> Setup | None:
        side = Side.BUY if regime.daily_dir == Direction.UP else Side.SELL
        pullback_levels = [level for level in levels_d1 if level.kind in {"PIVOT_PP", "PDC"}]
        if side == Side.BUY:
            pullback_levels = [level for level in pullback_levels if int(level.price_ticks) <= int(last_price_ticks)]
        else:
            pullback_levels = [level for level in pullback_levels if int(level.price_ticks) >= int(last_price_ticks)]
        if not pullback_levels:
            return self._reject(
                setup_kind="PULLBACK_LIMIT",
                rule="missing_pullback_levels",
                candidate_levels=int(len(levels_d1)),
            )
        selected = sorted(pullback_levels, key=lambda level: abs(int(level.price_ticks) - int(last_price_ticks)))[0]

        max_dist_mult = float(self.cfg.get("pullback_max_dist_atr_mult", 1.0))
        max_dist_ticks = max(round_half_away_from_zero(max_dist_mult * float(max(regime.h1_atr_ticks, 1))), 1)
        if abs(int(last_price_ticks) - int(selected.price_ticks)) > max_dist_ticks:
            return self._reject(
                setup_kind="PULLBACK_LIMIT",
                rule="entry_level_too_far_from_last_price",
                distance_ticks=int(abs(int(last_price_ticks) - int(selected.price_ticks))),
                max_dist_ticks=int(max_dist_ticks),
            )

        zone_offset = int(self.cfg.get("entry_zone_offset_ticks", 0))
        entry_ticks = int(selected.price_ticks + zone_offset) if side == Side.BUY else int(selected.price_ticks - zone_offset)
        sl_ticks, stop_model = self._choose_stop_ticks(
            side=side,
            entry_ticks=entry_ticks,
            regime=regime,
            exec_params=exec_params,
            m5=m5,
        )
        if side == Side.BUY and int(sl_ticks) >= int(entry_ticks):
            sl_ticks = self._volatility_stop_ticks(
                side=side,
                entry_ticks=entry_ticks,
                regime=regime,
                exec_params=exec_params,
            )
            stop_model = "volatility_fallback"
        if side == Side.SELL and int(sl_ticks) <= int(entry_ticks):
            sl_ticks = self._volatility_stop_ticks(
                side=side,
                entry_ticks=entry_ticks,
                regime=regime,
                exec_params=exec_params,
            )
            stop_model = "volatility_fallback"

        risk_ticks = abs(int(entry_ticks) - int(sl_ticks))
        if risk_ticks <= 0:
            return self._reject(
                setup_kind="PULLBACK_LIMIT",
                rule="non_positive_risk_ticks",
                risk_ticks=int(risk_ticks),
            )
        min_target_ticks = int(self.cfg.get("min_target_ticks", 3))
        tp_ticks = self.execution_engine.choose_tp_from_levels(
            side=side,
            entry_ticks=entry_ticks,
            candidate_levels=levels_d1,
            min_target_ticks=min_target_ticks,
        )
        if tp_ticks is None:
            rr_default = float(self.cfg.get("rr_default", 1.6))
            delta = max(round_half_away_from_zero(rr_default * float(risk_ticks)), min_target_ticks)
            tp_ticks = entry_ticks + delta if side == Side.BUY else entry_ticks - delta
        target_return_pct = _potential_return_pct(entry_ticks, tp_ticks)
        if float(target_return_pct) < float(self._min_target_return_pct()):
            return self._reject(
                setup_kind="PULLBACK_LIMIT",
                rule="target_return_pct_below_min",
                target_return_pct=float(target_return_pct),
                min_target_return_pct=float(self._min_target_return_pct()),
            )

        cost_gate = self._cost_gate_metrics(
            reward_gross_ticks=abs(int(tp_ticks) - int(entry_ticks)),
            risk_gross_ticks=int(risk_ticks),
        )
        if self._cost_gate_enabled() and not bool(cost_gate.get("pass")):
            return self._reject(
                setup_kind="PULLBACK_LIMIT",
                rule="cost_gate_blocked",
                reward_net_ticks=float(cost_gate.get("reward_net_ticks", 0.0)),
                min_reward_net_ticks=float(cost_gate.get("min_reward_net_ticks", 0.0)),
                rr_net=float(cost_gate.get("rr_net", 0.0)),
                min_rr_net=float(cost_gate.get("min_rr_net", 0.0)),
            )

        expiry_policy = str(self.cfg.get("entry_expiry_policy", "EOD_BEFORE_EVENING_CLEARING"))
        expiry_ts = calendar.recommended_entry_expiry(as_of_ts, expiry_policy)
        ttl_minutes = self._entry_ttl_minutes()
        if ttl_minutes > 0:
            expiry_ts = min(expiry_ts, as_of_ts + timedelta(minutes=ttl_minutes))
        entry_range_low, entry_range_high = self._entry_range_ticks(
            entry_ticks=entry_ticks,
            order_type=OrderType.LIMIT,
            side=side,
        )
        setup_id = f"{instrument_id}:PULLBACK_LIMIT:{side.value}:{entry_ticks}"
        return Setup(
            setup_id=setup_id,
            side=side,
            entry_level=selected,
            entry_order=OrderIntent(
                order_type=OrderType.LIMIT,
                side=side,
                price_ticks=int(entry_ticks),
                qty_lots=max(int(self.cfg.get("qty_lots", 1)), 1),
                tif=str(self.cfg.get("entry_tif", "GTT")),
                price_range_low_ticks=int(entry_range_low),
                price_range_high_ticks=int(entry_range_high),
                activate_from_ts=None,
                expire_ts=expiry_ts,
                link_group=setup_id,
                meta={
                    "setup_kind": "PULLBACK_LIMIT",
                    "cost_gate": cost_gate,
                    "target_return_pct": float(target_return_pct),
                    "stop_model": str(stop_model),
                    "entry_range_low_ticks": int(entry_range_low),
                    "entry_range_high_ticks": int(entry_range_high),
                    "time_stop_minutes": int(self._time_stop_minutes()),
                },
            ),
            sl_order=OrderIntent(
                order_type=OrderType.STOP,
                side=Side.SELL if side == Side.BUY else Side.BUY,
                price_ticks=int(sl_ticks),
                qty_lots=max(int(self.cfg.get("qty_lots", 1)), 1),
                tif="GTC",
                activate_from_ts=None,
                expire_ts=None,
                link_group=setup_id,
                meta={"setup_kind": "PULLBACK_LIMIT", "stop_model": str(stop_model)},
            ),
            tp_order=OrderIntent(
                order_type=OrderType.LIMIT,
                side=Side.SELL if side == Side.BUY else Side.BUY,
                price_ticks=int(tp_ticks),
                qty_lots=max(int(self.cfg.get("qty_lots", 1)), 1),
                tif="GTC",
                activate_from_ts=None,
                expire_ts=None,
                link_group=setup_id,
                meta={"setup_kind": "PULLBACK_LIMIT"},
            ),
            horizon=str(self.cfg.get("horizon", "EOD")),
            rationale=[
                "trend_first",
                "d1_pullback_level",
                f"daily_dir_{regime.daily_dir.value.lower()}",
            ],
            risk_ticks=int(risk_ticks),
        )

def _find_level(levels: list[Level], kind: str) -> Level | None:
    for level in levels:
        if str(level.kind) == str(kind):
            return level
    return None


def _safe_non_negative_float(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    if parsed < 0.0:
        return 0.0
    return float(parsed)


def _normalize_setup_kind_tokens(raw: object) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, str):
        tokens = [raw]
    elif isinstance(raw, (list, tuple, set)):
        tokens = [str(item) for item in raw]
    else:
        return set()
    normalized: set[str] = set()
    for token in tokens:
        value = str(token).strip().upper()
        if value:
            normalized.add(value)
    return normalized


def _potential_return_pct(entry_ticks: int, tp_ticks: int) -> float:
    base = max(abs(int(entry_ticks)), 1)
    distance = abs(int(tp_ticks) - int(entry_ticks))
    return float(100.0 * distance / base)


def _trace_scalar(value: object) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
