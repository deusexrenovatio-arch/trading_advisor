from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from context_router import route_files  # noqa: E402


def _entry(result: dict[str, object], context_id: str) -> dict[str, object]:
    for item in result["contexts"]:
        if item["id"] == context_id:
            return item
    raise AssertionError(f"missing context entry {context_id}")


def test_route_files_uses_intent_fallback_for_orchestration() -> None:
    result = route_files(
        [],
        request_text="adjust pipeline config runtime entrypoint",
        target_modules=["pipeline"],
        session_handoff_text="Goal: keep pipeline runtime wiring deterministic.",
    )

    assert result["primary_context"] == "CTX-ORCHESTRATION"
    assert "No diff yet. Using request/session intent fallback." in result["recommendations"]


def test_route_files_reports_contract_risk_for_mixed_paths() -> None:
    result = route_files(
        [
            "src/moex_carry/ui/app.py",
            "docs/contracts/api-v2.yaml",
        ]
    )

    assert result["primary_context"] == "CTX-API-UI"
    assert any(
        "CTX-CONTRACTS is combined with other contexts." in note
        for note in result["recommendations"]
    )


def test_route_files_adds_dependency_hints_for_pipeline() -> None:
    result = route_files(["src/moex_carry/pipeline.py"])
    entry = _entry(result, "CTX-ORCHESTRATION")

    assert result["primary_context"] == "CTX-ORCHESTRATION"
    assert "CTX-DATA" in entry["dependency_contexts"]
    assert "CTX-STRATEGY" in entry["dependency_contexts"]
