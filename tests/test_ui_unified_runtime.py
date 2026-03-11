from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from moex_carry.config import AppSettings, DataConfig, SpreadCarryAlphaConfig, UiConfig
from moex_carry.signal_replay.core import ReplayMetrics, ReplayResult
from moex_carry.signal_replay.incremental import ReplayMutation
from moex_carry.server import create_server_app as create_app
import moex_carry.unified_runtime as core_unified_runtime
import moex_carry.ui.unified_runtime as unified_runtime
from moex_carry.ui.unified_runtime import (
    build_unified_market_snapshot,
    build_unified_spread_series,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _seed_unified_fixture(tmp_path: Path) -> None:
    _write_csv(
        tmp_path / "raw" / "shares.csv",
        [
            {"SECID": "AAA", "SHORTNAME": "Alpha", "CURRENCYID": "RUB", "BOARDID": "TQBR"},
        ],
    )
    _write_csv(
        tmp_path / "raw" / "futures.csv",
        [
            {
                "SECID": "AAH6",
                "ASSETCODE": "AAA",
                "LASTTRADEDATE": "2026-03-19",
                "LOTVOLUME": 1,
                "MINSTEP": 0.01,
                "MULTIPLIER": 1,
            },
            {
                "SECID": "AAM6",
                "ASSETCODE": "AAA",
                "LASTTRADEDATE": "2026-06-18",
                "LOTVOLUME": 1,
                "MINSTEP": 0.01,
                "MULTIPLIER": 1,
            },
        ],
    )
    _write_csv(
        tmp_path / "raw" / "key_rates.csv",
        [
            {"date": "2026-01-01", "rate": 0.1},
            {"date": "2026-01-02", "rate": 0.1},
        ],
    )

    base_rows: list[dict[str, object]] = []
    start = date(2026, 1, 2)
    for idx in range(40):
        day = start + timedelta(days=idx)
        if day.weekday() >= 5:
            continue
        for minute_offset in (0, 30):
            spot = 100.0 + idx * 0.1
            future = 101.0 + idx * 0.1
            ts = pd.Timestamp(day.isoformat()) + pd.Timedelta(hours=10, minutes=minute_offset)
            spread = spot - future
            base_rows.append(
                {
                    "date": day.isoformat(),
                    "spot_mid": spot,
                    "future_mid": future,
                    "pv_div": 0.0,
                    "div_sum": 0.0,
                    "spread_mid": spread,
                    "spread_pct": spread / spot if spot else 0.0,
                    "exec_ts": ts.isoformat(sep=" "),
                    "spot_volume": 1000.0,
                    "future_volume": 800.0,
                }
            )
    series = pd.DataFrame(base_rows)
    cache_payload = {
        "schema_version": 1,
        "series_base": series,
        "dividends": [],
    }
    cache_dir = tmp_path / "output" / "intraday_preload_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(
        cache_payload,
        cache_dir / "AAA_AAH6_2025-01-01_2026-12-31_fixture.pkl",
    )


def _settings(tmp_path: Path, *, allow_legacy_fallback: bool) -> AppSettings:
    alpha = SpreadCarryAlphaConfig(
        price_source="common_minute_close",
        common_minute_anchor="last",
        signal_exec_lag_days=0,
        execution_lag_minutes=30,
        execution_max_wait_minutes=360,
        entry_price_tolerance_pct=0.02,
        annual_target_threshold=0.0,
        r_cb_annual=0.0,
        r_fund_annual=0.0,
        r_disc_annual=0.0,
        min_DTE_entry=1,
        close_buffer_days=0,
        H_max_days=20,
        TP_pct=0.01,
        SL_pct=0.01,
        allowed_expiry_months=[3, 6, 9, 12],
        allowed_expiry_years=[2026],
    )
    ui = UiConfig(
        use_unified_signal_engine=True,
        unified_allow_legacy_fallback=allow_legacy_fallback,
        unified_snapshot_ttl_sec=300,
        unified_pair_workers=1,
        unified_front_only=True,
        unified_front_roll_days=7,
        require_score_gate_by_default=False,
        incremental_replay_enabled=False,
    )
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path), compute_lookback_days=120),
        spread_carry_alpha=alpha,
        ui=ui,
    )


