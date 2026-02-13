from datetime import datetime

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_open_executions,
    store_signal_execution,
    store_signal_history,
    store_signal_run,
)
from moex_carry.ui.app import SIGNAL_METRIC_CONTRACT_KEYS, create_app


def _seed_signal_run(session, run_id: str, timestamp: datetime, records: list[dict[str, object]]):
    store_signal_run(session, run_id, timestamp, params={"source": "test"})
    store_signal_history(session, run_id, timestamp, records)


def _build_settings(tmp_path):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/signals.db"),
    )


def _assert_signal_metric_contract(row: dict[str, object]) -> None:
    metrics = row.get("signal_metrics")
    assert isinstance(metrics, dict)
    for key in SIGNAL_METRIC_CONTRACT_KEYS:
        assert key in row
        assert key in metrics


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
                    "signal_metrics": {"zscore": 2.1, "entry_spread_pct_min": 0.01},
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
    assert data[0]["entry_spread_pct_min"] == 0.01
    assert data[0]["signal_metrics"]["entry_spread_pct_min"] == 0.01
    _assert_signal_metric_contract(data[0])
    assert data[0]["tp_spread_pct_level"] is None


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
    _assert_signal_metric_contract(data[0])
    assert data[0]["entry_spread_pct_min"] is None


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


def test_signals_execute_endpoint_generates_order_id_for_legged_entries(tmp_path):
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
            "quantity": 1,
            "side": "stock",
            "note": "leg-1",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert isinstance(payload.get("order_id"), str)
    assert payload.get("order_id")

    session_factory = create_session_factory(engine)
    with session_factory() as session:
        rows = load_open_executions(session)
        assert len(rows) == 1
        assert rows[0].order_id == payload["order_id"]


def test_signals_execute_endpoint_v1_adapter_idempotency(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    app = create_app(settings)
    client = app.server.test_client()

    payload = {
        "stock": "AAA",
        "future": "AAH6",
        "direction": "cash_and_carry",
        "action": "enter",
        "price": 100.5,
        "quantity": 1,
        "side": "stock",
        "idempotency_key": "sig-exec-idem-1",
    }
    first = client.post("/api/signals/execute", json=payload)
    assert first.status_code == 200
    assert first.headers.get("Deprecation") == "true"
    first_data = first.get_json()
    assert first_data["status"] == "ok"
    assert isinstance(first_data.get("order_id"), str)

    duplicate = client.post("/api/signals/execute", json=payload)
    assert duplicate.status_code == 200
    duplicate_data = duplicate.get_json()
    assert duplicate_data["status"] == "duplicate"
    assert duplicate_data.get("order_id") == first_data.get("order_id")

    session_factory = create_session_factory(engine)
    with session_factory() as session:
        rows = load_open_executions(session)
        assert len(rows) == 1


def test_signals_execute_normalizes_hold_open_action_to_enter(tmp_path):
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
            "action": "hold_open",
            "price": 100.5,
            "quantity": 1,
            "side": "future",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"

    session_factory = create_session_factory(engine)
    with session_factory() as session:
        rows = load_open_executions(session)
        assert len(rows) == 1
        assert rows[0].action == "enter"


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
    assert "order_id" in data[0]


def test_signals_executions_endpoint_normalizes_hold_open_action(tmp_path):
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
                "action": "hold_open",
                "price": 101.0,
                "quantity": 1,
                "side": "future",
                "order_id": "ord-1",
                "status": None,
                "note": None,
            },
        )

    app = create_app(settings)
    client = app.server.test_client()
    response = client.get("/api/signals/executions?stock=AAA&future=AAH6&limit=5")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["action"] == "enter"


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
                    "signal_metrics": {"forecast_exit_days": 3},
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
    assert open_row["forecast_exit_days"] == 3
    _assert_signal_metric_contract(open_row)

    enter_row = next(row for row in data if row["stock"] == "BBB")
    assert enter_row["signal_action"] == "enter"
    _assert_signal_metric_contract(enter_row)
    assert enter_row["entry_spread_pct_min"] is None


