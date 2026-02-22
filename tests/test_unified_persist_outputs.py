from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from moex_carry.unified_runtime import UnifiedMarketSnapshot, persist_snapshot_to_csv_with_meta


def _sample_snapshot() -> UnifiedMarketSnapshot:
    top_pairs = pd.DataFrame([{"stock": "AAA", "future": "AAH6", "signal_score": 0.42}])
    signals = pd.DataFrame([{"stock": "AAA", "future": "AAH6", "signal_action": "enter"}])
    backtests = pd.DataFrame([{"stock": "AAA", "future": "AAH6", "trades_closed": 5}])
    return UnifiedMarketSnapshot(
        created_at=datetime(2026, 2, 20, tzinfo=timezone.utc),
        top_pairs=top_pairs,
        signals=signals,
        backtests=backtests,
        warnings=[],
        errors=[],
    )


def _read_csv(path: Path) -> pd.DataFrame:
    assert path.exists()
    return pd.read_csv(path)


def test_unified_persist_publishes_root_alias(tmp_path):
    snapshot = _sample_snapshot()
    meta = persist_snapshot_to_csv_with_meta(snapshot, tmp_path, engine_tag="unified")

    unified_top_pairs = tmp_path / "output" / "unified" / "top_pairs.csv"
    root_top_pairs = tmp_path / "output" / "top_pairs.csv"
    unified_signals = tmp_path / "output" / "unified" / "signals.csv"
    root_signals = tmp_path / "output" / "signals.csv"

    assert meta["engine"] == "unified"
    assert meta["root_alias_published"] is True
    assert isinstance(meta["root_alias_datasets"], dict)
    assert _read_csv(unified_top_pairs).to_dict("records") == _read_csv(root_top_pairs).to_dict("records")
    assert _read_csv(unified_signals).to_dict("records") == _read_csv(root_signals).to_dict("records")


def test_non_unified_persist_keeps_engine_scoped_outputs(tmp_path):
    snapshot = _sample_snapshot()
    meta = persist_snapshot_to_csv_with_meta(snapshot, tmp_path, engine_tag="legacy")

    legacy_top_pairs = tmp_path / "output" / "legacy" / "top_pairs.csv"
    root_top_pairs = tmp_path / "output" / "top_pairs.csv"

    assert meta["engine"] == "legacy"
    assert meta["root_alias_published"] is False
    assert meta["root_alias_datasets"] is None
    assert legacy_top_pairs.exists()
    assert not root_top_pairs.exists()

