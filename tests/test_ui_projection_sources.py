import json

import pandas as pd

from moex_carry.config import AppSettings, DataConfig
from moex_carry.server import create_server_app as create_app
from moex_carry.ui.data import (
    load_projection_sources,
    load_signals_with_source,
    load_top_pairs_with_source,
)


def _write_csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)


def test_load_top_pairs_prefers_unified_projection(tmp_path):
    output_dir = tmp_path / "output"
    unified_dir = output_dir / "unified"
    unified_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "top_pairs.csv", [{"stock": "LEG", "future": "LGH6"}])
    _write_csv(unified_dir / "top_pairs.csv", [{"stock": "UNI", "future": "UNH6"}])
    (unified_dir / "snapshot_meta.json").write_text(
        json.dumps(
            {
                "engine": "unified",
                "generated_at_utc": "2026-02-19T16:20:00Z",
                "datasets": {"top_pairs": {"rows": 1, "sha256": "hash-top"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    df, source = load_top_pairs_with_source(tmp_path, preferred_engine="unified")

    assert len(df) == 1
    assert df.iloc[0]["stock"] == "UNI"
    assert source["selected_engine"] == "unified"
    assert source["fallback_to_legacy"] is False
    assert source["selected_generated_at_utc"] == "2026-02-19T16:20:00Z"
    assert source["selected_sha256"] == "hash-top"


def test_load_signals_falls_back_to_legacy_when_unified_missing(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "signals.csv", [{"stock": "LEG", "future": "LGH6"}])

    df, source = load_signals_with_source(tmp_path, preferred_engine="unified")

    assert len(df) == 1
    assert df.iloc[0]["stock"] == "LEG"
    assert source["selected_engine"] == "legacy"
    assert source["fallback_to_legacy"] is True


def test_projection_source_endpoint_reports_selected_paths(tmp_path):
    output_dir = tmp_path / "output"
    unified_dir = output_dir / "unified"
    unified_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(unified_dir / "top_pairs.csv", [{"stock": "AAA", "future": "AAH6"}])
    _write_csv(unified_dir / "signals.csv", [{"stock": "AAA", "future": "AAH6"}])
    _write_csv(unified_dir / "backtest_summary.csv", [{"sharpe": 1.2}])
    (unified_dir / "snapshot_meta.json").write_text(
        json.dumps(
            {
                "engine": "unified",
                "generated_at_utc": "2026-02-19T16:25:00Z",
                "datasets": {
                    "top_pairs": {"rows": 1, "sha256": "h1"},
                    "signals": {"rows": 1, "sha256": "h2"},
                    "backtest_summary": {"rows": 1, "sha256": "h3"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    app = create_app(settings)
    client = app.server.test_client()

    response = client.get("/api/projections/source")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["active_engine"] == "unified"
    assert payload["datasets"]["top_pairs"]["selected_engine"] == "unified"
    assert payload["datasets"]["signals"]["selected_engine"] == "unified"
    assert payload["datasets"]["backtest_summary"]["selected_engine"] == "unified"

    direct = load_projection_sources(tmp_path, preferred_engine="unified")
    assert direct["datasets"]["top_pairs"]["selected_engine"] == "unified"

