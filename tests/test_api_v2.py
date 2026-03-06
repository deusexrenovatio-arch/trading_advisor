from __future__ import annotations

import json
from datetime import datetime

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig, UiConfig
from moex_carry.contracts.strategy_test import BacktestRequest, HpoRequest
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_signal_executions,
    store_signal_execution,
    store_signal_history,
    store_signal_run,
    upsert_decision_view_projection,
)
from moex_carry.ui.app import create_app
import moex_carry.ui.app as ui_app


def _build_settings(
    tmp_path,
    *,
    ff_db_projection_source: bool = False,
    ff_fail_closed_execution: bool = False,
    auto_unwind_timeout_sec: int = 600,
    max_api_payload_bytes: int = 262144,
):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/api-v2.db"),
        ui=UiConfig(
            ff_db_projection_source=ff_db_projection_source,
            ff_fail_closed_execution=ff_fail_closed_execution,
            auto_unwind_timeout_sec=auto_unwind_timeout_sec,
            max_api_payload_bytes=max_api_payload_bytes,
        ),
    )


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _seed_signal_history(session, run_id: str):
    ts = datetime(2025, 1, 1, 12, 0, 0)
    store_signal_run(session, run_id, ts, params={"source": "test"})
    store_signal_history(
        session,
        run_id,
        ts,
        [
            {
                "stock": "AAA",
                "future": "AAH6",
                "signal_action": "enter",
                "signal_direction": "cash_and_carry",
                "signal_score": 0.2,
                "signal_reasons": ["test"],
                "signal_metrics": {"score_gate_pass": True},
            }
        ],
    )


