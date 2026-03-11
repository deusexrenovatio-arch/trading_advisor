from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_routes_contract_surface_into_ui_suite() -> None:
    ci_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert 'ui_surface = {"ui", "contracts", "mixed"}' in ci_text


def test_pre_push_uses_scoped_loop_gate_instead_of_pr_gate() -> None:
    hook_text = (ROOT / ".githooks/pre-push").read_text(encoding="utf-8")
    assert "python scripts/run_loop_gate.py --base-ref origin/main --head-ref HEAD --skip-session-check" in hook_text
    assert "python scripts/run_pr_gate.py --base-ref origin/main --head-ref HEAD --skip-session-check" not in hook_text


def test_release_notes_main_push_override_contract_is_current() -> None:
    notes = (ROOT / "docs/release-notes.md").read_text(encoding="utf-8")
    assert "MOEX_CARRY_ALLOW_MAIN_PUSH=1" not in notes
    assert "MOEX_CARRY_EMERGENCY_MAIN_PUSH=1" in notes
    assert "MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON" in notes
