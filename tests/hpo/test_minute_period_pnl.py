from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.hpo.minute_period_pnl import evaluate_minute_period_metrics


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _seed_raw(tmp_path: Path) -> None:
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


def _seed_minute_cache(tmp_path: Path, *, future: str = "AAH6") -> None:
    rows: list[dict[str, object]] = []
    for ts in ("2026-01-01 10:00:00", "2026-01-01 10:30:00", "2026-01-02 10:00:00", "2026-01-02 10:30:00"):
        spot = 100.0
        fut = 101.0
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
                "future_volume": 800.0,
            }
        )
    payload = {
        "schema_version": 1,
        "series_base": pd.DataFrame(rows),
        "dividends": [],
    }
    cache_dir = tmp_path / "output" / "intraday_preload_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(payload, cache_dir / f"AAA_{future}_2026-01-01_2026-01-02_fixture.pkl")


def _base_request(*, fail_fast: bool, include_futures: list[str] | None = None) -> BacktestRequest:
    payload = BacktestRequest().model_dump(mode="python")
    payload["test"]["start_date"] = date(2026, 1, 1)
    payload["test"]["end_date"] = date(2026, 1, 2)
    payload["execution"]["mode"] = "INTRADAY_MINUTE"
    payload["execution"]["execution_model"] = "MINUTE_REPLAY"
    payload["execution"]["minute_fail_fast"] = fail_fast
    payload["strategy"]["execution_lag_minutes"] = 20
    payload["strategy"]["signal_exec_lag_days"] = 0
    payload["strategy"]["execution_max_wait_minutes"] = 360
    payload["strategy"]["min_DTE_entry"] = 1
    payload["strategy"]["close_buffer_days"] = 0
    payload["strategy"]["H_max_days"] = 20
    payload["strategy"]["w_floor"] = 0.5
    payload["strategy"]["w_alpha"] = 0.5
    payload["rates"]["r_cb_annual"] = 0.0
    payload["rates"]["r_fund_annual"] = 0.0
    payload["rates"]["r_disc_annual"] = 0.0
    if include_futures is not None:
        payload["universe"]["include_futures"] = include_futures
    return BacktestRequest.model_validate(payload)


def test_minute_period_pnl_metrics_success(tmp_path):
    _seed_raw(tmp_path)
    _seed_minute_cache(tmp_path, future="AAH6")
    request = _base_request(fail_fast=True, include_futures=["AAH6"])
    metrics = evaluate_minute_period_metrics(
        request=request,
        data_dir=tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
    )
    assert "ExcessAnn" in metrics
    assert "MinutePairs" in metrics
    assert metrics["MinutePairs"] >= 1


def test_minute_period_pnl_respects_fail_fast(tmp_path):
    _seed_raw(tmp_path)
    _seed_minute_cache(tmp_path, future="AAH6")

    request_fail_fast = _base_request(fail_fast=True)
    with pytest.raises(ValueError, match="minute_fail_fast_missing_series"):
        evaluate_minute_period_metrics(
            request=request_fail_fast,
            data_dir=tmp_path,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
        )

    request_non_blocking = _base_request(fail_fast=False)
    metrics = evaluate_minute_period_metrics(
        request=request_non_blocking,
        data_dir=tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
    )
    assert metrics["MinutePairs"] == 1.0
    assert metrics["MinutePairsFailed"] >= 1.0


def test_minute_period_pnl_parallel_workers_consistency(tmp_path):
    _seed_raw(tmp_path)
    _seed_minute_cache(tmp_path, future="AAH6")
    _seed_minute_cache(tmp_path, future="AAM6")

    request_single = _base_request(fail_fast=True, include_futures=["AAH6", "AAM6"])
    request_single.execution.pair_workers = 1
    metrics_single = evaluate_minute_period_metrics(
        request=request_single,
        data_dir=tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
    )

    request_parallel = _base_request(fail_fast=True, include_futures=["AAH6", "AAM6"])
    request_parallel.execution.pair_workers = 4
    metrics_parallel = evaluate_minute_period_metrics(
        request=request_parallel,
        data_dir=tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
    )

    keys = [
        "MinutePairs",
        "MinutePairsOk",
        "MinutePairsFailed",
        "MinuteExcessAnnMean",
        "MinuteRealizedAnnualMean",
        "MinuteUnfilledEntryRateMean",
        "MinuteForcedExitRateMean",
        "MinuteIdleRatioMean",
        "MinuteTradesClosedTotal",
    ]
    for key in keys:
        assert float(metrics_parallel[key]) == pytest.approx(float(metrics_single[key]))
