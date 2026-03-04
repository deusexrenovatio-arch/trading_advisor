from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from moex_carry.news_silver_store import (
    apply_silver_labels_from_db,
    ingest_event_labels_jsonl_to_db,
    persist_task_merged_labels_to_db,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in rows:
            handle.write(json.dumps(item, ensure_ascii=False))
            handle.write("\n")


def _db_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_ingest_event_labels_and_apply_by_title_fallback(tmp_path: Path) -> None:
    labels_jsonl = tmp_path / "labels.jsonl"
    tasks_jsonl = tmp_path / "tasks.jsonl"
    db_path = tmp_path / "silver.db"

    _write_jsonl(
        tasks_jsonl,
        [
            {
                "task_id": "hitl-1",
                "event_id": "evt-weather-1",
                "published_at": "2026-03-01T10:00:00Z",
                "input_payload": {
                    "event_id": "evt-weather-1",
                    "canonical_summary": "Severe cold weather boosts U.S. gas heating demand",
                    "canonical_mechanism": "NG_US weather demand",
                },
            }
        ],
    )
    _write_jsonl(
        labels_jsonl,
        [
            {
                "event_id": "evt-weather-1",
                "label": {
                    "commodity": ["natural_gas"],
                    "direction": "positive",
                    "confidence": 0.92,
                    "relevance": 0.88,
                    "magnitude": 0.75,
                },
            }
        ],
    )
    result = ingest_event_labels_jsonl_to_db(
        labels_jsonl=labels_jsonl,
        tasks_jsonl=tasks_jsonl,
        database_url=_db_url(db_path),
        data_dir=tmp_path,
        source_tag="test_event",
        min_confidence=0.6,
        min_relevance=0.5,
    )
    assert int(result["records_stored"]) >= 1

    shocks = pd.DataFrame(
        [
            {
                "symbol": "NG_US",
                "shock_ts": "2026-03-01T10:05:00Z",
                "shock_direction": "up",
                "selected_event_id": "",
                "selected_title": "Severe cold weather boosts U.S. gas heating demand",
                "label_has_any": 0,
                "label_has_silver": 0,
                "label_silver_direction": "",
                "silver_direction_match": pd.NA,
            }
        ]
    )
    labeled = apply_silver_labels_from_db(
        df=shocks,
        database_url=_db_url(db_path),
        data_dir=tmp_path,
    )
    row = labeled.iloc[0]
    assert int(row["label_has_any"]) == 1
    assert int(row["label_has_silver"]) == 1
    assert str(row["label_silver_direction"]) == "up"
    assert int(row["silver_direction_match"]) == 1


def test_persist_task_labels_and_apply_by_event_id(tmp_path: Path) -> None:
    db_path = tmp_path / "silver_task.db"
    merged = pd.DataFrame(
        [
            {
                "task_id": "shock-00001-BRN",
                "symbol": "BRN",
                "shock_ts_utc": "2026-03-02T09:00:00Z",
                "primary_event_id": "newsapi-brn-attack-1",
                "primary_title": "Oil jumps after shipping attack in chokepoint",
                "label_direction": "down",
                "label_confidence": 0.81,
                "label_is_causal": 1,
            }
        ]
    )
    stored = persist_task_merged_labels_to_db(
        merged=merged,
        database_url=_db_url(db_path),
        data_dir=tmp_path,
        source_tag="test_task",
        source_ref="tasks.jsonl",
    )
    assert int(stored) == 1

    shocks = pd.DataFrame(
        [
            {
                "symbol": "BRN",
                "shock_ts": "2026-03-02T09:05:00Z",
                "shock_direction": "down",
                "selected_event_id": "newsapi-brn-attack-1",
                "selected_title": "Some other title",
                "label_has_any": 0,
                "label_has_silver": 0,
                "label_silver_direction": "",
                "silver_direction_match": pd.NA,
            }
        ]
    )
    labeled = apply_silver_labels_from_db(
        df=shocks,
        database_url=_db_url(db_path),
        data_dir=tmp_path,
    )
    row = labeled.iloc[0]
    assert int(row["label_has_any"]) == 1
    assert int(row["label_has_silver"]) == 1
    assert str(row["label_silver_direction"]) == "down"
    assert int(row["silver_direction_match"]) == 1
