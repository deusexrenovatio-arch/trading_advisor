from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pandas as pd

from moex_carry.config import AppSettings, CostsConfig, SpreadCarryAlphaConfig
from moex_carry.domain.models import ContractSpec
from moex_carry.domain.portfolio import PairSpec
from moex_carry.pipeline import _apply_spread_carry_signals
from moex_carry.signal_replay.core import run_minute_replay


def _load_sweep_module():
    path = Path("scripts/intraday_minute_sweep.py")
    spec = importlib.util.spec_from_file_location("intraday_minute_sweep", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable_to_load_intraday_minute_sweep")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def _settings(cutoff_minutes: int = 0) -> AppSettings:
    return AppSettings(
        costs=CostsConfig(
            stock_commission_bps=0.0,
            futures_commission_bps=0.0,
            exchange_fee_bps=0.0,
            slippage_bps=0.0,
        ),
        spread_carry_alpha=SpreadCarryAlphaConfig(
            r_cb_annual=0.0,
            r_fund_annual=0.0,
            r_disc_annual=0.0,
            min_DTE_entry=1,
            close_buffer_days=0,
            H_max_days=20,
            TP_pct=0.01,
            SL_pct=0.01,
            entry_price_tolerance_pct=0.02,
            fee_stock_bps=0.0,
            fee_fut_per_contract=0.0,
            slip_stock_bps=0.0,
            slip_fut_bps=0.0,
            signal_exec_lag_days=0,
            execution_lag_minutes=20,
            execution_max_wait_minutes=360,
            annual_target_threshold=0.0,
            signal_cutoff_before_day_end_minutes=cutoff_minutes,
        ),
    )


def _load_manifest() -> pd.DataFrame:
    path = Path("tests/fixtures/minute_replay/manifest.csv")
    frame = pd.read_csv(path)
    assert len(frame) >= 5, "expected at least 5 golden fixtures"
    return frame


def _future_spec_from_row(row: pd.Series) -> ContractSpec:
    return ContractSpec(
        secid=str(row["future"]),
        asset_code=str(row["stock"]),
        expiry=pd.to_datetime(row["expiry"]).date(),
        lot_size=1.0,
        price_step=0.01,
        multiplier=1.0,
    )


def _pair_from_row(row: pd.Series) -> PairSpec:
    return PairSpec(
        stock_secid=str(row["stock"]),
        future_secid=str(row["future"]),
        expiry=pd.to_datetime(row["expiry"]).date(),
        lot_size=1.0,
        tick_size=0.01,
        multiplier=1.0,
    )


def _metric_or_none(value):
    if value is None:
        return None
    numeric = float(value)
    return None if pd.isna(numeric) else numeric


def test_golden_parity_event_track_and_metrics_for_5_pairs():
    sweep = _load_sweep_module()
    manifest = _load_manifest().head(5)
    settings = _settings(cutoff_minutes=0)

    for _, row in manifest.iterrows():
        fixture = Path(row["fixture"])
        base = pd.read_csv(fixture)
        base["date"] = pd.to_datetime(base["date"]).dt.date
        base["exec_ts"] = pd.to_datetime(base["exec_ts"])
        future_spec = _future_spec_from_row(row)
        pair = _pair_from_row(row)

        replay_result = run_minute_replay(
            series_base=base,
            pair=pair,
            settings=settings,
            dividends=[],
            key_rates=[],
        )

        baseline_series = sweep._apply_day_cutoff(base, 0)
        baseline_replay = _apply_spread_carry_signals(
            baseline_series,
            merged=None,
            dividends=[],
            key_rates=[],
            settings=settings,
            future_spec=future_spec,
            alpha_cfg=settings.spread_carry_alpha,
        )
        sweep_metrics = sweep._run_scenario_on_pair(
            base_series=base,
            cutoff_minutes=0,
            settings=settings,
            future_spec=future_spec,
            dividends=[],
            key_rates=[],
        )

        event_cols = [
            "signal_action",
            "entry_fill_status",
            "exit_fill_status",
            "entry_fill_ts",
            "exit_fill_ts",
            "entry_wait_minutes",
            "exit_wait_minutes",
            "exit_forced",
            "unfilled_reason",
        ]
        for col in event_cols:
            left = replay_result.replay[col].reset_index(drop=True).astype(str)
            right = baseline_replay[col].reset_index(drop=True).astype(str)
            assert left.equals(right), f"event_track_mismatch:{row['stock']}-{row['future']}:{col}"

        metrics = replay_result.metrics.to_dict()
        compare_keys = [
            "unfilled_entry_rate",
            "unfilled_exit_rate",
            "forced_exit_rate",
            "avg_trade_return_annual_fill_to_fill_last5",
            "avg_trade_return_annual_operational_last5",
            "trades_closed",
        ]
        for key in compare_keys:
            got = _metric_or_none(metrics.get(key))
            exp = _metric_or_none(sweep_metrics.get(key))
            if got is None or exp is None:
                assert got == exp, f"metric_mismatch_none:{row['stock']}-{row['future']}:{key}"
            else:
                assert abs(got - exp) < 1e-12, f"metric_mismatch:{row['stock']}-{row['future']}:{key}"
