from __future__ import annotations

from moex_carry.integrations.telegram_news_broadcast import format_news_message


def test_format_news_message_includes_story_and_reason_terms() -> None:
    alert = {
        "published_at_utc": "2026-03-04T07:00:00Z",
        "commodity": "BRN",
        "commodity_scope": "BRN,GOLD",
        "direction": "up",
        "severity": "critical",
        "impact_score": 0.95,
        "confidence": 0.97,
        "source_name": "reuters.com",
        "provider": "newsapi",
        "title": "Oil jumps after Iran escalation",
        "url": "https://example.com/news-1",
        "story_key": "story-iran-attack",
        "reason_terms_up": '["iran","attack","supply risk"]',
        "reason_terms_down": "demand slowdown",
    }

    message = format_news_message(alert)

    assert "📰 Новостной импакт-сигнал" in message
    assert "🧷 Товар: BRN | 🧭 Направление: ⬆️ Рост" in message
    assert "🧬 История: story-iran-attack" in message
    assert "✅ Драйверы роста: iran, attack, supply risk" in message
    assert "⚠️ Драйверы снижения: demand slowdown" in message
    assert "🔗 Ссылка: https://example.com/news-1" in message


def test_format_news_message_truncates_long_headline() -> None:
    alert = {
        "published_at_utc": "2026-03-04T07:00:00Z",
        "commodity": "NG_US",
        "direction": "up",
        "severity": "high",
        "impact_score": 0.72,
        "confidence": 0.91,
        "source_name": "example.com",
        "title": "A" * 500,
    }

    message = format_news_message(alert)
    headline_lines = [line for line in message.splitlines() if line.startswith("🗞️ Заголовок: ")]
    assert len(headline_lines) == 1
    assert headline_lines[0].endswith("...")
    assert len(headline_lines[0]) <= 230
