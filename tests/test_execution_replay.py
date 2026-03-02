from datetime import date, datetime

import pandas as pd

from moex_carry.config import AppSettings, CostsConfig, SpreadCarryAlphaConfig
from moex_carry.domain.models import ContractSpec, KeyRate
from moex_carry.pipeline import _apply_spread_carry_signals


def _base_settings(alpha_overrides: dict | None = None) -> AppSettings:
    overrides = {
        "r_cb_annual": 0.0,
        "r_fund_annual": 0.0,
        "r_disc_annual": 0.0,
        "min_DTE_entry": 1,
        "close_buffer_days": 0,
        "H_max_days": 20,
        "TP_pct": 0.0,
        "SL_pct": 0.01,
        "entry_price_tolerance_pct": 0.01,
        "fee_stock_bps": 0.0,
        "fee_fut_per_contract": 0.0,
        "slip_stock_bps": 0.0,
        "slip_fut_bps": 0.0,
        "signal_exec_lag_days": 1,
        "execution_lag_minutes": 0,
        "execution_max_wait_minutes": 1440,
        "force_exit_policy": "next_anchor",
        "force_exit_penalty_bps": 0.0,
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


def _future_spec() -> ContractSpec:
    return ContractSpec(
        secid="AAH6",
        asset_code="AAA",
        expiry=date(2026, 3, 19),
        lot_size=1.0,
        price_step=0.01,
        multiplier=1.0,
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


def _rates(start_day: date) -> list[KeyRate]:
    return [KeyRate(date=start_day, rate=0.0)]


def test_replay_is_causal_d_plus_one_for_entry_and_exit():
    settings = _base_settings()
    df = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-02 10:00:00", 100.0, 101.0),
            ("2026-01-03 10:00:00", 100.0, 101.0),
        ]
    )
    result = _apply_spread_carry_signals(
        df,
        merged=None,
        dividends=[],
        key_rates=_rates(date(2026, 1, 1)),
        settings=settings,
        future_spec=_future_spec(),
        alpha_cfg=settings.spread_carry_alpha,
    )

    assert result.iloc[0]["signal_action"] == "enter"
    assert bool(result.iloc[1]["entry_flag"]) is True
    assert result.iloc[1]["entry_fill_status"] == "filled"
    assert result.iloc[1]["entry_signal_day"] == "2026-01-01"
    assert str(result.iloc[1]["entry_fill_ts"]).startswith("2026-01-02")

    exit_signal_idx = int(result.index[result["signal_action"] == "exit"][0])
    exit_fill_idx = int(result.index[result["exit_flag"] == True][0])  # noqa: E712
    assert exit_fill_idx > exit_signal_idx
    assert result.iloc[exit_fill_idx]["exit_fill_status"] in {"filled", "forced"}
    assert result.iloc[exit_fill_idx]["annual_target_threshold"] == 0.0
    assert result.iloc[exit_fill_idx]["annual_target_pass"] is True


def test_replay_supports_same_day_lag_when_signal_exec_lag_is_zero():
    settings = _base_settings(
        {
            "signal_exec_lag_days": 0,
            "execution_lag_minutes": 30,
            "execution_max_wait_minutes": 120,
            "TP_pct": 1.0,
        }
    )
    df = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-01 10:10:00", 100.0, 101.0),
            ("2026-01-01 10:30:00", 100.0, 101.0),
            ("2026-01-01 11:00:00", 100.0, 101.0),
        ]
    )
    result = _apply_spread_carry_signals(
        df,
        merged=None,
        dividends=[],
        key_rates=_rates(date(2026, 1, 1)),
        settings=settings,
        future_spec=_future_spec(),
        alpha_cfg=settings.spread_carry_alpha,
    )

    filled_row = result[result["entry_flag"] == True].iloc[0]  # noqa: E712
    assert str(filled_row["entry_submit_ts"]).startswith("2026-01-01T10:30:00")
    assert str(filled_row["entry_fill_ts"]).startswith("2026-01-01T10:30:00")
    assert filled_row["entry_signal_day"] == "2026-01-01"
    assert filled_row["entry_fill_status"] == "filled"


def test_replay_marks_entry_unfilled_when_timeout_expires():
    settings = _base_settings({"execution_max_wait_minutes": 1})
    df = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-02 10:00:00", 103.0, 104.0),
        ]
    )
    result = _apply_spread_carry_signals(
        df,
        merged=None,
        dividends=[],
        key_rates=_rates(date(2026, 1, 1)),
        settings=settings,
        future_spec=_future_spec(),
        alpha_cfg=settings.spread_carry_alpha,
    )

    assert result.iloc[0]["signal_action"] == "enter"
    assert result.iloc[0]["entry_fill_status"] == "entry_unfilled"
    assert result.iloc[0]["unfilled_reason"] in {"entry_timeout", "entry_no_fill_in_window"}
    assert not bool(result["entry_flag"].any())


