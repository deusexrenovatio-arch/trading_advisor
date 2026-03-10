from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from compute_change_surface import compute_surface  # noqa: E402


MAPPING = ROOT / "configs" / "change_surface_mapping.yaml"


def test_docs_only_surface_detected() -> None:
    result = compute_surface(
        [
            "docs/README.md",
            "docs/workflows/context-budget.md",
        ],
        mapping_path=MAPPING,
    )

    assert result["docs_only"] is True
    assert "docs-only" in result["surfaces"]
    assert result["primary_surface"] in {"governance", "docs-only"}


def test_mixed_surface_detected_for_core_and_ui() -> None:
    result = compute_surface(
        [
            "src/moex_carry/pipeline.py",
            "ui-web/src/App.tsx",
        ],
        mapping_path=MAPPING,
    )

    assert "core" in result["surfaces"]
    assert "ui" in result["surfaces"]
    assert "mixed" in result["surfaces"]


def test_loop_commands_include_surface_specific_entries() -> None:
    result = compute_surface(
        ["src/moex_carry/news_live_runtime.py"],
        mapping_path=MAPPING,
    )

    loop_commands = result["commands"]["loop"]
    assert any("validate_python_style.py" in command for command in loop_commands)
    assert any("test_news_live_runtime.py" in command for command in loop_commands)
