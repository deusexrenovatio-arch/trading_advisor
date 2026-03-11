from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_news_golden_top20 as news_gold  # noqa: E402


def test_require_feedparser_reports_install_hint_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(news_gold, "_feedparser", None)
    with pytest.raises(SystemExit, match="pip install -e \\.\\[news\\]"):
        news_gold._require_feedparser()


def test_require_feedparser_returns_module_when_available(monkeypatch) -> None:
    fake_module = SimpleNamespace(parse=lambda _url: SimpleNamespace(entries=[]))
    monkeypatch.setattr(news_gold, "_feedparser", fake_module)
    assert news_gold._require_feedparser() is fake_module
