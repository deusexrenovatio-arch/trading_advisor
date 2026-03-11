from __future__ import annotations

import warnings
from typing import Any

from moex_carry.ui import app as legacy_ui_app

SIGNAL_METRIC_CONTRACT_KEYS = legacy_ui_app.SIGNAL_METRIC_CONTRACT_KEYS


def create_server_app(settings: Any):
    return legacy_ui_app.create_app(settings)


def run_server(settings: Any) -> None:
    legacy_ui_app.run_ui(settings)


def create_app(settings: Any):
    warnings.warn(
        "moex_carry.server.app.create_app is deprecated; use create_server_app.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_server_app(settings)


def run_ui(settings: Any) -> None:
    warnings.warn(
        "moex_carry.server.app.run_ui is deprecated; use run_server.",
        DeprecationWarning,
        stacklevel=2,
    )
    run_server(settings)


def __getattr__(name: str) -> Any:
    return getattr(legacy_ui_app, name)


__all__ = [
    "SIGNAL_METRIC_CONTRACT_KEYS",
    "create_server_app",
    "run_server",
    "create_app",
    "run_ui",
]