def test_signals_active_marks_open_position_hold_rows(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_run(
            session,
            "run-1",
            datetime(2025, 1, 2, 12, 0, 0),
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "hold",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.08,
                    "signal_reasons": ["hold"],
                    "signal_metrics": {"forecast_exit_days": 2},
                }
            ],
        )
        store_signal_execution(
            session,
            datetime(2025, 1, 2, 12, 1, 0),
            {
                "stock": "AAA",
                "future": "AAH6",
                "direction": "cash_and_carry",
                "action": "enter",
                "price": 101.0,
                "quantity": 1,
                "side": "stock",
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
    assert len(data) == 1

    row = data[0]
    assert row["stock"] == "AAA"
    assert row["signal_action"] == "hold_open"
    assert row["position_open"] is True
    assert row["position_state"] == "open"
    assert row["position_net_executions"] == 1
    assert row["position_enter_order_count"] == 1
    assert row["position_exit_order_count"] == 0
    assert row["position_net_orders"] == 1
    assert row["position_open_stock_legs"] == 1
    assert row["position_open_future_legs"] == 0
    assert row["position_open_leg_total"] == 1
    assert row["position_leg_imbalance"] is True
    assert row["forecast_exit_days"] == 2
    _assert_signal_metric_contract(row)


def test_signals_active_treats_hold_open_execution_as_enter_for_position_balance(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_run(
            session,
            "run-1",
            datetime(2025, 1, 2, 12, 0, 0),
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "hold",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.08,
                    "signal_reasons": ["hold"],
                    "signal_metrics": {"forecast_exit_days": 2},
                }
            ],
        )
        store_signal_execution(
            session,
            datetime(2025, 1, 2, 12, 1, 0),
            {
                "stock": "AAA",
                "future": "AAH6",
                "direction": "cash_and_carry",
                "action": "enter",
                "price": 101.0,
                "quantity": 1,
                "side": "stock",
                "order_id": "ord-1",
                "note": None,
            },
        )
        store_signal_execution(
            session,
            datetime(2025, 1, 2, 12, 1, 5),
            {
                "stock": "AAA",
                "future": "AAH6",
                "direction": "cash_and_carry",
                "action": "hold_open",
                "price": 102.0,
                "quantity": 1,
                "side": "future",
                "order_id": "ord-1",
                "note": None,
            },
        )

    app = create_app(settings)
    client = app.server.test_client()
    response = client.get("/api/signals/active")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1

    row = data[0]
    assert row["signal_action"] == "hold_open"
    assert row["position_open"] is True
    assert row["position_open_stock_legs"] == 1
    assert row["position_open_future_legs"] == 1
    assert row["position_open_leg_total"] == 2
    assert row["position_leg_imbalance"] is False
    assert row["position_net_executions"] == 2
    _assert_signal_metric_contract(row)


def test_signals_active_keeps_partial_two_leg_exit_open(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_run(
            session,
            "run-1",
            datetime(2025, 1, 3, 12, 0, 0),
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "exit",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.08,
                    "signal_reasons": ["zscore_revert"],
                    "signal_metrics": {},
                }
            ],
        )
        store_signal_execution(
            session,
            datetime(2025, 1, 3, 12, 1, 0),
            {
                "stock": "AAA",
                "future": "AAH6",
                "direction": "cash_and_carry",
                "action": "enter",
                "price": 101.0,
                "quantity": 1,
                "side": "stock",
                "order_id": "ord-enter-1",
                "note": None,
            },
        )
        store_signal_execution(
            session,
            datetime(2025, 1, 3, 12, 1, 5),
            {
                "stock": "AAA",
                "future": "AAH6",
                "direction": "cash_and_carry",
                "action": "enter",
                "price": 101.2,
                "quantity": 1,
                "side": "future",
                "order_id": "ord-enter-1",
                "note": None,
            },
        )
        store_signal_execution(
            session,
            datetime(2025, 1, 3, 12, 2, 0),
            {
                "stock": "AAA",
                "future": "AAH6",
                "direction": "cash_and_carry",
                "action": "exit",
                "price": 102.0,
                "quantity": 1,
                "side": "stock",
                "order_id": "ord-exit-1",
                "note": None,
            },
        )

    app = create_app(settings)
    client = app.server.test_client()
    response = client.get("/api/signals/active")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1

    row = data[0]
    assert row["signal_action"] == "exit"
    assert row["position_open"] is True
    assert row["position_net_executions"] == 1
    assert row["position_enter_order_count"] == 1
    assert row["position_exit_order_count"] == 1
    assert row["position_net_orders"] == 0
    assert row["position_open_stock_legs"] == 0
    assert row["position_open_future_legs"] == 1
    assert row["position_open_leg_total"] == 1
    assert row["position_leg_imbalance"] is True
    assert row["position_linked_two_leg_orders"] == 1
    _assert_signal_metric_contract(row)


def test_signals_active_includes_execution_only_open_pairs(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_run(
            session,
            "run-1",
            datetime(2025, 1, 3, 12, 0, 0),
            [
                {
                    "stock": "BBB",
                    "future": "BBH6",
                    "signal_action": "enter",
                    "signal_direction": "reverse",
                    "signal_score": 0.05,
                    "signal_reasons": [],
                    "signal_metrics": {},
                }
            ],
        )
        store_signal_execution(
            session,
            datetime(2025, 1, 3, 12, 2, 0),
            {
                "stock": "AAA",
                "future": "AAH6",
                "direction": "cash_and_carry",
                "action": "enter",
                "price": 99.5,
                "quantity": 1,
                "side": "future",
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

    missing_row = next(row for row in data if row["stock"] == "AAA")
    assert missing_row["future"] == "AAH6"
    assert missing_row["signal_action"] == "hold_open"
    assert missing_row["position_open"] is True
    assert missing_row["signal_reasons"] == ["position_open_no_active_signal"]
    _assert_signal_metric_contract(missing_row)
