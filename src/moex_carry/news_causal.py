from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

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
        if needle and needle in lowered:
            hits.append(needle)
    return sorted(dict.fromkeys(hits))


@dataclass(frozen=True)
class CausalRule:
    bucket: str
    event: str
    transmission_channel: str
    direction_bias: str
    weight: float
    terms: tuple[str, ...]


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


_GLOBAL_RULES: tuple[CausalRule, ...] = (
    CausalRule(
        bucket="trade_policy",
        event="export_restriction",
        transmission_channel="physical_supply",
        direction_bias="up",
        weight=0.95,
        terms=(
            "export ban",
            "export curb",
            "export quota",
            "export duty",
            "sanctions",
            "embargo",
        ),
    ),
    CausalRule(
        bucket="demand",
        event="import_demand_surge",
        transmission_channel="physical_demand",
        direction_bias="up",
        weight=0.85,
        terms=(
            "import surge",
            "import demand rises",
            "china imports",
            "india imports",
            "refinery runs rise",
        ),
    ),
    CausalRule(
        bucket="demand",
        event="import_demand_drop",
        transmission_channel="physical_demand",
        direction_bias="down",
        weight=0.85,
        terms=(
            "import demand slowdown",
            "demand destruction",
            "import cuts",
            "manufacturing contraction",
            "recession risk",
        ),
    ),
    CausalRule(
        bucket="logistics",
        event="transport_disruption",
        transmission_channel="transport_costs",
        direction_bias="up",
        weight=0.9,
        terms=(
            "port closure",
            "shipping disruption",
            "red sea",
            "suez",
            "hormuz",
            "pipeline outage",
            "rail disruption",
            "canal congestion",
        ),
    ),
    CausalRule(
        bucket="weather",
        event="extreme_weather_supply_shock",
        transmission_channel="weather_supply",
        direction_bias="up",
        weight=0.75,
        terms=(
            "hurricane",
            "storm",
            "flood",
            "freeze",
            "heatwave",
            "drought",
            "wildfire",
        ),
    ),
    CausalRule(
        bucket="monetary_policy",
        event="central_bank_dovish_shift",
        transmission_channel="rates_fx",
        direction_bias="up",
        weight=0.92,
        terms=(
            "rate cut",
            "dovish",
            "qe",
            "liquidity easing",
            "real yields fall",
        ),
    ),
    CausalRule(
        bucket="monetary_policy",
        event="central_bank_hawkish_shift",
        transmission_channel="rates_fx",
        direction_bias="down",
        weight=0.92,
        terms=(
            "rate hike",
            "hawkish",
            "tightening",
            "real yields rise",
            "balance sheet runoff",
        ),
    ),
)