def test_unified_runtime_selects_front_pair_and_builds_snapshot(tmp_path):
    _seed_unified_fixture(tmp_path)
    settings = _settings(tmp_path, allow_legacy_fallback=False)
    snapshot = build_unified_market_snapshot(
        settings,
        tmp_path,
        force=True,
        ttl_sec=60,
        as_of=date(2026, 2, 12),
    )
    assert not snapshot.top_pairs.empty
    assert not snapshot.signals.empty
    assert not snapshot.backtests.empty
    assert snapshot.top_pairs.iloc[0]["future"] == "AAH6"
    assert snapshot.signals.iloc[0]["stock"] == "AAA"
    assert isinstance(snapshot.signals.iloc[0]["signal_metrics"], dict)


def test_unified_runtime_parallel_workers_consistency(tmp_path):
    _seed_unified_fixture(tmp_path)
    settings = _settings(tmp_path, allow_legacy_fallback=False)
    settings.ui.unified_pair_workers = 1
    single = build_unified_market_snapshot(
        settings,
        tmp_path,
        force=True,
        ttl_sec=60,
        as_of=date(2026, 2, 12),
    )

    settings.ui.unified_pair_workers = 4
    parallel = build_unified_market_snapshot(
        settings,
        tmp_path,
        force=True,
        ttl_sec=60,
        as_of=date(2026, 2, 12),
    )

    top_columns = [
        "stock",
        "future",
        "signal_action",
        "total_score",
        "score_exec_probability",
        "score_earn_probability",
    ]
    signal_columns = [
        "stock",
        "future",
        "signal_action",
        "total_score",
        "score_exec_probability",
        "score_earn_probability",
    ]

    pd.testing.assert_frame_equal(
        single.top_pairs[top_columns].reset_index(drop=True),
        parallel.top_pairs[top_columns].reset_index(drop=True),
        check_dtype=False,
        check_exact=False,
        atol=1e-12,
        rtol=1e-12,
    )
    pd.testing.assert_frame_equal(
        single.signals[signal_columns].reset_index(drop=True),
        parallel.signals[signal_columns].reset_index(drop=True),
        check_dtype=False,
        check_exact=False,
        atol=1e-12,
        rtol=1e-12,
    )


def test_unified_spread_series_and_api_endpoints(tmp_path):
    _seed_unified_fixture(tmp_path)
    settings = _settings(tmp_path, allow_legacy_fallback=False)

    spread = build_unified_spread_series(
        settings,
        tmp_path,
        stock="AAA",
        future="AAH6",
        window_days=60,
        full_life=False,
        ttl_sec=60,
    )
    assert not spread.empty
    assert "spread_mid" in spread.columns
    assert "signal_action" in spread.columns

    app = create_app(settings)
    client = app.server.test_client()

    top_pairs = client.get("/api/top-pairs?limit=5")
    assert top_pairs.status_code == 200
    top_pairs_data = top_pairs.get_json()
    assert isinstance(top_pairs_data, list)
    assert top_pairs_data
    assert top_pairs_data[0]["stock"] == "AAA"
    assert top_pairs_data[0]["future"] == "AAH6"
    assert top_pairs_data[0]["score_model"] == "probabilistic_edge_v1"
    assert "score_exec_probability" in top_pairs_data[0]
    assert "score_earn_probability" in top_pairs_data[0]
    assert "score_gate_pass" in top_pairs_data[0]
    assert isinstance(top_pairs_data[0]["signal_metrics"], dict)
    assert "score_exec_probability" in top_pairs_data[0]["signal_metrics"]
    assert "forecast_tp_first_probability" in top_pairs_data[0]["signal_metrics"]
    assert "forecast_n_effective" in top_pairs_data[0]["signal_metrics"]
    assert "forecast_confidence_tier" in top_pairs_data[0]["signal_metrics"]
    assert isinstance(top_pairs_data[0]["execution_quality"], dict)
    assert "unfilled_entry_rate" in top_pairs_data[0]["execution_quality"]
    assert "forced_exit_rate" in top_pairs_data[0]["execution_quality"]

    signals = client.get("/api/signals?limit=5")
    assert signals.status_code == 200
    signals_data = signals.get_json()
    assert isinstance(signals_data, list)
    assert signals_data
    assert signals_data[0]["stock"] == "AAA"
    assert "signal_metrics" in signals_data[0]

    backtests = client.get("/api/backtests?limit=5")
    assert backtests.status_code == 200
    backtests_data = backtests.get_json()
    assert isinstance(backtests_data, list)
    assert backtests_data
    assert backtests_data[0]["stock"] == "AAA"

    spread_api = client.get("/api/spread-series?stock=AAA&future=AAH6&window_days=60")
    assert spread_api.status_code == 200
    spread_payload = spread_api.get_json()
    assert isinstance(spread_payload, list)
    assert spread_payload
    assert "spread_mid" in spread_payload[0]

    refresh = client.post("/api/signals/refresh")
    assert refresh.status_code == 200
    status_payload = refresh.get_json()
    assert status_payload["status"] == "ok"
    assert status_payload["engine"] == "unified_minute_replay"
    assert int(status_payload["rows"]) >= 0
    for key in (
        "incremental_enabled",
        "data_watermark_before",
        "data_watermark_after",
        "pairs_total",
        "pairs_recomputed",
        "pairs_reused",
        "pairs_skipped",
        "skip_reason",
    ):
        assert key in status_payload

    refresh_status = client.get("/api/signals/refresh-status")
    assert refresh_status.status_code == 200
    refresh_status_payload = refresh_status.get_json()
    for key in (
        "incremental_enabled",
        "data_watermark_before",
        "data_watermark_after",
        "pairs_total",
        "pairs_recomputed",
        "pairs_reused",
        "pairs_skipped",
        "skip_reason",
    ):
        assert key in refresh_status_payload

    history = client.get("/api/signals/history?limit=5")
    assert history.status_code == 200
    history_data = history.get_json()
    assert isinstance(history_data, list)
    assert history_data
    assert "signal_reasons" in history_data[0]
    assert "signal_metrics" in history_data[0]
    assert "trades_closed" in history_data[0]


