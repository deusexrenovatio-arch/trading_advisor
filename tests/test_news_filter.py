from datetime import datetime, timedelta, timezone

from moex_carry.domain.decision import NewsItem
from moex_carry.strategy.news_filter import apply_news_filter


def test_news_filter_blocks_high_severity():
    now = datetime.now(timezone.utc)
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
    )
    assert result.action == "block"


def test_news_filter_allows_old_items():
    old_time = datetime.now(timezone.utc) - timedelta(minutes=400)
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
    )
    assert result.action == "allow"
