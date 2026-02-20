from datetime import date
from types import SimpleNamespace

import pandas as pd

import moex_carry.pipeline as pipeline
from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.storage.db import create_engine_from_settings, create_session_factory
from moex_carry.storage.repositories import load_latest_signal_run, load_signal_history


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
