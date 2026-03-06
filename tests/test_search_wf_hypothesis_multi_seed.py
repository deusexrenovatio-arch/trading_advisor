from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "search_wf_hypothesis_multi_seed.py"
    spec = importlib.util.spec_from_file_location("search_wf_hypothesis_multi_seed_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_candidate_generator_emits_unique_candidates():
    mod = _load_module()
    universe = {
        "setup_kinds": ["ORB_BREAKOUT", "EMA_PULLBACK_LIMIT"],
        "slots": ["10:30", "12:00", "14:15"],
        "roots": ["AN", "CC", "DX", "KC", "MM", "RI", "SF", "SX", "ZC"],
        "instruments": ["ANH6", "CCH6", "DXH6"],
        "sides": ["BUY", "SELL"],
        "clusters": ["energy", "metals", "other"],
    }
    candidates = mod._candidate_generator(universe=universe, count=500, seed=17)
    assert len(candidates) == 500
    signatures = {mod._candidate_signature(item) for item in candidates}
    assert len(signatures) == len(candidates)
    assert all(item["include_setup_kinds"] for item in candidates)
    assert all(item["include_slots"] for item in candidates)
    assert all(item["include_clusters"] for item in candidates)
    assert all(item["include_roots"] for item in candidates)


def test_objective_row_counts_passes_and_stability_fields():
    mod = _load_module()
    row = mod._objective_row(
        candidate={"include_setup_kinds": ["ORB_BREAKOUT"]},
        per_report=[
            {
                "passed": True,
                "win_rate_net": 0.80,
                "trades_per_week": 2.4,
                "net_ticks_sum": 1200.0,
                "concentration_top_share": 0.30,
            },
            {
                "passed": False,
                "win_rate_net": 0.72,
                "trades_per_week": 1.9,
                "net_ticks_sum": 800.0,
                "concentration_top_share": 0.36,
            },
            {
                "passed": True,
                "win_rate_net": 0.77,
                "trades_per_week": 2.1,
                "net_ticks_sum": 950.0,
                "concentration_top_share": 0.33,
            },
        ],
    )
    assert row["passes"] == 2
    assert row["min_win_rate_net"] == 0.72
    assert row["min_trades_per_week"] == 1.9
    assert row["max_concentration_top_share"] == 0.36
    assert row["score"] > 0.0
