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
            "docs/overview.md",
        ],
        mapping_path=MAPPING,
    )

    assert result["docs_only"] is True
    assert result["primary_surface"] == "docs-only"
    assert result["surfaces"] == ["docs-only"]


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


def test_rename_notation_is_classified_by_new_path() -> None:
    result = compute_surface(
        [
            "src/moex_carry/old_module.py -> src/moex_carry/pipeline.py",
        ],
        mapping_path=MAPPING,
    )

    assert result["primary_surface"] == "core"
    assert "core" in result["surfaces"]
    assert result["changed_files"] == ["src/moex_carry/pipeline.py"]


def test_deleted_docs_path_remains_docs_only() -> None:
    result = compute_surface(
        [
            "docs/deprecated-guideline.md",
        ],
        mapping_path=MAPPING,
    )

    assert result["docs_only"] is True
    assert result["primary_surface"] == "docs-only"
    assert "docs-only" in result["surfaces"]


def test_unknown_path_is_fail_closed_to_governance() -> None:
    result = compute_surface(
        ["tmp/unmapped.file"],
        mapping_path=MAPPING,
    )

    assert result["docs_only"] is False
    assert result["primary_surface"] == "governance"
    assert "governance" in result["surfaces"]
    assert any("validate_plans.py" in command for command in result["commands"]["loop"])


def test_unknown_path_adds_governance_to_mapped_surface() -> None:
    result = compute_surface(
        [
            "src/moex_carry/pipeline.py",
            "tmp/unmapped.file",
        ],
        mapping_path=MAPPING,
    )

    assert "core" in result["surfaces"]
    assert "governance" in result["surfaces"]
    assert any("validate_file_size_policy.py" in command for command in result["commands"]["loop"])


def test_loop_commands_include_surface_specific_entries() -> None:
    result = compute_surface(
        ["src/moex_carry/news_live_runtime.py"],
        mapping_path=MAPPING,
    )

    loop_commands = result["commands"]["loop"]
    assert any("validate_python_style.py" in command for command in loop_commands)
    assert any("test_news_live_runtime.py" in command for command in loop_commands)


def test_pr_commands_include_ui_checks_for_contracts_surface() -> None:
    result = compute_surface(
        ["contracts/api-v2.yaml"],
        mapping_path=MAPPING,
    )

    pr_commands = result["commands"]["pr"]
    assert any("npm --prefix ui-web run lint" in command for command in pr_commands)
    assert any("npm --prefix ui-web run build" in command for command in pr_commands)
    assert any("pytest tests/test_api_v2.py -q" in command for command in pr_commands)


def test_windows_style_paths_are_normalized() -> None:
    result = compute_surface(
        [r"src\moex_carry\storage\repositories_v2.py"],
        mapping_path=MAPPING,
    )
    assert result["primary_surface"] == "contracts"
    assert result["changed_files"] == ["src/moex_carry/storage/repositories_v2.py"]


def test_server_paths_are_classified_as_core() -> None:
    result = compute_surface(
        [
            "src/moex_carry/server/app.py",
            "scripts/run_server.py",
        ],
        mapping_path=MAPPING,
    )

    assert result["primary_surface"] == "core"
    assert "core" in result["surfaces"]
