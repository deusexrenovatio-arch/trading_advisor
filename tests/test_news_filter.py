from datetime import datetime, timedelta, timezone

from moex_carry.domain.decision import NewsItem
from moex_carry.strategy.news_filter import apply_news_filter


def test_news_filter_blocks_high_severity():
    now = datetime(2026, 3, 4, 10, 0, tzinfo=timezone.utc)
    items = [
        NewsItem(
            item_id="news-1",
            timestamp=now,
            source="trusted-feed",
            title="Policy shock",
            severity="high",
            impact_score=0.9,
        )
    ]
    result = apply_news_filter(
        items,
        lookback_minutes=180,
        block_severity_threshold="high",
        reduce_severity_threshold="medium",
        as_of_utc=now,
    )
    assert result.action == "block"


def test_news_filter_allows_old_items():
    as_of = datetime(2026, 3, 4, 10, 0, tzinfo=timezone.utc)
    old_time = as_of - timedelta(minutes=400)
    items = [
        NewsItem(
            item_id="news-2",
            timestamp=old_time,
            source="trusted-feed",
            title="Old news",
            severity="high",
            impact_score=0.9,
        )
    ]
    result = apply_news_filter(
        items,
        lookback_minutes=180,
        block_severity_threshold="high",
        reduce_severity_threshold="medium",
        as_of_utc=as_of,
    )
    assert result.action == "allow"


def test_news_filter_uses_explicit_as_of_for_causal_replay():
    news_time = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    items = [
        NewsItem(
            item_id="news-3",
            timestamp=news_time,
            source="trusted-feed",
            title="Pipeline disruption",
            severity="high",
            impact_score=0.9,
        )
    ]
    result = apply_news_filter(
        items,
        lookback_minutes=180,
        block_severity_threshold="high",
        reduce_severity_threshold="medium",
        as_of_utc=news_time + timedelta(minutes=60),
    )
    assert result.action == "block"
