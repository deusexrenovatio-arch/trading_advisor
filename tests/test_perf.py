from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from moex_carry.data.history_store import HistoryDataStore
from moex_carry.domain.portfolio import PairSpec
from moex_carry.perf import resolve_pair_workers


def test_resolve_pair_workers_from_explicit_value():
    assert resolve_pair_workers(6) == 6


def test_resolve_pair_workers_uses_env(monkeypatch):
    monkeypatch.setenv("MOEX_CARRY_PAIR_WORKERS", "5")
    assert resolve_pair_workers(None) == 5


def test_resolve_pair_workers_falls_back_to_cpu(monkeypatch):
    monkeypatch.delenv("MOEX_CARRY_PAIR_WORKERS", raising=False)
    workers = resolve_pair_workers(None)
    assert workers >= 1


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def test_history_store_parallel_workers_consistent(tmp_path, monkeypatch):
    _write_csv(
        tmp_path / "raw" / "key_rates.csv",
        [{"date": "2025-01-01", "rate": 0.1}],
    )
    _write_csv(
        tmp_path / "history" / "candles" / "shares" / "AAA.csv",
        [
            {"date": "2025-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"date": "2025-01-02", "open": 101, "high": 102, "low": 100, "close": 101, "volume": 900},
        ],
    )
    _write_csv(
        tmp_path / "history" / "candles" / "futures" / "AAA_F.csv",
        [
            {"date": "2025-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 500},
            {"date": "2025-01-02", "open": 101, "high": 102, "low": 100, "close": 101, "volume": 450},
        ],
    )
    pairs = [PairSpec(stock_secid="AAA", future_secid="AAA_F", expiry=date(2025, 3, 20))]

    monkeypatch.setenv("MOEX_CARRY_PAIR_WORKERS", "1")
    single = HistoryDataStore(tmp_path, pairs, start_date=date(2025, 1, 1), end_date=date(2025, 1, 2))

    monkeypatch.setenv("MOEX_CARRY_PAIR_WORKERS", "4")
    parallel = HistoryDataStore(tmp_path, pairs, start_date=date(2025, 1, 1), end_date=date(2025, 1, 2))

    days = [date(2025, 1, 1), date(2025, 1, 2)]
    for day in days:
        assert len(single.get_stock_bars(day, ["AAA"])) == len(parallel.get_stock_bars(day, ["AAA"]))
        assert len(single.get_fut_bars(day, ["AAA_F"])) == len(parallel.get_fut_bars(day, ["AAA_F"]))
