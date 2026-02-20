from datetime import date, datetime

import pandas as pd

from moex_carry.config import AppSettings, CostsConfig, SpreadCarryAlphaConfig
from moex_carry.domain.portfolio import PairSpec
from moex_carry.signal_replay.core import run_minute_replay
from moex_carry.signal_replay.incremental import ReplayMutation, run_true_incremental_replay


def _settings() -> AppSettings:
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
            signal_cutoff_before_day_end_minutes=0,
        ),
    )


def _pair() -> PairSpec:
    return PairSpec(
        stock_secid="AAA",
        future_secid="AAH6",
        expiry=date(2026, 3, 19),
        lot_size=1.0,
        multiplier=1.0,
        tick_size=0.01,
    )


def _series(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    payload: list[dict[str, object]] = []
    for ts_raw, spot_mid, future_mid in rows:
        spread_mid = spot_mid - future_mid
        payload.append(
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
    return pd.DataFrame(payload)


def test_true_incremental_append_matches_full_replay(tmp_path):
    settings = _settings()
    pair = _pair()
    checkpoint_root = tmp_path / "state" / "incremental_replay"
    output_root = tmp_path / "output" / "incremental_replay"

    head = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-01 10:20:00", 100.0, 101.0),
            ("2026-01-01 10:40:00", 100.5, 100.8),
            ("2026-01-01 11:00:00", 100.5, 100.8),
        ]
    )
    first = run_true_incremental_replay(
        pair_id="AAA|AAH6",
        pair=pair,
        series_base=head,
        settings=settings,
        dividends=[],
        key_rates=[],
        mutation=ReplayMutation(
            changed=True,
            append_only=True,
            earliest_changed_exec_ts=None,
            watermark_before=None,
            watermark_after="wm-head",
        ),
        checkpoint_root=checkpoint_root,
        output_root=output_root,
        overlap_minutes=180,
        checkpoint_interval_minutes=60,
        force_full=False,
    )
    assert first.mode == "full"
    assert not first.replay_result.replay.empty

    extended = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-01 10:20:00", 100.0, 101.0),
            ("2026-01-01 10:40:00", 100.5, 100.8),
            ("2026-01-01 11:00:00", 100.5, 100.8),
            ("2026-01-01 11:20:00", 100.2, 100.9),
            ("2026-01-01 11:40:00", 100.2, 100.9),
        ]
    )
    second = run_true_incremental_replay(
        pair_id="AAA|AAH6",
        pair=pair,
        series_base=extended,
        settings=settings,
        dividends=[],
        key_rates=[],
        mutation=ReplayMutation(
            changed=True,
            append_only=True,
            earliest_changed_exec_ts=None,
            watermark_before="wm-head",
            watermark_after="wm-extended",
        ),
        checkpoint_root=checkpoint_root,
        output_root=output_root,
        overlap_minutes=180,
        checkpoint_interval_minutes=60,
        force_full=False,
    )

    baseline = run_minute_replay(
        series_base=extended,
        pair=pair,
        settings=settings,
        dividends=[],
        key_rates=[],
    )
    compare_cols = [
        "signal_action",
        "entry_fill_status",
        "exit_fill_status",
        "entry_fill_ts",
        "exit_fill_ts",
        "entry_wait_minutes",
        "exit_wait_minutes",
    ]
    for col in compare_cols:
        left = second.replay_result.replay[col].astype(str).reset_index(drop=True)
        right = baseline.replay[col].astype(str).reset_index(drop=True)
        assert left.equals(right), f"incremental_parity_mismatch:{col}"