def test_pair_replay_cache_reuses_single_slot_per_pair_window(tmp_path, monkeypatch):
    settings = _settings(tmp_path, allow_legacy_fallback=False)
    settings.ui.unified_pair_replay_cache_max = 64
    pair = core_unified_runtime._UniversePair(
        stock="AAA",
        stock_name="Alpha",
        future="AAH6",
        expiry=date(2026, 3, 19),
        lot_size=1.0,
        multiplier=1.0,
        tick_size=0.01,
    )

    call_counter = {"count": 0}

    def _fake_compute_pair_replay(**_kwargs):
        call_counter["count"] += 1
        frame = pd.DataFrame(
            [
                {
                    "date": "2026-02-12",
                    "exec_ts": f"2026-02-12 10:0{call_counter['count']}:00",
                    "spot_mid": 100.0,
                    "future_mid": 101.0,
                    "spread_mid": -1.0,
                    "spread_pct": -0.01,
                    "signal_action": "hold",
                }
            ]
        )
        metrics = ReplayMetrics(
            rows=1,
            days=1,
            entry_signals=0,
            exit_signals=0,
            trades_closed=0,
            avg_trade_return_annual_fill_to_fill_last5=None,
            avg_trade_return_annual_operational_last5=None,
            share_target_pass=None,
            unfilled_entry_rate=None,
            unfilled_exit_rate=None,
            forced_exit_rate=None,
            avg_entry_wait_min_closed=None,
            avg_exit_wait_min_closed=None,
        )
        return core_unified_runtime._PairReplayFetch(
            replay_result=ReplayResult(replay=frame, metrics=metrics, cutoff_minutes=0),
            source="test",
            error=None,
            cache_hit=False,
            skip_reason=None,
            fallback_reason=None,
            replay_mode="full",
        )

    monkeypatch.setattr(core_unified_runtime, "_compute_pair_replay", _fake_compute_pair_replay)

    with core_unified_runtime._PAIR_REPLAY_CACHE_LOCK:
        core_unified_runtime._PAIR_REPLAY_CACHE.clear()

    changed_w1 = ReplayMutation(
        changed=True,
        append_only=True,
        earliest_changed_exec_ts=None,
        watermark_before=None,
        watermark_after="w1",
    )
    changed_w2 = ReplayMutation(
        changed=True,
        append_only=True,
        earliest_changed_exec_ts=None,
        watermark_before="w1",
        watermark_after="w2",
    )
    unchanged_w2 = ReplayMutation(
        changed=False,
        append_only=True,
        earliest_changed_exec_ts=None,
        watermark_before="w2",
        watermark_after="w2",
    )

    first = core_unified_runtime.get_pair_replay(
        settings=settings,
        data_dir=tmp_path,
        pair=pair,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 12),
        key_rates=[],
        force=False,
        ttl_sec=120,
        data_watermark="w1",
        mutation=changed_w1,
    )
    assert first.cache_hit is False

    second = core_unified_runtime.get_pair_replay(
        settings=settings,
        data_dir=tmp_path,
        pair=pair,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 12),
        key_rates=[],
        force=False,
        ttl_sec=120,
        data_watermark="w2",
        mutation=changed_w2,
    )
    assert second.cache_hit is False

    with core_unified_runtime._PAIR_REPLAY_CACHE_LOCK:
        cache_size = len(core_unified_runtime._PAIR_REPLAY_CACHE)
        cached_items = list(core_unified_runtime._PAIR_REPLAY_CACHE.values())
    assert cache_size == 1
    assert cached_items[0].data_watermark == "w2"

    third = core_unified_runtime.get_pair_replay(
        settings=settings,
        data_dir=tmp_path,
        pair=pair,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 12),
        key_rates=[],
        force=False,
        ttl_sec=120,
        data_watermark="w2",
        mutation=unchanged_w2,
    )
    assert third.cache_hit is True
    assert call_counter["count"] == 2

    with core_unified_runtime._PAIR_REPLAY_CACHE_LOCK:
        core_unified_runtime._PAIR_REPLAY_CACHE.clear()


