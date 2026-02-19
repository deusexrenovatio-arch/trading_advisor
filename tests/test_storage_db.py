from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
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



def test_create_engine_from_settings_anchors_relative_default_db_to_data_dir(tmp_path):
    data_dir = tmp_path / "shared-data"
    settings = AppSettings(
        data=DataConfig(data_dir=str(data_dir)),
        database=DatabaseConfig(url="sqlite:///./data/moex_carry.db"),
    )

    engine = create_engine_from_settings(settings)
    init_db(engine)

    db_path = Path(str(engine.url.database)).resolve()
    assert db_path == (data_dir / "moex_carry.db").resolve()
    assert db_path.exists()
