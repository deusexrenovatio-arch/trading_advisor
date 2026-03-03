from __future__ import annotations

from datetime import datetime

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


class SetupGenerator:
    def __init__(self, cfg: dict, execution_engine: ExecutionEngine | None = None):
        self.cfg = cfg or {}
        self.execution_engine = execution_engine or ExecutionEngine({})

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
        if regime.daily_trend_state != TrendState.TREND:
            return []
        if regime.daily_dir == Direction.NEUTRAL:
            return []
        if not regime.h1_alignment:
            return []
        if regime.liquidity_state == LiquidityState.VACUUM:
            return []
        if calendar.forbid_new_position(as_of_ts):
            return []
        if self._eligibility_filter_enabled():
            cost_ticks = self._estimated_round_trip_cost_ticks()
            min_h1_mult = _safe_non_negative_float(self.cfg.get("min_atr_h1_cost_mult"), 6.0)
            min_d1_mult = _safe_non_negative_float(self.cfg.get("min_atr_d1_cost_mult"), 12.0)
            min_h1_ticks = max(round_half_away_from_zero(min_h1_mult * cost_ticks), 1)
            min_d1_ticks = max(round_half_away_from_zero(min_d1_mult * cost_ticks), 1)
            if int(regime.h1_atr_ticks) < int(min_h1_ticks):
                return []
            if int(regime.daily_atr_ticks) < int(min_d1_ticks):
                return []

        setups: list[Setup] = []
        s1 = self._generate_box_breakout(
            as_of_ts=as_of_ts,
            instrument_id=instrument_id,
            regime=regime,
            levels_d1=levels_d1,
            levels_h1=levels_h1,
            exec_params=exec_params,
            calendar=calendar,
            m5=m5 or [],
        )
        if s1 is not None:
            setups.append(s1)
        s2 = self._generate_pullback_limit(
            as_of_ts=as_of_ts,
            instrument_id=instrument_id,
            last_price_ticks=int(last_price_ticks),
            regime=regime,
            levels_d1=levels_d1,
            exec_params=exec_params,
            calendar=calendar,
            m5=m5 or [],
        )
        if s2 is not None:
            setups.append(s2)

        max_setups = max(int(self.cfg.get("max_setups_per_instrument", 2)), 0)
        if max_setups <= 0:
            return []
        ranked = sorted(
            setups,
            key=lambda item: (int(item.risk_ticks), abs(item.tp_order.price_ticks - item.entry_order.price_ticks)),
        )
        return ranked[:max_setups]

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
            return None

        box_h = _find_level(levels_h1, "BOX_H")
        box_l = _find_level(levels_h1, "BOX_L")
        if regime.daily_dir == Direction.UP:
            if box_h is None:
                return None
            side = Side.BUY
            entry_stop_ticks = int(box_h.price_ticks) + int(exec_params.buffer_ticks)
            limit_ticks = entry_stop_ticks + int(exec_params.limit_slip_ticks)
        elif regime.daily_dir == Direction.DOWN:
            if box_l is None:
                return None
            side = Side.SELL
            entry_stop_ticks = int(box_l.price_ticks) - int(exec_params.buffer_ticks)
            limit_ticks = entry_stop_ticks - int(exec_params.limit_slip_ticks)
        else:
            return None

        sl_ticks = self.execution_engine.choose_stop_from_m5_structure(
            m5=m5,
            side=side,
            entry_ticks=entry_stop_ticks,
            buffer_ticks=int(exec_params.buffer_ticks),
        )
        risk_ticks = abs(int(entry_stop_ticks) - int(sl_ticks))
        if risk_ticks <= 0:
            return None
        max_risk_atr_mult = float(self.cfg.get("max_risk_atr_mult", 1.2))
        if regime.h1_atr_ticks > 0:
            max_risk = max(round_half_away_from_zero(max_risk_atr_mult * float(regime.h1_atr_ticks)), 1)
            if risk_ticks > max_risk:
                return None

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
            return None

        cost_gate = self._cost_gate_metrics(
            reward_gross_ticks=abs(int(tp_ticks) - int(entry_stop_ticks)),
            risk_gross_ticks=int(risk_ticks),
        )
        if self._cost_gate_enabled() and not bool(cost_gate.get("pass")):
            return None

        expiry_policy = str(self.cfg.get("entry_expiry_policy", "EOD_BEFORE_EVENING_CLEARING"))
        expiry_ts = calendar.recommended_entry_expiry(as_of_ts, expiry_policy)
        setup_id = f"{instrument_id}:BOX_BREAKOUT:{side.value}:{entry_stop_ticks}"
        entry_level = box_h if side == Side.BUY else box_l
        if entry_level is None:
            return None
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
                activate_from_ts=None,
                expire_ts=expiry_ts,
                link_group=setup_id,
                meta={
                    "limit_price_ticks": int(limit_ticks),
                    "setup_kind": "BOX_BREAKOUT",
                    "cost_gate": cost_gate,
                    "target_return_pct": float(target_return_pct),
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
                meta={"setup_kind": "BOX_BREAKOUT"},
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
            return None
        selected = sorted(pullback_levels, key=lambda level: abs(int(level.price_ticks) - int(last_price_ticks)))[0]

        max_dist_mult = float(self.cfg.get("pullback_max_dist_atr_mult", 1.0))
        max_dist_ticks = max(round_half_away_from_zero(max_dist_mult * float(max(regime.h1_atr_ticks, 1))), 1)
        if abs(int(last_price_ticks) - int(selected.price_ticks)) > max_dist_ticks:
            return None

        zone_offset = int(self.cfg.get("entry_zone_offset_ticks", 0))
        entry_ticks = int(selected.price_ticks + zone_offset) if side == Side.BUY else int(selected.price_ticks - zone_offset)
        sl_ticks = self.execution_engine.choose_stop_from_m5_structure(
            m5=m5,
            side=side,
            entry_ticks=entry_ticks,
            buffer_ticks=max(int(exec_params.buffer_ticks), 1),
        )
        if abs(int(entry_ticks) - int(sl_ticks)) <= 0:
            sl_mult = float(self.cfg.get("sl_atr_mult", 0.8))
            fallback_delta = max(round_half_away_from_zero(sl_mult * float(max(regime.h1_atr_ticks, 1))), 1)
            sl_ticks = entry_ticks - fallback_delta if side == Side.BUY else entry_ticks + fallback_delta

        risk_ticks = abs(int(entry_ticks) - int(sl_ticks))
        if risk_ticks <= 0:
            return None
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
            return None

        cost_gate = self._cost_gate_metrics(
            reward_gross_ticks=abs(int(tp_ticks) - int(entry_ticks)),
            risk_gross_ticks=int(risk_ticks),
        )
        if self._cost_gate_enabled() and not bool(cost_gate.get("pass")):
            return None

        expiry_policy = str(self.cfg.get("entry_expiry_policy", "EOD_BEFORE_EVENING_CLEARING"))
        expiry_ts = calendar.recommended_entry_expiry(as_of_ts, expiry_policy)
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
                activate_from_ts=None,
                expire_ts=expiry_ts,
                link_group=setup_id,
                meta={
                    "setup_kind": "PULLBACK_LIMIT",
                    "cost_gate": cost_gate,
                    "target_return_pct": float(target_return_pct),
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
                meta={"setup_kind": "PULLBACK_LIMIT"},
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


def _potential_return_pct(entry_ticks: int, tp_ticks: int) -> float:
    base = max(abs(int(entry_ticks)), 1)
    distance = abs(int(tp_ticks) - int(entry_ticks))
    return float(100.0 * distance / base)
