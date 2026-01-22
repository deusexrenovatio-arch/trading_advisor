from datetime import datetime

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_open_executions,
    store_signal_execution,
    store_signal_history,
    store_signal_run,
)
from moex_carry.ui.app import create_app


def _seed_signal_run(session, run_id: str, timestamp: datetime, records: list[dict[str, object]]):
    store_signal_run(session, run_id, timestamp, params={"source": "test"})
    store_signal_history(session, run_id, timestamp, records)


def _build_settings(tmp_path):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/signals.db"),
    )


def test_signals_history_endpoint_returns_rows(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_run(
            session,
            "run-1",
            datetime(2025, 1, 1, 12, 0, 0),
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.2,
                    "signal_reasons": ["stat_confirmed"],
                    "signal_metrics": {"zscore": 2.1},
                }
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()
    response = client.get("/api/signals/history?limit=10")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["stock"] == "AAA"
    assert data[0]["signal_action"] == "enter"


def test_signals_history_date_range_is_inclusive(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_run(
            session,
            "run-1",
            datetime(2025, 1, 12, 19, 6, 54),
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.2,
                    "signal_reasons": ["stat_confirmed"],
                    "signal_metrics": {"zscore": 2.1},
                }
            ],
        )
        _seed_signal_run(
            session,
            "run-2",
            datetime(2025, 1, 13, 9, 0, 0),
            [
                {
                    "stock": "BBB",
                    "future": "BBH6",
                    "signal_action": "exit",
                    "signal_direction": "reverse",
                    "signal_score": 0.1,
                    "signal_reasons": ["zscore_revert"],
                    "signal_metrics": {"zscore": 0.4},
                }
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()
    response = client.get("/api/signals/history?from=2025-01-12&to=2025-01-12")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["stock"] == "AAA"


def test_signals_history_filters_by_stock_future_action(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_run(
            session,
            "run-1",
            datetime(2025, 1, 10, 9, 0, 0),
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.2,
                    "signal_reasons": [],
                    "signal_metrics": {},
                }
            ],
        )
        _seed_signal_run(
            session,
            "run-2",
            datetime(2025, 1, 10, 10, 0, 0),
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "exit",
                    "signal_direction": "reverse",
                    "signal_score": 0.1,
                    "signal_reasons": [],
                    "signal_metrics": {},
                },
                {
                    "stock": "BBB",
                    "future": "BBH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.3,
                    "signal_reasons": [],
                    "signal_metrics": {},
                },
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()
    response = client.get("/api/signals/history?stock=AAA&future=AAH6&signal_action=enter&limit=10")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["stock"] == "AAA"
    assert data[0]["future"] == "AAH6"
    assert data[0]["signal_action"] == "enter"


def test_signals_execute_endpoint_persists_execution(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    app = create_app(settings)
    client = app.server.test_client()

    response = client.post(
        "/api/signals/execute",
        json={
            "stock": "AAA",
            "future": "AAH6",
            "direction": "cash_and_carry",
            "action": "enter",
            "price": 100.5,
            "quantity": 2,
            "side": "buy",
            "status": "filled",
            "note": "manual",
        },
    )
    assert response.status_code == 200

    session_factory = create_session_factory(engine)
    with session_factory() as session:
        rows = load_open_executions(session)
        assert len(rows) == 1
        assert rows[0].stock_secid == "AAA"


def test_signals_executions_endpoint_returns_rows(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        store_signal_execution(
            session,
            datetime(2025, 1, 1, 12, 30, 0),
            {
                "stock": "AAA",
                "future": "AAH6",
                "direction": "cash_and_carry",
                "action": "enter",
                "price": 101.0,
                "quantity": 1,
                "side": "buy",
                "status": "filled",
                "note": "manual",
            },
        )

    app = create_app(settings)
    client = app.server.test_client()
    response = client.get("/api/signals/executions?stock=AAA&future=AAH6&limit=5")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["stock"] == "AAA"


def test_signals_active_includes_open_positions(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_run(
            session,
            "run-1",
            datetime(2025, 1, 1, 12, 0, 0),
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "exit",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.1,
                    "signal_reasons": [],
                    "signal_metrics": {},
                },
                {
                    "stock": "BBB",
                    "future": "BBH6",
                    "signal_action": "enter",
                    "signal_direction": "reverse",
                    "signal_score": 0.05,
                    "signal_reasons": [],
                    "signal_metrics": {},
                },
            ],
        )
        store_signal_execution(
            session,
            datetime(2025, 1, 1, 12, 30, 0),
            {
                "stock": "AAA",
                "future": "AAH6",
                "direction": "cash_and_carry",
                "action": "enter",
                "price": 101.0,
                "quantity": 1,
                "side": "buy",
                "status": "filled",
                "note": None,
            },
        )

    app = create_app(settings)
    client = app.server.test_client()
    response = client.get("/api/signals/active")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 2
    open_row = next(row for row in data if row["stock"] == "AAA")
    assert open_row["signal_action"] == "exit"
