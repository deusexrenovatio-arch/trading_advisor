from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from moex_carry.news_shock_pipeline import (
    LabelPackConfig,
    ShockCurationConfig,
    build_shock_label_pack,
    curate_shock_dataset,
    ingest_chat_labels,
    write_label_pack_jsonl,
)


def _raw_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "NG_US",
                "shock_ts": "2026-01-20T10:00:00Z",
                "z_score": 3.2,
                "abs_move_pct": 5.1,
                "prev_price": 3.0,
                "price": 3.15,
                "logret": 0.01,
                "shock_direction": "up",
                "v2_event_id": "evt-v2-a",
                "v2_delay_min": 9.0,
                "v2_event_ts": "2026-01-20T09:51:00Z",
                "v2_title": "Colder forecast lifts gas demand",
                "v2_url": "https://example/v2-a",
                "broad_event_id": "evt-broad-a",
                "broad_delay_min": 8.0,
                "broad_event_ts": "2026-01-20T09:52:00Z",
                "broad_title": "Energy market update",
                "broad_url": "https://example/b-a",
            },
            {
                "symbol": "NG_US",
                "shock_ts": "2026-01-20T10:05:00Z",
                "z_score": 35.0,
                "abs_move_pct": 70.0,
                "prev_price": 3.15,
                "price": 5.35,
                "logret": 0.2,
                "shock_direction": "up",
                "v2_event_id": "",
                "v2_delay_min": "",
                "v2_event_ts": "",
                "v2_title": "",
                "v2_url": "",
                "broad_event_id": "",
                "broad_delay_min": "",
                "broad_event_ts": "",
                "broad_title": "",
                "broad_url": "",
            },
        ]
    )


def _raw_df_sources() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "NG_US",
                "shock_ts": "2026-01-20T10:00:00Z",
                "z_score": 3.2,
                "abs_move_pct": 5.1,
                "prev_price": 3.0,
                "price": 3.15,
                "logret": 0.01,
                "shock_direction": "up",
                "v2_event_id": "evt-v2-a",
                "v2_delay_min": 9.0,
                "v2_event_ts": "2026-01-20T09:51:00Z",
                "v2_title": "Colder forecast lifts gas demand",
                "v2_url": "https://example/v2-a",
                "broad_event_id": "",
                "broad_delay_min": "",
                "broad_event_ts": "",
                "broad_title": "",
                "broad_url": "",
            },
            {
                "symbol": "BRN",
                "shock_ts": "2026-01-21T12:00:00Z",
                "z_score": 2.8,
                "abs_move_pct": 2.1,
                "prev_price": 80.0,
                "price": 81.7,
                "logret": 0.02,
                "shock_direction": "up",
                "v2_event_id": "",
                "v2_delay_min": "",
                "v2_event_ts": "",
                "v2_title": "",
                "v2_url": "",
                "broad_event_id": "evt-broad-b",
                "broad_delay_min": 15.0,
                "broad_event_ts": "2026-01-21T11:45:00Z",
                "broad_title": "Shipping disruption risk rises",
                "broad_url": "https://example/b-b",
            },
            {
                "symbol": "GOLD",
                "shock_ts": "2026-01-22T08:00:00Z",
                "z_score": 2.7,
                "abs_move_pct": 1.0,
                "prev_price": 2020.0,
                "price": 2035.0,
                "logret": 0.007,
                "shock_direction": "up",
                "v2_event_id": "",
                "v2_delay_min": "",
                "v2_event_ts": "",
                "v2_title": "",
                "v2_url": "",
                "broad_event_id": "",
                "broad_delay_min": "",
                "broad_event_ts": "",
                "broad_title": "",
                "broad_url": "",
            },
        ]
    )


def test_curate_shock_dataset_filters_critical_outliers() -> None:
    curated, issues, summary = curate_shock_dataset(_raw_df(), ShockCurationConfig.defaults())
    assert len(curated) == 1
    assert len(issues) == 2
    all_row = summary[summary["symbol"] == "ALL"].iloc[0]
    assert int(all_row["rows_critical_dropped"]) == 1
    dropped = issues[issues["critical_issue"] == 1].iloc[0]
    assert "abs_move_over_cap" in str(dropped["issue_codes"])


def test_build_shock_label_pack_includes_symbol_and_candidate() -> None:
    curated, _, _ = curate_shock_dataset(_raw_df(), ShockCurationConfig.defaults())
    tasks, pack_summary = build_shock_label_pack(curated, LabelPackConfig(min_abs_z=2.5, max_tasks_total=10))
    assert len(tasks) == 1
    task = tasks[0]
    assert task["symbol"] == "NG_US"
    assert task["candidate_primary"]["source"] == "v2_clean"
    assert not pack_summary.empty


def test_build_shock_label_pack_filters_by_primary_candidate_source() -> None:
    curated, _, _ = curate_shock_dataset(_raw_df_sources(), ShockCurationConfig.defaults())
    tasks, _ = build_shock_label_pack(
        curated,
        LabelPackConfig(
            min_abs_z=2.5,
            max_tasks_total=10,
            candidate_sources=("broad",),
        ),
    )
    assert len(tasks) == 1
    assert tasks[0]["candidate_primary"]["source"] == "broad"
    assert tasks[0]["symbol"] == "BRN"


def test_build_shock_label_pack_supports_causal_only_mode() -> None:
    curated, _, _ = curate_shock_dataset(_raw_df_sources(), ShockCurationConfig.defaults())
    tasks, summary = build_shock_label_pack(
        curated,
        LabelPackConfig(
            min_abs_z=2.5,
            max_tasks_total=10,
            candidate_sources=("none",),
            causal_only=True,
        ),
    )
    assert len(tasks) == 1
    task = tasks[0]
    assert task["label_mode"] == "causal_only"
    assert "allowed_direction" not in task["labeling_instruction"]
    assert task["labeling_instruction"]["required_fields"] == ["task_id", "is_causal", "confidence"]
    assert summary.iloc[0]["label_mode"] == "causal_only"


def test_ingest_chat_labels_parses_nested_and_flat_payloads(tmp_path: Path) -> None:
    curated, _, _ = curate_shock_dataset(_raw_df(), ShockCurationConfig.defaults())
    tasks, _ = build_shock_label_pack(curated, LabelPackConfig(min_abs_z=2.5, max_tasks_total=10))
    tasks_path = tmp_path / "tasks.jsonl"
    write_label_pack_jsonl(tasks, tasks_path)

    labels_path = tmp_path / "labels.jsonl"
    payloads = [
        {"task_id": tasks[0]["task_id"], "label": {"direction": "up", "confidence": 0.91, "is_causal": True}},
        {"task_id": "unknown-task", "direction": "down", "confidence": 0.4, "is_causal": True},
    ]
    labels_path.write_text("\n".join(json.dumps(item) for item in payloads), encoding="utf-8")

    merged, summary = ingest_chat_labels(tasks_path, labels_path, min_confidence=0.6)
    assert len(merged) == 1
    row = merged.iloc[0]
    assert row["label_direction"] == "up"
    assert float(row["label_confidence"]) == 0.91
    assert int(row["is_high_conf"]) == 1
    assert not summary.empty
