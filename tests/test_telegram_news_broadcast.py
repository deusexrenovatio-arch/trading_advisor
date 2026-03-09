from __future__ import annotations

from moex_carry.integrations.telegram_news_broadcast import format_news_message, group_story_alerts


def test_group_story_alerts_merges_multi_commodity_rows() -> None:
    rows = [
        {
            "story_id": "story-iran-attack",
            "published_at_utc": "2026-03-04T07:00:00Z",
            "commodity": "BRN",
            "commodity_link_score": 0.93,
            "link_reason": "anchor+seed",
            "direction": "up",
            "severity": "critical",
            "impact_score": 0.95,
            "confidence": 0.97,
            "source_name": "reuters.com",
            "provider": "newsapi",
            "title": "Oil jumps after Iran escalation",
            "url": "https://example.com/news-1",
        },
        {
            "story_id": "story-iran-attack",
            "published_at_utc": "2026-03-04T07:00:00Z",
            "commodity": "GOLD",
            "commodity_link_score": 0.71,
            "link_reason": "anchor",
            "direction": "up",
            "severity": "critical",
            "impact_score": 0.95,
            "confidence": 0.97,
            "source_name": "reuters.com",
            "provider": "newsapi",
            "title": "Oil jumps after Iran escalation",
            "url": "https://example.com/news-1",
        },
    ]

    grouped = group_story_alerts(rows)

    assert len(grouped) == 1
    alert = grouped[0]
    assert alert["story_id"] == "story-iran-attack"
    assert alert["lead_commodity"] == "BRN"
    assert alert["is_multi_commodity"] is True
    assert len(alert["story_scope_rows"]) == 2


def test_format_news_message_uses_discovery_contract() -> None:
    alert = {
        "story_id": "story-iran-attack",
        "published_at_utc": "2026-03-04T07:00:00Z",
        "lead_commodity": "BRN",
        "lead_link_score": 0.93,
        "commodity": "BRN",
        "commodity_link_score": 0.93,
        "story_scope_rows": [
            {"commodity": "BRN", "commodity_link_score": 0.93, "link_reason": "anchor+seed", "link_evidence_json": '["oil","middle east"]'},
            {"commodity": "GOLD", "commodity_link_score": 0.71, "link_reason": "anchor", "link_evidence_json": '["gold","safe haven"]'},
        ],
        "direction": "up",
        "severity": "critical",
        "impact_score": 0.95,
        "confidence": 0.97,
        "source_name": "reuters.com",
        "provider": "newsapi",
        "title": "Oil jumps after Iran escalation",
        "url": "https://example.com/news-1",
        "reason_terms_up": '["iran","attack","supply risk"]',
        "reason_terms_down": "demand slowdown",
        "cause_classification": "cause",
        "cause_event": "route_risk",
        "cause_route_key": "hormuz_supply",
        "cause_claim_status": "confirmed",
        "fundamental_score": 0.88,
        "cause_confidence": 0.81,
        "is_primary_cause": 1,
    }

    message = format_news_message(alert)

    assert "НОВОСТНЫЙ АЛЕРТ" in message
    assert "🧺 Инструменты: BRN (0.93), GOLD (0.71)" in message
    assert "🔗 Ведущая связь: BRN (0.93)" in message
    assert "Move verification" not in message
    assert "Oil jumps after Iran escalation" in message


def test_format_news_message_truncates_long_headline() -> None:
    alert = {
        "published_at_utc": "2026-03-04T07:00:00Z",
        "lead_commodity": "NG_US",
        "lead_link_score": 0.82,
        "direction": "up",
        "severity": "high",
        "impact_score": 0.72,
        "confidence": 0.91,
        "source_name": "example.com",
        "title": "A" * 500,
    }

    message = format_news_message(alert)
    headline_lines = [line for line in message.splitlines() if line.startswith("🗞 ")]
    assert len(headline_lines) == 1
    assert headline_lines[0].endswith("...")
    assert len(headline_lines[0]) <= 220
