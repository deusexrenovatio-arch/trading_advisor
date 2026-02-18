from __future__ import annotations

from pathlib import Path

from moex_carry.news.taxonomy_catalog import load_news_taxonomy_catalog


def test_load_news_taxonomy_catalog_from_default_file():
    catalog = load_news_taxonomy_catalog()
    assert catalog.schema_version
    assert len(catalog.factors) >= 5
    assert len(catalog.event_families) >= 5
    assert "NG_STORAGE_EIA" in set(catalog.event_family_codes())


def test_load_news_taxonomy_catalog_missing_file_returns_empty(tmp_path):
    missing_path = Path(tmp_path) / "missing-taxonomy.yaml"
    catalog = load_news_taxonomy_catalog(str(missing_path))
    assert catalog.schema_version == "v0"
    assert catalog.factors == ()
    assert catalog.event_families == ()
