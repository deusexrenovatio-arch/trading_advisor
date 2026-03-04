from __future__ import annotations

from datetime import datetime

from moex_carry.signal_engine.core.calendar import MarketCalendar
from moex_carry.signal_engine.core.math_utils import price_to_ticks
from moex_carry.signal_engine.core.types import MorningPlan, TF
from moex_carry.signal_engine.data.candles import DataProvider
from moex_carry.signal_engine.execution.engine import ExecutionEngine
from moex_carry.signal_engine.levels.engine import LevelEngine
from moex_carry.signal_engine.news.gate import CommodityNewsGate
from moex_carry.signal_engine.regime.engine import RegimeEngine
from moex_carry.signal_engine.setups.generator import SetupGenerator


class MorningPlanBuilder:
    def __init__(self, data_provider: DataProvider, calendar: MarketCalendar, cfg: dict):
        self.dp = data_provider
        self.calendar = calendar
        self.cfg = cfg or {}
        self.regime_engine = RegimeEngine(self.cfg.get("regime", {}))
        self.level_engine = LevelEngine(self.cfg.get("levels", {}))
        self.exec_engine = ExecutionEngine(self.cfg.get("execution", {}))
        self.setup_gen = SetupGenerator(self.cfg.get("setups", {}), execution_engine=self.exec_engine)
        self.news_gate = CommodityNewsGate(self.cfg.get("news_gate", {}))

    def build_plan(self, as_of_ts: datetime, instrument_id: str, tick_size: float) -> MorningPlan:
        data_cfg = self.cfg.get("data", {})
        d1_limit = int(data_cfg.get("d1_limit", 200))
        h1_limit = int(data_cfg.get("h1_limit", 300))
        m5_limit = int(data_cfg.get("m5_limit", 300))

        d1 = self.dp.get_candles(instrument_id, TF.D1, as_of_ts, d1_limit)
        h1 = self.dp.get_candles(instrument_id, TF.H1, as_of_ts, h1_limit)
        m5 = self.dp.get_candles(instrument_id, TF.M5, as_of_ts, m5_limit)

        regime = self.regime_engine.compute(
            as_of_ts=as_of_ts,
            d1=d1,
            h1=h1,
            m5=m5,
            tick_size=tick_size,
            orderbook=None,
            calendar=self.calendar,
        )

        d1_levels = self.level_engine.compute_d1_levels(d1, tick_size=tick_size)
        h1_levels = self.level_engine.compute_h1_levels(h1, calendar=self.calendar, tick_size=tick_size)
        levels = self.level_engine.merge_and_rank(d1_levels + h1_levels)

        exec_params = self.exec_engine.compute_params(m5, tick_size=tick_size)
        if m5:
            last_price_ticks = price_to_ticks(float(m5[-1].close), tick_size)
        elif h1:
            last_price_ticks = price_to_ticks(float(h1[-1].close), tick_size)
        elif d1:
            last_price_ticks = price_to_ticks(float(d1[-1].close), tick_size)
        elif levels:
            last_price_ticks = int(levels[0].price_ticks)
        else:
            last_price_ticks = 0
        setups = self.setup_gen.generate(
            as_of_ts=as_of_ts,
            instrument_id=instrument_id,
            last_price_ticks=last_price_ticks,
            regime=regime,
            levels_d1=d1_levels,
            levels_h1=h1_levels,
            exec_params=exec_params,
            calendar=self.calendar,
            m5=m5,
        )

        gate_decision = self.news_gate.evaluate(as_of_ts=as_of_ts, instrument_id=instrument_id)
        news_warnings: list[str] = []
        if gate_decision.action == "block":
            setups = []
            news_warnings.append(
                "news_gate:block:"
                f"commodity={gate_decision.commodity or 'UNKNOWN'}:"
                f"severity={gate_decision.highest_severity}:"
                f"matched={len(gate_decision.matched_items)}"
            )
        elif gate_decision.action == "reduce" and setups:
            original_count = len(setups)
            setups = setups[: self.news_gate.reduce_max_setups]
            if len(setups) < original_count:
                news_warnings.append(
                    "news_gate:reduce:"
                    f"commodity={gate_decision.commodity or 'UNKNOWN'}:"
                    f"severity={gate_decision.highest_severity}:"
                    f"kept={len(setups)}:"
                    f"dropped={original_count - len(setups)}"
                )
        if self.news_gate.enabled and gate_decision.reasons:
            news_warnings.extend([f"news_gate:{reason}" for reason in gate_decision.reasons])

        warnings = sorted(set(list(regime.warnings) + list(exec_params.warnings) + news_warnings))
        return MorningPlan(
            as_of_ts=as_of_ts,
            instrument_id=instrument_id,
            regime=regime,
            levels=levels,
            exec_params=exec_params,
            setups=setups,
            warnings=warnings,
        )
