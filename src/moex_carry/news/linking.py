from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from moex_carry.news_commodity_graph import infer_event_first_cause
from moex_carry.news_shock_symbol_map import GLOBAL_CONTEXT_KEYWORDS, SYMBOL_TOPIC_KEYWORDS
from moex_carry.news.taxonomy import TAG_TAXONOMY


DEFAULT_COMMODITY_ALIASES: dict[str, tuple[str, ...]] = {
    "BRN": ("brent", "brent crude", "ice brent", "crude oil", "opec", "barrel"),
    "NG_US": ("natural gas", "henry hub", "nymex gas", "lng"),
    "GOLD": ("gold", "bullion"),
    "SILVER": ("silver", "xag"),
    "PLATINUM": ("platinum", "xpt"),
    "PALLADIUM": ("palladium", "xpd"),
    "COPPER": ("copper", "lme copper", "comex copper"),
    "ALUMINUM": ("aluminum", "aluminium", "bauxite", "alumina"),
    "NICKEL": ("nickel", "class 1 nickel", "lme nickel"),
    "ZINC": ("zinc", "lme zinc"),
    "WHEAT": ("wheat", "black sea wheat"),
    "SUGAR": ("sugar", "raw sugar", "sugar cane"),
    "COFFEE": ("coffee", "arabica", "robusta"),
    "COCOA": ("cocoa", "ivory coast cocoa", "ghana cocoa"),
    "ORANGE": ("orange juice", "fcoj", "citrus"),
    "OIL": ("oil", "wti", "crude"),
    "GAS": ("gas", "lng", "natural gas"),
    "CORN": ("corn", "maize"),
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


@dataclass(frozen=True)
class CommodityLink:
    commodity_id: str
    score: float
    reason: str
    evidence_terms: list[str]
    is_primary: bool
    link_mode: str = "deterministic"


_GENERIC_TOPIC_TERMS: frozenset[str] = frozenset(
    {
        "weather",
        "storm",
        "flood",
        "drought",
        "freeze",
        "hurricane",
        "inventory",
        "stocks",
        "pipeline",
        "mine strike",
        "mine disruption",
        "smelter",
        "industrial demand",
        "china demand",
        "sanctions",
    }
)


def normalize_text(title: str | None, content: str | None) -> str:
    text = " ".join([str(title or ""), str(content or "")]).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _contains_alias(text: str, alias: str) -> bool:
    needle = str(alias or "").strip().lower()
    if not needle:
        return False
    if " " in needle or "-" in needle or "/" in needle:
        return needle in text
    pattern = rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def text_supports_ticker(
    *,
    ticker: str | None,
    title: str | None,
    content: str | None,
    min_hits: int = 1,
) -> bool:
    normalized_ticker = str(ticker or "").strip().upper()
    aliases = DEFAULT_COMMODITY_ALIASES.get(normalized_ticker)
    if not aliases:
        return False
    text = f" {normalize_text(title, content)} "
    if not text.strip():
        return False
    hits = sum(1 for alias in aliases if _contains_alias(text, alias))
    return bool(hits >= max(int(min_hits), 1))


def _anchor_terms(commodity_id: str) -> tuple[str, ...]:
    aliases = DEFAULT_COMMODITY_ALIASES.get(commodity_id, ())
    topic_terms = SYMBOL_TOPIC_KEYWORDS.get(commodity_id, ())
    combined = [*aliases, *topic_terms]
    deduped: list[str] = []
    seen: set[str] = set()
    for term in combined:
        normalized = str(term or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized)
    return tuple(deduped)


@lru_cache(maxsize=None)
def _topic_term_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for terms in SYMBOL_TOPIC_KEYWORDS.values():
        for term in terms:
            normalized = str(term or "").strip().lower()
            if not normalized:
                continue
            counts[normalized] = counts.get(normalized, 0) + 1
    return counts


@lru_cache(maxsize=None)
def _alias_term_set(commodity_id: str) -> frozenset[str]:
    return frozenset(
        str(term or "").strip().lower()
        for term in DEFAULT_COMMODITY_ALIASES.get(commodity_id, ())
        if str(term or "").strip()
    )


def _is_specific_topic_term(commodity_id: str, term: str) -> bool:
    normalized = str(term or "").strip().lower()
    if not normalized:
        return False
    if normalized in _GENERIC_TOPIC_TERMS:
        return False
    if normalized in _alias_term_set(commodity_id):
        return True
    if _topic_term_counts().get(normalized, 0) > 1:
        return False
    return True


def _matched_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    matches: list[str] = []
    for term in terms:
        if _contains_alias(text, term):
            matches.append(term)
    return matches


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        normalized = str(item or "").strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def score_commodity_links(
    *,
    title: str | None,
    description: str | None = None,
    content: str | None = None,
    seed_commodities: list[str] | tuple[str, ...] | None = None,
) -> list[CommodityLink]:
    text = normalize_text(
        " ".join(str(part or "") for part in (title, description)),
        content,
    )
    seed_set = {
        str(item or "").strip().upper()
        for item in (seed_commodities or [])
        if str(item or "").strip()
    }
    if not text:
        return [
            CommodityLink(
                commodity_id=item,
                score=0.45,
                reason="seed_only",
                evidence_terms=[],
                is_primary=(idx == 0),
            )
            for idx, item in enumerate(sorted(seed_set))
        ]

    global_hits = [term for term in GLOBAL_CONTEXT_KEYWORDS if _contains_alias(text, term)]
    candidates: list[CommodityLink] = []
    commodity_ids = sorted(set(DEFAULT_COMMODITY_ALIASES) | set(SYMBOL_TOPIC_KEYWORDS))
    for commodity_id in commodity_ids:
        alias_hits = _matched_terms(text, DEFAULT_COMMODITY_ALIASES.get(commodity_id, ()))
        topic_hits = _matched_terms(text, SYMBOL_TOPIC_KEYWORDS.get(commodity_id, ()))
        specific_topic_hits = [term for term in topic_hits if _is_specific_topic_term(commodity_id, term)]
        weak_topic_hits = [term for term in topic_hits if term not in specific_topic_hits]
        route_inference = infer_event_first_cause(commodity=commodity_id, text=text)
        route_only_allowed = bool(
            route_inference is not None
            and str(route_inference.route_key).startswith(("chokepoint:", "terminal:", "operator:", "regulator:"))
        )
        if not alias_hits and not specific_topic_hits and not route_only_allowed:
            continue

        evidence_terms = _dedupe_preserve(
            alias_hits
            + specific_topic_hits
            + ([f"route:{route_inference.route_key}"] if route_inference is not None else [])
            + weak_topic_hits[:2]
            + global_hits[:2]
        )
        score = 0.0
        if alias_hits:
            score = max(score, 0.64 + (0.1 * min(len(alias_hits), 2)))
        if specific_topic_hits:
            score = max(score, 0.62 + (0.08 * min(len(specific_topic_hits), 2)))
        if route_inference is not None:
            score = max(
                score,
                0.74
                + (0.04 * min(len(route_inference.matched_entities), 2))
                + (0.02 * min(len(route_inference.cause_terms), 2)),
            )
        score += 0.03 * min(len(weak_topic_hits), 2)
        score += 0.02 * min(len(global_hits), 2)

        reason_parts: list[str] = []
        if alias_hits:
            reason_parts.append("alias")
        if specific_topic_hits:
            reason_parts.append("topic")
        if route_inference is not None:
            reason_parts.append("route")
        if commodity_id in seed_set:
            score += 0.06
            reason_parts.append("seed")
        candidates.append(
            CommodityLink(
                commodity_id=commodity_id,
                score=min(score, 0.98),
                reason="+".join(reason_parts) if reason_parts else "anchor",
                evidence_terms=evidence_terms[:6],
                is_primary=False,
            )
        )

    if not candidates:
        return [
            CommodityLink(
                commodity_id=item,
                score=0.45,
                reason="seed_only",
                evidence_terms=global_hits[:3],
                is_primary=(idx == 0),
            )
            for idx, item in enumerate(sorted(seed_set))
        ]

    existing = {item.commodity_id for item in candidates}
    for seed in sorted(seed_set):
        if seed in existing:
            continue
        candidates.append(
            CommodityLink(
                commodity_id=seed,
                score=0.45,
                reason="seed_only",
                evidence_terms=global_hits[:3],
                is_primary=False,
            )
        )

    candidates = sorted(
        candidates,
        key=lambda item: (
            item.score,
            1 if item.commodity_id in seed_set else 0,
            len(item.evidence_terms),
            item.commodity_id,
        ),
        reverse=True,
    )
    return [
        CommodityLink(
            commodity_id=item.commodity_id,
            score=item.score,
            reason=item.reason,
            evidence_terms=item.evidence_terms,
            is_primary=(idx == 0),
            link_mode=item.link_mode,
        )
        for idx, item in enumerate(candidates)
    ]


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
