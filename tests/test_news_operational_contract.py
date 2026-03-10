from __future__ import annotations

from pathlib import Path

from moex_carry.config import load_settings


REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_PROD_PATHS = [
    "scripts/manage_news_ingest_tasks.ps1",
    "scripts/start_news_ingest_cycle.ps1",
    "scripts/manage_news_shock_live_plan.ps1",
    "scripts/manage_shock_label_cycle_task.ps1",
    "scripts/start_shock_label_cycle.ps1",
    "scripts/run_shock_label_cycle.py",
    "src/moex_carry/news_shock_automation.py",
]
LEGACY_TOKENS = [
    "manage_news_ingest_tasks.ps1",
    "start_news_ingest_cycle.ps1",
    "manage_news_shock_live_plan.ps1",
    "manage_shock_label_cycle_task.ps1",
    "start_shock_label_cycle.ps1",
    "run_shock_label_cycle.py",
    "shock_label_cycle",
    "live_news_signals.csv",
]


def test_legacy_operational_paths_are_removed() -> None:
    for relative_path in LEGACY_PROD_PATHS:
        assert not (REPO_ROOT / relative_path).exists(), relative_path


def test_root_cycle_scripts_define_single_scheduler_contract() -> None:
    start_script = (REPO_ROOT / "scripts" / "start_news_root_cycle.ps1").read_text(encoding="utf-8")
    manager_script = (REPO_ROOT / "scripts" / "manage_news_root_cycle_task.ps1").read_text(encoding="utf-8")

    assert "news_root_cycle" in start_script
    assert "shock_label_cycle" not in start_script
    assert "MoexCarry-NewsRootLive" in manager_script
    assert "MoexCarry-NewsRootBackfill" in manager_script
    assert "start_news_root_cycle.ps1" in manager_script
    for token in (
        "manage_news_ingest_tasks.ps1",
        "manage_shock_label_cycle_task.ps1",
        "manage_news_shock_live_plan.ps1",
        "start_shock_label_cycle.ps1",
        "run_shock_label_cycle.py",
    ):
        assert token not in manager_script


def test_docs_and_defaults_point_to_discovery_and_root_cycle() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (REPO_ROOT / "docs" / "runbooks" / "news-shock-go-live.md").read_text(encoding="utf-8")

    for text in (readme, runbook):
        assert "news_root_cycle" in text
    for token in LEGACY_TOKENS:
        assert token not in runbook
    for token in ("manage_news_ingest_tasks.ps1", "manage_shock_label_cycle_task.ps1", "run_shock_label_cycle.py"):
        assert token not in readme

    assert "live_news_discovery.csv" in runbook
    assert "live_news_verified.csv" in runbook
    assert "manage_news_root_cycle_task.ps1" in runbook
    assert "telegram.news_feed_path" in runbook

    settings = load_settings()
    assert settings.telegram.news_feed_path.endswith("live_news_discovery.csv")
    assert settings.news_filter.live_feed_path.endswith("live_news_discovery.csv")