def test_pair_rows_apply_turnover_gate_and_alpha_cap(tmp_path):
    settings = _settings(tmp_path, allow_legacy_fallback=False)
    pair = core_unified_runtime._UniversePair(
        stock="AAA",
        stock_name="Alpha",
        future="AAH6",
        expiry=date(2026, 3, 19),
        lot_size=1.0,
        multiplier=1.0,
        tick_size=0.01,
    )
    frame = pd.DataFrame(
        [
            {
                "date": f"2026-02-{10 + idx:02d}",
                "exec_ts": f"2026-02-{10 + idx:02d} 10:00:00",
                "spot_mid": 100.0,
                "future_mid": 101.0,
                "spread_mid": -1.0,
                "spread_pct": -0.01 + idx * 0.0005,
                "signal_action": "hold",
                "rtc_pct": 0.0003,
                "floor_rate_annual": 0.2,
                "entry_spread_pct_exec": -0.01,
                "tp_net": 0.01,
                "sl_net": 0.01,
            }
            for idx in range(6)
        ]
    )
    metrics = ReplayMetrics(
        rows=len(frame),
        days=40,
        entry_signals=250,
        exit_signals=200,
        trades_closed=200,  # 5/day > max turnover gate (2/day)
        avg_trade_return_annual_fill_to_fill_last5=120.0,
        avg_trade_return_annual_operational_last5=120.0,
        share_target_pass=0.8,
        unfilled_entry_rate=0.0,
        unfilled_exit_rate=0.0,
        forced_exit_rate=0.0,
        avg_entry_wait_min_closed=2.0,
        avg_exit_wait_min_closed=5.0,
    )
    replay = ReplayResult(replay=frame, metrics=metrics, cutoff_minutes=0)

    top_row, signal_row, _ = core_unified_runtime._build_pair_rows(
        pair=pair,
        replay=replay,
        source="test",
        settings=settings,
        key_rates=[],
    )

    assert signal_row["score_alpha_raw"] == 120.0
    assert signal_row["score_alpha"] == 2.0
    assert signal_row["score_gate_pass"] is False
    assert signal_row["trades_per_day"] == 5.0
    assert signal_row["score_gate_max_trades_per_day"] == 2.0
    assert "excessive_turnover" in signal_row["signal_reasons"]
    assert "score_alpha_capped" in signal_row["signal_reasons"]
    assert top_row["score_gate_pass"] is False


def test_manual_refresh_defaults_to_incremental_and_supports_force_full(tmp_path, monkeypatch):
    _seed_unified_fixture(tmp_path)
    settings = _settings(tmp_path, allow_legacy_fallback=False)
    settings.ui.incremental_replay_enabled = True

    calls: list[str] = []

    def _fake_incremental_ingest(**_kwargs):
        calls.append("incremental")
        return SimpleNamespace(
            global_watermark_before="before",
            global_watermark_after="after",
            pair_results={},
            degraded=False,
        )

    monkeypatch.setattr("moex_carry.ui.app.run_incremental_minute_ingest", _fake_incremental_ingest)

    app = create_app(settings)
    client = app.server.test_client()

    refresh = client.post("/api/signals/refresh")
    assert refresh.status_code == 200
    assert calls == ["incremental"]

    refresh_force = client.post("/api/signals/refresh", json={"force_full": True})
    assert refresh_force.status_code == 200
    assert calls == ["incremental"]


