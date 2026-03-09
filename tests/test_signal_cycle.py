from datetime import date
from types import SimpleNamespace

import pandas as pd

import moex_carry.pipeline as pipeline
from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.storage.db import create_engine_from_settings, create_session_factory
from moex_carry.storage.repositories import load_latest_signal_run, load_signal_history
from moex_carry.strategy.strategy_signal import StrategySignal


def test_run_signal_cycle_persists_history(tmp_path, monkeypatch):
    sample = pd.DataFrame(
        [
            {
                "stock": "AAA",
                "future": "AAH6",
                "signal_action": "enter",
                "signal_direction": "cash_and_carry",
                "signal_score": 0.12,
                "signal_reasons": ["stat_confirmed", "carry_confirmed"],
                "signal_metrics": {"zscore": 2.3},
            }
        ]
    )

    def fake_fetch_data(*_args, **_kwargs):
        return None

    def fake_compute_pairs(*_args, **_kwargs):
        return sample.copy()

    monkeypatch.setattr(pipeline, "fetch_data", fake_fetch_data)
    monkeypatch.setattr(pipeline, "compute_pairs", fake_compute_pairs)

    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/signals.db"),
    )
    settings.ui.use_unified_signal_engine = False
    result = pipeline.run_signal_cycle(settings, max_pairs=1, save_csv=False)
    assert not result.empty

    engine = create_engine_from_settings(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        latest = load_latest_signal_run(session)
        assert latest is not None
        rows = load_signal_history(session, limit=10)
        assert len(rows) == 1
        assert rows[0].stock_secid == "AAA"


def test_run_signal_cycle_two_layer_runtime_adapter_overrides_legacy_fields(tmp_path, monkeypatch):
    sample = pd.DataFrame(
        [
            {
                "stock": "AAA",
                "future": "AAH6",
                "signal_action": "hold",
                "signal_direction": "cash_and_carry",
                "signal_score": 0.12,
                "signal_reasons": ["legacy_hold"],
                "signal_metrics": {"legacy": True},
                "forecast_tp_probability": 0.6,
                "forecast_sl_probability": 0.2,
                "forecast_no_exit_probability": 0.2,
                "forecast_n_effective": 120.0,
                "tp_net": 0.01,
                "sl_net": 0.01,
            }
        ]
    )
    calls: list[dict[str, object]] = []

    def fake_fetch_data(*_args, **_kwargs):
        return None

    def fake_compute_pairs(*_args, **_kwargs):
        return sample.copy()

    def fake_evaluate(**kwargs):
        calls.append(kwargs)
        strategy_signal = StrategySignal(
            strategy_id="spread_carry_runtime_v1_two_layer",
            strategy_type="speculative",
            cadence="intraday",
            horizon="60m",
            action="enter",
            confidence=0.74,
            expected_return=2.4,
            risk_estimate=1.0,
            warnings=["runtime_adapter_applied"],
            metadata={"engine_action": "BUY"},
        )
        evaluation = SimpleNamespace(
            forecast=SimpleNamespace(
                p_tp=0.6,
                p_sl=0.2,
                p_exit=0.2,
                n_effective=120.0,
                probability_source="dirichlet_decay_v1",
            ),
            cost_ticks=1.5,
            expected_return_ticks=2.4,
        )
        return strategy_signal, evaluation

    monkeypatch.setattr(pipeline, "fetch_data", fake_fetch_data)
    monkeypatch.setattr(pipeline, "compute_pairs", fake_compute_pairs)
    monkeypatch.setattr(pipeline, "evaluate_proposal_to_strategy_signal", fake_evaluate)

    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/signals.db"),
    )
    settings.ui.use_unified_signal_engine = False
    settings.signal_engine.runtime_adapter.enabled = True
    settings.signal_engine.runtime_adapter.override_signal_fields = True

    result = pipeline.run_signal_cycle(settings, max_pairs=1, save_csv=False)
    assert not result.empty
    assert len(calls) == 1
    assert len(calls[0]["historical_outcomes"]) == 120
    row = result.iloc[0]
    assert row["signal_action_legacy"] == "hold"
    assert row["signal_action_two_layer"] == "enter"
    assert row["signal_action"] == "enter"
    assert row["signal_direction"] == "cash_and_carry"
    assert isinstance(row["signal_metrics"], dict)
    assert "two_layer" in row["signal_metrics"]
    assert row["signal_metrics"]["strategy_type"] == "speculative"
    assert row["signal_metrics"]["strategy_stream"] == "commodity_futures"


