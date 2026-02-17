from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from moex_carry.signal_replay.minute_loader import PRELOAD_SCHEMA_VERSION, load_pair_minute_series


def _write_preload(
    *,
    root: Path,
    stock: str,
    future: str,
    suffix: str,
    rows: list[dict[str, object]],
) -> Path:
    cache_dir = root / "output" / "intraday_preload_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{stock}_{future}_{suffix}.pkl"
    payload = {
        "schema_version": PRELOAD_SCHEMA_VERSION,
        "series_base": pd.DataFrame(rows),
        "dividends": [],
    }
    pd.to_pickle(payload, path)
    return path


def _write_csv(
    *,
    root: Path,
    stock: str,
    future: str,
    rows: list[dict[str, object]],
) -> Path:
    out_dir = root / "output" / "intraday_minute_series"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"intraday_minute_series_{stock}_{future}.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_load_pair_minute_series_prefers_fresher_csv_over_stale_preload(tmp_path):
    stock = "AAA"
    future = "AAH6"
    _write_preload(
        root=tmp_path,
        stock=stock,
        future=future,
        suffix="old",
        rows=[
            {
                "date": "2025-01-02",
                "exec_ts": "2025-01-02T10:00:00Z",
                "spot": 100.0,
                "future_price": 101.0,
            }
        ],
    )
    csv_path = _write_csv(
        root=tmp_path,
        stock=stock,
        future=future,
        rows=[
            {
                "date": "2025-01-03",
                "exec_ts": "2025-01-03T10:00:00Z",
                "spot": 100.5,
                "future_price": 101.2,
            }
        ],
    )

    payload = load_pair_minute_series(
        data_dir=tmp_path,
        stock=stock,
        future=future,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 5),
    )

    assert payload is not None
    assert payload.source.endswith(str(csv_path).replace("\\", "/"))
    assert str(payload.series_base["date"].max()) == "2025-01-03"


def test_load_pair_minute_series_prefers_fresher_preload_over_csv(tmp_path):
    stock = "AAA"
    future = "AAH6"
    preload_path = _write_preload(
        root=tmp_path,
        stock=stock,
        future=future,
        suffix="new",
        rows=[
            {
                "date": "2025-01-04",
                "exec_ts": "2025-01-04T10:00:00Z",
                "spot": 101.0,
                "future_price": 102.0,
            }
        ],
    )
    _write_csv(
        root=tmp_path,
        stock=stock,
        future=future,
        rows=[
            {
                "date": "2025-01-03",
                "exec_ts": "2025-01-03T10:00:00Z",
                "spot": 100.5,
                "future_price": 101.2,
            }
        ],
    )

    payload = load_pair_minute_series(
        data_dir=tmp_path,
        stock=stock,
        future=future,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 5),
    )

    assert payload is not None
    assert payload.source.endswith(str(preload_path).replace("\\", "/"))
    assert str(payload.series_base["date"].max()) == "2025-01-04"