def test_forward_forecast_uses_minute_horizon_and_converts_half_life_to_days(monkeypatch):
    frame = pd.DataFrame(
        [
            {"date": "2026-01-10", "exec_ts": "2026-01-10 10:00:00", "spread_pct": -0.010},
            {"date": "2026-01-10", "exec_ts": "2026-01-10 10:30:00", "spread_pct": -0.009},
            {"date": "2026-01-10", "exec_ts": "2026-01-10 11:00:00", "spread_pct": -0.008},
            {"date": "2026-01-11", "exec_ts": "2026-01-11 10:00:00", "spread_pct": -0.007},
            {"date": "2026-01-11", "exec_ts": "2026-01-11 10:30:00", "spread_pct": -0.006},
            {"date": "2026-01-11", "exec_ts": "2026-01-11 11:00:00", "spread_pct": -0.005},
        ]
    )
    calls: list[int] = []

    def _fake_alpha_metrics(_series, *, horizon, tp, sl):
        del tp, sl
        calls.append(int(horizon))
        return SimpleNamespace(p_hit_tp=0.6, p_hit_sl=0.2, half_life=4.0)

    monkeypatch.setattr(unified_runtime, "alpha_metrics", _fake_alpha_metrics)
    monkeypatch.setattr(core_unified_runtime, "alpha_metrics", _fake_alpha_metrics)

    settings = AppSettings(
        data=DataConfig(data_dir="."),
        spread_carry_alpha=SpreadCarryAlphaConfig(H_max_days=2, TP_pct=0.01, SL_pct=0.01),
        ui=UiConfig(),
    )
    forecast = unified_runtime._build_forward_signal_forecast(
        frame=frame,
        settings=settings,
        tp_net=None,
        as_of_snapshot=date(2026, 1, 11),
    )

    # 2 days * 3 bars/day = 6, capped by len(series)-1 = 5.
    assert calls == [5]
    assert forecast["forward_half_life_days"] == 4.0 / 3.0
    assert forecast["forecast_exit_days"] == 1


def test_forward_forecast_fallback_without_date_columns():
    frame = pd.DataFrame(
        [
            {"spread_pct": -0.010},
            {"spread_pct": -0.009},
            {"spread_pct": -0.008},
            {"spread_pct": -0.007},
        ]
    )
    settings = AppSettings(
        data=DataConfig(data_dir="."),
        spread_carry_alpha=SpreadCarryAlphaConfig(H_max_days=3, TP_pct=0.01, SL_pct=0.01),
        ui=UiConfig(),
    )
    forecast = unified_runtime._build_forward_signal_forecast(
        frame=frame,
        settings=settings,
        tp_net=None,
        as_of_snapshot=date(2026, 1, 11),
    )
    # Without date/exec_ts we treat each bar as one day.
    assert forecast["forecast_exit_days"] >= 1


def test_forward_forecast_event_first_hit_shrinkage_and_effective_sample():
    frame = pd.DataFrame(
        [
            {"spread_pct": 0.00, "signal_action": "enter"},
            {"spread_pct": 0.02, "signal_action": "enter"},
            {"spread_pct": -0.01, "signal_action": "enter"},
            {"spread_pct": 0.03, "signal_action": "enter"},
            {"spread_pct": -0.02, "signal_action": "enter"},
            {"spread_pct": 0.04, "signal_action": "enter"},
            {"spread_pct": -0.03, "signal_action": "enter"},
            {"spread_pct": 0.05, "signal_action": "hold"},
        ]
    )
    settings = AppSettings(
        data=DataConfig(data_dir="."),
        spread_carry_alpha=SpreadCarryAlphaConfig(H_max_days=2, TP_pct=0.01, SL_pct=0.01),
        ui=UiConfig(),
    )
    forecast = unified_runtime._build_forward_signal_forecast(
        frame=frame,
        settings=settings,
        tp_net=None,
        as_of_snapshot=date(2026, 1, 11),
    )
    # Non-overlap selection with horizon=2 yields entries at indices [0, 2, 4].
    assert int(forecast["forward_n_effective"]) == 3
    assert forecast["forward_confidence_tier"] == "very_low"
    assert 0.5 <= float(forecast["forward_tp_first_probability"]) <= 0.7
    assert 0.05 <= float(forecast["forward_sl_first_probability"]) <= 0.15
    assert 0.2 <= float(forecast["forward_no_exit_first_probability"]) <= 0.4

