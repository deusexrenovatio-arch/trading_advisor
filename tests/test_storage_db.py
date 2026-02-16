from __future__ import annotations

from sqlalchemy import text

from moex_carry.config import AppSettings, DatabaseConfig
from moex_carry.storage.db import create_engine_from_settings, init_db


def test_create_engine_from_settings_creates_sqlite_parent_dir(tmp_path):
    db_path = tmp_path / "nested" / "db" / "moex_carry.db"
    settings = AppSettings(database=DatabaseConfig(url=f"sqlite:///{db_path}"))

    assert not db_path.parent.exists()

    engine = create_engine_from_settings(settings)
    init_db(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1

    assert db_path.parent.exists()
    assert db_path.exists()
