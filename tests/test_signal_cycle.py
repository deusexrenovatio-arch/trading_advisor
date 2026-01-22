from datetime import date

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
    stored = pipeline.backfill_signal_history(
        settings, days=2, max_pairs=1, save_csv_latest=False
    )
    assert stored == 2

    engine = create_engine_from_settings(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        rows = load_signal_history(session, limit=10)
        assert len(rows) == 2
