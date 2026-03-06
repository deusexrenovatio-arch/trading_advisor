from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re

from moex_carry.news_commodity_graph_knowledge import CommodityEntity, CommodityKnowledge, COMMODITY_KNOWLEDGE


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split()).lower()


def _match_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = _normalize_text(text)
    hits: list[str] = []
    for term in terms:
        needle = _normalize_text(term)
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


def _unique_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        normalized = str(item or "").strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out

@dataclass(frozen=True)
class EventTemplate:
    event: str
    bucket: str
    transmission_channel: str
    direction_bias: str
    weight: float
    terms: tuple[str, ...]
    required_roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventInference:
    event: str
    bucket: str
    transmission_channel: str
    direction_bias: str
    claim_status: str
    evidence: float
    cause_terms: tuple[str, ...]
    matched_entities: tuple[str, ...]
    route_key: str


_CLAIM_CONFIRMED_TERMS: tuple[str, ...] = (
    "official statement",
    "officially announced",
    "ministry said",
    "authority said",
    "operator said",
)

_CLAIM_RUMOR_TERMS: tuple[str, ...] = (
    "reportedly",
    "report says",
    "rumor",
    "unconfirmed",
    "could",
    "may",
    "possible closure",
)

_CLAIM_DENIED_TERMS: tuple[str, ...] = (
    "denied",
    "not closed",
    "remains open",
    "no closure",
    "false claim",
    "dismissed reports",
)


_EVENT_TEMPLATES: tuple[EventTemplate, ...] = (
    EventTemplate(
        event="chokepoint_closure",
        bucket="geopolitics",
        transmission_channel="transport_chokepoint",
        direction_bias="up",
        weight=1.0,
        terms=(
            "closed",
            "closure",
            "could be closed",
            "blocked",
            "suspended transit",
            "halted transit",
            "shipping halted",
            "blockade",
            "sealed",
        ),
        required_roles=("chokepoint",),
    ),
    EventTemplate(
        event="chokepoint_reopen",
        bucket="geopolitics",
        transmission_channel="transport_chokepoint",
        direction_bias="down",
        weight=0.95,
        terms=("reopened", "reopen", "transit resumed", "shipping resumed", "flows restored"),
        required_roles=("chokepoint",),
    ),
    EventTemplate(
        event="producer_outage",
        bucket="supply",
        transmission_channel="physical_supply",
        direction_bias="up",
        weight=0.92,
        terms=(
            "outage",
            "force majeure",
            "leak",
            "explosion",
            "fire",
            "shutdown",
            "strike on oil facility",
            "strike on refinery",
            "strike on export terminal",
            "pipeline attack",
            "refinery attack",
            "oil facility hit",
            "refinery hit",
            "export terminal hit",
            "terminal attack",
            "operations halt",
            "landslide",
        ),
        required_roles=("producer", "exporter", "operator", "terminal"),
    ),
    EventTemplate(
        event="exporter_military_strike_risk",
        bucket="geopolitics",
        transmission_channel="geopolitical_risk",
        direction_bias="up",
        weight=0.9,
        terms=(
            "strikes iran",
            "strike on iran",
            "attack on iran",
            "israel attacks iran",
            "us strikes iran",
            "military strike on iran",
        ),
        required_roles=("exporter",),
    ),
    EventTemplate(
        event="producer_restart",
        bucket="supply",
        transmission_channel="physical_supply",
        direction_bias="down",
        weight=0.88,
        terms=("restart", "operations resumed", "restored output", "terminal restart"),
        required_roles=("producer", "exporter", "operator", "terminal"),
    ),
    EventTemplate(
        event="export_restriction",
        bucket="trade_policy",
        transmission_channel="physical_supply",
        direction_bias="up",
        weight=1.0,
        terms=("export ban", "export curb", "export quota", "embargo", "sanctions", "export duty"),
        required_roles=("producer", "exporter", "regulator", "operator"),
    ),
    EventTemplate(
        event="export_normalization",
        bucket="trade_policy",
        transmission_channel="physical_supply",
        direction_bias="down",
        weight=0.9,
        terms=("ban lifted", "sanctions eased", "export resumed", "waiver granted"),
        required_roles=("producer", "exporter", "regulator", "operator"),
    ),
    EventTemplate(
        event="producer_output_cut",
        bucket="supply",
        transmission_channel="physical_supply",
        direction_bias="up",
        weight=0.95,
        terms=(
            "output cut",
            "production cut",
            "voluntary cut",
            "supply cut",
            "quota cut",
            "permit volume slashed",
            "production limits",
            "told to slash output",
        ),
        required_roles=("producer", "exporter"),
    ),
    EventTemplate(
        event="producer_output_hike",
        bucket="supply",
        transmission_channel="physical_supply",
        direction_bias="down",
        weight=0.9,
        terms=(
            "output increase",
            "production increase",
            "supply hike",
            "boost output",
            "higher production quota",
            "record harvest",
            "crop prospects improve",
        ),
        required_roles=("producer", "exporter"),
    ),
    EventTemplate(
        event="import_demand_surge",
        bucket="demand",
        transmission_channel="physical_demand",
        direction_bias="up",
        weight=0.86,
        terms=("import surge", "record imports", "tender demand", "stockpiling"),
        required_roles=("importer",),
    ),
    EventTemplate(
        event="import_demand_drop",
        bucket="demand",
        transmission_channel="physical_demand",
        direction_bias="down",
        weight=0.86,
        terms=("import cuts", "demand slowdown", "cancelled tender", "reduced purchases"),
        required_roles=("importer",),
    ),
    EventTemplate(
        event="weather_supply_shock",
        bucket="weather",
        transmission_channel="weather_supply",
        direction_bias="up",
        weight=0.82,
        terms=("hurricane", "freeze", "flood", "wildfire", "drought"),
    ),
    EventTemplate(
        event="weather_demand_drop",
        bucket="weather",
        transmission_channel="weather_demand",
        direction_bias="down",
        weight=0.74,
        terms=("mild weather", "warm winter", "demand weak", "cooling demand drop"),
    ),
)