def test_replay_forces_exit_after_timeout_when_policy_enabled():
    settings = _base_settings(
        {
            "execution_max_wait_minutes": 1,
            "force_exit_policy": "next_anchor",
        }
    )
    df = _series(
        [
            ("2026-01-01 00:00:00", 100.0, 101.0),
            ("2026-01-02 00:00:00", 100.0, 101.0),
            ("2026-01-03 00:10:00", 102.0, 103.0),
        ]
    )
    result = _apply_spread_carry_signals(
        df,
        merged=None,
        dividends=[],
        key_rates=_rates(date(2026, 1, 1)),
        settings=settings,
        future_spec=_future_spec(),
        alpha_cfg=settings.spread_carry_alpha,
    )

    forced_rows = result[result["exit_fill_status"] == "forced"]
    assert not forced_rows.empty
    assert bool((forced_rows["exit_forced"] == True).any())  # noqa: E712
    assert bool((forced_rows["exit_flag"] == True).any())  # noqa: E712


def test_replay_supports_sequential_entry_by_legs():
    settings = _base_settings(
        {
            "signal_exec_lag_days": 0,
            "execution_lag_minutes": 0,
            "execution_max_wait_minutes": 120,
            "sequential_entry_enabled": True,
            "sequential_entry_first_leg": "future",
            "sequential_entry_second_leg_max_wait_minutes": 30,
            "TP_pct": 1.0,
        }
    )
    df = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-01 10:05:00", 104.0, 101.0),
            ("2026-01-01 10:20:00", 100.2, 101.2),
        ]
    )
    result = _apply_spread_carry_signals(
        df,
        merged=None,
        dividends=[],
        key_rates=_rates(date(2026, 1, 1)),
        settings=settings,
        future_spec=_future_spec(),
        alpha_cfg=settings.spread_carry_alpha,
    )

    assert result.iloc[0]["signal_action"] == "enter"
    assert bool(result["entry_flag"].any()) is True
    filled_row = result[result["entry_flag"] == True].iloc[0]  # noqa: E712
    assert str(filled_row["entry_fill_ts"]).startswith("2026-01-01T10:20:00")
    assert float(filled_row["entry_wait_minutes"]) >= 20.0
    assert filled_row["entry_fill_status"] == "filled"


def test_replay_sequential_entry_marks_unfilled_when_second_leg_times_out():
    settings = _base_settings(
        {
            "signal_exec_lag_days": 0,
            "execution_lag_minutes": 0,
            "execution_max_wait_minutes": 120,
            "sequential_entry_enabled": True,
            "sequential_entry_first_leg": "future",
            "sequential_entry_second_leg_max_wait_minutes": 5,
            "TP_pct": 1.0,
        }
    )
    df = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-01 10:05:00", 104.0, 101.0),
            ("2026-01-01 10:20:00", 105.0, 101.0),
        ]
    )
    result = _apply_spread_carry_signals(
        df,
        merged=None,
        dividends=[],
        key_rates=_rates(date(2026, 1, 1)),
        settings=settings,
        future_spec=_future_spec(),
        alpha_cfg=settings.spread_carry_alpha,
    )

    assert result.iloc[0]["signal_action"] == "enter"
    assert result.iloc[0]["entry_fill_status"] == "entry_unfilled"
    assert result.iloc[0]["unfilled_reason"] in {"entry_second_leg_timeout_unwound", "entry_no_fill_in_window"}
    assert bool(result["entry_flag"].any()) is False


def test_replay_sequential_exit_forces_second_leg_after_gap_timeout():
    settings = _base_settings(
        {
            "signal_exec_lag_days": 0,
            "execution_lag_minutes": 0,
            "execution_max_wait_minutes": 60,
            "sequential_exit_enabled": True,
            "sequential_exit_first_leg": "future",
            "sequential_exit_second_leg_max_wait_minutes": 5,
            "force_exit_policy": "market_worse",
            "force_exit_penalty_bps": 5.0,
            "TP_pct": 1.0,
            "SL_pct": 0.001,
        }
    )
    df = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-01 10:01:00", 100.0, 101.0),
            ("2026-01-01 10:02:00", 95.0, 105.0),
            ("2026-01-01 10:03:00", 90.0, 105.0),
            ("2026-01-01 10:20:00", 90.0, 105.0),
        ]
    )
    result = _apply_spread_carry_signals(
        df,
        merged=None,
        dividends=[],
        key_rates=_rates(date(2026, 1, 1)),
        settings=settings,
        future_spec=_future_spec(),
        alpha_cfg=settings.spread_carry_alpha,
    )

    forced_rows = result[result["exit_fill_status"] == "forced"]
    assert not forced_rows.empty
    assert bool((forced_rows["exit_forced"] == True).any())  # noqa: E712
    assert bool((forced_rows["unfilled_reason"] == "exit_second_leg_timeout_forced").any())  # noqa: E712
