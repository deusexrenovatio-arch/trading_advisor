from __future__ import annotations

from moex_carry.news_commodity_graph import (
    build_event_first_query_terms,
    commodity_role_catalog,
    infer_event_first_cause,
)


def test_commodity_role_catalog_contains_wide_role_sets() -> None:
    catalog = commodity_role_catalog("NG_US")

    assert "producer" in catalog
    assert "importer" in catalog
    assert "terminal" in catalog
    assert "chokepoint" in catalog
    assert "Appalachia" in catalog["producer"]
    assert "European Union" in catalog["importer"]


def test_infer_event_first_cause_returns_route_and_entities() -> None:
    inference = infer_event_first_cause(
        commodity="NG_US",
        text=(
            "Freeport LNG terminal outage confirmed by operator, "
            "cargo loading suspended and exports halted."
        ),
    )

    assert inference is not None
    assert inference.event == "producer_outage"
    assert inference.claim_status == "confirmed"
    assert "Freeport LNG" in inference.matched_entities
    assert "NG_US" in inference.route_key


def test_event_first_query_terms_include_chokepoints_and_actions() -> None:
    terms = build_event_first_query_terms("BRN", max_terms=12)
    lowered = {item.lower() for item in terms}

    assert "strait of hormuz" in lowered
    assert "shipping halted" in lowered
    assert "opec output cut" in lowered


def test_infer_event_first_cause_detects_iran_strike_as_route_risk() -> None:
    inference = infer_event_first_cause(
        commodity="BRN",
        text=(
            "Official statement says Israel strikes Iranian oil facilities and missile strike"
            " hit export infrastructure."
        ),
    )

    assert inference is not None
    assert inference.event == "exporter_military_strike_risk"
    assert inference.claim_status == "confirmed"
    assert "Iran" in inference.matched_entities
    assert "exporter:iran->seaborne_crude->BRN" in inference.route_key


def test_commodity_role_catalog_supports_wheat_graph() -> None:
    catalog = commodity_role_catalog("WHEAT")

    assert "producer" in catalog
    assert "importer" in catalog
    assert "chokepoint" in catalog
    assert "Russia" in catalog["producer"]
    assert "Egypt" in catalog["importer"]


def test_infer_event_first_cause_supports_copper_supply_route() -> None:
    inference = infer_event_first_cause(
        commodity="COPPER",
        text=(
            "Official statement: Codelco reports mine outage in Chile after strike,"
            " smelter feed disrupted."
        ),
    )

    assert inference is not None
    assert inference.event == "producer_outage"
    assert inference.claim_status == "confirmed"
    assert "Chile" in inference.matched_entities
    assert "commodity:COPPER" not in inference.route_key
    assert "COPPER" in inference.route_key