_DENIAL_EVENT_INVERSION: dict[str, str] = {
    "chokepoint_closure": "chokepoint_reopen",
    "producer_outage": "producer_restart",
    "export_restriction": "export_normalization",
    "producer_output_cut": "producer_output_hike",
}

_ENERGY_CONTEXT_TERMS: tuple[str, ...] = (
    "oil",
    "crude",
    "refinery",
    "export terminal",
    "terminal",
    "pipeline",
    "tanker",
    "shipping",
    "strait of hormuz",
    "hormuz",
    "lng",
    "gas field",
)

def commodity_role_catalog(commodity: str) -> dict[str, tuple[str, ...]]:
    knowledge = COMMODITY_KNOWLEDGE.get(_normalize_text(commodity).upper())
    if knowledge is None:
        return {}
    by_role: dict[str, list[str]] = {}
    for entity in knowledge.entities:
        by_role.setdefault(entity.role, []).append(entity.canonical)
    return {role: tuple(_unique_preserve(values)) for role, values in by_role.items()}


def build_event_first_query_terms(commodity: str, *, max_terms: int = 14) -> tuple[str, ...]:
    knowledge = COMMODITY_KNOWLEDGE.get(_normalize_text(commodity).upper())
    if knowledge is None:
        return ()
    terms = list(knowledge.event_query_terms)
    for entity in knowledge.entities:
        if entity.role in {"chokepoint", "terminal", "regulator", "operator"}:
            terms.extend(entity.aliases[:2])
    deduped = _unique_preserve(terms)
    return tuple(deduped[: max(int(max_terms), 1)])


def _detect_claim_status(text: str) -> str:
    lowered = _normalize_text(text)
    denied = _match_terms(lowered, _CLAIM_DENIED_TERMS)
    if denied:
        return "denied"
    confirmed = _match_terms(lowered, _CLAIM_CONFIRMED_TERMS)
    rumor = _match_terms(lowered, _CLAIM_RUMOR_TERMS)
    if rumor and not confirmed:
        return "rumor"
    return "confirmed"


def _match_entities(text: str, knowledge: CommodityKnowledge) -> list[tuple[CommodityEntity, str]]:
    lowered = _normalize_text(text)
    hits: list[tuple[CommodityEntity, str]] = []
    for entity in knowledge.entities:
        for alias in entity.aliases:
            needle = _normalize_text(alias)
            if needle and needle in lowered:
                hits.append((entity, needle))
                break
    return hits


