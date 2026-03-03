from __future__ import annotations

from pathlib import Path

import pandas as pd

from moex_carry.news_shock_readiness import ReadinessConfig, run_readiness_assessment


def _build_input(rows: int = 200) -> pd.DataFrame:
    data: list[dict[str, object]] = []
    symbols = ["BRN", "GOLD", "NG_US"]
    for idx in range(rows):
        symbol = symbols[idx % len(symbols)]
        minute = idx % 60
        hour = (idx // 60) % 24
        day = 1 + (idx // 120)
        shock_ts = f"2026-01-{day:02d}T{hour:02d}:{minute:02d}:00Z"
        z_score = 3.0 if idx % 4 != 0 else 2.3
        label_has = 1 if idx % 2 == 0 else 0
        selected_source = "v2_clean" if idx % 3 != 0 else "broad"
        data.append(
            {
                "symbol": symbol,
                "shock_ts": shock_ts,
                "prev_ts": shock_ts,
                "bar_minutes": 5,
                "prev_price": 100.0 + idx * 0.1,
                "price": 100.0 + idx * 0.1 + (0.6 if idx % 2 == 0 else -0.5),
                "logret": 0.006 if idx % 2 == 0 else -0.005,
                "abs_move_pct": 0.6 if idx % 2 == 0 else 0.5,
                "shock_direction": "up" if idx % 2 == 0 else "down",
                "rolling_sigma": 0.002,
                "z_score": z_score,
                "broad_event_id": f"evt-b-{idx}" if idx % 3 == 0 else "",
                "broad_event_ts": shock_ts,
                "broad_delay_min": 10.0 if idx % 3 == 0 else "",
                "broad_title": "Market update",
                "broad_url": "https://example/broad",
                "v2_event_id": f"evt-v2-{idx}" if idx % 3 != 0 else "",
                "v2_event_ts": shock_ts,
                "v2_delay_min": 8.0 if idx % 3 != 0 else "",
                "v2_title": "Commodity event",
                "v2_url": "https://example/v2",
                "selected_event_source": selected_source,
                "selected_event_id": f"evt-{idx}",
                "selected_event_ts": shock_ts,
                "selected_delay_min": 8.0,
                "selected_title": "Selected event",
                "selected_url": "https://example/selected",
                "label_has_any": label_has,
                "label_has_gold": 0,
                "label_has_silver": label_has,
                "label_gold_direction": "",
                "label_silver_direction": "up" if idx % 2 == 0 else "down",
                "gold_direction_match": "",
                "silver_direction_match": 1 if label_has and selected_source == "v2_clean" else 0,
            }
        )
    return pd.DataFrame(data)


def test_readiness_assessment_produces_artifacts(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    _build_input(240).to_csv(input_path, index=False)
    output_dir = tmp_path / "out"
    outputs = run_readiness_assessment(input_path, output_dir, config=ReadinessConfig())
    assert (output_dir / "readiness_report.json").exists()
    assert (output_dir / "readiness_report.md").exists()
    assert Path(outputs["checks"]).exists()
    checks = pd.read_csv(outputs["checks"])
    assert {"check_name", "passed", "critical"}.issubset(checks.columns)
