from pathlib import Path

import moex_carry.config as config_module
from moex_carry.config import SignalEngineMorningExecutionConfig, load_settings


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


def test_load_settings_merges_runtime_adapter_override_file(tmp_path, monkeypatch):
    default_path = tmp_path / "default.yaml"
    override_path = tmp_path / "override.yaml"
    _write_yaml(
        default_path,
        """
signal_engine:
  runtime_adapter:
    enabled: false
    override_signal_fields: true
""".strip(),
    )
    _write_yaml(
        override_path,
        """
signal_engine:
  runtime_adapter:
    enabled: true
    override_signal_fields: false
""".strip(),
    )
    monkeypatch.setattr(config_module, "_default_config_path", lambda: default_path)

    settings = load_settings(str(override_path))

    assert settings.signal_engine.runtime_adapter.enabled is True
    assert settings.signal_engine.runtime_adapter.override_signal_fields is False


def test_load_settings_supports_signal_engine_morning_plan_section(tmp_path, monkeypatch):
    default_path = tmp_path / "default.yaml"
    _write_yaml(
        default_path,
        """
signal_engine:
  morning_plan:
    calendar:
      forbid_new_positions_margin_min: 7
    setups:
      max_setups_per_instrument: 1
      rr_default: 2.0
      stop_model: volatility
      entry_range_half_width_ticks: 3
    news_gate:
      enabled: true
      lookback_minutes: 240
      reduce_max_setups: 1
      commodity_map:
        BR: BRN
""".strip(),
    )
    monkeypatch.setattr(config_module, "_default_config_path", lambda: default_path)

    settings = load_settings()

    assert settings.signal_engine.morning_plan.calendar.forbid_new_positions_margin_min == 7
    assert settings.signal_engine.morning_plan.setups.max_setups_per_instrument == 1
    assert settings.signal_engine.morning_plan.setups.rr_default == 2.0
    assert settings.signal_engine.morning_plan.setups.stop_model == "volatility"
    assert settings.signal_engine.morning_plan.setups.entry_range_half_width_ticks == 3
    assert settings.signal_engine.morning_plan.setups.min_target_return_pct == 0.5
    assert settings.signal_engine.morning_plan.news_gate.enabled is True
    assert settings.signal_engine.morning_plan.news_gate.lookback_minutes == 240
    assert settings.signal_engine.morning_plan.news_gate.reduce_max_setups == 1
    assert settings.signal_engine.morning_plan.news_gate.commodity_map["BR"] == "BRN"


def test_signal_engine_morning_execution_defaults_preserve_h4_baseline():
    cfg = SignalEngineMorningExecutionConfig()

    assert cfg.break_even_rr == 0.1
    assert cfg.break_even_buffer_ticks == 2
    assert cfg.tp_rr == 0.6
    assert cfg.sl_rr == 2.5
    assert cfg.max_holding_minutes == 180
    assert cfg.max_profit_rr == 0.0
    assert cfg.max_profit_ticks == 0
    assert cfg.trail_activation_rr == 0.1
    assert cfg.trail_offset_ticks == 2
    assert cfg.same_bar_policy == "open_direction"
    assert cfg.limit_entry_improve_ticks == 1
    assert cfg.limit_fallback_to_market_minutes == 10
    assert cfg.limit_fallback_slip_ticks == 1
    assert cfg.tp_cost_mult == 0.2
    assert cfg.sl_cost_mult == 0.7
    assert cfg.exit_cost_mult == 0.4
