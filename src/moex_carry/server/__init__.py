from __future__ import annotations

import argparse
import warnings

from moex_carry.config import load_settings
from moex_carry.ui.app import create_app, run_ui


def create_server_app(settings):
    return create_app(settings)


def run_server(settings) -> None:
    run_ui(settings)


def run_ui_alias(settings) -> None:
    warnings.warn(
        "moex_carry.ui is deprecated; use moex_carry.server instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    run_server(settings)


def main() -> None:
    parser = argparse.ArgumentParser(prog="moex-carry-server")
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    args = parser.parse_args()
    settings = load_settings(args.config)
    run_server(settings)


__all__ = ["create_server_app", "run_server", "run_ui_alias", "main"]
