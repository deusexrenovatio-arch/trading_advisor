from __future__ import annotations

from pathlib import Path


def _python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _contains_pipeline_import(source: str) -> bool:
    checks = (
        "from moex_carry.pipeline import",
        "import moex_carry.pipeline",
    )
    return any(token in source for token in checks)


def test_hpo_modules_do_not_import_pipeline_directly():
    root = Path("src/moex_carry/hpo")
    offenders: list[str] = []
    for path in _python_files(root):
        source = path.read_text(encoding="utf-8")
        if _contains_pipeline_import(source):
            offenders.append(path.as_posix())
    assert not offenders, f"hpo_pipeline_import_boundary_violation:{offenders}"


def test_signal_replay_core_does_not_import_pipeline_directly():
    path = Path("src/moex_carry/signal_replay/core.py")
    source = path.read_text(encoding="utf-8")
    assert not _contains_pipeline_import(source), "signal_replay_core_pipeline_import_boundary_violation"


def test_pipeline_does_not_import_unified_runtime_directly():
    path = Path("src/moex_carry/pipeline.py")
    source = path.read_text(encoding="utf-8")
    checks = (
        "from moex_carry.unified_runtime import",
        "import moex_carry.unified_runtime",
    )
    assert not any(token in source for token in checks), "pipeline_unified_runtime_direct_import_violation"

def test_signal_replay_incremental_does_not_import_pipeline_directly():
    path = Path("src/moex_carry/signal_replay/incremental.py")
    source = path.read_text(encoding="utf-8")
    assert not _contains_pipeline_import(source), "signal_replay_incremental_pipeline_import_boundary_violation"
