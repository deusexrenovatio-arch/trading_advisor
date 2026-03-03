from __future__ import annotations

from datetime import date

from moex_carry.news import live_eval


class _StubMoexClient:
    def get_futures_specs(self, board):
        assert board == "RFUD"
        return [
            {"SECID": "BRJ6", "ASSETCODE": "BR", "LASTTRADEDATE": "2026-03-20"},
            {"SECID": "BRH6", "ASSETCODE": "BR", "LASTTRADEDATE": "2026-03-01"},
        ]

    def get_candles(self, engine, market, secid, board, from_date, till_date, interval=1):
        assert engine == "futures"
        assert market == "forts"
        assert secid == "BRJ6"
        assert board == "RFUD"
        assert interval == 1
        return [
            {"begin": "2026-03-01 23:29:00", "close": 100.0},
            {"begin": "2026-03-02 00:29:00", "close": 103.0},
            {"begin": "2026-03-02 00:30:00", "close": 103.1},
        ]


def test_build_news_live_eval_rows_tracks_gap_and_tradable_hit_rate(monkeypatch):
    event_rows = [
        {
            "event_id": "evt-gap",
            "event_first_published_at_utc": "2026-03-01T21:00:00Z",
            "canonical_summary": "Weekend geopolitical risk",
        },
        {
            "event_id": "evt-trade",
            "event_first_published_at_utc": "2026-03-03T08:00:00Z",
            "canonical_summary": "In-session supply update",
        },
        {
            "event_id": "evt-leak",
            "event_first_published_at_utc": "2026-03-03T09:00:00Z",
            "canonical_summary": "Late publication after move",
        },
    ]
    event_item_rows = [
        {"event_id": "evt-gap", "news_id": "news-gap"},
        {"event_id": "evt-trade", "news_id": "news-trade"},
        {"event_id": "evt-leak", "news_id": "news-leak"},
    ]
    news_rows = [
        {"news_id": "news-gap", "title": "Weekend headline", "url": "https://example.com/gap"},
        {"news_id": "news-trade", "title": "Session headline", "url": "https://example.com/trade"},
        {"news_id": "news-leak", "title": "Late headline", "url": "https://example.com/leak"},
    ]
    entity_rows = [
        {"news_id": "news-gap", "ticker": "BRN"},
        {"news_id": "news-trade", "ticker": "BRN"},
        {"news_id": "news-leak", "ticker": "BRN"},
    ]
    event_score_rows = [
        {"target_id": "evt-gap", "model_id": "model.primary", "direction": "up", "prob_up": 0.7, "prob_down": 0.2},
        {"target_id": "evt-trade", "model_id": "model.primary", "direction": "up", "prob_up": 0.8, "prob_down": 0.1},
        {"target_id": "evt-leak", "model_id": "model.primary", "direction": "up", "prob_up": 0.7, "prob_down": 0.2},
    ]
    target_rows = [
        {
            "event_id": "evt-gap",
            "symbol": "BRN",
            "label_v2": 1,
            "r_raw": 0.01,
            "ar": 0.0,
            "is_hi_conf": True,
            "is_overlapped": False,
            "is_repost": False,
            "leakage_postmove": False,
            "t0": "2026-03-01T16:00:00Z",
            "t1": "2026-03-01T17:00:00Z",
        },
        {
            "event_id": "evt-trade",
            "symbol": "BRN",
            "label_v2": 1,
            "r_raw": 0.02,
            "ar": 0.0,
            "is_hi_conf": True,
            "is_overlapped": False,
            "is_repost": False,
            "leakage_postmove": False,
            "t0": "2026-03-03T08:15:00Z",
            "t1": "2026-03-03T09:15:00Z",
        },
        {
            "event_id": "evt-leak",
            "symbol": "BRN",
            "label_v2": 1,
            "r_raw": 0.03,
            "ar": 0.0,
            "is_hi_conf": True,
            "is_overlapped": False,
            "is_repost": False,
            "leakage_postmove": True,
            "t0": "2026-03-03T08:45:00Z",
            "t1": "2026-03-03T09:45:00Z",
        },
    ]

    monkeypatch.setattr(live_eval, "load_news_events", lambda *args, **kwargs: event_rows)
    monkeypatch.setattr(live_eval, "load_news_event_items", lambda *args, **kwargs: event_item_rows)
    monkeypatch.setattr(live_eval, "load_news_items_by_ids", lambda *args, **kwargs: news_rows)
    monkeypatch.setattr(live_eval, "load_news_entity_links", lambda *args, **kwargs: entity_rows)
    monkeypatch.setattr(live_eval, "load_news_impact_scores", lambda *args, **kwargs: event_score_rows)
    monkeypatch.setattr(live_eval, "load_event_target_v2", lambda *args, **kwargs: target_rows)

    rows, summary = live_eval.build_news_live_eval_rows(
        None,
        from_date=date(2026, 3, 1),
        to_date=date(2026, 3, 4),
        tickers=["BRN"],
        horizon="1h",
        timezone_name="Europe/Moscow",
        limit=100,
        preferred_models=["model.primary"],
        gap_lag_minutes=180,
    )

    by_event_id = {str(row["news_event_id"]): row for row in rows}
    assert by_event_id["evt-gap"]["actual_gap_likely"] is True
    assert by_event_id["evt-trade"]["actual_gap_likely"] is False
    assert by_event_id["evt-leak"]["actual_t0_before_publication"] is True

    ticker_summary = summary["BRN"]
    assert ticker_summary["events_with_predictions"] == 3
    assert ticker_summary["events_with_moex_eval"] == 0
    assert ticker_summary["t0_before_publication_events"] == 2
    assert ticker_summary["t0_after_publication_events"] == 1
    assert ticker_summary["gap_likely_events"] == 1
    assert ticker_summary["directional_comparable_r_raw"] == 3
    assert ticker_summary["directional_hits_r_raw"] == 3
    assert ticker_summary["directional_comparable_r_raw_no_gap"] == 2
    assert ticker_summary["directional_hits_r_raw_no_gap"] == 2


