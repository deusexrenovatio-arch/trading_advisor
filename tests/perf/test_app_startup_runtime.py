from __future__ import annotations

import time

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig, UiConfig
from moex_carry.ui.app import create_app


def _build_settings(tmp_path) -> AppSettings:
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/perf-startup.db"),
        ui=UiConfig(),
    )


def test_app_startup_under_12_seconds(tmp_path):
    settings = _build_settings(tmp_path)
    started = time.perf_counter()
    app = create_app(settings)
    elapsed = time.perf_counter() - started

    assert app is not None
    assert elapsed <= 12.0, f"app_startup_too_slow:{elapsed:.3f}s"
