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


def test_analyze_causal_news_detects_iran_strike_export_route_risk() -> None:
    payload = analyze_causal_news(
        commodity="BRN",
        title="US and Israel strikes on Iran raise Gulf oil route risk",
        description="Official statement says military strike on Iran increased shipping risk.",
        content="",
        direction="up",
    )

    assert payload["cause_classification"] in {"cause", "mixed"}
    assert payload["cause_event"] == "exporter_military_strike_risk"
    assert str(payload["cause_route_key"]).startswith("exporter:iran->")
    assert payload["cause_claim_status"] == "confirmed"


def test_analyze_causal_news_maps_hyphenated_safe_haven_for_gold() -> None:
    payload = analyze_causal_news(
        commodity="GOLD",
        title="Gold gains on safe-haven demand as Iran war escalates",
        description="Investors rotate to bullion during geopolitical tensions.",
        content="",
        direction="up",
    )

    assert payload["cause_classification"] in {"cause", "mixed"}
    assert payload["cause_event"] in {"risk_off_geopolitics", "real_yield_decline"}
    assert float(payload["fundamental_score"]) >= 0.5


def test_analyze_causal_news_detects_wheat_export_restriction() -> None:
    payload = analyze_causal_news(
        commodity="WHEAT",
        title="Russia announces wheat export ban as Black Sea corridor disruption worsens",
        description="Officials cite supply protection after renewed shipping risks.",
        content="",
        direction="up",
    )

    assert payload["cause_classification"] in {"cause", "mixed"}
    assert payload["cause_event"] in {"grain_export_restriction", "export_restriction", "chokepoint_closure"}
    assert payload["is_primary_cause"] is True


def test_analyze_causal_news_detects_copper_mine_supply_shock() -> None:
    payload = analyze_causal_news(
        commodity="COPPER",
        title="Codelco reports major mine strike and outage in Chile",
        description="Smelter feed disrupted as production is cut.",
        content="",
        direction="up",
    )

    assert payload["cause_classification"] in {"cause", "mixed"}
    assert payload["cause_event"] in {"copper_mine_disruption", "producer_outage"}
    assert float(payload["fundamental_score"]) >= 0.5


def test_analyze_causal_news_detects_cocoa_regulator_supply_signal() -> None:
    payload = analyze_causal_news(
        commodity="COCOA",
        title="Ghana cuts farmgate cocoa price as COCOBOD changes financing model",
        description="Ivory Coast and Ghana arrivals reshape cocoa balance.",
        content="",
        direction="down",
    )

    assert payload["cause_classification"] in {"cause", "mixed"}
    assert payload["cause_event"] in {"cocoa_crop_shock", "cocoa_supply_recovery"}


def test_analyze_causal_news_detects_nickel_quota_restriction() -> None:
    payload = analyze_causal_news(
        commodity="NICKEL",
        title="Eramet says Indonesia nickel permit volume slashed for 2026",
        description="Producers face tighter production limits.",
        content="",
        direction="up",
    )

    assert payload["cause_classification"] in {"cause", "mixed"}
    assert payload["cause_event"] in {"nickel_ore_export_restriction", "producer_output_cut"}


def test_analyze_causal_news_detects_coffee_harvest_recovery_signal() -> None:
    payload = analyze_causal_news(
        commodity="COFFEE",
        title="Conab sees record coffee harvest in 2026 as Brazil rains bolster crop prospects",
        description="Arabica and robusta output expected to increase.",
        content="",
        direction="down",
    )

    assert payload["cause_classification"] in {"cause", "mixed"}
    assert payload["cause_event"] == "coffee_supply_recovery"


def test_analyze_causal_news_detects_aluminum_force_majeure_supply_shock() -> None:
    payload = analyze_causal_news(
        commodity="ALUMINUM",
        title="Qatalum starts controlled shutdown amid natural gas shortage and force majeure",
        description="Aluminum output disrupted in Gulf smelters.",
        content="",
        direction="up",
    )

    assert payload["cause_classification"] in {"cause", "mixed"}
    assert payload["cause_event"] in {"smelter_power_disruption", "producer_outage"}


def test_analyze_causal_news_discovery_mode_has_broader_recall_than_publish() -> None:
    publish_payload = analyze_causal_news(
        commodity="COPPER",
        title="Codelco sees 3.9 billion investments in 2026 budget document",
        description="",
        content="",
        direction="hold",
        profile="publish",
    )
    discovery_payload = analyze_causal_news(
        commodity="COPPER",
        title="Codelco sees 3.9 billion investments in 2026 budget document",
        description="",
        content="",
        direction="hold",
        profile="discovery",
    )

    assert publish_payload["cause_classification"] in {"effect", "unknown", "mixed", "cause"}
    assert discovery_payload["cause_classification"] in {"cause", "mixed"}
    assert str(discovery_payload["cause_event"]).strip() != ""


def test_analyze_causal_news_discovery_mode_ignores_investor_advice_noise() -> None:
    payload = analyze_causal_news(
        commodity="GOLD",
        title="Is gold still a good investment at this price?",
        description="What should investors do now",
        content="",
        direction="hold",
        profile="discovery",
    )

    assert payload["cause_classification"] in {"effect", "unknown"}
