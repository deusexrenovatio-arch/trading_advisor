from pathlib import Path

import moex_carry.config as config_module
from moex_carry.config import load_settings


def _write_yaml(path: Path, payload: str) -> None:
    path.write_text(payload, encoding="utf-8")


def test_load_settings_merges_default_with_override(tmp_path, monkeypatch):
    default_path = tmp_path / "default.yaml"
    override_path = tmp_path / "override.yaml"
    _write_yaml(
        default_path,
        """
ui:
  port: 8050
  signal_refresh_enabled: true
spread_carry_alpha:
  price_source: "common_minute_close"
  execution_lag_minutes: 30
""".strip(),
    )
    _write_yaml(
        override_path,
        """
ui:
  port: 8060
data:
  data_dir: "/tmp/data"
""".strip(),
    )
    monkeypatch.setattr(config_module, "_default_config_path", lambda: default_path)

    settings = load_settings(str(override_path))

    assert settings.ui.port == 8060
    assert settings.ui.signal_refresh_enabled is True
    assert settings.spread_carry_alpha.price_source == "common_minute_close"
    assert settings.spread_carry_alpha.execution_lag_minutes == 30
    assert settings.data.data_dir == "/tmp/data"


def test_load_settings_uses_default_when_override_missing(tmp_path, monkeypatch):
    default_path = tmp_path / "default.yaml"
    _write_yaml(
        default_path,
        """
ui:
  port: 8051
spread_carry_alpha:
  signal_exec_lag_days: 0
""".strip(),
    )
    missing_override = tmp_path / "missing.yaml"
    monkeypatch.setattr(config_module, "_default_config_path", lambda: default_path)

    settings = load_settings(str(missing_override))

    assert settings.ui.port == 8051
    assert settings.spread_carry_alpha.signal_exec_lag_days == 0

def test_load_settings_supports_signal_engine_section(tmp_path, monkeypatch):
    default_path = tmp_path / "default.yaml"
    _write_yaml(
        default_path,
        """
signal_engine:
  runtime_adapter:
    enabled: true
  gate:
    min_expected_return_ticks: 1.5
  probability:
    tier_thresholds:
      mid: 120
      high: 600
""".strip(),
    )
    monkeypatch.setattr(config_module, "_default_config_path", lambda: default_path)

    settings = load_settings()

    assert settings.signal_engine.runtime_adapter.enabled is True
    assert settings.signal_engine.gate.min_expected_return_ticks == 1.5
    assert settings.signal_engine.probability.tier_thresholds.mid == 120
    assert settings.signal_engine.probability.tier_thresholds.high == 600
