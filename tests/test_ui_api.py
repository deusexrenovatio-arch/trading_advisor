from datetime import date

import pandas as pd
import requests

from moex_carry.config import AppSettings, DataConfig
from moex_carry.ui.app import SIGNAL_METRIC_CONTRACT_KEYS, create_app
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
                "signal_metrics": {
                    "entry_spread_pct_min": 0.009,
                    "tp_spread_pct_level": 0.02,
                },
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
    assert "signal_metrics" in top_pairs_data[0]
    assert "score_model" in top_pairs_data[0]
    assert "score_exec_probability" in top_pairs_data[0]
    assert "score_exec_probability" in top_pairs_data[0]["signal_metrics"]

    signals = client.get("/api/signals?limit=5")
    assert signals.status_code == 200
    signals_data = signals.get_json()
    assert isinstance(signals_data, list)
    assert len(signals_data) == 1
    assert signals_data[0]["signal_action"] == "enter"
    assert signals_data[0]["entry_spread_pct_min"] == 0.009
    assert signals_data[0]["sl_spread_pct_level"] is None
    for key in SIGNAL_METRIC_CONTRACT_KEYS:
        assert key in signals_data[0]
        assert key in signals_data[0]["signal_metrics"]

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


class _FakeMoexClientPretrade:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def get_marketdata(self, _engine: str, _market: str, _board: str, secid: str):
        if secid == "AAA":
            return [
                {
                    "BID": 100.0,
                    "OFFER": 100.1,
                    "LAST": 100.05,
                    "VOLTODAY": 1000,
                    "NUMTRADES": 2000,
                    "SYSTIME": "2026-02-09 16:40:00",
                }
            ]
        return [
            {
                "BID": 1010.0,
                "OFFER": 1012.0,
                "LAST": 1011.0,
                "VOLTODAY": 100,
                "NUMTRADES": 1000,
                "SYSTIME": "2026-02-09 16:40:30",
            }
        ]


class _FakeMoexClientPretradeTransportFail:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def get_marketdata(self, _engine: str, _market: str, _board: str, _secid: str):
        raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")


def test_pretrade_check_endpoint_returns_price_bands_and_volume_gate(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    raw_dir = tmp_path / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "top_pairs.csv",
        [
            {
                "stock": "AAA",
                "future": "AAH6",
                "spot": 100.0,
                "future_price": 101.0,
                "spread_mid": -1.0,
                "signal_direction": "cash_and_carry",
            }
        ],
    )
    _write_csv(
        raw_dir / "futures.csv",
        [
            {
                "SECID": "AAH6",
                "LOTVOLUME": 10,
                "MULTIPLIER": 1,
            }
        ],
    )
    monkeypatch.setattr(ui_app, "MoexIssClient", _FakeMoexClientPretrade)

    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    app = create_app(settings)
    client = app.server.test_client()

    response = client.get(
        "/api/pretrade/check?stock=AAA&future=AAH6&snapshots=1&min_hits=1&poll_sec=0"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "PLACE"
    assert payload["ready_to_place"] is True
    assert "require_live_quotes_for_legs" not in payload["params"]
    assert payload["params"]["stock_eps"] == 0.0015
    assert payload["params"]["future_eps"] == 0.0015
    assert payload["params"]["spread_eps"] == 0.0015
    assert payload["gates"]["quote_pass"] is True
    assert payload["gates"]["fut_quote_pass"] is True
    assert payload["gates"]["stock_volume_pass"] is True
    assert payload["gates"]["fut_volume_pass"] is True
    assert "order_price_bands" in payload
    assert "future_sell_min_contract" in payload["order_price_bands"]


def test_pretrade_check_endpoint_fail_opens_on_iss_transport_error(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    raw_dir = tmp_path / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "top_pairs.csv",
        [
            {
                "stock": "AAA",
                "future": "AAH6",
                "spot": 100.0,
                "future_price": 101.0,
                "spread_mid": -1.0,
                "signal_direction": "cash_and_carry",
            }
        ],
    )
    _write_csv(
        raw_dir / "futures.csv",
        [
            {
                "SECID": "AAH6",
                "LOTVOLUME": 10,
                "MULTIPLIER": 1,
            }
        ],
    )
    monkeypatch.setattr(ui_app, "MoexIssClient", _FakeMoexClientPretradeTransportFail)

    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    app = create_app(settings)
    client = app.server.test_client()

    response = client.get(
        "/api/pretrade/check?stock=AAA&future=AAH6&snapshots=1&min_hits=1&poll_sec=0"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "PLACE"
    assert payload["ready_to_place"] is True
    assert payload["manual_confirm_required"] is True
    assert payload["degraded"] is True
    assert payload["gate_policy"]["mode"] == "iss_manual_drive_transport_fail_open"
    assert "iss_transport_error" in payload["advisory_reasons"]
    assert payload["params"]["stock_eps"] == 0.0015
    assert payload["params"]["future_eps"] == 0.0015
    assert payload["params"]["spread_eps"] == 0.0015
    assert "order_price_bands" in payload
    assert "future_sell_min_contract" in payload["order_price_bands"]
