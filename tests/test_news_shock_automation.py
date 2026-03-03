from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from moex_carry.news_shock_automation import ShockLabelCycleConfig, run_shock_label_cycle


def _input_df() -> pd.DataFrame:
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


def test_run_shock_label_cycle_builds_direction_and_causal_packs(tmp_path: Path) -> None:
    input_csv = tmp_path / "input.csv"
    output_dir = tmp_path / "cycle"
    _input_df().to_csv(input_csv, index=False)

    outputs = run_shock_label_cycle(
        input_csv=input_csv,
        output_dir=output_dir,
        config=ShockLabelCycleConfig(
            min_abs_z=2.5,
            direction_max_tasks_total=10,
            causal_max_tasks_total=10,
            direction_candidate_sources=("v2_clean",),
            causal_candidate_sources=("broad", "none"),
            run_readiness=False,
        ),
    )

    assert int(outputs["curated_rows"]) == 3
    assert int(outputs["direction_pack"]["tasks_count"]) == 1
    assert int(outputs["causal_pack"]["tasks_count"]) == 2
    manifest_path = Path(str(outputs["manifest_path"]))
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["direction_pack"]["tasks_count"] == 1
    assert payload["causal_pack"]["tasks_count"] == 2
