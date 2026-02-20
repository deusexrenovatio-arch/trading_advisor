
import pandas as pd

from moex_carry.config import AppSettings, DataConfig
from moex_carry.contracts.strategy_test import BacktestRequest, ForwardTestRequest
from moex_carry.ui.app import create_app


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _seed_history(tmp_path):
    raw_dir = tmp_path / "raw"
    _write_csv(
        raw_dir / "shares.csv",
        [
            {"SECID": "AAA", "SHORTNAME": "Alpha", "CURRENCYID": "RUB", "BOARDID": "TQBR"},
        ],
    )
    _write_csv(
        raw_dir / "futures.csv",
        [
            {
                "SECID": "AAA_F",
                "ASSETCODE": "AAA",
                "LASTTRADEDATE": "2025-02-01",
                "LOTVOLUME": 1,
                "MINSTEP": 1,
                "MULTIPLIER": 1,
            }
        ],
    )
    _write_csv(
        raw_dir / "key_rates.csv",
        [
            {"date": "2025-01-01", "rate": 0.1},
            {"date": "2025-01-02", "rate": 0.1},
        ],
    )
    shares_dir = tmp_path / "history" / "candles" / "shares"
    futures_dir = tmp_path / "history" / "candles" / "futures"
    _write_csv(
        shares_dir / "AAA.csv",
        [
            {"date": "2025-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"date": "2025-01-02", "open": 101, "high": 102, "low": 100, "close": 101, "volume": 900},
            {"date": "2025-01-03", "open": 102, "high": 103, "low": 101, "close": 102, "volume": 800},
        ],
    )
    _write_csv(
        futures_dir / "AAA_F.csv",
        [
            {"date": "2025-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 500},
            {"date": "2025-01-02", "open": 101, "high": 102, "low": 100, "close": 101, "volume": 450},
            {"date": "2025-01-03", "open": 102, "high": 103, "low": 101, "close": 102, "volume": 400},
        ],
    )


def _seed_history_long(tmp_path, days: int = 220):
    raw_dir = tmp_path / "raw"
    _write_csv(
        raw_dir / "shares.csv",
        [
            {"SECID": "AAA", "SHORTNAME": "Alpha", "CURRENCYID": "RUB", "BOARDID": "TQBR"},
        ],
    )
    _write_csv(
        raw_dir / "futures.csv",
        [
            {
                "SECID": "AAA_F",
                "ASSETCODE": "AAA",
                "LASTTRADEDATE": "2026-12-31",
                "LOTVOLUME": 1,
                "MINSTEP": 1,
                "MULTIPLIER": 1,
            }
        ],
    )
    rows_rates = []
    rows_stock = []
    rows_fut = []
    base = pd.Timestamp("2025-01-01")
    for idx in range(days):
        day = (base + pd.Timedelta(days=idx)).date().isoformat()
        price = 100 + idx * 0.1
        rows_rates.append({"date": day, "rate": 0.1})
        rows_stock.append({"date": day, "open": price, "high": price + 1, "low": price - 1, "close": price, "volume": 1000})
        rows_fut.append({"date": day, "open": price, "high": price + 1, "low": price - 1, "close": price, "volume": 500})
    _write_csv(raw_dir / "key_rates.csv", rows_rates)
    shares_dir = tmp_path / "history" / "candles" / "shares"
    futures_dir = tmp_path / "history" / "candles" / "futures"
    _write_csv(shares_dir / "AAA.csv", rows_stock)
    _write_csv(futures_dir / "AAA_F.csv", rows_fut)


def _build_backtest_payload():
    payload = BacktestRequest().model_dump(mode="json")
    payload["test"]["start_date"] = "2025-01-01"
    payload["test"]["end_date"] = "2025-01-03"
    payload["strategy"]["min_DTE_entry"] = 1
    payload["strategy"]["close_buffer_days"] = 0
    payload["strategy"]["H_max_days"] = 1
    payload["strategy"]["w_floor"] = 1.0
    payload["strategy"]["w_alpha"] = 0.0
    payload["rates"]["r_cb_annual"] = 0.0
    payload["rates"]["r_fund_annual"] = 0.0
    payload["rates"]["r_disc_annual"] = 0.0
    payload["execution"]["half_spread_bps"] = 0.0
    payload["execution"]["slip_stock_bps"] = 0.0
    payload["execution"]["slip_fut_bps"] = 0.0
    payload["costs"]["fee_stock_bps"] = 0.0
    payload["costs"]["fee_fut_per_contract"] = 0.0
    return payload


def test_backtest_run_api_handles_precompute(tmp_path):
    _seed_history(tmp_path)
    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    app = create_app(settings)
    client = app.server.test_client()

    payload = _build_backtest_payload()
    payload["execution"]["pair_workers"] = 2
    response = client.post("/api/backtest/run", json={**payload, "precompute": True})
    assert response.status_code == 200
    data = response.get_json()
    assert "summary_metrics" in data
    assert "equity_curve" in data
    assert "trades" in data
    assert "fill_quality_summary" in data
    assert "execution_model" in data
    assert int(data["execution_model"]["pair_workers"]) == 2

    response = client.post("/api/backtest/run", json={**payload, "precompute": False})
    assert response.status_code == 200
    data = response.get_json()
    assert "summary_metrics" in data
    assert "fill_quality_summary" in data
    assert "execution_model" in data
    assert int(data["execution_model"]["pair_workers"]) == 2

    response = client.post(
        "/api/backtest/run",
        json={**payload, "precompute": False, "compute_fill_quality": False},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["fill_quality_summary"] is None


def test_backtest_run_api_validation_error(tmp_path):
    _seed_history(tmp_path)
    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    app = create_app(settings)
    client = app.server.test_client()

    response = client.post("/api/backtest/run", json={"test": {"start_date": "bad-date"}})
    assert response.status_code == 400


def test_forward_start_and_status(tmp_path):
    _seed_history(tmp_path)
    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    app = create_app(settings)
    client = app.server.test_client()

    payload = ForwardTestRequest().model_dump(mode="json")
    payload["test"]["start_date"] = "2025-01-01"
    payload["test"]["end_date"] = "2025-01-03"
    response = client.post("/api/forward/start", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    run_id = data.get("run_id")
    assert run_id

    status = client.get("/api/forward/status")
    assert status.status_code == 200
    status_data = status.get_json()
    assert status_data.get("run_id") == run_id
    assert "state" in status_data


def test_forward_start_accepts_intraday_execution_mode(tmp_path):
    _seed_history(tmp_path)
    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    app = create_app(settings)
    client = app.server.test_client()

    payload = ForwardTestRequest().model_dump(mode="json")
    payload["test"]["start_date"] = "2025-01-01"
    payload["test"]["end_date"] = "2025-01-03"
    payload["execution"]["mode"] = "INTRADAY_MINUTE"
    payload["strategy"]["execution_lag_minutes"] = 20
    response = client.post("/api/forward/start", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data.get("run_id")


def test_hpo_run_accepts_intraday_execution_mode(tmp_path):
    _seed_history_long(tmp_path)
    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    app = create_app(settings)
    client = app.server.test_client()

    base = _build_backtest_payload()
    base["test"]["start_date"] = "2025-01-01"
    base["test"]["end_date"] = "2025-08-01"
    base["execution"]["mode"] = "INTRADAY_MINUTE"
    base["strategy"]["execution_lag_minutes"] = 20
    payload = {
        "request": {
            "base": base,
            "optimization": {"max_trials": 1},
        },
        "precompute": True,
    }
    response = client.post("/api/hpo/run", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data.get("run_id")
