from __future__ import annotations

from importlib import import_module
from types import ModuleType
import sys
import warnings
from typing import Any

_SYNC_EXCLUDE = {
    "Any",
    "SIGNAL_METRIC_CONTRACT_KEYS",
    "create_app",
    "create_server_app",
    "import_module",
    "run_server",
    "run_ui",
    "warnings",
}


def _legacy_ui_app():
    return import_module("moex_carry.ui.app")


def _sync_server_overrides_to_legacy() -> None:
    legacy_ui_app = _legacy_ui_app()
    for name, value in list(globals().items()):
        if name.startswith("_") or name in _SYNC_EXCLUDE:
            continue
        if not hasattr(legacy_ui_app, name):
            continue
        if getattr(legacy_ui_app, name) is value:
            continue
        setattr(legacy_ui_app, name, value)


SIGNAL_METRIC_CONTRACT_KEYS = _legacy_ui_app().SIGNAL_METRIC_CONTRACT_KEYS


def create_server_app(settings: Any):
    _sync_server_overrides_to_legacy()
    legacy_ui_app = _legacy_ui_app()
    return legacy_ui_app.create_app(settings)


def run_server(settings: Any) -> None:
    _sync_server_overrides_to_legacy()
    legacy_ui_app = _legacy_ui_app()
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
    legacy_ui_app = _legacy_ui_app()
    return getattr(legacy_ui_app, name)


class _ServerAppModule(ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if name.startswith("_") or name in _SYNC_EXCLUDE:
            return
        legacy_ui_app = _legacy_ui_app()
        if hasattr(legacy_ui_app, name):
            setattr(legacy_ui_app, name, value)


sys.modules[__name__].__class__ = _ServerAppModule


__all__ = [
    "SIGNAL_METRIC_CONTRACT_KEYS",
    "create_server_app",
    "run_server",
    "create_app",
    "run_ui",
]