def test_true_incremental_reuse_when_watermark_unchanged(tmp_path):
    settings = _settings()
    pair = _pair()
    checkpoint_root = tmp_path / "state" / "incremental_replay"
    output_root = tmp_path / "output" / "incremental_replay"
    series = _series(
        [
            ("2026-01-01 10:00:00", 100.0, 101.0),
            ("2026-01-01 10:20:00", 100.0, 101.0),
            ("2026-01-01 10:40:00", 100.5, 100.8),
            ("2026-01-01 11:00:00", 100.5, 100.8),
        ]
    )
    first = run_true_incremental_replay(
        pair_id="AAA|AAH6",
        pair=pair,
        series_base=series,
        settings=settings,
        dividends=[],
        key_rates=[],
        mutation=ReplayMutation(
            changed=True,
            append_only=True,
            earliest_changed_exec_ts=None,
            watermark_before=None,
            watermark_after="wm-static",
        ),
        checkpoint_root=checkpoint_root,
        output_root=output_root,
        overlap_minutes=180,
        checkpoint_interval_minutes=60,
        force_full=False,
    )
    second = run_true_incremental_replay(
        pair_id="AAA|AAH6",
        pair=pair,
        series_base=series,
        settings=settings,
        dividends=[],
        key_rates=[],
        mutation=ReplayMutation(
            changed=False,
            append_only=True,
            earliest_changed_exec_ts=None,
            watermark_before="wm-static",
            watermark_after="wm-static",
        ),
        checkpoint_root=checkpoint_root,
        output_root=output_root,
        overlap_minutes=180,
        checkpoint_interval_minutes=60,
        force_full=False,
    )

    assert first.replay_result.replay.equals(second.replay_result.replay)
    assert second.mode == "reuse"
    assert second.recomputed is False
    assert second.skip_reason == "no_data_change"


def test_true_incremental_rebuilds_when_history_expands_with_same_watermark(tmp_path):
    settings = _settings()
    pair = _pair()
    checkpoint_root = tmp_path / "state" / "incremental_replay"
    output_root = tmp_path / "output" / "incremental_replay"
    short_series = _series(
        [
            ("2026-01-02 10:00:00", 100.0, 101.0),
            ("2026-01-02 10:20:00", 100.0, 101.0),
            ("2026-01-02 10:40:00", 100.5, 100.8),
            ("2026-01-02 11:00:00", 100.5, 100.8),
        ]
    )
    first = run_true_incremental_replay(
        pair_id="AAA|AAH6",
        pair=pair,
        series_base=short_series,
        settings=settings,
        dividends=[],
        key_rates=[],
        mutation=ReplayMutation(
            changed=True,
            append_only=True,
            earliest_changed_exec_ts=None,
            watermark_before=None,
            watermark_after="wm-static",
        ),
        checkpoint_root=checkpoint_root,
        output_root=output_root,
        overlap_minutes=180,
        checkpoint_interval_minutes=60,
        force_full=False,
    )
    assert first.mode == "full"

    expanded_series = _series(
        [
            ("2026-01-01 10:00:00", 100.1, 101.2),
            ("2026-01-01 10:20:00", 100.2, 101.1),
            ("2026-01-02 10:00:00", 100.0, 101.0),
            ("2026-01-02 10:20:00", 100.0, 101.0),
            ("2026-01-02 10:40:00", 100.5, 100.8),
            ("2026-01-02 11:00:00", 100.5, 100.8),
        ]
    )
    second = run_true_incremental_replay(
        pair_id="AAA|AAH6",
        pair=pair,
        series_base=expanded_series,
        settings=settings,
        dividends=[],
        key_rates=[],
        mutation=ReplayMutation(
            changed=False,
            append_only=True,
            earliest_changed_exec_ts=None,
            watermark_before="wm-static",
            watermark_after="wm-static",
        ),
        checkpoint_root=checkpoint_root,
        output_root=output_root,
        overlap_minutes=180,
        checkpoint_interval_minutes=60,
        force_full=False,
    )

    baseline = run_minute_replay(
        series_base=expanded_series,
        pair=pair,
        settings=settings,
        dividends=[],
        key_rates=[],
    )
    assert second.mode == "full"
    assert second.fallback_reason == "source_history_expanded"
    assert second.recomputed is True
    assert second.replay_result.replay.equals(baseline.replay)
