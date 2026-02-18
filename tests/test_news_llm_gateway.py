from __future__ import annotations

from datetime import datetime

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.news.llm_gateway import build_news_llm_batch_requests, run_news_llm_full_pass
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_news_labels,
    load_news_llm_runs,
    upsert_news_event_items,
    upsert_news_events,
    upsert_news_items,
)


def _settings(tmp_path):
    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-llm.db"),
    )
    settings.news_llm.enabled = True
    settings.news_llm.full_pass_enabled = True
    settings.news_llm.max_items_per_run = 10
    settings.news_llm.model_id = "gpt-test"
    settings.news_llm.prompt_version = "news-v1"
    settings.news_llm.api_key_env = "OPENAI_API_KEY"
    return settings


def _seed_event(session, *, suffix: str = "1", ts: datetime | None = None):
    ts = ts or datetime(2026, 1, 20, 10, 0, 0)
    suffix_key = str(suffix).strip() or "1"
    news_id = f"news-llm-{suffix_key}"
    event_id = f"evt-llm-{suffix_key}"
    upsert_news_items(
        session,
        [
            {
                "news_id": news_id,
                "source": "Reuters",
                "url": f"https://example.org/{news_id}",
                "title": f"Unexpected export cut supports crude ({suffix_key})",
                "content": "Supply decline can tighten near-term futures.",
                "language": "en",
                "published_at": ts.isoformat() + "Z",
                "ingested_at": ts.isoformat() + "Z",
                "hash": f"hash-{news_id}",
            }
        ],
    )
    upsert_news_events(
        session,
        [
            {
                "event_id": event_id,
                "event_first_published_at_utc": ts.isoformat() + "Z",
                "event_first_ingested_at_utc": ts.isoformat() + "Z",
                "event_last_published_at_utc": ts.isoformat() + "Z",
                "event_status": "active",
                "canonical_summary": f"Export cut in crude market ({suffix_key})",
                "canonical_mechanism": "Lower supply may push futures prices higher.",
                "cluster_version": "det-v1",
            }
        ],
    )
    upsert_news_event_items(
        session,
        [
            {
                "event_id": event_id,
                "news_id": news_id,
                "link_role": "primary",
                "similarity_score": 0.99,
                "added_at": ts.isoformat() + "Z",
            }
        ],
    )


def test_news_llm_full_pass_writes_label_and_uses_cache(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        _seed_event(session)

    call_counter = {"count": 0}

    def _fake_call(*, settings, input_payload):
        call_counter["count"] += 1
        return (
            {
                "commodity": ["BRN"],
                "market_scope": "futures",
                "instrument_candidates": [{"symbol": "BRN", "exchange": "ICE"}],
                "relevance": 0.93,
                "news_type": ["SUP_DEC"],
                "direction": "positive",
                "magnitude": 0.8,
                "lag_bucket": "short",
                "confidence": 0.9,
                "uncertainty_type": "none",
                "geo_scope": "global",
                "evidence_spans": [{"start": 0, "end": 30, "text": "export cut supports crude"}],
            },
            {"token_in": 120, "token_out": 40, "latency_ms": 35},
        )

    monkeypatch.setattr("moex_carry.news.llm_gateway._call_openai_structured", _fake_call)

    with session_factory() as session:
        first = run_news_llm_full_pass(session, settings)
        second = run_news_llm_full_pass(session, settings)
        labels = load_news_labels(session, target_level="event", target_ids=["evt-llm-1"], label_source="llm", limit=20)
        runs = load_news_llm_runs(session, target_level="event", target_id="evt-llm-1", limit=20)

    assert first.completed_count == 1
    assert first.labeled_count == 1
    assert second.skipped_count >= 1
    assert call_counter["count"] == 1
    assert len(labels) >= 1
    assert any(str(row.get("status") or "") == "done" for row in runs)


def test_news_llm_full_pass_marks_skipped_without_api_key(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        _seed_event(session)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with session_factory() as session:
        report = run_news_llm_full_pass(session, settings)
        runs = load_news_llm_runs(session, target_level="event", target_id="evt-llm-1", limit=20)

    assert report.skipped_count == 1
    assert report.failed_count == 0
    assert any(str(row.get("status") or "") == "skipped" for row in runs)
    assert any(str(row.get("error_code") or "") == "missing_api_key" for row in runs)


def test_news_llm_full_pass_respects_call_budget(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    settings.news_llm.max_calls_per_run = 1
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        _seed_event(session, suffix="1", ts=datetime(2026, 1, 20, 10, 0, 0))
        _seed_event(session, suffix="2", ts=datetime(2026, 1, 20, 10, 5, 0))

    def _fake_call(*, settings, input_payload):
        return (
            {
                "commodity": ["BRN"],
                "market_scope": "futures",
                "instrument_candidates": [{"symbol": "BRN", "exchange": "ICE"}],
                "relevance": 0.90,
                "news_type": ["SUP_DEC"],
                "direction": "positive",
                "magnitude": 0.7,
                "lag_bucket": "short",
                "confidence": 0.8,
                "uncertainty_type": "none",
                "geo_scope": "global",
                "evidence_spans": [{"start": 0, "end": 20, "text": "export cut"}],
            },
            {"token_in": 100, "token_out": 20, "latency_ms": 15},
        )

    monkeypatch.setattr("moex_carry.news.llm_gateway._call_openai_structured", _fake_call)

    with session_factory() as session:
        report = run_news_llm_full_pass(session, settings)
        runs = load_news_llm_runs(session, target_level="event", limit=20)

    assert report.budget_exhausted is True
    assert report.budget_reason == "max_calls_per_run"
    assert report.processed_count == 1
    assert report.completed_count == 1
    assert report.token_in_total == 100
    assert report.token_out_total == 20
    assert len([row for row in runs if str(row.get("status") or "") == "done"]) == 1


def test_news_llm_batch_export_skips_cached_by_default(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        _seed_event(session)

    def _fake_call(*, settings, input_payload):
        return (
            {
                "commodity": ["BRN"],
                "market_scope": "futures",
                "instrument_candidates": [{"symbol": "BRN", "exchange": "ICE"}],
                "relevance": 0.93,
                "news_type": ["SUP_DEC"],
                "direction": "positive",
                "magnitude": 0.8,
                "lag_bucket": "short",
                "confidence": 0.9,
                "uncertainty_type": "none",
                "geo_scope": "global",
                "evidence_spans": [{"start": 0, "end": 30, "text": "export cut supports crude"}],
            },
            {"token_in": 120, "token_out": 40, "latency_ms": 35},
        )

    monkeypatch.setattr("moex_carry.news.llm_gateway._call_openai_structured", _fake_call)

    with session_factory() as session:
        _ = run_news_llm_full_pass(session, settings)
        report_default = build_news_llm_batch_requests(session, settings, max_items=10, include_cached=False)
        report_include = build_news_llm_batch_requests(session, settings, max_items=10, include_cached=True)

    assert int(report_default["requested_count"]) >= 1
    assert int(report_default["exported_count"]) == 0
    assert int(report_default["skipped_cached_count"]) >= 1
    assert int(report_include["exported_count"]) >= 1
