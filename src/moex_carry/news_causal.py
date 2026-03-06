from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from moex_carry.news_causal_rules import COMMODITY_RULES, GLOBAL_RULES
from moex_carry.news_commodity_graph import infer_event_first_cause


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _to_text_blob(*parts: object) -> str:
    normalized = [_normalize_text(part).lower() for part in parts]
    return " ".join(piece for piece in normalized if piece)


def _match_terms(text: str, terms: Iterable[str]) -> list[str]:
    lowered = str(text or "").lower()
    hits: list[str] = []
    for term in terms:
        needle = _normalize_text(term).lower()
        if not needle:
            continue
        if " " in needle or any(ch in needle for ch in "+-/"):
            matched = needle in lowered
        else:
            pattern = rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
            matched = re.search(pattern, lowered) is not None
        if matched:
            hits.append(needle)
    return sorted(dict.fromkeys(hits))

@dataclass(frozen=True)
class CausalCandidate:
    bucket: str
    event: str
    transmission_channel: str
    direction_bias: str
    weight: float
    cause_terms: tuple[str, ...]
    evidence: float
    source: str = "rule"
    route_key: str = ""
    claim_status: str = "confirmed"
    entities: tuple[str, ...] = ()

_EFFECT_ONLY_TERMS: tuple[str, ...] = (
    "prices rose",
    "prices jumped",
    "prices fell",
    "futures gained",
    "futures dropped",
    "gold climbs",
    "gold rises",
    "gold falls",
    "gold retreats",
    "gold wavers",
    "gold tumbles",
    "silver falls",
    "extended gains",
    "profit taking",
    "technical rebound",
    "buying momentum",
    "risk appetite improved",
)


_HIGH_SIGNAL_EVENTS: set[str] = {
    "opec_supply_cut",
    "opec_supply_increase",
    "inventory_draw",
    "inventory_build",
    "storage_withdrawal",
    "storage_injection",
    "central_bank_dovish_shift",
    "central_bank_hawkish_shift",
    "middle_east_supply_risk",
    "exporter_military_strike_risk",
    "chokepoint_closure",
    "export_restriction",
    "producer_outage",
    "producer_output_cut",
    "pgm_mine_disruption",
    "russian_palladium_supply_risk",
    "copper_mine_disruption",
    "smelter_power_disruption",
    "nickel_ore_export_restriction",
    "zinc_smelter_disruption",
    "grain_export_restriction",
    "sugar_export_restriction",
    "coffee_crop_weather_shock",
    "cocoa_crop_shock",
    "citrus_crop_shock",
}

_DISCOVERY_EVENT_BY_COMMODITY: dict[str, str] = {
    "BRN": "middle_east_supply_risk",
    "NG_US": "extreme_weather_supply_shock",
    "GOLD": "risk_off_geopolitics",
    "SILVER": "manufacturing_upturn",
    "PLATINUM": "pgm_mine_disruption",
    "PALLADIUM": "russian_palladium_supply_risk",
    "COPPER": "copper_mine_disruption",
    "ALUMINUM": "smelter_power_disruption",
    "NICKEL": "nickel_ore_export_restriction",
    "ZINC": "zinc_smelter_disruption",
    "WHEAT": "grain_export_restriction",
    "SUGAR": "sugar_export_restriction",
    "COFFEE": "coffee_supply_recovery",
    "COCOA": "cocoa_crop_shock",
    "ORANGE": "citrus_crop_shock",
}

_DISCOVERY_CAUSE_TERMS: tuple[str, ...] = (
    "output",
    "production",
    "harvest",
    "quota",
    "permit",
    "export",
    "import",
    "tariff",
    "duty",
    "inventory",
    "stocks",
    "crop",
    "mine",
    "smelter",
    "outage",
    "shutdown",
    "force majeure",
    "drought",
    "frost",
    "storm",
    "farmgate",
    "arrivals",
    "supply",
    "demand",
    "policy",
    "sanction",
    "investment",
    "budget",
)

