from __future__ import annotations

from moex_carry.news_causal import analyze_causal_news


def test_analyze_causal_news_detects_brent_supply_cause() -> None:
    payload = analyze_causal_news(
        commodity="BRN",
        title="OPEC output cut and export curbs tighten oil market",
        description="Shipping disruptions raise supply risk.",
        content="",
        direction="up",
    )

    assert payload["cause_classification"] in {"cause", "mixed"}
    assert payload["is_primary_cause"] is True
    assert payload["cause_event"] in {"opec_supply_cut", "export_restriction", "transport_disruption"}
    assert float(payload["fundamental_score"]) >= 0.5


def test_analyze_causal_news_flags_effect_only_headline() -> None:
    payload = analyze_causal_news(
        commodity="BRN",
        title="Oil prices rose as futures gained in risk-on trade",
        description="",
        content="",
        direction="up",
    )

    assert payload["cause_classification"] == "effect"
    assert payload["is_primary_cause"] is False
    assert float(payload["fundamental_score"]) < 0.2


def test_analyze_causal_news_detects_event_first_chokepoint_root_cause() -> None:
    payload = analyze_causal_news(
        commodity="BRN",
        title="Iran confirms Strait of Hormuz closure after attacks",
        description="Shipping halted in official statement from regional authorities.",
        content="",
        direction="up",
    )

    assert payload["cause_event"] == "chokepoint_closure"
    assert payload["cause_claim_status"] == "confirmed"
    assert payload["is_primary_cause"] is True
    assert str(payload["cause_route_key"]).strip() != ""
    assert "Strait of Hormuz" in payload["cause_entities"]


def test_analyze_causal_news_marks_rumor_as_non_primary() -> None:
    payload = analyze_causal_news(
        commodity="BRN",
        title="Reports suggest Strait of Hormuz could be closed",
        description="Unconfirmed rumor from social media accounts.",
        content="",
        direction="up",
    )

    assert payload["cause_event"] == "chokepoint_closure"
    assert payload["cause_claim_status"] == "rumor"
    assert payload["is_primary_cause"] is False