def _best_route(knowledge: CommodityKnowledge, *, start_node: str) -> tuple[str, ...]:
    target = f"commodity:{knowledge.commodity}"
    adjacency: dict[str, list[str]] = {}
    for edge in knowledge.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)
    queue: deque[tuple[str, tuple[str, ...]]] = deque([(start_node, (start_node,))])
    visited: set[str] = {start_node}
    while queue:
        node, path = queue.popleft()
        if node == target:
            return path
        for nxt in adjacency.get(node, []):
            if nxt in visited:
                continue
            visited.add(nxt)
            queue.append((nxt, (*path, nxt)))
    return (start_node, target)


def infer_event_first_cause(*, commodity: str, text: str) -> EventInference | None:
    commodity_key = _normalize_text(commodity).upper()
    knowledge = COMMODITY_KNOWLEDGE.get(commodity_key)
    if knowledge is None:
        return None

    entity_hits = _match_entities(text, knowledge)
    if not entity_hits:
        return None
    available_roles = {entity.role for entity, _ in entity_hits}
    entity_canonicals = _unique_preserve([entity.canonical for entity, _ in entity_hits])
    entity_aliases = _unique_preserve([alias for _entity, alias in entity_hits])

    candidates: list[tuple[EventTemplate, list[str], float]] = []
    lowered = _normalize_text(text)
    for template in _EVENT_TEMPLATES:
        hits = _match_terms(lowered, template.terms)
        if not hits:
            continue
        if template.required_roles and not (set(template.required_roles) & available_roles):
            continue
        if template.event == "exporter_military_strike_risk":
            context_hits = _match_terms(lowered, _ENERGY_CONTEXT_TERMS)
            if not context_hits:
                continue
            hits = _unique_preserve([*hits, *context_hits[:2]])
        evidence = 1.35 + 0.22 * len(hits) + 0.12 * len(entity_hits) + 0.3 * float(template.weight)
        if "chokepoint" in available_roles and template.event.startswith("chokepoint_"):
            evidence += 0.12
        candidates.append((template, hits, evidence))
    if not candidates:
        return None

    template, event_hits, evidence = sorted(
        candidates,
        key=lambda item: (item[2], len(item[1]), item[0].weight),
        reverse=True,
    )[0]
    claim_status = _detect_claim_status(text)
    selected_template = template
    selected_hits = event_hits
    if claim_status == "denied":
        inverted = _DENIAL_EVENT_INVERSION.get(template.event)
        if inverted:
            for candidate in _EVENT_TEMPLATES:
                if candidate.event == inverted:
                    selected_template = candidate
                    selected_hits = [*event_hits, "denial-confirmed"]
                    break
    if claim_status == "rumor":
        evidence = max(0.0, evidence - 0.24)
    elif claim_status == "confirmed":
        evidence += 0.06

    prioritized_nodes = sorted(
        entity_hits,
        key=lambda item: (
            {"chokepoint": 4, "terminal": 3, "exporter": 3, "producer": 2, "importer": 1}.get(item[0].role, 0),
            len(item[1]),
        ),
        reverse=True,
    )
    start_node = prioritized_nodes[0][0].node
    if selected_template.event == "exporter_military_strike_risk":
        exporter_nodes = [entity.node for entity, _alias in entity_hits if entity.role == "exporter"]
        if exporter_nodes:
            start_node = next((node for node in exporter_nodes if "iran" in node), exporter_nodes[0])
    route = _best_route(knowledge, start_node=start_node)
    route_key = "->".join(segment.replace("commodity:", "").replace("flow:", "") for segment in route)
    cause_terms = tuple(
        _unique_preserve(
            [*selected_hits, *entity_aliases[:4], f"status:{claim_status}", f"route:{route_key}"]
        )
    )
    return EventInference(
        event=selected_template.event,
        bucket=selected_template.bucket,
        transmission_channel=selected_template.transmission_channel,
        direction_bias=selected_template.direction_bias,
        claim_status=claim_status,
        evidence=round(float(evidence), 6),
        cause_terms=cause_terms,
        matched_entities=tuple(entity_canonicals[:6]),
        route_key=route_key,
    )
