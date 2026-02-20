from __future__ import annotations

import time

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig, UiConfig
from moex_carry.ui.app import create_app


def _build_settings(tmp_path) -> AppSettings:
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/perf-journey.db"),
        ui=UiConfig(),
    )


def _latency_budget_get(client, path: str, budget_sec: float) -> None:
    started = time.perf_counter()
    response = client.get(path)
    elapsed = time.perf_counter() - started
    assert response.status_code == 200, f"unexpected_status:{path}:{response.status_code}"
    assert elapsed <= budget_sec, f"journey_latency_too_slow:{path}:{elapsed:.3f}s"


def test_core_api_journey_under_latency_budget(tmp_path):
    app = create_app(_build_settings(tmp_path))
    client = app.server.test_client()

    _latency_budget_get(client, "/api/v2/signals/active?limit=5", 2.0)
    _latency_budget_get(client, "/api/v2/decisions/view?limit=5", 2.0)
    _latency_budget_get(client, "/api/v2/ops/slo", 2.0)
