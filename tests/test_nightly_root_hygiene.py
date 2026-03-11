from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nightly_root_hygiene  # noqa: E402


def test_nightly_root_hygiene_preserves_git_and_dotfiles(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".gitignore").write_text("# gitignore\n", encoding="utf-8")
    (repo / ".cursorignore").write_text("data/\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "src").mkdir()
    (repo / "stale.log").write_text("stale\n", encoding="utf-8")

    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", ["nightly_root_hygiene.py", "--apply"])

    assert nightly_root_hygiene.main() == 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    archive_root = repo / "docs" / "archive" / "root-hygiene" / stamp
    assert (archive_root / "stale.log").exists()
    assert not (archive_root / ".git").exists()
    assert (repo / ".git").exists()
    assert (repo / ".gitignore").exists()
    assert (repo / ".cursorignore").exists()


def test_nightly_root_hygiene_dry_run_reports_stale(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "docs").mkdir()
    (repo / "scratch.tmp").write_text("x\n", encoding="utf-8")

    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", ["nightly_root_hygiene.py"])

    assert nightly_root_hygiene.main() == 1
