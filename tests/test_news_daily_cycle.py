from __future__ import annotations

from datetime import date, datetime, timedelta

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.news.backfill import NewsBackfillReport
from moex_carry.news.daily_cycle import run_news_daily_silver_cycle
from moex_carry.news.gold_bootstrap import V2SilverBootstrapReport
from moex_carry.news.target_v2 import EventTargetV2BuildReport
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import upsert_event_target_v2, upsert_news_gold_labels


def _settings(tmp_path) -> AppSettings:
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-daily-cycle.db"),
    )


def test_run_news_daily_silver_cycle_reports_new_labels(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    window_orders: list[str] = []

    def _fake_backfill(
        session,
        settings,
        *,
        period_from,
        period_to,
        commodities,
        include_prices,
        run_inference,
        chunk_days_override,
        max_windows_per_commodity,
        window_order_override,
    ):
        ticker = str(commodities[0])
        window_orders.append(str(window_order_override))
        return NewsBackfillReport(
            period_from=period_from.isoformat(),
            period_to=period_to.isoformat(),
            commodities=[ticker],
            ingested_count=2,
            entity_link_count=2,
            tag_link_count=0,
            score_count=0,
            event_link_count=2,
            event_created_count=1,
            event_updated_count=1,
            event_refuted_count=0,
            event_resolved_count=0,
            quote_count=0,
            windows_processed=1,
            window_order=str(window_order_override),
            newsapi_requests_used=1,
            newsapi_requests_remaining=99,
            qc_report={"passed": True, "commodities": []},
        )

    def _fake_target(
        session,
        *,
        horizon,
        symbol,
        published_from,
        published_to,
        processing_lag_sec,
        max_events,
        use_midpoint,
    ):
        return EventTargetV2BuildReport(
            horizon=str(horizon),
            symbol_filter=str(symbol),
            events_seen=10,
            rows_candidate=3,
            rows_upserted=3,
            rows_deleted=3,
            clean_rows=2,
            hi_conf_rows=1,
            overlap_rows=0,
            leakage_rows=0,
            skipped_no_ticker=0,
            skipped_missing_quotes=0,
            skipped_invalid_time=0,
            skipped_short_history=0,
        )

    def _fake_bootstrap(
        session,
        *,
        horizon,
        symbol,
        published_from,
        published_to,
        min_model_confidence,
        require_both_models,
        require_direction_match_to_target,
        allow_no_model_scores,
        source,
        quality,
        label_schema_version,
        max_events,
        include_overlapped,
        target_selector,
        min_target_confidence,
        min_impact_bin,
        min_abs_z_post,
        min_abs_ar,
        require_primary_news_relevance,
        allowed_languages,
        allow_target_only_fallback,
    ):
        assert target_selector == "impact"
        assert require_primary_news_relevance is True
        assert tuple(allowed_languages) == ("en",)
        assert allow_target_only_fallback is False
        now = datetime(2026, 2, 20, 14, 0, 0)
        upsert_event_target_v2(
            session,
            [
                {
                    "event_id": "evt-new",
                    "symbol": str(symbol),
                    "horizon": str(horizon),
                    "t_pub": now.isoformat() + "Z",
                    "t_anchor": now.isoformat() + "Z",
                    "t0": now.isoformat() + "Z",
                    "t1": (now + timedelta(minutes=5)).isoformat() + "Z",
                    "p0": 100.0,
                    "p1": 101.0,
                    "r_raw": 0.00995,
                    "r_exp": 0.0,
                    "ar": 0.00995,
                    "sigma_pre": 0.0020,
                    "label_v2": 1,
                    "is_hi_conf": False,
                    "leakage_postmove": False,
                    "is_repost": False,
                    "is_overlapped": False,
                    "price_source": "mid",
                }
            ],
        )
        upsert_news_gold_labels(
            session,
            [
                {
                    "target_type": "event",
                    "target_id": "evt-new",
                    "direction_label": "up",
                    "quality": str(quality),
                    "source": str(source),
                    "label_schema_version": str(label_schema_version),
                    "confidence": 0.8,
                }
            ],
        )
        return V2SilverBootstrapReport(
            scanned=1,
            eligible_targets=1,
            accepted=1,
            stored=1,
            skipped_no_primary_news=0,
            skipped_missing_scores=0,
            skipped_confidence=0,
            skipped_disagreement=0,
            skipped_relevance=0,
        )

    monkeypatch.setattr("moex_carry.news.daily_cycle.run_news_backfill", _fake_backfill)
    monkeypatch.setattr("moex_carry.news.daily_cycle.rebuild_event_target_v2", _fake_target)
    monkeypatch.setattr("moex_carry.news.daily_cycle.bootstrap_silver_from_v2_targets", _fake_bootstrap)

    with session_factory() as session:
        baseline_ts = datetime(2026, 2, 20, 10, 0, 0)
        upsert_event_target_v2(
            session,
            [
                {
                    "event_id": "evt-old",
                    "symbol": "NG_US",
                    "horizon": "5m",
                    "t_pub": baseline_ts.isoformat() + "Z",
                    "t_anchor": baseline_ts.isoformat() + "Z",
                    "t0": baseline_ts.isoformat() + "Z",
                    "t1": (baseline_ts + timedelta(minutes=5)).isoformat() + "Z",
                    "p0": 100.0,
                    "p1": 99.5,
                    "r_raw": -0.005,
                    "r_exp": 0.0,
                    "ar": -0.005,
                    "sigma_pre": 0.0020,
                    "label_v2": -1,
                    "is_hi_conf": True,
                    "leakage_postmove": False,
                    "is_repost": False,
                    "is_overlapped": False,
                    "price_source": "mid",
                }
            ],
        )
        upsert_news_gold_labels(
            session,
            [
                {
                    "target_type": "event",
                    "target_id": "evt-old",
                    "direction_label": "down",
                    "quality": "silver",
                    "source": "auto_target_v2",
                    "label_schema_version": "v2",
                    "confidence": 0.7,
                }
            ],
        )

        report = run_news_daily_silver_cycle(
            session,
            settings,
            run_date=date(2026, 2, 20),
            symbol="NG_US",
            horizon="5m",
            fresh_days=2,
            fresh_chunk_days=1,
            fresh_max_windows=40,
            backlog_from_date=date(2026, 1, 1),
            backlog_chunk_days=30,
            backlog_max_windows=1,
            include_prices=False,
            run_inference=False,
            processing_lag_sec=60,
            use_midpoint=True,
            min_model_confidence=0.55,
            require_both_models=False,
            require_direction_match_to_target=False,
            allow_no_model_scores=True,
            include_overlapped=False,
            target_selector="impact",
            min_target_confidence=0.35,
            min_impact_bin=1,
            min_abs_z_post=1.0,
            min_abs_ar=0.0005,
            source_v2="auto_target_v2",
            quality_v2="silver",
            label_schema_version="v2",
        )

    assert window_orders == ["recent_first", "shock_first"]
    assert report.silver_labels_before == 1
    assert report.silver_labels_after == 2
    assert report.silver_labels_new == 1
    assert report.silver_report.accepted == 1
