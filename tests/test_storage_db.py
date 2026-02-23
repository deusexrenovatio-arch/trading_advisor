from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    release_runtime_lease,
    renew_runtime_lease,
    store_signal_execution,
    try_acquire_runtime_lease,
)


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


def test_init_db_enforces_signal_execution_idempotency_uniqueness(tmp_path):
    db_path = tmp_path / "moex_carry.db"
    settings = AppSettings(database=DatabaseConfig(url=f"sqlite:///{db_path}"))
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        store_signal_execution(
            session,
            datetime(2025, 1, 1, 10, 0, 0),
            {
                "stock": "AAA",
                "future": "AAH6",
                "direction": "cash_and_carry",
                "action": "enter",
                "status": "recorded",
                "idempotency_key": "idem-storage-1",
                "note": "{\"kind\":\"signal_action_v2\",\"idempotency_key\":\"idem-storage-1\"}",
            },
        )

    with pytest.raises(IntegrityError):
        with session_factory() as session:
            store_signal_execution(
                session,
                datetime(2025, 1, 1, 10, 1, 0),
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "direction": "cash_and_carry",
                    "action": "enter",
                    "status": "recorded",
                    "idempotency_key": "idem-storage-1",
                    "note": "{\"kind\":\"signal_action_v2\",\"idempotency_key\":\"idem-storage-1\"}",
                },
            )


def test_runtime_lease_acquire_renew_release(tmp_path):
    db_path = tmp_path / "moex_carry.db"
    settings = AppSettings(database=DatabaseConfig(url=f"sqlite:///{db_path}"))
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        assert try_acquire_runtime_lease(
            session,
            lease_name="signal_refresh_scheduler",
            owner_id="owner-a",
            ttl_sec=60,
        )

    with session_factory() as session:
        assert not try_acquire_runtime_lease(
            session,
            lease_name="signal_refresh_scheduler",
            owner_id="owner-b",
            ttl_sec=60,
        )

    with session_factory() as session:
        assert renew_runtime_lease(
            session,
            lease_name="signal_refresh_scheduler",
            owner_id="owner-a",
            ttl_sec=60,
        )

    with session_factory() as session:
        assert release_runtime_lease(
            session,
            lease_name="signal_refresh_scheduler",
            owner_id="owner-a",
        )

    with session_factory() as session:
        assert try_acquire_runtime_lease(
            session,
            lease_name="signal_refresh_scheduler",
            owner_id="owner-b",
            ttl_sec=60,
        )
