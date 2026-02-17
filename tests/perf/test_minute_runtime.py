from __future__ import annotations

from datetime import date
from pathlib import Path
import time

import pandas as pd

from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.hpo.minute_period_pnl import evaluate_minute_period_metrics


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _seed_perf_fixture(tmp_path: Path, pairs: int = 25) -> list[str]:
    shares: list[dict[str, object]] = []
    futures: list[dict[str, object]] = []
    include_futures: list[str] = []
    for idx in range(pairs):
        stock = f"AA{idx:02d}"
        future = f"{stock}H6"
        shares.append({"SECID": stock, "SHORTNAME": stock, "CURRENCYID": "RUB", "BOARDID": "TQBR"})
        futures.append(
            {
                "SECID": future,
                "ASSETCODE": stock,
                "LASTTRADEDATE": "2026-03-19",
                "LOTVOLUME": 1,
                "MINSTEP": 0.01,
                "MULTIPLIER": 1,
            }
        )
        include_futures.append(future)
        rows = []
        for ts in (
            "2026-01-01 10:00:00",
            "2026-01-01 10:30:00",
            "2026-01-02 10:00:00",
            "2026-01-02 10:30:00",
        ):
            spot = 100.0 + idx * 0.01
            fut = 101.0 + idx * 0.01
            spread = spot - fut
            rows.append(
                {
                    "date": str(pd.to_datetime(ts).date()),
                    "exec_ts": ts,
                    "spot_mid": spot,
                    "future_mid": fut,
                    "pv_div": 0.0,
                    "div_sum": 0.0,
                    "spread_mid": spread,
                    "spread_pct": spread / spot if spot else 0.0,
                    "spot_volume": 1000.0,
                    "future_volume": 1000.0,
                }
            )
        payload = {"schema_version": 1, "series_base": pd.DataFrame(rows), "dividends": []}
        cache_dir = tmp_path / "output" / "intraday_preload_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.to_pickle(payload, cache_dir / f"{stock}_{future}_2026-01-01_2026-01-02_perf.pkl")

    _write_csv(tmp_path / "raw" / "shares.csv", shares)
    _write_csv(tmp_path / "raw" / "futures.csv", futures)
    _write_csv(
        tmp_path / "raw" / "key_rates.csv",
        [
            {"date": "2026-01-01", "rate": 0.1},
            {"date": "2026-01-02", "rate": 0.1},
        ],
    )
    return include_futures


def _request(include_futures: list[str]) -> BacktestRequest:
    payload = BacktestRequest().model_dump(mode="python")
    payload["test"]["start_date"] = date(2026, 1, 1)
    payload["test"]["end_date"] = date(2026, 1, 2)
    payload["execution"]["mode"] = "INTRADAY_MINUTE"
    payload["execution"]["execution_model"] = "MINUTE_REPLAY"
    payload["execution"]["minute_fail_fast"] = True
    payload["strategy"]["signal_exec_lag_days"] = 0
    payload["strategy"]["execution_lag_minutes"] = 20
    payload["strategy"]["execution_max_wait_minutes"] = 360
    payload["strategy"]["min_DTE_entry"] = 1
    payload["strategy"]["close_buffer_days"] = 0
    payload["strategy"]["H_max_days"] = 20
    payload["strategy"]["w_floor"] = 0.5
    payload["strategy"]["w_alpha"] = 0.5
    payload["rates"]["r_cb_annual"] = 0.0
    payload["rates"]["r_fund_annual"] = 0.0
    payload["rates"]["r_disc_annual"] = 0.0
    payload["universe"]["include_futures"] = include_futures
    return BacktestRequest.model_validate(payload)


def test_minute_runtime_25_pairs_under_45_seconds_warm_cache(tmp_path):
    include_futures = _seed_perf_fixture(tmp_path, pairs=25)
    request = _request(include_futures)

    # Warm-up run to emulate warm-cache benchmark.
    evaluate_minute_period_metrics(
        request=request,
        data_dir=tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
    )

    started = time.perf_counter()
    metrics = evaluate_minute_period_metrics(
        request=request,
        data_dir=tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
    )
    elapsed = time.perf_counter() - started

    assert metrics["MinutePairs"] == 25.0
    assert elapsed <= 45.0, f"minute_runtime_too_slow:{elapsed:.3f}s"
