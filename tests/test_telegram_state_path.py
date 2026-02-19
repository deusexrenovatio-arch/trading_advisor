from __future__ import annotations

from moex_carry.integrations.telegram_worker import TelegramWorker


def test_telegram_state_path_anchors_data_relative_to_data_dir(tmp_path):
    data_dir = tmp_path / "shared-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    resolved = TelegramWorker._resolve_state_path("./data/telegram/bot_state.json", data_dir)

    assert resolved == (data_dir / "telegram" / "bot_state.json").resolve()


def test_telegram_state_path_anchors_generic_relative_to_data_dir(tmp_path):
    data_dir = tmp_path / "shared-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    resolved = TelegramWorker._resolve_state_path("telegram/bot_state.json", data_dir)

    assert resolved == (data_dir / "telegram" / "bot_state.json").resolve()