def test_v2_signals_active_and_actions_idempotency(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_history(session, "run-v2-1")

    app = create_app(settings)
    client = app.server.test_client()

    active_response = client.get("/api/v2/signals/active")
    assert active_response.status_code == 200
    assert active_response.headers.get("X-Request-Id")
    rows = active_response.get_json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    row = rows[0]
    assert "signal_id" in row
    assert row["stock"] == "AAA"
    assert row["future"] == "AAH6"
    assert row["lifecycle_state"] == "ready"
    assert row["signal_action_effective"] == "enter"
    assert row["entity_ref"]["entity_type"] == "pair"
    assert isinstance(row["gate_results"], list)
    assert "legacy" not in row
    signal_id = row["signal_id"]

    payload = {
        "action": "ack",
        "source": "ui",
        "actor_id": "tester",
        "idempotency_key": "idem-123",
    }
    action_first = client.post(f"/api/v2/signals/{signal_id}/actions", json=payload)
    assert action_first.status_code == 200
    first_data = action_first.get_json()
    assert first_data["status"] == "ok"

    action_second = client.post(f"/api/v2/signals/{signal_id}/actions", json=payload)
    assert action_second.status_code == 200
    second_data = action_second.get_json()
    assert second_data["status"] == "duplicate"

    history_response = client.get("/api/v2/signals/history?limit=10")
    assert history_response.status_code == 200
    history_rows = history_response.get_json()
    assert isinstance(history_rows, list)
    assert history_rows[0]["stock"] == "AAA"
    assert history_rows[0]["future"] == "AAH6"

    executions_response = client.get("/api/v2/signals/executions?stock=AAA&future=AAH6&limit=10")
    assert executions_response.status_code == 200
    execution_rows = executions_response.get_json()
    assert isinstance(execution_rows, list)
    assert len(execution_rows) == 1
    assert execution_rows[0]["stock"] == "AAA"
    assert execution_rows[0]["future"] == "AAH6"

    top_pairs_response = client.get(
        "/api/v2/top-pairs?limit=5",
        headers={"X-Request-Id": "req-fixed-1"},
    )
    assert top_pairs_response.status_code == 200
    assert top_pairs_response.headers.get("X-Request-Id") == "req-fixed-1"
    assert isinstance(top_pairs_response.get_json(), list)


def test_v2_signals_actions_require_idempotency_key(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_history(session, "run-v2-idem-required")

    app = create_app(settings)
    client = app.server.test_client()
    active_response = client.get("/api/v2/signals/active")
    assert active_response.status_code == 200
    rows = active_response.get_json()
    assert isinstance(rows, list)
    assert rows
    signal_id = rows[0]["signal_id"]

    response = client.post(
        f"/api/v2/signals/{signal_id}/actions",
        json={
            "action": "ack",
            "source": "ui",
            "actor_id": "tester",
        },
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "invalid_request"
    assert payload["message"] == "idempotency_key is required"


def test_v2_signals_actionability_exposes_axes_and_policy_trace(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        ts = datetime(2025, 1, 4, 12, 0, 0)
        store_signal_run(session, "run-v2-actionability-review", ts, params={"source": "test"})
        store_signal_history(
            session,
            "run-v2-actionability-review",
            ts,
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.35,
                    "signal_reasons": ["test-review"],
                    "signal_metrics": {
                        "score_gate_pass": True,
                        "pretrade_status": "check",
                        "news_gate_action": "reduce",
                    },
                }
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()

    response = client.get("/api/v2/signals/actionability?entity_type=pair&include_non_actionable=true")
    assert response.status_code == 200
    rows = response.get_json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    row = rows[0]
    assert row["entity_ref"]["entity_type"] == "pair"
    assert row["axes"]["policy_state"] in {"allow", "reduce", "review", "block"}
    assert row["axes"]["intent_state"] in {"none", "active", "out_of_range", "consumed", "expired", "superseded"}
    assert row["actionability_state"] in {
        "actionable_enter",
        "actionable_enter_repriced",
        "enter_out_of_range",
        "review_entry",
        "actionable_exit",
        "hold_open",
        "blocked_entry",
        "inactive",
    }
    policy = row["policy_outcome"]
    assert policy["status"] in {"allow", "reduce", "review", "block"}
    assert policy["precedence_version"] == "v1"
    assert isinstance(policy["gate_trace"], list)
    assert len(policy["gate_trace"]) >= 1
    assert {"gate_id", "status", "priority"}.issubset(policy["gate_trace"][0].keys())


def test_v2_signals_actionability_derives_evidence_from_gate_metrics(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        ts = datetime(2025, 1, 6, 12, 0, 0)
        store_signal_run(session, "run-v2-actionability-evidence", ts, params={"source": "test"})
        store_signal_history(
            session,
            "run-v2-actionability-evidence",
            ts,
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.31,
                    "signal_reasons": ["news_veto"],
                    "signal_metrics": {
                        "score_gate_pass": True,
                        "pretrade_status": "check",
                        "risk_gate_status": "reduce",
                        "news_gate_action": "block",
                        "news_gate_reasons": ["news_event_high_impact"],
                        "liquidity_gate_status": "pass",
                        "orderbook_pass": False,
                        "source_freshness_status": "review",
                    },
                }
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()

    response = client.get("/api/v2/signals/actionability?entity_type=pair&include_non_actionable=true")
    assert response.status_code == 200
    rows = response.get_json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    row = rows[0]

    evidence_items = row["evidence_items"]
    assert isinstance(evidence_items, list)
    assert len(evidence_items) >= 4

    source_keys = {str(item.get("source_key") or "") for item in evidence_items}
    assert "technical_score_gate" in source_keys
    assert "news_geopolitics_gate" in source_keys
    assert "liquidity_orderbook" in source_keys

    freshness_values = [item.get("freshness_sec") for item in evidence_items if item.get("freshness_sec") is not None]
    assert freshness_values
    assert min(int(value) for value in freshness_values) >= 0

    summary = row["evidence_summary"]
    assert summary["veto_active"] is True
    assert isinstance(summary.get("veto_reasons"), list)

    policy = row["policy_outcome"]
    assert policy["status"] == "block"
    assert policy["applied_gate_id"] in {"news_geopolitics", "risk_profile"}


def test_v2_signals_actionability_supports_instrument_filter_and_pairs_view(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        ts = datetime(2025, 1, 5, 12, 0, 0)
        store_signal_run(session, "run-v2-actionability-instrument", ts, params={"source": "test"})
        store_signal_history(
            session,
            "run-v2-actionability-instrument",
            ts,
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.4,
                    "signal_reasons": ["test-enter"],
                    "signal_metrics": {"score_gate_pass": True},
                }
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()

    instrument_response = client.get(
        "/api/v2/signals/actionability?entity_type=instrument&instrument_type=stock&include_non_actionable=true"
    )
    assert instrument_response.status_code == 200
    instrument_rows = instrument_response.get_json()
    assert isinstance(instrument_rows, list)
    assert len(instrument_rows) == 1
    assert instrument_rows[0]["entity_ref"]["entity_type"] == "instrument"
    assert instrument_rows[0]["instrument_type"] == "stock"

    pair_response = client.get("/api/v2/pairs/actionability?include_non_actionable=true")
    assert pair_response.status_code == 200
    pair_rows = pair_response.get_json()
    assert isinstance(pair_rows, list)
    assert len(pair_rows) == 1
    assert pair_rows[0]["pair_id"] == "AAA__AAH6"
    assert pair_rows[0]["entity_ref"]["entity_type"] == "pair"
    assert "axes" in pair_rows[0]
    assert "policy_outcome" in pair_rows[0]


def test_v2_pairs_actionability_preserves_entry_plan_and_live_range_fields(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        ts = datetime(2025, 1, 7, 12, 0, 0)
        store_signal_run(session, "run-v2-actionability-pair-fields", ts, params={"source": "test"})
        store_signal_history(
            session,
            "run-v2-actionability-pair-fields",
            ts,
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.45,
                    "signal_reasons": ["test-enter"],
                    "signal_metrics": {
                        "score_gate_pass": True,
                        "entry_stock_min": 99.0,
                        "entry_stock_max": 101.0,
                        "entry_future_min_per_share": 100.0,
                        "entry_future_max_per_share": 102.0,
                        "entry_spread_min": 0.5,
                        "entry_spread_max": 1.5,
                        "entry_spread_pct_min": 0.005,
                        "entry_spread_pct_max": 0.015,
                        "spread_pct": 0.01,
                        "spread_mid": 1.0,
                        "spot_mid": 100.0,
                        "future_mid": 101.0,
                    },
                }
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()

    response = client.get("/api/v2/pairs/actionability?include_non_actionable=true")
    assert response.status_code == 200
    rows = response.get_json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    row = rows[0]

    plan = row["entry_plan"]
    assert plan["entry_stock_min"] == 99.0
    assert plan["entry_stock_max"] == 101.0
    assert plan["entry_future_min_per_share"] == 100.0
    assert plan["entry_future_max_per_share"] == 102.0

    live = row["entry_range_now"]
    assert live["stock_now"] == 100.0
    assert live["future_now"] == 101.0
    assert live["spread_now"] == 1.0
    assert live["spread_pct_now"] == 0.01


def test_v2_actionability_strategy_filters_split_streams(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        ts = datetime(2025, 1, 8, 12, 0, 0)
        store_signal_run(session, "run-v2-actionability-strategy-filter", ts, params={"source": "test"})
        store_signal_history(
            session,
            "run-v2-actionability-strategy-filter",
            ts,
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.21,
                    "signal_reasons": ["arb"],
                    "signal_metrics": {
                        "score_gate_pass": True,
                        "strategy_type": "arbitrage",
                        "strategy_stream": "arbitrage",
                    },
                },
                {
                    "stock": "BBB",
                    "future": "BBH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.37,
                    "signal_reasons": ["spec"],
                    "signal_metrics": {
                        "score_gate_pass": True,
                        "strategy_type": "speculative",
                        "strategy_stream": "commodity_futures",
                    },
                },
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()

    stream_response = client.get(
        "/api/v2/pairs/actionability?include_non_actionable=true&strategy_stream=commodity_futures"
    )
    assert stream_response.status_code == 200
    stream_rows = stream_response.get_json()
    assert isinstance(stream_rows, list)
    assert len(stream_rows) == 1
    assert stream_rows[0]["pair_id"] == "BBB__BBH6"
    assert stream_rows[0]["strategy_type"] == "speculative"
    assert stream_rows[0]["strategy_stream"] == "commodity_futures"

    alias_type_response = client.get(
        "/api/v2/signals/actionability?entity_type=pair&include_non_actionable=true&strategy_type=commodity_futures"
    )
    assert alias_type_response.status_code == 200
    alias_type_rows = alias_type_response.get_json()
    assert isinstance(alias_type_rows, list)
    assert len(alias_type_rows) == 1
    assert alias_type_rows[0]["stock"] == "BBB"
    assert alias_type_rows[0]["strategy_stream"] == "commodity_futures"

    type_response = client.get(
        "/api/v2/signals/actionability?entity_type=pair&include_non_actionable=true&strategy_type=arbitrage"
    )
    assert type_response.status_code == 200
    type_rows = type_response.get_json()
    assert isinstance(type_rows, list)
    assert len(type_rows) == 1
    assert type_rows[0]["stock"] == "AAA"
    assert type_rows[0]["strategy_stream"] == "arbitrage"


def test_v2_entity_and_pair_actions_endpoints_are_idempotent(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_history(session, "run-v2-actionability-actions")

    app = create_app(settings)
    client = app.server.test_client()

    pair_rows = client.get("/api/v2/pairs/actionability?include_non_actionable=true").get_json()
    assert isinstance(pair_rows, list)
    assert len(pair_rows) == 1
    current_intent_id = str((pair_rows[0].get("intent") or {}).get("intent_id") or "")
    assert current_intent_id != ""

    payload = {
        "action": "ack",
        "source": "ui",
        "actor_id": "tester",
        "intent_id": current_intent_id,
        "idempotency_key": "idem-entity-action-1",
    }
    first = client.post("/api/v2/entities/pair/AAA__AAH6/signals/actions", json=payload)
    assert first.status_code == 200
    first_data = first.get_json()
    assert first_data["status"] == "ok"
    assert first_data["entity_ref"]["entity_type"] == "pair"
    assert first_data["action"] == "ack"

    second = client.post("/api/v2/entities/pair/AAA__AAH6/signals/actions", json=payload)
    assert second.status_code == 200
    second_data = second.get_json()
    assert second_data["status"] == "duplicate"
    assert second_data["action"] == "ack"

    pair_payload = {
        "action": "ack",
        "source": "ui",
        "actor_id": "tester",
        "intent_id": current_intent_id,
        "idempotency_key": "idem-pair-action-1",
    }
    pair_result = client.post("/api/v2/pairs/AAA__AAH6/actions", json=pair_payload)
    assert pair_result.status_code == 200
    pair_data = pair_result.get_json()
    assert pair_data["status"] == "ok"
    assert pair_data["pair_id"] == "AAA__AAH6"

    with session_factory() as session:
        executions = load_signal_executions(session, stock="AAA", future="AAH6", limit=20)
        assert len(executions) == 2


def test_v2_pair_actions_reject_stale_intent_id(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_history(session, "run-v2-actionability-stale-intent")

    app = create_app(settings)
    client = app.server.test_client()

    pair_rows = client.get("/api/v2/pairs/actionability?include_non_actionable=true").get_json()
    assert isinstance(pair_rows, list)
    assert len(pair_rows) == 1
    current_intent_id = str((pair_rows[0].get("intent") or {}).get("intent_id") or "")
    assert current_intent_id != ""

    response = client.post(
        "/api/v2/pairs/AAA__AAH6/actions",
        json={
            "action": "ack",
            "source": "ui",
            "actor_id": "tester",
            "intent_id": f"stale-{current_intent_id}",
            "idempotency_key": "idem-stale-intent-1",
        },
    )
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["status"] == "blocked"
    assert payload["message"] == "intent_superseded_or_stale"
    assert payload["error"] == "intent_mismatch"
    assert payload["current_intent_id"] == current_intent_id

    with session_factory() as session:
        executions = load_signal_executions(session, stock="AAA", future="AAH6", limit=20)
        assert executions == []


def test_v2_pair_ack_consumes_intent_in_projection(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        ts = datetime.utcnow().replace(microsecond=0)
        store_signal_run(session, "run-v2-ack-consume", ts, params={"source": "test"})
        store_signal_history(
            session,
            "run-v2-ack-consume",
            ts,
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.25,
                    "signal_reasons": ["test"],
                    "signal_metrics": {"score_gate_pass": True},
                }
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()

    before_rows = client.get("/api/v2/pairs/actionability?include_non_actionable=true").get_json()
    assert isinstance(before_rows, list)
    assert len(before_rows) == 1
    before = before_rows[0]
    intent_id = str((before.get("intent") or {}).get("intent_id") or "")
    assert intent_id != ""
    assert str((before.get("intent") or {}).get("status") or "") == "active"

    action = client.post(
        "/api/v2/pairs/AAA__AAH6/actions",
        json={
            "action": "ack",
            "source": "ui",
            "actor_id": "tester",
            "intent_id": intent_id,
            "idempotency_key": "idem-ack-consume-1",
        },
    )
    assert action.status_code == 200
    assert action.get_json()["status"] == "ok"

    after_rows = client.get("/api/v2/pairs/actionability?include_non_actionable=true").get_json()
    assert isinstance(after_rows, list)
    assert len(after_rows) == 1
    after = after_rows[0]
    assert str((after.get("intent") or {}).get("status") or "") == "consumed"
    assert after["actionability_state"] in {"inactive", "hold_open"}
    assert str((after.get("delivery") or {}).get("delivery_suppressed_reason") or "") == "intent_consumed"


def test_v2_instrument_actions_resolve_pair_context_and_store_execution(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_history(session, "run-v2-actionability-instrument-action")

    app = create_app(settings)
    client = app.server.test_client()

    instrument_rows = client.get(
        "/api/v2/signals/actionability?entity_type=instrument&instrument_type=stock&include_non_actionable=true"
    ).get_json()
    assert isinstance(instrument_rows, list)
    assert len(instrument_rows) == 1
    instrument_row = instrument_rows[0]
    current_intent_id = str((instrument_row.get("intent") or {}).get("intent_id") or "")
    assert current_intent_id != ""

    response = client.post(
        "/api/v2/entities/instrument/AAA/signals/actions",
        json={
            "action": "ack",
            "source": "ui",
            "actor_id": "tester",
            "intent_id": current_intent_id,
            "pair_id": "AAA__AAH6",
            "idempotency_key": "idem-instrument-action-1",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["entity_ref"]["entity_type"] == "instrument"
    assert payload["pair_ref"]["entity_type"] == "pair"
    assert payload["pair_id"] == "AAA__AAH6"
    assert payload["instrument_type"] == "stock"

    with session_factory() as session:
        executions = load_signal_executions(session, stock="AAA", future="AAH6", limit=20)
        assert len(executions) == 1
        assert executions[0].action == "ack"


def test_v2_instrument_actions_require_pair_hint_when_ambiguous(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        ts = datetime(2025, 1, 8, 12, 0, 0)
        store_signal_run(session, "run-v2-instrument-ambiguous", ts, params={"source": "test"})
        store_signal_history(
            session,
            "run-v2-instrument-ambiguous",
            ts,
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.2,
                    "signal_reasons": ["test"],
                    "signal_metrics": {"score_gate_pass": True},
                },
                {
                    "stock": "AAA",
                    "future": "AAM6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.3,
                    "signal_reasons": ["test"],
                    "signal_metrics": {"score_gate_pass": True},
                },
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()

    ambiguous = client.post(
        "/api/v2/entities/instrument/AAA/signals/actions",
        json={
            "action": "ack",
            "source": "ui",
            "actor_id": "tester",
            "idempotency_key": "idem-instrument-ambiguous-1",
        },
    )
    assert ambiguous.status_code == 409
    ambiguous_payload = ambiguous.get_json()
    assert ambiguous_payload["status"] == "blocked"
    assert ambiguous_payload["error"] == "ambiguous_instrument_entity"
    assert isinstance(ambiguous_payload.get("candidate_pairs"), list)
    assert sorted(ambiguous_payload["candidate_pairs"]) == ["AAA__AAH6", "AAA__AAM6"]

def test_v2_signal_action_fail_closed_blocks_unconfirmed_entry(tmp_path):
    settings = _build_settings(tmp_path, ff_fail_closed_execution=True)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        ts = datetime(2025, 1, 1, 12, 0, 0)
        store_signal_run(session, "run-v2-fc-block", ts, params={"source": "test"})
        store_signal_history(
            session,
            "run-v2-fc-block",
            ts,
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.2,
                    "signal_reasons": ["test"],
                    "signal_metrics": {"score_gate_pass": True, "pretrade_status": "check"},
                }
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()
    active_rows = client.get("/api/v2/signals/active").get_json()
    assert isinstance(active_rows, list)
    assert len(active_rows) == 1
    signal_id = active_rows[0]["signal_id"]

    blocked = client.post(
        f"/api/v2/signals/{signal_id}/actions",
        json={
            "action": "enter",
            "source": "ui",
            "actor_id": "tester",
            "idempotency_key": "idem-fc-block-1",
        },
    )
    assert blocked.status_code == 409
    data = blocked.get_json()
    assert data["status"] == "blocked"
    assert data["error"] == "fail_closed_execution"
    assert data["reason_code"] == "PRETRADE_NOT_CONFIRMED"

    with session_factory() as session:
        executions = load_signal_executions(session, stock="AAA", future="AAH6", limit=20)
        assert executions == []


def test_v2_signal_action_fail_closed_allows_privileged_override(tmp_path):
    settings = _build_settings(tmp_path, ff_fail_closed_execution=True)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        ts = datetime(2025, 1, 1, 12, 0, 0)
        store_signal_run(session, "run-v2-fc-override", ts, params={"source": "test"})
        store_signal_history(
            session,
            "run-v2-fc-override",
            ts,
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.2,
                    "signal_reasons": ["test"],
                    "signal_metrics": {"score_gate_pass": True, "pretrade_status": "check"},
                }
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()
    signal_id = client.get("/api/v2/signals/active").get_json()[0]["signal_id"]
    response = client.post(
        f"/api/v2/signals/{signal_id}/actions",
        json={
            "action": "enter",
            "source": "system",
            "actor_id": "risk-service",
            "idempotency_key": "idem-fc-override-1",
            "fail_closed_override": True,
            "reason_code": "ISS_OVERRIDE",
            "comment": "approved by risk owner",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["fail_closed"]["status"] == "override"

    with session_factory() as session:
        executions = load_signal_executions(session, stock="AAA", future="AAH6", limit=20)
        assert len(executions) == 1
        assert executions[0].action == "enter"
        assert '"fail_closed_override":true' in str(executions[0].note or "")


def test_v2_auto_unwind_policy_run_dry_run_and_live(tmp_path):
    settings = _build_settings(tmp_path, auto_unwind_timeout_sec=60)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        ts = datetime(2025, 1, 2, 12, 0, 0)
        store_signal_run(session, "run-v2-au-1", ts, params={"source": "test"})
        store_signal_history(
            session,
            "run-v2-au-1",
            ts,
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "hold",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.1,
                    "signal_reasons": ["hold"],
                    "signal_metrics": {"score_gate_pass": True},
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
                "quantity": 1.0,
                "side": "stock",
                "order_id": "ord-au-1",
                "status": "filled",
                "note": "seed-open-leg",
            },
        )

    app = create_app(settings)
    client = app.server.test_client()

    dry_run = client.post(
        "/api/v2/policies/auto-unwind/run",
        json={"dry_run": True, "timeout_sec": 60, "actor_id": "auto-unwind"},
    )
    assert dry_run.status_code == 200
    dry_payload = dry_run.get_json()
    assert dry_payload["status"] == "dry_run"
    assert dry_payload["candidate_count"] == 1

    live = client.post(
        "/api/v2/policies/auto-unwind/run",
        json={"timeout_sec": 60, "actor_id": "auto-unwind"},
    )
    assert live.status_code == 200
    live_payload = live.get_json()
    assert live_payload["status"] == "ok"
    assert live_payload["triggered_count"] == 1
    assert live_payload["duplicate_count"] == 0

    second_live = client.post(
        "/api/v2/policies/auto-unwind/run",
        json={"timeout_sec": 60, "actor_id": "auto-unwind"},
    )
    assert second_live.status_code == 200
    second_payload = second_live.get_json()
    assert second_payload["candidate_count"] == 0
    assert second_payload["duplicate_count"] == 0

    with session_factory() as session:
        executions = load_signal_executions(session, stock="AAA", future="AAH6", limit=20)
        assert len(executions) == 2
        assert executions[0].action == "exit"
        assert "LEG_IMBALANCE_TIMEOUT" in str(executions[0].note or "")


def test_v2_ops_health_and_slo_observability(tmp_path, monkeypatch):
    settings = _build_settings(tmp_path, ff_fail_closed_execution=True)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        ts = datetime(2025, 1, 3, 10, 0, 0)
        store_signal_run(session, "run-v2-ops-1", ts, params={"source": "test"})
        store_signal_history(
            session,
            "run-v2-ops-1",
            ts,
            [
                {
                    "stock": "AAA",
                    "future": "AAH6",
                    "signal_action": "enter",
                    "signal_direction": "cash_and_carry",
                    "signal_score": 0.2,
                    "signal_reasons": ["test"],
                    "signal_metrics": {"score_gate_pass": True, "pretrade_status": "check"},
                }
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()

    active_rows = client.get("/api/v2/signals/active").get_json()
    assert isinstance(active_rows, list)
    assert len(active_rows) == 1
    signal_id = active_rows[0]["signal_id"]

    for idx in range(5):
        blocked = client.post(
            f"/api/v2/signals/{signal_id}/actions",
            json={
                "action": "enter",
                "source": "ui",
                "actor_id": "tester",
                "idempotency_key": f"idem-ops-block-{idx}",
            },
        )
        assert blocked.status_code == 409

    monkeypatch.setattr(
        ui_app,
        "run_delay_gate",
        lambda *_args, **_kwargs: {
            "status": "CHECK",
            "ready_to_place": False,
            "manual_confirm_required": True,
            "reasons": ["snapshot_unsynced"],
            "degraded": True,
            "pair": {"stock": "AAA", "future": "AAH6", "direction": "cash_and_carry"},
            "gates": {"stock_quote_pass": False},
            "hits": {"required": 2, "snapshots": 2},
        },
    )

    for _ in range(10):
        pretrade = client.post(
            "/api/v2/pretrade/check",
            json={
                "stock": "AAA",
                "future": "AAH6",
                "spot_target": 100.0,
                "future_target": 101.0,
                "snapshots": 1,
                "min_hits": 1,
                "poll_sec": 0.0,
            },
        )
        assert pretrade.status_code == 200

    health = client.get("/api/v2/ops/health")
    assert health.status_code == 200
    health_payload = health.get_json()
    assert health_payload["status"] in {"ok", "degraded"}
    assert "checks" in health_payload
    assert "database" in health_payload["checks"]

    slo = client.get("/api/v2/ops/slo")
    assert slo.status_code == 200
    payload = slo.get_json()
    assert "api" in payload
    assert "v2_signals_actions" in payload["api"]
    assert "v2_pretrade_check" in payload["api"]
    assert payload["events_15m"]["execution_rejections_fail_closed"] >= 5
    assert payload["events_15m"]["pretrade_failures"] >= 10
    assert payload["events_15m"]["pretrade_degraded"] >= 10
    alert_codes = {str(item.get("code")) for item in payload["alerts"] if isinstance(item, dict)}
    assert "EXECUTION_REJECTION_SPIKE" in alert_codes
    assert "PRETRADE_FAILURE_SPIKE" in alert_codes


def test_v2_decision_view_and_news_feed(tmp_path):
    settings = _build_settings(tmp_path)
    app = create_app(settings)
    client = app.server.test_client()

    decisions_dir = tmp_path / "decisions"
    _write_jsonl(
        decisions_dir / "decision_view.jsonl",
        [
            {
                "decision_id": "dec-1",
                "decision_view_id": "view-dec-1",
                "created_at": "2025-01-01T10:00:00Z",
                "strategy_type": "arbitrage",
                "primary_instrument": "SBER",
                "action": "hold",
                "risk_state": "green",
                "news_severity": "high",
                "cost_summary": {"round_trip_cost": 1.0, "break_even_ticks": 1},
                "key_features": [{"name": "x", "value": 1}],
                "links": {"decision_log": "dec-1"},
            }
        ],
    )
    _write_jsonl(
        decisions_dir / "decision_log.jsonl",
        [
            {
                "decision_id": "dec-1",
                "created_at": "2025-01-01T10:00:00Z",
                "news_context": {
                    "severity": "high",
                    "headline_count": 2,
                    "summary": "news_blocked",
                },
            }
        ],
    )
    _write_jsonl(
        decisions_dir / "decision_actions.jsonl",
        [
            {
                "action_id": "dact-1",
                "decision_id": "dec-1",
                "action": "execute",
                "status": "execute_requested",
                "actor": "tester",
                "source": "ui",
                "idempotency_key": "idem-dec-1",
                "created_at": "2025-01-01T10:01:00Z",
            }
        ],
    )
    _write_jsonl(
        decisions_dir / "execution_requests.jsonl",
        [
            {
                "decision_id": "dec-1",
                "request_id": "dreq-1",
                "action": "execute",
                "status": "queued",
                "requested_at": "2025-01-01T10:01:00Z",
                "idempotency_key": "idem-dec-1",
            }
        ],
    )

    view_response = client.get("/api/v2/decisions/view")
    assert view_response.status_code == 200
    view_rows = view_response.get_json()
    assert isinstance(view_rows, list)
    assert view_rows[0]["projection_version"] == "v2.0"
    assert view_rows[0]["entity_ref"]["entity_type"] == "instrument"
    assert view_rows[0]["decision_ref"]["decision_id"] == "dec-1"
    assert view_rows[0]["decision_ref"]["action_id"] == "dact-1"
    assert view_rows[0]["execution_ref"]["request_id"] == "dreq-1"
    assert view_rows[0]["execution_ref"]["status"] == "queued"

    alias_response = client.get("/api/v2/decision-view")
    assert alias_response.status_code == 200
    alias_rows = alias_response.get_json()
    assert isinstance(alias_rows, list)
    assert alias_rows[0]["decision_id"] == "dec-1"
    assert alias_rows[0]["decision_ref"]["latest_action"] == "execute"

    news_response = client.get("/api/v2/news/feed?severity=high&ticker=SBER")
    assert news_response.status_code == 200
    news_rows = news_response.get_json()
    assert isinstance(news_rows, list)
    assert len(news_rows) == 1
    assert news_rows[0]["severity"] == "high"
    assert news_rows[0]["entity_links"][0]["ticker"] == "SBER"


def test_v2_decision_view_uses_db_projection_source(tmp_path):
    settings = _build_settings(tmp_path, ff_db_projection_source=True)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        upsert_decision_view_projection(
            session,
            [
                {
                    "decision_id": "dec-db-1",
                    "decision_view_id": "view-dec-db-1",
                    "created_at": "2025-01-02T09:00:00Z",
                    "strategy_type": "arbitrage",
                    "primary_instrument": "GAZP",
                    "action": "hold",
                    "risk_state": "green",
                    "news_severity": "low",
                }
            ],
        )

    app = create_app(settings)
    client = app.server.test_client()
    response = client.get("/api/v2/decisions/view?limit=5")
    assert response.status_code == 200
    rows = response.get_json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["decision_id"] == "dec-db-1"
    assert rows[0]["projection_source"] == "db"
    assert rows[0]["entity_ref"]["ticker"] == "GAZP"


def test_v2_decision_view_db_projection_bootstraps_from_jsonl(tmp_path):
    settings = _build_settings(tmp_path, ff_db_projection_source=True)
    engine = create_engine_from_settings(settings)
    init_db(engine)

    decisions_dir = tmp_path / "decisions"
    _write_jsonl(
        decisions_dir / "decision_view.jsonl",
        [
            {
                "decision_id": "dec-jsonl-1",
                "decision_view_id": "view-dec-jsonl-1",
                "created_at": "2025-01-03T10:00:00Z",
                "strategy_type": "arbitrage",
                "primary_instrument": "SBER",
                "action": "hold",
                "risk_state": "yellow",
                "news_severity": "medium",
            }
        ],
    )

    app = create_app(settings)
    client = app.server.test_client()
    response = client.get("/api/v2/decisions/view?limit=5")
    assert response.status_code == 200
    rows = response.get_json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["decision_id"] == "dec-jsonl-1"
    assert rows[0]["projection_source"] == "db"


def test_v2_research_wrappers(tmp_path, monkeypatch):
    settings = _build_settings(tmp_path)
    app = create_app(settings)
    client = app.server.test_client()

    monkeypatch.setattr(ui_app, "run_backtest_v2_cached", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        ui_app,
        "serialize_backtest_report",
        lambda _report: {"summary_metrics": {"cagr": 0.1}},
    )
    monkeypatch.setattr(
        ui_app,
        "start_hpo_run",
        lambda *_args, **_kwargs: {"run_id": "hpo-1", "status": "running", "progress": {"completed": 0, "total": 1}},
    )
    monkeypatch.setattr(
        ui_app,
        "load_hpo_status",
        lambda *_args, **_kwargs: {
            "run_id": "hpo-1",
            "status": "completed",
            "result": {"leaderboard": [{"objective": 1.0}]},
        },
    )

    backtest_request = BacktestRequest().model_dump(mode="json")
    backtest_request["test"]["start_date"] = "2025-01-01"
    backtest_request["test"]["end_date"] = "2025-01-10"
    backtest_request["universe"]["include_stocks"] = ["AAA"]
    backtest_request["universe"]["include_futures"] = ["AAH6"]

    backtest_response = client.post(
        "/api/v2/research/backtests/run",
        json={
            "experiment_id": "exp-a",
            "request": backtest_request,
        },
    )
    assert backtest_response.status_code == 200
    backtest_data = backtest_response.get_json()
    assert backtest_data["experiment_id"] == "exp-a"
    assert backtest_data["status"] == "completed"
    assert backtest_data["report"]["summary_metrics"]["cagr"] == 0.1

    hpo_request = HpoRequest().model_dump(mode="json")
    hpo_request["base"]["test"]["start_date"] = "2025-01-01"
    hpo_request["base"]["test"]["end_date"] = "2025-01-10"
    hpo_request["base"]["universe"]["include_stocks"] = ["AAA"]
    hpo_request["base"]["universe"]["include_futures"] = ["AAH6"]

    hpo_run_response = client.post(
        "/api/v2/research/hpo/run",
        json={
            "experiment_id": "exp-b",
            "request": hpo_request,
        },
    )
    assert hpo_run_response.status_code == 200
    hpo_run_data = hpo_run_response.get_json()
    assert hpo_run_data["experiment_id"] == "exp-b"
    assert hpo_run_data["run_id"] == "hpo-1"

    hpo_status_response = client.get("/api/v2/research/hpo/status?run_id=hpo-1")
    assert hpo_status_response.status_code == 200
    hpo_status_data = hpo_status_response.get_json()
    assert hpo_status_data["promotion_gate"]["status"] == "pass"


def test_v2_research_morning_plan_wrapper(tmp_path, monkeypatch):
    settings = _build_settings(tmp_path)
    app = create_app(settings)
    client = app.server.test_client()

    class _FakeMorningPlanBuilder:
        def __init__(self, _provider, _calendar, _cfg):
            pass

        def build_plan(self, *, as_of_ts, instrument_id, tick_size):
            assert instrument_id == "BRK6"
            assert tick_size == 0.01
            return {
                "instrument_id": instrument_id,
                "tick_size": tick_size,
                "as_of_ts": as_of_ts,
                "setups": [{"setup_id": "S1"}],
                "warnings": ["ok"],
            }

    monkeypatch.setattr(ui_app, "MorningPlanBuilder", _FakeMorningPlanBuilder)

    response = client.post(
        "/api/v2/research/morning-plan",
        json={
            "instrument_id": "BRK6",
            "tick_size": 0.01,
            "as_of_ts": "2026-03-02T07:00:00Z",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["instrument_id"] == "BRK6"
    assert payload["tick_size"] == 0.01
    assert payload["as_of_ts"] == "2026-03-02T07:00:00+00:00"
    assert payload["setups"][0]["setup_id"] == "S1"

    invalid_tick_size = client.post(
        "/api/v2/research/morning-plan",
        json={"instrument_id": "BRK6", "tick_size": 0},
    )
    assert invalid_tick_size.status_code == 400
    assert invalid_tick_size.get_json()["message"] == "invalid_tick_size"


def test_v2_hpo_status_fails_on_quality_gate(tmp_path, monkeypatch):
    settings = _build_settings(tmp_path)
    app = create_app(settings)
    client = app.server.test_client()

    monkeypatch.setattr(
        ui_app,
        "load_hpo_status",
        lambda *_args, **_kwargs: {
            "run_id": "hpo-1",
            "status": "completed",
            "result": {
                "leaderboard": [{"objective": 1.0}],
                "quality_review": {"skipped": False, "quality_gate_pass_count": 0},
            },
        },
    )

    response = client.get("/api/v2/research/hpo/status?run_id=hpo-1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["promotion_gate"]["status"] == "fail"
    assert "quality_gate_fail" in payload["promotion_gate"]["checks"]


def test_v2_portfolio_rebalance_preview_and_commit(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_signal_history(session, "run-v2-rebal")

    app = create_app(settings)
    client = app.server.test_client()

    preview_response = client.get("/api/v2/portfolio/rebalance/preview?limit=5")
    assert preview_response.status_code == 200
    preview = preview_response.get_json()
    assert "rebalance_plan_id" in preview
    assert isinstance(preview["positions"], list)

    commit_response = client.post(
        "/api/v2/portfolio/rebalance/commit",
        json={
            "rebalance_plan_id": preview["rebalance_plan_id"],
            "actor_id": "tester",
            "positions": preview["positions"],
        },
    )
    assert commit_response.status_code == 200
    commit_data = commit_response.get_json()
    assert commit_data["status"] == "ok"
    assert commit_data["positions_committed"] == len(preview["positions"])


def test_v2_portfolio_rebalance_commit_blocks_on_failed_risk_gate(tmp_path):
    settings = _build_settings(tmp_path)
    settings.risk_profile.max_positions = 1
    app = create_app(settings)
    client = app.server.test_client()

    response = client.post(
        "/api/v2/portfolio/rebalance/commit",
        json={
            "rebalance_plan_id": "rebal-test-1",
            "actor_id": "tester",
            "positions": [
                {
                    "entity_ref": {"entity_type": "pair", "entity_id": "AAA__AAH6"},
                    "signal_action": "enter",
                    "target_weight": 0.5,
                },
                {
                    "entity_ref": {"entity_type": "pair", "entity_id": "BBB__BBH6"},
                    "signal_action": "hold_open",
                    "target_weight": 0.5,
                },
            ],
        },
    )
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["status"] == "blocked"
    assert payload["error"] == "risk_gate_failed"
    assert payload["rebalance_plan_id"] == "rebal-test-1"
    assert payload["risk_checks"][0]["check"] == "max_positions"
    assert payload["risk_checks"][0]["passed"] is False


def test_v2_decision_actions_and_v1_adapter(tmp_path):
    settings = _build_settings(tmp_path)
    app = create_app(settings)
    client = app.server.test_client()

    decisions_dir = tmp_path / "decisions"
    _write_jsonl(
        decisions_dir / "decision_view.jsonl",
        [
            {
                "decision_id": "dec-9",
                "created_at": "2025-01-01T10:00:00Z",
                "strategy_type": "arbitrage",
                "primary_instrument": "SBER",
                "action": "hold",
                "risk_state": "green",
                "news_severity": "low",
            }
        ],
    )

    payload = {
        "action": "EXECUTE",
        "actor_id": "tester",
        "reason_code": "manual_ok",
        "comment": "run it",
        "idempotency_key": "dec-9-idem-1",
    }
    first = client.post("/api/v2/decisions/dec-9/actions", json=payload)
    assert first.status_code == 200
    first_data = first.get_json()
    assert first_data["status"] == "ok"
    assert first_data["operator_action"]["action"] == "execute"
    assert first_data["decision_ref"]["decision_id"] == "dec-9"
    assert first_data["decision_ref"]["latest_action"] == "execute"
    assert first_data["execution_ref"]["status"] in {"queued", "execute_requested"}
    assert first_data["execution_ref"]["request_id"] is not None

    duplicate = client.post("/api/v2/decisions/dec-9/actions", json=payload)
    assert duplicate.status_code == 200
    duplicate_data = duplicate.get_json()
    assert duplicate_data["status"] == "duplicate"
    assert duplicate_data["decision_ref"]["decision_id"] == "dec-9"
    assert duplicate_data["decision_ref"]["latest_action"] == "execute"

    v1 = client.post(
        "/api/decisions/dec-9/action",
        json={"action": "approve", "actor": "legacy-user", "note": "legacy-path"},
    )
    assert v1.status_code == 200
    assert v1.headers.get("Deprecation") == "true"
    assert "/api/v2/decisions/dec-9/actions" in str(v1.headers.get("Link", ""))
    v1_data = v1.get_json()
    assert v1_data["status"] == "ok"
    assert v1_data["operator_action"]["source"] == "v1_adapter"
    assert v1_data["operator_action"]["action"] == "approve"

    view_response = client.get("/api/v2/decisions/view?limit=10")
    assert view_response.status_code == 200
    view_rows = view_response.get_json()
    assert isinstance(view_rows, list)
    dec_row = next(row for row in view_rows if row.get("decision_id") == "dec-9")
    assert dec_row["decision_ref"]["decision_id"] == "dec-9"
    assert dec_row["decision_ref"]["latest_action"] in {"approve", "execute"}
    assert dec_row["execution_ref"]["status"] is not None


def test_v2_decision_actions_require_idempotency_key(tmp_path):
    settings = _build_settings(tmp_path)
    app = create_app(settings)
    client = app.server.test_client()

    decisions_dir = tmp_path / "decisions"
    _write_jsonl(
        decisions_dir / "decision_view.jsonl",
        [
            {
                "decision_id": "dec-required-idem",
                "created_at": "2025-01-01T10:00:00Z",
                "strategy_type": "arbitrage",
                "primary_instrument": "SBER",
                "action": "hold",
                "risk_state": "green",
                "news_severity": "low",
            }
        ],
    )

    response = client.post(
        "/api/v2/decisions/dec-required-idem/actions",
        json={
            "action": "EXECUTE",
            "actor_id": "tester",
        },
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "invalid_request"
    assert payload["message"] == "idempotency_key is required"


def test_v2_pretrade_check_post(tmp_path, monkeypatch):
    settings = _build_settings(tmp_path)
    app = create_app(settings)
    client = app.server.test_client()

    monkeypatch.setattr(
        ui_app,
        "run_delay_gate",
        lambda *_args, **_kwargs: {
            "status": "PLACE",
            "ready_to_place": True,
            "manual_confirm_required": True,
            "reasons": [],
            "pair": {"stock": "AAA", "future": "AAH6", "direction": "cash_and_carry"},
            "gates": {"stock_quote_pass": True},
            "hits": {"required": 2, "snapshots": 2},
        },
    )

    response = client.post(
        "/api/v2/pretrade/check",
        json={
            "stock": "AAA",
            "future": "AAH6",
            "spot_target": 100.0,
            "future_target": 101.0,
            "snapshots": 3,
            "min_hits": 2,
        },
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["ready_to_place"] is True
    assert data["pretrade_status"] == "pass"
    assert data["params"]["snapshots"] == 3


def test_v2_rejects_oversized_payload_and_preserves_request_id(tmp_path):
    settings = _build_settings(tmp_path, max_api_payload_bytes=256)
    app = create_app(settings)
    client = app.server.test_client()

    response = client.post(
        "/api/v2/decisions/missing/actions",
        headers={"X-Request-Id": "req-large-1"},
        json={
            "action": "execute",
            "comment": "x" * 2048,
        },
    )
    assert response.status_code == 413
    assert response.headers.get("X-Request-Id") == "req-large-1"
    payload = response.get_json()
    assert payload["error"] == "payload_too_large"
    assert payload["max_api_payload_bytes"] == 256
