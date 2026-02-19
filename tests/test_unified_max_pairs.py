from __future__ import annotations

from moex_carry.config import AppSettings
from moex_carry.pipeline import _resolve_unified_max_pairs


def test_resolve_unified_max_pairs_defaults_to_full_universe_when_not_configured():
    settings = AppSettings()
    settings.strategy.max_pairs = 25
    settings.ui.signal_refresh_max_pairs = None

    assert _resolve_unified_max_pairs(settings, None) is None


def test_resolve_unified_max_pairs_uses_ui_cap_when_configured():
    settings = AppSettings()
    settings.strategy.max_pairs = 25
    settings.ui.signal_refresh_max_pairs = 40

    assert _resolve_unified_max_pairs(settings, None) == 40


def test_resolve_unified_max_pairs_prefers_explicit_argument():
    settings = AppSettings()
    settings.ui.signal_refresh_max_pairs = 40

    assert _resolve_unified_max_pairs(settings, 12) == 12