def test_build_news_live_eval_rows_uses_moex_contract_eval_when_requested(monkeypatch):
    event_rows = [
        {
            "event_id": "evt-moex",
            "event_first_published_at_utc": "2026-03-01T20:30:00Z",
            "canonical_summary": "Geopolitical escalation",
        }
    ]
    event_item_rows = [{"event_id": "evt-moex", "news_id": "news-moex"}]
    news_rows = [{"news_id": "news-moex", "title": "Weekend headline", "url": "https://example.com/moex"}]
    entity_rows = [{"news_id": "news-moex", "ticker": "BRN"}]
    event_score_rows = [
        {"target_id": "evt-moex", "model_id": "model.primary", "direction": "up", "prob_up": 0.9, "prob_down": 0.05}
    ]

    monkeypatch.setattr(live_eval, "load_news_events", lambda *args, **kwargs: event_rows)
    monkeypatch.setattr(live_eval, "load_news_event_items", lambda *args, **kwargs: event_item_rows)
    monkeypatch.setattr(live_eval, "load_news_items_by_ids", lambda *args, **kwargs: news_rows)
    monkeypatch.setattr(live_eval, "load_news_entity_links", lambda *args, **kwargs: entity_rows)
    monkeypatch.setattr(live_eval, "load_news_impact_scores", lambda *args, **kwargs: event_score_rows)
    monkeypatch.setattr(live_eval, "load_event_target_v2", lambda *args, **kwargs: [])

    rows, summary = live_eval.build_news_live_eval_rows(
        None,
        from_date=date(2026, 3, 1),
        to_date=date(2026, 3, 2),
        tickers=["BRN"],
        horizon="1h",
        timezone_name="Europe/Moscow",
        limit=100,
        preferred_models=["model.primary"],
        gap_lag_minutes=180,
        moex_client=_StubMoexClient(),
        moex_futures_board="RFUD",
        moex_roll_days=1,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["target_row_found"] is False
    assert row["moex_eval_row_found"] is True
    assert row["actual_eval_source"] == "moex_contract"
    assert row["actual_contract_secid"] == "BRJ6"
    assert row["directional_comparable_r_raw_with_gap"] is True
    assert row["directional_match_r_raw_with_gap"] is True

    ticker_summary = summary["BRN"]
    assert ticker_summary["events_with_predictions"] == 1
    assert ticker_summary["events_with_moex_eval"] == 1
    assert ticker_summary["directional_comparable_r_raw_with_gap"] == 1
    assert ticker_summary["directional_hits_r_raw_with_gap"] == 1
