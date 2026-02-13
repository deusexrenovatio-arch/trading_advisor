from __future__ import annotations

from pathlib import Path

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.decision_log import (
    DecisionLogStore,
    build_decision_view,
    load_jsonl,
)
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import load_decision_view_projection


def _build_decision_log(
    *,
    decision_id: str,
    created_at: str,
    action: str,
    risk_state: str,
    primary_instrument: str,
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "decision_id": decision_id,
        "created_at": created_at,
        "environment": {
            "mode": "paper",
            "venue": "MOEX",
            "timezone": "UTC",
        },
        "input_snapshots": [
            {
                "source": "MOEX_ISS",
                "snapshot_id": f"snap-{decision_id}",
                "as_of": created_at,
                "hash": "hash-1",
            }
        ],
        "feature_set": {
            "feature_version": "v1",
            "features": [
                {
                    "name": "spread_mid",
                    "value": 1.0,
                }
            ],
        },
        "strategies": [
            {
                "name": "stock_futures_spread_carry_alpha",
                "type": "arbitrage",
                "enabled": True,
                "signals": [
                    {
                        "name": "signal_score",
                        "value": 0.9,
                        "direction": "long",
                    }
                ],
                "rules_evaluated": [
                    {
                        "id": "rule-1",
                        "result": True,
                    }
                ],
            }
        ],
        "portfolio_proposal": {
            "allocations": [
                {
                    "instrument": primary_instrument,
                    "side": "long",
                }
            ]
        },
        "risk_checks": [
            {
                "id": "risk-max",
                "passed": risk_state == "green",
            }
        ],
        "cost_model": {
            "fee_side": 1.0,
            "round_trip_cost": 2.0,
            "break_even_ticks": 0.5,
        },
        "decision": {
            "action": action,
            "risk_state": risk_state,
        },
        "news_context": {
            "severity": "low",
            "headline_count": 0,
            "summary": "none",
        },
        "decision_view_id": f"view-{decision_id}",
    }


def _build_session_factory(tmp_path: Path):
    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/write-through.db"),
    )
    engine = create_engine_from_settings(settings)
    init_db(engine)
    return create_session_factory(engine)


def test_decision_log_store_write_through_inserts_projection(tmp_path):
    session_factory = _build_session_factory(tmp_path)
    store = DecisionLogStore(tmp_path, session_factory=session_factory)

    decision_log = _build_decision_log(
        decision_id="dec-write-through-1",
        created_at="2025-01-01T10:00:00Z",
        action="approve",
        risk_state="green",
        primary_instrument="SBER",
    )
    decision_view = build_decision_view(decision_log)
    store.append(decision_log, decision_view)

    jsonl_rows = load_jsonl(tmp_path / "decisions" / "decision_view.jsonl")
    assert len(jsonl_rows) == 1

    with session_factory() as session:
        projection_rows = load_decision_view_projection(session, limit=10)
    assert len(projection_rows) == 1
    assert projection_rows[0]["decision_id"] == "dec-write-through-1"
    assert projection_rows[0]["primary_instrument"] == "SBER"


def test_decision_log_store_write_through_updates_projection_on_same_decision_id(tmp_path):
    session_factory = _build_session_factory(tmp_path)
    store = DecisionLogStore(tmp_path, session_factory=session_factory)

    first_log = _build_decision_log(
        decision_id="dec-write-through-2",
        created_at="2025-01-01T10:00:00Z",
        action="approve",
        risk_state="green",
        primary_instrument="GAZP",
    )
    second_log = _build_decision_log(
        decision_id="dec-write-through-2",
        created_at="2025-01-01T11:00:00Z",
        action="hold",
        risk_state="red",
        primary_instrument="GAZP",
    )
    store.append(first_log, build_decision_view(first_log))
    store.append(second_log, build_decision_view(second_log))

    jsonl_rows = load_jsonl(tmp_path / "decisions" / "decision_view.jsonl")
    assert len(jsonl_rows) == 2

    with session_factory() as session:
        projection_rows = load_decision_view_projection(session, limit=10)
    assert len(projection_rows) == 1
    assert projection_rows[0]["decision_id"] == "dec-write-through-2"
    assert projection_rows[0]["risk_state"] == "red"
    assert projection_rows[0]["action"] == "hold"