def test_backfill_signal_history_persists_days(tmp_path, monkeypatch):
    sample = pd.DataFrame(
        [
            {
                "stock": "AAA",
                "future": "AAH6",
                "signal_action": "enter",
                "signal_direction": "cash_and_carry",
                "signal_score": 0.12,
                "signal_reasons": ["stat_confirmed", "carry_confirmed"],
                "signal_metrics": {"zscore": 2.3},
                "snapshot_as_of": "2025-01-12T00:00:00Z",
            }
        ]
    )

    def fake_fetch_data(*_args, **_kwargs):
        return None

    def fake_compute_pairs(*_args, **kwargs):
        as_of = kwargs.get("as_of")
        if isinstance(as_of, date):
            return sample.assign(snapshot_as_of=f"{as_of.isoformat()}T00:00:00Z")
        return sample.copy()

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2025, 1, 12)

    monkeypatch.setattr(pipeline, "fetch_data", fake_fetch_data)
    monkeypatch.setattr(pipeline, "compute_pairs", fake_compute_pairs)
    monkeypatch.setattr(pipeline, "date", FixedDate)

    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/signals.db"),
    )
    settings.ui.use_unified_signal_engine = False
    stored = pipeline.backfill_signal_history(
        settings, days=2, max_pairs=1, save_csv_latest=False
    )
    assert stored == 2

    engine = create_engine_from_settings(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        rows = load_signal_history(session, limit=10)
        assert len(rows) == 2


def test_backfill_signal_history_unified_uses_incremental_ingest(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "shares.csv").write_text("SECID,SHORTNAME\nAAA,AAA\n", encoding="utf-8")
    (raw_dir / "futures.csv").write_text(
        "SECID,ASSETCODE,LASTTRADEDATE,LOTVOLUME,MULTIPLIER,MINSTEP\nAAH6,AAA,2026-03-20,1,1,0.01\n",
        encoding="utf-8",
    )
    (raw_dir / "key_rates.csv").write_text("date,rate\n2025-01-01,0.21\n", encoding="utf-8")

    fetch_calls: list[int] = []
    ingest_calls: list[int] = []
    snapshot_days: list[date] = []
    sample = pd.DataFrame(
        [
            {
                "stock": "AAA",
                "future": "AAH6",
                "signal_action": "enter",
                "signal_direction": "cash_and_carry",
                "signal_score": 0.33,
                "signal_reasons": ["stat_confirmed", "carry_confirmed"],
                "signal_metrics": {"zscore": 2.1},
            }
        ]
    )

    def fake_fetch_data(*_args, **_kwargs):
        fetch_calls.append(1)
        return None

    def fake_list_pairs(*_args, **_kwargs):
        return [SimpleNamespace(stock="AAA", future="AAH6", future_scale=1.0, pair_id="AAA|AAH6")]

    def fake_ingest(**_kwargs):
        ingest_calls.append(1)
        return SimpleNamespace(
            pair_results={},
            global_watermark_before="before",
            global_watermark_after="after",
            degraded=False,
        )

    def fake_snapshot(
        _settings,
        _data_dir,
        *,
        force=False,
        ttl_sec=120,
        as_of=None,
        max_pairs=None,
        ingest_result_map=None,
        global_data_watermark_before=None,
        global_data_watermark_after=None,
    ):
        del force, ttl_sec, max_pairs, ingest_result_map, global_data_watermark_before, global_data_watermark_after
        snapshot_days.append(as_of)
        return SimpleNamespace(
            created_at=None,
            top_pairs=sample.copy(),
            signals=sample.assign(snapshot_as_of=f"{as_of.isoformat()}T00:00:00Z"),
            backtests=pd.DataFrame(),
            warnings=[],
            errors=[],
        )

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2025, 1, 12)

    monkeypatch.setattr(pipeline, "fetch_data", fake_fetch_data)
    monkeypatch.setattr(pipeline, "date", FixedDate)
    monkeypatch.setattr("moex_carry.unified_runtime.list_unified_ingest_pairs", fake_list_pairs)
    monkeypatch.setattr("moex_carry.minute_ingest.runner.run_incremental_minute_ingest", fake_ingest)
    monkeypatch.setattr("moex_carry.unified_runtime.build_unified_market_snapshot", fake_snapshot)
    monkeypatch.setattr("moex_carry.unified_runtime.persist_snapshot_to_csv", lambda *_a, **_k: None)

    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/signals.db"),
    )
    settings.ui.use_unified_signal_engine = True
    settings.ui.incremental_replay_enabled = True

    stored = pipeline.backfill_signal_history(settings, days=2, max_pairs=1, save_csv_latest=False)
    assert stored == 2
    assert fetch_calls == []
    assert ingest_calls == [1]
    assert snapshot_days == [FixedDate(2025, 1, 12), FixedDate(2025, 1, 11)]

    engine = create_engine_from_settings(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        rows = load_signal_history(session, limit=10)
        assert len(rows) == 2


def test_run_signal_cycle_unified_runtime_adapter_keeps_top_pairs_and_signals_in_sync(
    tmp_path, monkeypatch
):
    top_pairs = pd.DataFrame(
        [
            {
                "stock": "AAA",
                "future": "AAH6",
                "signal_action": "hold",
                "signal_direction": None,
                "signal_score": 0.11,
                "signal_reasons": ["legacy_hold_top_pairs"],
                "signal_metrics": {"legacy": "top_pairs"},
                "forecast_tp_probability": 0.55,
                "forecast_sl_probability": 0.25,
                "forecast_no_exit_probability": 0.20,
                "forecast_n_effective": 140.0,
                "tp_net": 0.01,
                "sl_net": 0.01,
            }
        ]
    )
    signals = pd.DataFrame(
        [
            {
                "stock": "AAA",
                "future": "AAH6",
                "signal_action": "enter",
                "signal_direction": "cash_and_carry",
                "signal_score": 0.45,
                "signal_reasons": ["legacy_enter_signals"],
                "signal_metrics": {"legacy": "signals"},
                "forecast_tp_probability": 0.50,
                "forecast_sl_probability": 0.30,
                "forecast_no_exit_probability": 0.20,
                "forecast_n_effective": 160.0,
                "tp_net": 0.01,
                "sl_net": 0.01,
            }
        ]
    )

    persisted_snapshots: list[SimpleNamespace] = []

    def fake_build_snapshot(*_args, **_kwargs):
        return SimpleNamespace(
            created_at=None,
            top_pairs=top_pairs.copy(),
            signals=signals.copy(),
            backtests=pd.DataFrame(),
            warnings=[],
            errors=[],
        )

    def fake_ingest(*_args, **_kwargs):
        return SimpleNamespace(
            degraded=False,
            global_watermark_before="before",
            global_watermark_after="after",
        )

    def fake_persist(snapshot, _data_dir):
        persisted_snapshots.append(
            SimpleNamespace(
                top_pairs=snapshot.top_pairs.copy(),
                signals=snapshot.signals.copy(),
            )
        )

    def fake_evaluate(**_kwargs):
        strategy_signal = StrategySignal(
            strategy_id="spread_carry_runtime_v1_two_layer",
            strategy_type="speculative",
            cadence="intraday",
            horizon="60m",
            action="enter",
            confidence=0.81,
            expected_return=2.7,
            risk_estimate=1.1,
            warnings=[],
            metadata={"engine_action": "BUY"},
        )
        evaluation = SimpleNamespace(
            forecast=SimpleNamespace(
                p_tp=0.55,
                p_sl=0.25,
                p_exit=0.20,
                n_effective=150.0,
                probability_source="dirichlet_decay_v1",
            ),
            cost_ticks=1.4,
            expected_return_ticks=2.7,
        )
        return strategy_signal, evaluation

    monkeypatch.setattr(pipeline, "_ensure_reference_data", lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, "_run_unified_incremental_ingest", fake_ingest)
    monkeypatch.setattr(pipeline, "_build_unified_snapshot", fake_build_snapshot)
    monkeypatch.setattr(pipeline, "evaluate_proposal_to_strategy_signal", fake_evaluate)
    monkeypatch.setattr("moex_carry.unified_runtime.persist_snapshot_to_csv", fake_persist)

    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/signals.db"),
    )
    settings.ui.use_unified_signal_engine = True
    settings.signal_engine.runtime_adapter.enabled = True
    settings.signal_engine.runtime_adapter.override_signal_fields = True

    result = pipeline.run_signal_cycle(settings, max_pairs=1, save_csv=True)
    assert not result.empty
    assert len(persisted_snapshots) == 1

    persisted = persisted_snapshots[0]
    merged = persisted.top_pairs.merge(
        persisted.signals,
        on=["stock", "future"],
        suffixes=("_top", "_sig"),
    )
    assert not merged.empty
    row = merged.iloc[0]
    assert row["signal_action_top"] == row["signal_action_sig"] == "enter"
    assert row["signal_direction_top"] == row["signal_direction_sig"] == "cash_and_carry"
