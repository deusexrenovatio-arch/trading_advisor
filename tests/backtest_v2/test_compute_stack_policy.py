from __future__ import annotations

import ast
from pathlib import Path
from typing import get_type_hints

import numpy as np

from moex_carry.analytics.alpha import alpha_matrices_fast
from moex_carry.backtest_v2 import batch as bt_batch


REPO_ROOT = Path(__file__).resolve().parents[2]
HOT_PATHS = (
    REPO_ROOT / "src/moex_carry/backtest_v2/batch.py",
    REPO_ROOT / "src/moex_carry/analytics/alpha.py",
)


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_hot_path_modules_do_not_import_pandas() -> None:
    for path in HOT_PATHS:
        imports = _import_roots(path)
        assert "pandas" not in imports, f"pandas import found in hot path: {path}"


def test_feature_matrices_are_numpy_arrays() -> None:
    hints = get_type_hints(bt_batch.FeatureMatrices, globalns=bt_batch.__dict__)
    fields = (
        "r_cb",
        "floor_rate",
        "floor_pass",
        "rtc_pct",
        "spread_bps_stock",
        "spread_bps_fut",
        "liquidity_pass",
        "event_blocked",
        "dte",
        "spread_pct",
    )
    for field in fields:
        assert hints[field] is np.ndarray


def test_alpha_matrices_fast_is_deterministic_on_sample_input() -> None:
    spread_pct = np.array(
        [
            [0.0100, 0.0120],
            [0.0108, 0.0115],
            [0.0112, 0.0110],
            [0.0105, 0.0107],
            [0.0109, 0.0109],
        ],
        dtype=float,
    )
    out_a = alpha_matrices_fast(
        spread_pct,
        horizon=2,
        tp=0.001,
        sl=0.001,
        history_days=3,
    )
    out_b = alpha_matrices_fast(
        spread_pct,
        horizon=2,
        tp=0.001,
        sl=0.001,
        history_days=3,
    )
    assert len(out_a) == 4
    for arr_a, arr_b in zip(out_a, out_b):
        assert arr_a.shape == spread_pct.shape
        np.testing.assert_allclose(arr_a, arr_b, rtol=0.0, atol=0.0)
