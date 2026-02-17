from datetime import date, datetime

import pandas as pd

from moex_carry.config import AppSettings, CostsConfig, SpreadCarryAlphaConfig
from moex_carry.domain.models import ContractSpec
from moex_carry.domain.portfolio import PairSpec
from moex_carry.signal_replay.minute_replay import _apply_spread_carry_signals
from moex_carry.signal_replay.core import apply_day_cutoff, run_minute_replay


def _pair() -> PairSpec:
    return PairSpec(
        stock_secid="AAA",
        future_secid="AAH6",
        expiry=date(2026, 3, 19),
        lot_size=1.0,
        multiplier=1.0,
        tick_size=0.01,
    )


def _settings(alpha_overrides: dict | None = None) -> AppSettings:
    overrides = {
        "r_cb_annual": 0.0,
        "r_fund_annual": 0.0,
        "r_disc_annual": 0.0,
        "min_DTE_entry": 1,
        "close_buffer_days": 0,
        "H_max_days": 20,
        "TP_pct": 0.5,
        "SL_pct": 0.005,
        "entry_price_tolerance_pct": 0.001,
        "fee_stock_bps": 0.0,
        "fee_fut_per_contract": 0.0,
        "slip_stock_bps": 0.0,
        "slip_fut_bps": 0.0,
        "signal_exec_lag_days": 0,
        "execution_lag_minutes": 30,
        "execution_max_wait_minutes": 120,
        "annual_target_threshold": 0.0,
    }
    if alpha_overrides:
        overrides.update(alpha_overrides)
    return AppSettings(
        costs=CostsConfig(
            stock_commission_bps=0.0,
            futures_commission_bps=0.0,
            exchange_fee_bps=0.0,
            slippage_bps=0.0,
        ),
        spread_carry_alpha=SpreadCarryAlphaConfig(**overrides),
    )


def _series(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    data = []
    for ts_raw, spot_mid, future_mid in rows:
        spread_mid = spot_mid - future_mid
        data.append(
            {
                "date": datetime.fromisoformat(ts_raw).date(),
                "exec_ts": ts_raw,
                "spot_mid": spot_mid,
                "future_mid": future_mid,
                "pv_div": 0.0,
                "div_sum": 0.0,
                "spread_mid": spread_mid,
                "spread_pct": spread_mid / spot_mid if spot_mid else 0.0,
                "spot_volume": 1000.0,
                "future_volume": 1000.0,
            }
        )
    return pd.DataFrame(data)


def test_apply_day_cutoff_filters_last_minutes():
    base = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-01 10:30:00", 100.0, 101.0),
            ("2026-01-01 10:59:00", 100.0, 101.0),
        ]
    )
    filtered = apply_day_cutoff(base, 20)
    assert len(filtered) == 2
    assert filtered["exec_ts"].max().strftime("%H:%M:%S") == "10:30:00"


def test_split_tolerance_overrides_fallback():
    base = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-01 10:30:00", 101.5, 102.5),
            ("2026-01-01 11:00:00", 101.5, 102.5),
        ]
    )
    strict = run_minute_replay(
        series_base=base,
        pair=_pair(),
        settings=_settings({"entry_price_tolerance_pct": 0.001}),
        dividends=[],
        key_rates=[],
    )
    assert strict.metrics.unfilled_entry_rate == 1.0

    split = run_minute_replay(
        series_base=base,
        pair=_pair(),
        settings=_settings(
            {
                "entry_price_tolerance_pct": 0.001,
                "entry_stock_tolerance_pct": 0.02,
                "entry_future_tolerance_pct": 0.02,
                "entry_spread_tolerance_pct": 0.02,
            }
        ),
        dividends=[],
        key_rates=[],
    )
    assert split.metrics.unfilled_entry_rate == 0.0


def test_replay_is_sign_sensitive_for_negative_move():
    base = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-01 10:30:00", 100.0, 101.0),
            ("2026-01-01 11:00:00", 95.0, 104.0),
            ("2026-01-01 11:30:00", 95.0, 104.0),
        ]
    )
    result = run_minute_replay(
        series_base=base,
        pair=_pair(),
        settings=_settings({"TP_pct": 1.0, "SL_pct": 0.001}),
        dividends=[],
        key_rates=[],
    )
    assert "exit_flag" in result.replay.columns
    exits = result.replay[result.replay["exit_flag"].fillna(False).astype(bool)]
    assert not exits.empty
    assert float(exits.iloc[-1]["trade_pnl_cash"]) < 0.0


def test_replay_parity_with_pipeline_execution_track():
    base = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-01 10:30:00", 100.0, 101.0),
            ("2026-01-01 11:00:00", 99.0, 100.0),
            ("2026-01-01 11:30:00", 99.0, 100.0),
        ]
    )
    settings = _settings({"TP_pct": 0.001, "SL_pct": 0.001})
    replay = run_minute_replay(
        series_base=base,
        pair=_pair(),
        settings=settings,
        dividends=[],
        key_rates=[],
    ).replay
    pair = _pair()
    expected = _apply_spread_carry_signals(
        base,
        merged=None,
        dividends=[],
        key_rates=[],
        settings=settings,
        future_spec=ContractSpec(
            secid=pair.future_secid,
            asset_code=pair.stock_secid,
            expiry=pair.expiry or date(2026, 3, 19),
            lot_size=float(pair.lot_size or 1.0),
            price_step=float(pair.tick_size or 0.01),
            multiplier=float(pair.multiplier or 1.0),
        ),
        alpha_cfg=settings.spread_carry_alpha,
    )
    assert replay["entry_fill_status"].tolist() == expected["entry_fill_status"].tolist()
    assert replay["exit_fill_status"].tolist() == expected["exit_fill_status"].tolist()
