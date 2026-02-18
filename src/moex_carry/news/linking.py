from __future__ import annotations

import re
from dataclasses import dataclass

from moex_carry.news.taxonomy import TAG_TAXONOMY


DEFAULT_COMMODITY_ALIASES: dict[str, tuple[str, ...]] = {
    "BRN": ("brent", "brent crude", "ice brent", "crude oil", "opec", "barrel"),
    "NG_US": ("natural gas", "henry hub", "nymex gas", "lng"),
    "GOLD": ("gold", "bullion"),
    "OIL": ("oil", "wti", "crude"),
    "GAS": ("gas", "lng", "natural gas"),
    "SILVER": ("silver"),
    "COPPER": ("copper"),
    "NICKEL": ("nickel"),
    "WHEAT": ("wheat", "grain"),
    "CORN": ("corn", "maize"),
    "COFFEE": ("coffee"),
    "COCOA": ("cocoa"),
}

TAG_RULES: dict[str, tuple[str, ...]] = {
    "SUP_INC": ("increase output", "production rose", "export up", "record output"),
    "SUP_DEC": ("cut output", "production cut", "shutdown", "sanctions", "outage"),
    "DEM_INC": ("demand rose", "consumption up", "stimulus", "import growth"),
    "DEM_DEC": ("demand fell", "consumption down", "recession", "slowdown"),
    "GEO_POL": ("sanction", "war", "conflict", "geopolitical"),
    "ECON_POL": ("rate hike", "rate cut", "central bank", "inflation", "fed"),
    "WEATHER": (
        "hurricane",
        "storm",
        "flood",
        "drought",
        "freeze",
        "cold snap",
        "heat wave",
        "heatwave",
        "blizzard",
        "snowstorm",
        "extreme weather",
        "temperature",
        "warmer",
        "colder",
        "winter",
        "weather",
        "el nino",
        "la nina",
    ),
    "TECH_DEV": ("technology", "battery", "electrification", "innovation"),
    "MARKET": ("hedge fund", "positioning", "risk-on", "risk-off"),
    "PRICE_MOV": ("price rose", "price fell", "forecast", "target price"),
}


@dataclass(frozen=True)
class LinkingResult:
    news_id: str
    primary_commodity_id: str
    secondary_commodity_ids: list[str]
    tag_codes: list[str]
    confidence: float
    resolution_stage: str
    matched_rules: list[str]
    unknown: bool


def normalize_text(title: str | None, content: str | None) -> str:
    text = " ".join([str(title or ""), str(content or "")]).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _match_commodities(text: str) -> tuple[list[str], list[str]]:
    matched: list[tuple[str, int]] = []
    rules: list[str] = []
    for commodity_id, aliases in DEFAULT_COMMODITY_ALIASES.items():
        count = 0
        for alias in aliases:
            if alias in text:
                count += 1
                rules.append(f"kw:{alias}")
        if count > 0:
            matched.append((commodity_id, count))
    matched.sort(key=lambda item: item[1], reverse=True)
    return [item[0] for item in matched], rules


def _match_tags(text: str) -> tuple[list[str], list[str]]:
    found: list[str] = []
    rules: list[str] = []
    for code, keywords in TAG_RULES.items():
        for keyword in keywords:
            # Use token boundaries so "war" does not match "warmer".
            pattern = rf"(?<![a-z0-9]){re.escape(keyword.lower())}(?![a-z0-9])"
            if re.search(pattern, text):
                found.append(code)
                rules.append(f"tag:{code}")
                break
    if not found:
        found = ["MARKET"]
    return found, rules


def link_news_item(
    *,
    news_id: str,
    title: str | None,
    content: str | None,
) -> LinkingResult:
    text = normalize_text(title, content)
    if not text:
        return LinkingResult(
            news_id=news_id,
            primary_commodity_id="UNKNOWN",
            secondary_commodity_ids=[],
            tag_codes=["MARKET"],
            confidence=0.0,
            resolution_stage="unknown",
            matched_rules=["empty_text"],
            unknown=True,
        )

    commodities, commodity_rules = _match_commodities(text)
    tag_codes, tag_rules = _match_tags(text)
    if not commodities:
        stage = "context_rule" if any(tag != "MARKET" for tag in tag_codes) else "unknown"
        confidence = 0.35 if stage == "context_rule" else 0.0
        primary = "UNKNOWN"
        secondary: list[str] = []
        unknown = stage == "unknown"
    else:
        stage = "dictionary"
        primary = commodities[0]
        secondary = commodities[1:]
        confidence = min(0.5 + 0.15 * len(commodity_rules), 0.95)
        unknown = False

    matched_rules = commodity_rules + tag_rules
    return LinkingResult(
        news_id=news_id,
        primary_commodity_id=primary,
        secondary_commodity_ids=secondary,
        tag_codes=tag_codes,
        confidence=confidence,
        resolution_stage=stage,
        matched_rules=matched_rules,
        unknown=unknown,
    )


def default_tag_rows() -> list[dict[str, object]]:
    return [
        {
            "tag_code": tag.code,
            "tag_name": tag.name,
            "description": tag.description,
        }
        for tag in TAG_TAXONOMY
    ]
