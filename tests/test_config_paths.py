from pathlib import Path

from moex_carry.config import AppSettings, DataConfig, _repo_root, load_settings, resolve_paths


def test_resolve_paths_anchors_relative_data_dir():
    settings = AppSettings(data=DataConfig(data_dir="data"))
    paths = resolve_paths(settings)
    assert paths.data_dir == _repo_root() / "data"


def test_resolve_paths_keeps_absolute_data_dir(tmp_path: Path):
    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    paths = resolve_paths(settings)
    assert paths.data_dir == tmp_path


def test_load_settings_env_overrides_yaml_nested_fields(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "telegram:",
                "  enabled: false",
                "  bot_token: null",
                "  allowed_user_ids: []",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MOEX_CARRY_TELEGRAM__ENABLED", "true")
    monkeypatch.setenv("MOEX_CARRY_TELEGRAM__BOT_TOKEN", "token-1")
    monkeypatch.setenv("MOEX_CARRY_TELEGRAM__ALLOWED_USER_IDS", "[186419048]")

    settings = load_settings(str(config_path))

    assert settings.telegram.enabled is True
    assert settings.telegram.bot_token == "token-1"
    assert settings.telegram.allowed_user_ids == [186419048]
