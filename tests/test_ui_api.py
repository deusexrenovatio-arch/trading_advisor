from datetime import date

import pandas as pd

from moex_carry.config import AppSettings, DataConfig
from moex_carry.ui.app import create_app
import moex_carry.ui.app as ui_app


def _write_csv(path, rows):
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)


def test_api_endpoints_return_rows(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "top_pairs.csv",
        [
            {
                "stock": "AAA",
                "stock_name": "Alpha",
                "future": "AAH6",
                "spread_pct": 0.01,
                "rtc_pct": 0.002,
                "floor_rate_annual": 0.12,
                "score_floor": 0.01,
                "avg_trade_return_annual_recent": 0.2,
                "total_score": 0.02,
                "decision": "ENTER_OK",
                "signal_action": "enter",
                "signal_direction": "cash_and_carry",
                "signal_score": 0.1,
            }
        ],
    )
    _write_csv(
        output_dir / "signals.csv",
        [
            {
                "stock": "AAA",
                "stock_name": "Alpha",
                "future": "AAH6",
                "signal_action": "enter",
                "signal_direction": "cash_and_carry",
                "signal_score": 0.1,
                "spread_pct": 0.01,
                "floor_rate_annual": 0.12,
            }
        ],
    )
    _write_csv(
        output_dir / "backtest_summary.csv",
        [
            {
                "cagr": 0.08,
                "max_drawdown": -0.03,
                "sharpe": 1.1,
                "hit_rate": 0.55,
                "turnover": 8.0,
            }
        ],
    )

    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    app = create_app(settings)
    client = app.server.test_client()

    top_pairs = client.get("/api/top-pairs?limit=5")
    assert top_pairs.status_code == 200
    top_pairs_data = top_pairs.get_json()
    assert isinstance(top_pairs_data, list)
    assert len(top_pairs_data) == 1
    assert top_pairs_data[0]["stock"] == "AAA"

    signals = client.get("/api/signals?limit=5")
    assert signals.status_code == 200
    signals_data = signals.get_json()
    assert isinstance(signals_data, list)
    assert len(signals_data) == 1
    assert signals_data[0]["signal_action"] == "enter"

    backtests = client.get("/api/backtests?limit=5")
    assert backtests.status_code == 200
    backtests_data = backtests.get_json()
    assert isinstance(backtests_data, list)
    assert len(backtests_data) == 1
    assert backtests_data[0]["sharpe"] == 1.1


def test_spread_series_endpoint_uses_builder(tmp_path, monkeypatch):
    df = pd.DataFrame(
        [
            {
                "date": date(2024, 1, 1),
                "spot_mid": 100.0,
                "future_mid": 101.5,
                "spread_mid": 2.0,
                "spread_pct": 0.02,
                "entry_flag": True,
                "exit_flag": False,
            }
        ]
    )
    monkeypatch.setattr(ui_app, "build_spread_series", lambda *args, **kwargs: df)
    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    app = create_app(settings)
    client = app.server.test_client()

    response = client.get("/api/spread-series?stock=AAA&future=AAH6&window_days=60")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["spread_mid"] == 2.0
    assert data[0]["date"] == "2024-01-01"
    assert data[0]["spread_pct"] == 0.02
    assert data[0]["entry_flag"] is True