_COMMODITY_RULES: dict[str, tuple[CausalRule, ...]] = {
    "BRN": (
        CausalRule(
            bucket="supply",
            event="opec_supply_cut",
            transmission_channel="physical_supply",
            direction_bias="up",
            weight=1.0,
            terms=("opec cut", "output cut", "production cut", "voluntary cut"),
        ),
        CausalRule(
            bucket="supply",
            event="opec_supply_increase",
            transmission_channel="physical_supply",
            direction_bias="down",
            weight=0.95,
            terms=("opec increase", "output increase", "production hike", "supply increase"),
        ),
        CausalRule(
            bucket="inventory",
            event="inventory_draw",
            transmission_channel="inventory_balance",
            direction_bias="up",
            weight=0.9,
            terms=("inventory draw", "stocks draw", "crude draw", "eia draw"),
        ),
        CausalRule(
            bucket="inventory",
            event="inventory_build",
            transmission_channel="inventory_balance",
            direction_bias="down",
            weight=0.9,
            terms=("inventory build", "stocks build", "crude build", "eia build"),
        ),
        CausalRule(
            bucket="geopolitics",
            event="middle_east_supply_risk",
            transmission_channel="geopolitical_risk",
            direction_bias="up",
            weight=1.0,
            terms=("iran", "missile", "drone attack", "shipping lane risk", "strait of hormuz"),
        ),
    ),
    "NG_US": (
        CausalRule(
            bucket="weather",
            event="cold_weather_demand",
            transmission_channel="weather_demand",
            direction_bias="up",
            weight=1.0,
            terms=("colder", "cold blast", "hdd", "freeze-off", "polar vortex"),
        ),
        CausalRule(
            bucket="weather",
            event="warm_weather_demand_drop",
            transmission_channel="weather_demand",
            direction_bias="down",
            weight=1.0,
            terms=("warmer", "mild weather", "cooling demand drop", "hdd miss"),
        ),
        CausalRule(
            bucket="inventory",
            event="storage_withdrawal",
            transmission_channel="inventory_balance",
            direction_bias="up",
            weight=0.95,
            terms=("storage withdrawal", "draw larger than expected", "eia withdrawal"),
        ),
        CausalRule(
            bucket="inventory",
            event="storage_injection",
            transmission_channel="inventory_balance",
            direction_bias="down",
            weight=0.95,
            terms=("storage injection", "build larger than expected", "eia injection"),
        ),
        CausalRule(
            bucket="lng",
            event="lng_export_outage",
            transmission_channel="export_flow",
            direction_bias="down",
            weight=0.85,
            terms=("lng outage", "export terminal outage", "freeport outage"),
        ),
        CausalRule(
            bucket="lng",
            event="lng_export_restart",
            transmission_channel="export_flow",
            direction_bias="up",
            weight=0.85,
            terms=("lng restart", "export terminal restart", "lng flows rise"),
        ),
    ),
    "GOLD": (
        CausalRule(
            bucket="monetary_policy",
            event="real_yield_decline",
            transmission_channel="rates_fx",
            direction_bias="up",
            weight=1.0,
            terms=("real yields fall", "treasury yields fall", "rate cuts priced"),
        ),
        CausalRule(
            bucket="monetary_policy",
            event="real_yield_rise",
            transmission_channel="rates_fx",
            direction_bias="down",
            weight=1.0,
            terms=("real yields rise", "treasury yields rise", "hawkish fed"),
        ),
        CausalRule(
            bucket="fx",
            event="usd_weakness",
            transmission_channel="fx_pass_through",
            direction_bias="up",
            weight=0.9,
            terms=("dollar weak", "usd weaker", "dxy falls"),
        ),
        CausalRule(
            bucket="fx",
            event="usd_strength",
            transmission_channel="fx_pass_through",
            direction_bias="down",
            weight=0.9,
            terms=("dollar stronger", "usd stronger", "dxy rises"),
        ),
        CausalRule(
            bucket="safe_haven",
            event="risk_off_geopolitics",
            transmission_channel="risk_appetite",
            direction_bias="up",
            weight=0.95,
            terms=("safe haven demand", "risk-off", "geopolitical escalation", "war risk"),
        ),
    ),
    "SILVER": (
        CausalRule(
            bucket="industrial_demand",
            event="manufacturing_upturn",
            transmission_channel="industrial_cycle",
            direction_bias="up",
            weight=0.9,
            terms=("manufacturing rebound", "pmi rises", "solar demand", "electronics demand"),
        ),
        CausalRule(
            bucket="industrial_demand",
            event="manufacturing_slowdown",
            transmission_channel="industrial_cycle",
            direction_bias="down",
            weight=0.9,
            terms=("manufacturing slowdown", "pmi contraction", "industrial demand weak"),
        ),
        CausalRule(
            bucket="supply",
            event="mine_supply_disruption",
            transmission_channel="physical_supply",
            direction_bias="up",
            weight=0.85,
            terms=("mine disruption", "strike", "smelter outage", "supply disruption"),
        ),
    ),
}


_EFFECT_ONLY_TERMS: tuple[str, ...] = (
    "prices rose",
    "prices jumped",
    "prices fell",
    "futures gained",
    "futures dropped",
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
    "chokepoint_closure",
    "export_restriction",
    "producer_outage",
    "producer_output_cut",
}


def _direction_alignment_score(direction: str, expected: str) -> float:
    normalized_direction = _normalize_text(direction).lower()
    normalized_expected = _normalize_text(expected).lower()
    if normalized_expected in {"", "hold", "neutral"}:
        return 0.5
    if normalized_direction in {"", "hold", "neutral"}:
        return 0.4
    return 1.0 if normalized_direction == normalized_expected else 0.0


def analyze_causal_news(
    *,
    commodity: str,
    title: str,
    description: str,
    content: str,
    direction: str,
    reason_terms_up: Iterable[object] | None = None,
    reason_terms_down: Iterable[object] | None = None,
) -> dict[str, object]:
    commodity_key = _normalize_text(commodity).upper()
    text = _to_text_blob(title, description, content)
    reason_blob = _to_text_blob(*(reason_terms_up or ()), *(reason_terms_down or ()))
    full_text = _to_text_blob(text, reason_blob)

    matched: list[CausalCandidate] = []
    for rule in (*_GLOBAL_RULES, *_COMMODITY_RULES.get(commodity_key, ())):
        terms = _match_terms(full_text, rule.terms)
        if not terms:
            continue
        evidence = float(len(terms)) * float(rule.weight)
        if commodity_key in _COMMODITY_RULES:
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
