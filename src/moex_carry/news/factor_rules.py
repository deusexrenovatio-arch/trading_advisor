from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FactorRule:
    factor: str
    keywords: tuple[str, ...]
    prototypes: tuple[str, ...]
    hypothesis: str
    prior_bullish_tokens: tuple[str, ...]
    prior_bearish_tokens: tuple[str, ...]


COMMODITY_RULES: dict[str, tuple[FactorRule, ...]] = {
    "BRN": (
        FactorRule(
            factor="OPEC_POLICY",
            keywords=("opec", "opec+", "quota", "production cut", "voluntary cuts", "meeting"),
            prototypes=(
                "OPEC announced production cuts and quota changes.",
                "OPEC policy decision changed expected oil supply.",
            ),
            hypothesis="This news is primarily about OPEC production policy.",
            prior_bullish_tokens=("cut", "cuts", "quota cut", "extend cuts"),
            prior_bearish_tokens=("raise output", "increase production", "output rise"),
        ),
        FactorRule(
            factor="SUPPLY_DISRUPTION_GEO",
            keywords=("attack", "missile", "drone", "sanctions", "hormuz", "pipeline explosion", "red sea"),
            prototypes=(
                "Geopolitical disruption reduced oil supply and raised risk premium.",
                "Conflict near shipping routes disrupted crude flows.",
            ),
            hypothesis="This news is primarily about geopolitical supply disruption in oil.",
            prior_bullish_tokens=("disruption", "attack", "sanctions", "outage"),
            prior_bearish_tokens=("ceasefire", "normalization", "supply restored"),
        ),
        FactorRule(
            factor="INVENTORIES_CRUDE_PRODUCTS",
            keywords=("eia", "api", "inventories", "crude stocks", "gasoline stocks", "draw", "build"),
            prototypes=(
                "EIA crude inventory report surprised the market.",
                "Oil inventories changed relative to expectations.",
            ),
            hypothesis="This news is primarily about oil inventory data.",
            prior_bullish_tokens=("draw", "withdrawal", "stocks fell"),
            prior_bearish_tokens=("build", "injection", "stocks rose"),
        ),
        FactorRule(
            factor="SHIPPING_LOGISTICS",
            keywords=("tanker", "freight", "shipping", "port", "suez", "panama"),
            prototypes=(
                "Shipping constraints affected oil transport capacity.",
                "Port disruptions tightened crude logistics.",
            ),
            hypothesis="This news is primarily about shipping and oil logistics.",
            prior_bullish_tokens=("restriction", "delay", "reroute", "constraint"),
            prior_bearish_tokens=("normal transit", "capacity increase", "discount"),
        ),
    ),
    "GOLD": (
        FactorRule(
            factor="RATES_REALYIELD_FED",
            keywords=("fed", "fomc", "hawkish", "dovish", "real yield", "treasury yield", "rate cut"),
            prototypes=(
                "Federal Reserve rate guidance moved real yields.",
                "Changes in rate expectations affected gold pricing.",
            ),
            hypothesis="This news is primarily about rates and real yields for gold.",
            prior_bullish_tokens=("dovish", "rate cut", "yields fell"),
            prior_bearish_tokens=("hawkish", "yields rose", "rate hike"),
        ),
        FactorRule(
            factor="USD",
            keywords=("dollar", "dxy", "greenback"),
            prototypes=(
                "US dollar move influenced gold prices.",
                "Dollar strength/weakness drove precious metals.",
            ),
            hypothesis="This news is primarily about USD impact on gold.",
            prior_bullish_tokens=("dollar fell", "weaker dollar"),
            prior_bearish_tokens=("dollar rose", "stronger dollar"),
        ),
        FactorRule(
            factor="RISK_GEO_SAFEHAVEN",
            keywords=("safe haven", "geopolitical", "conflict", "war", "risk-off"),
            prototypes=(
                "Geopolitical risk increased safe-haven demand for gold.",
                "Risk-off positioning supported gold demand.",
            ),
            hypothesis="This news is primarily about safe-haven demand for gold.",
            prior_bullish_tokens=("safe haven", "risk-off", "escalation"),
            prior_bearish_tokens=("de-escalation", "risk-on"),
        ),
        FactorRule(
            factor="CENTRAL_BANK_FLOWS",
            keywords=("central bank buying", "reserves", "pboc", "cb purchases"),
            prototypes=(
                "Central bank reserve allocation changed gold demand.",
                "Official sector buying supported bullion.",
            ),
            hypothesis="This news is primarily about central bank gold flows.",
            prior_bullish_tokens=("buying", "inflows", "reserve increase"),
            prior_bearish_tokens=("selling", "outflows", "reserve decrease"),
        ),
    ),
    "NG_US": (
        FactorRule(
            factor="WEATHER_HDD_CDD",
            keywords=("cold", "heat", "hdd", "cdd", "degree days", "polar vortex", "forecast"),
            prototypes=(
                "Weather forecast changed natural gas demand through HDD/CDD.",
                "Extreme cold or heat shifted gas demand expectations.",
            ),
            hypothesis="This news is primarily about weather-driven demand for US natural gas.",
            prior_bullish_tokens=("colder", "cold", "hdd up", "heat wave", "hotter"),
            prior_bearish_tokens=("warmer", "mild weather", "hdd down", "cooler"),
        ),
        FactorRule(
            factor="EIA_STORAGE",
            keywords=("eia", "storage", "injection", "withdrawal", "build", "draw"),
            prototypes=(
                "EIA natural gas storage release surprised the market.",
                "US natural gas inventory change affected prompt price.",
            ),
            hypothesis="This news is primarily about EIA natural gas storage.",
            prior_bullish_tokens=("draw", "withdrawal", "storage fell"),
            prior_bearish_tokens=("build", "injection", "storage rose"),
        ),
        FactorRule(
            factor="LNG_EXPORTS_TERMINALS",
            keywords=("lng", "freeport", "sabine", "terminal", "feedgas", "export outage"),
            prototypes=(
                "LNG terminal utilization changed US feedgas demand.",
                "LNG export outage shifted domestic gas balance.",
            ),
            hypothesis="This news is primarily about LNG exports and terminals.",
            prior_bullish_tokens=("feedgas up", "exports rose", "terminal restart"),
            prior_bearish_tokens=("outage", "maintenance", "feedgas down"),
        ),
        FactorRule(
            factor="PRODUCTION_FREEZE_OFF",
            keywords=("production", "output", "freeze-off", "rig count", "shale"),
            prototypes=(
                "US gas production changed due to operational conditions.",
                "Freeze-offs reduced near-term gas output.",
            ),
            hypothesis="This news is primarily about US gas production changes.",
            prior_bullish_tokens=("production down", "freeze-off", "output fell"),
            prior_bearish_tokens=("production up", "output rose", "recovery"),
        ),
        FactorRule(
            factor="PIPELINE_CONSTRAINTS",
            keywords=("pipeline", "constraint", "capacity", "force majeure", "maintenance"),
            prototypes=(
                "Pipeline constraint changed regional gas flow balance.",
                "Infrastructure outage altered gas transport capacity.",
            ),
            hypothesis="This news is primarily about gas pipeline constraints.",
            prior_bullish_tokens=("constraint", "force majeure", "capacity down"),
            prior_bearish_tokens=("constraint eased", "capacity up", "restart"),
        ),
    ),
}