_DISCOVERY_ANCHORS: dict[str, tuple[str, ...]] = {
    "BRN": ("oil", "brent", "opec", "hormuz", "crude"),
    "NG_US": ("natural gas", "lng", "henry hub", "eia"),
    "GOLD": ("gold", "bullion", "real yields", "central bank"),
    "SILVER": ("silver", "xag", "solar demand", "industrial demand"),
    "PLATINUM": ("platinum", "pgm", "south africa"),
    "PALLADIUM": ("palladium", "russian palladium", "autocatalyst"),
    "COPPER": ("copper", "codelco", "escondida", "el teniente"),
    "ALUMINUM": ("aluminum", "aluminium", "alumina", "bauxite", "qatalum"),
    "NICKEL": ("nickel", "indonesia", "morowali", "ore"),
    "ZINC": ("zinc", "smelter", "treatment charges"),
    "WHEAT": ("wheat", "grain", "usda", "black sea"),
    "SUGAR": ("sugar", "ethanol", "cane", "mills"),
    "COFFEE": ("coffee", "arabica", "robusta", "conab"),
    "COCOA": ("cocoa", "ivory coast", "ghana", "cocobod"),
    "ORANGE": ("orange", "citrus", "fcoj", "greening"),
}

_DISCOVERY_NOISE_TERMS: tuple[str, ...] = (
    "investment at this price",
    "what should investors do",
    "market outlook explained",
    "technical analysis",
    "price prediction",
)

_DISCOVERY_WEAK_TERMS: tuple[str, ...] = (
    "rebound",
    "record",
    "tariff",
    "duties",
    "cut",
    "boost",
    "higher",
    "lower",
    "decline",
    "rise",
    "fall",
    "slashed",
    "extension",
    "permit",
    "investment",
    "financing",
    "model",
    "regulator",
    "producers",
)


def _direction_alignment_score(direction: str, expected: str) -> float:
    normalized_direction = _normalize_text(direction).lower()
    normalized_expected = _normalize_text(expected).lower()
    if normalized_expected in {"", "hold", "neutral"}:
        return 0.5
    if normalized_direction in {"", "hold", "neutral"}:
        return 0.4
    return 1.0 if normalized_direction == normalized_expected else 0.0


def _infer_discovery_fallback(commodity: str, text: str) -> tuple[str, list[str]] | None:
    event = _DISCOVERY_EVENT_BY_COMMODITY.get(commodity)
    if not event:
        return None
    anchor_hits = _match_terms(text, _DISCOVERY_ANCHORS.get(commodity, ()))
    cause_hits = _match_terms(text, _DISCOVERY_CAUSE_TERMS)
    weak_hits = _match_terms(text, _DISCOVERY_WEAK_TERMS)
    noise_hits = _match_terms(text, _DISCOVERY_NOISE_TERMS)
    if not anchor_hits:
        return None
    if not cause_hits and not weak_hits:
        if noise_hits:
            return None
        evidence_base = anchor_hits
    else:
        evidence_base = cause_hits if cause_hits else weak_hits
    if noise_hits and len(evidence_base) < 2:
        return None
    evidence_terms = [*anchor_hits[:2], *evidence_base[:3]]
    return event, list(dict.fromkeys(evidence_terms))


