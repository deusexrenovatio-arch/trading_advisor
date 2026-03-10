from __future__ import annotations

import warnings

from moex_carry.server import create_server_app, run_server


def create_app(settings):
    warnings.warn(
        "moex_carry.ui.create_app is deprecated; use moex_carry.server.create_server_app.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_server_app(settings)


def run_ui(settings) -> None:
    warnings.warn(
        "moex_carry.ui.run_ui is deprecated; use moex_carry.server.run_server.",
        DeprecationWarning,
        stacklevel=2,
    )
    run_server(settings)


__all__ = ["create_app", "run_ui"]