def analyze_causal_news(
    *,
    commodity: str,
    title: str,
    description: str,
    content: str,
    direction: str,
    profile: str = "publish",
    reason_terms_up: Iterable[object] | None = None,
    reason_terms_down: Iterable[object] | None = None,
) -> dict[str, object]:
    commodity_key = _normalize_text(commodity).upper()
    text = _to_text_blob(title, description, content)
    reason_blob = _to_text_blob(*(reason_terms_up or ()), *(reason_terms_down or ()))
    full_text = _to_text_blob(text, reason_blob)

    matched: list[CausalCandidate] = []
    for rule in (*GLOBAL_RULES, *COMMODITY_RULES.get(commodity_key, ())):
        terms = _match_terms(full_text, rule.terms)
        if not terms:
            continue
        evidence = float(len(terms)) * float(rule.weight)
        if commodity_key in COMMODITY_RULES:
            evidence += 0.08
        matched.append(
            CausalCandidate(
                bucket=rule.bucket,
                event=rule.event,
                transmission_channel=rule.transmission_channel,
                direction_bias=rule.direction_bias,
                weight=float(rule.weight),
                cause_terms=tuple(terms),
                evidence=float(evidence),
                source="rule",
            )
        )

    event_first = infer_event_first_cause(commodity=commodity_key, text=full_text)
    if event_first is not None:
        matched.append(
            CausalCandidate(
                bucket=event_first.bucket,
                event=event_first.event,
                transmission_channel=event_first.transmission_channel,
                direction_bias=event_first.direction_bias,
                weight=1.05,
                cause_terms=tuple(event_first.cause_terms),
                evidence=float(event_first.evidence),
                source="graph",
                route_key=str(event_first.route_key),
                claim_status=str(event_first.claim_status),
                entities=tuple(str(item) for item in event_first.matched_entities),
            )
        )

    effect_hits = _match_terms(full_text, _EFFECT_ONLY_TERMS)
    profile_key = _normalize_text(profile).lower() or "publish"

    if matched:
        candidate = sorted(
            matched,
            key=lambda item: (item.evidence, len(item.cause_terms), item.weight, 1 if item.source == "graph" else 0),
            reverse=True,
        )[0]
        cause_terms = list(candidate.cause_terms)
        classification = "mixed" if effect_hits else "cause"
        if candidate.claim_status == "rumor" and classification == "cause":
            classification = "mixed"
        cause_confidence = min(1.0, 0.35 + 0.12 * len(cause_terms) + 0.18 * float(candidate.weight))
        fundamental_score = min(1.0, 0.28 + 0.14 * len(cause_terms) + 0.2 * float(candidate.weight))
        if candidate.source == "graph":
            cause_confidence = min(1.0, cause_confidence + 0.1)
            fundamental_score = min(1.0, fundamental_score + 0.12)
        if candidate.claim_status == "rumor":
            cause_confidence = max(0.0, cause_confidence - 0.2)
            fundamental_score = max(0.0, fundamental_score - 0.25)
        if candidate.event in _HIGH_SIGNAL_EVENTS:
            fundamental_score = min(1.0, fundamental_score + 0.15)
        if classification == "mixed":
            fundamental_score = max(0.0, fundamental_score - 0.05)
        direction_alignment = _direction_alignment_score(direction, candidate.direction_bias)
        cluster_seed = "|".join(
            [commodity_key or "UNK", candidate.bucket, candidate.event, candidate.route_key, *cause_terms[:2]]
        )
        digest = hashlib.sha1(cluster_seed.encode("utf-8")).hexdigest()[:12]
        cause_cluster_key = f"cause:{commodity_key or 'UNK'}:{candidate.event}:{digest}"
        is_primary_cause = bool(
            classification in {"cause", "mixed"}
            and cause_confidence >= 0.5
            and fundamental_score >= 0.5
            and candidate.claim_status != "rumor"
        )
        return {
            "cause_classification": classification,
            "cause_bucket": candidate.bucket,
            "cause_event": candidate.event,
            "transmission_channel": candidate.transmission_channel,
            "cause_cluster_key": cause_cluster_key,
            "cause_confidence": round(float(cause_confidence), 6),
            "fundamental_score": round(float(fundamental_score), 6),
            "direction_alignment": round(float(direction_alignment), 6),
            "is_primary_cause": bool(is_primary_cause),
            "cause_terms": cause_terms,
            "effect_terms": effect_hits,
            "cause_route_key": candidate.route_key,
            "cause_claim_status": candidate.claim_status,
            "cause_entities": list(candidate.entities),
        }

    if profile_key == "discovery":
        fallback = _infer_discovery_fallback(commodity_key, full_text)
        if fallback is not None:
            event, cause_terms = fallback
            cause_cluster_key = f"cause:{commodity_key or 'UNK'}:{event}:discovery"
            return {
                "cause_classification": "mixed",
                "cause_bucket": "discovery",
                "cause_event": event,
                "transmission_channel": "broad_fundamental",
                "cause_cluster_key": cause_cluster_key,
                "cause_confidence": 0.52,
                "fundamental_score": 0.54,
                "direction_alignment": 0.5,
                "is_primary_cause": False,
                "cause_terms": cause_terms,
                "effect_terms": effect_hits,
                "cause_route_key": "",
                "cause_claim_status": "confirmed",
                "cause_entities": [],
            }

    classification = "effect" if effect_hits else "unknown"
    is_primary_cause = False
    return {
        "cause_classification": classification,
        "cause_bucket": "",
        "cause_event": "",
        "transmission_channel": "",
        "cause_cluster_key": "",
        "cause_confidence": 0.18 if classification == "effect" else 0.0,
        "fundamental_score": 0.08 if classification == "effect" else 0.0,
        "direction_alignment": 0.5,
        "is_primary_cause": is_primary_cause,
        "cause_terms": [],
        "effect_terms": effect_hits,
        "cause_route_key": "",
        "cause_claim_status": "unknown",
        "cause_entities": [],
    }
