from __future__ import annotations

from collections import deque
from dataclasses import dataclass


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split()).lower()


def _match_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = _normalize_text(text)
    hits: list[str] = []
    for term in terms:
        needle = _normalize_text(term)
        if needle and needle in lowered:
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
class CommodityEntity:
    node: str
    role: str
    canonical: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class DependencyEdge:
    source: str
    target: str


@dataclass(frozen=True)
class CommodityKnowledge:
    commodity: str
    entities: tuple[CommodityEntity, ...]
    edges: tuple[DependencyEdge, ...]
    event_query_terms: tuple[str, ...]


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
        terms=("outage", "force majeure", "leak", "explosion", "fire", "shutdown"),
        required_roles=("producer", "exporter", "operator", "terminal"),
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
        terms=("output cut", "production cut", "voluntary cut", "supply cut"),
        required_roles=("producer", "exporter"),
    ),
    EventTemplate(
        event="producer_output_hike",
        bucket="supply",
        transmission_channel="physical_supply",
        direction_bias="down",
        weight=0.9,
        terms=("output increase", "production increase", "supply hike", "boost output"),
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


def _entity(node: str, role: str, canonical: str, *aliases: str) -> CommodityEntity:
    return CommodityEntity(node=node, role=role, canonical=canonical, aliases=tuple(aliases))


_COMMODITY_KNOWLEDGE: dict[str, CommodityKnowledge] = {
    "BRN": CommodityKnowledge(
        commodity="BRN",
        entities=(
            _entity("producer:opec", "producer", "OPEC+", "opec", "opec+", "producer group"),
            _entity("exporter:saudi_arabia", "exporter", "Saudi Arabia", "saudi arabia", "saudi", "ksa", "aramco"),
            _entity("exporter:russia", "exporter", "Russia", "russia", "russian exports"),
            _entity("exporter:iraq", "exporter", "Iraq", "iraq", "iraqi oil"),
            _entity("exporter:uae", "exporter", "UAE", "uae", "united arab emirates", "abu dhabi"),
            _entity("exporter:kuwait", "exporter", "Kuwait", "kuwait"),
            _entity("exporter:iran", "exporter", "Iran", "iran", "iranian crude"),
            _entity("importer:china", "importer", "China", "china", "chinese refiners"),
            _entity("importer:india", "importer", "India", "india", "indian refiners"),
            _entity("importer:eu", "importer", "European Union", "europe", "eu"),
            _entity("chokepoint:hormuz", "chokepoint", "Strait of Hormuz", "strait of hormuz", "hormuz"),
            _entity("chokepoint:suez", "chokepoint", "Suez Canal", "suez canal", "suez"),
            _entity("chokepoint:bab_el_mandeb", "chokepoint", "Bab el-Mandeb", "bab el-mandeb", "red sea lane"),
            _entity("regulator:us_treasury", "regulator", "US Treasury", "us treasury", "ofac", "sanctions office"),
        ),
        edges=(
            DependencyEdge("chokepoint:hormuz", "flow:seaborne_crude"),
            DependencyEdge("chokepoint:suez", "flow:seaborne_crude"),
            DependencyEdge("chokepoint:bab_el_mandeb", "flow:seaborne_crude"),
            DependencyEdge("exporter:saudi_arabia", "flow:seaborne_crude"),
            DependencyEdge("exporter:russia", "flow:seaborne_crude"),
            DependencyEdge("exporter:iraq", "flow:seaborne_crude"),
            DependencyEdge("exporter:uae", "flow:seaborne_crude"),
            DependencyEdge("exporter:kuwait", "flow:seaborne_crude"),
            DependencyEdge("exporter:iran", "flow:seaborne_crude"),
            DependencyEdge("producer:opec", "flow:seaborne_crude"),
            DependencyEdge("importer:china", "flow:crude_demand"),
            DependencyEdge("importer:india", "flow:crude_demand"),
            DependencyEdge("importer:eu", "flow:crude_demand"),
            DependencyEdge("flow:seaborne_crude", "commodity:BRN"),
            DependencyEdge("flow:crude_demand", "commodity:BRN"),
            DependencyEdge("regulator:us_treasury", "flow:seaborne_crude"),
        ),
        event_query_terms=(
            "strait of hormuz",
            "suez canal",
            "bab el-mandeb",
            "shipping halted",
            "export ban",
            "sanctions",
            "opec output cut",
            "pipeline outage",
            "terminal restart",
            "official statement",
        ),
    ),
    "NG_US": CommodityKnowledge(
        commodity="NG_US",
        entities=(
            _entity("producer:appalachia", "producer", "Appalachia", "appalachia", "marcellus", "utica"),
            _entity("producer:haynesville", "producer", "Haynesville", "haynesville"),
            _entity("producer:permian", "producer", "Permian", "permian", "associated gas"),
            _entity("terminal:freeport", "terminal", "Freeport LNG", "freeport lng", "freeport terminal"),
            _entity("terminal:sabine", "terminal", "Sabine Pass LNG", "sabine pass", "cheniere"),
            _entity("terminal:corpus", "terminal", "Corpus Christi LNG", "corpus christi lng"),
            _entity("terminal:cameron", "terminal", "Cameron LNG", "cameron lng"),
            _entity("importer:eu", "importer", "European Union", "europe", "eu gas buyers"),
            _entity("importer:japan", "importer", "Japan", "japan", "japanese buyers"),
            _entity("importer:korea", "importer", "South Korea", "south korea", "korean buyers"),
            _entity("importer:china", "importer", "China", "china", "chinese lng"),
            _entity("chokepoint:panama", "chokepoint", "Panama Canal", "panama canal", "panama transit"),
            _entity("chokepoint:hormuz", "chokepoint", "Strait of Hormuz", "strait of hormuz", "hormuz"),
            _entity("operator:eia", "operator", "EIA", "eia", "storage report"),
        ),
        edges=(
            DependencyEdge("producer:appalachia", "flow:us_gas_supply"),
            DependencyEdge("producer:haynesville", "flow:us_gas_supply"),
            DependencyEdge("producer:permian", "flow:us_gas_supply"),
            DependencyEdge("terminal:freeport", "flow:us_lng_exports"),
            DependencyEdge("terminal:sabine", "flow:us_lng_exports"),
            DependencyEdge("terminal:corpus", "flow:us_lng_exports"),
            DependencyEdge("terminal:cameron", "flow:us_lng_exports"),
            DependencyEdge("chokepoint:panama", "flow:lng_shipping"),
            DependencyEdge("chokepoint:hormuz", "flow:lng_shipping"),
            DependencyEdge("importer:eu", "flow:lng_import_demand"),
            DependencyEdge("importer:japan", "flow:lng_import_demand"),
            DependencyEdge("importer:korea", "flow:lng_import_demand"),
            DependencyEdge("importer:china", "flow:lng_import_demand"),
            DependencyEdge("flow:us_gas_supply", "commodity:NG_US"),
            DependencyEdge("flow:us_lng_exports", "commodity:NG_US"),
            DependencyEdge("flow:lng_shipping", "commodity:NG_US"),
            DependencyEdge("flow:lng_import_demand", "commodity:NG_US"),
            DependencyEdge("operator:eia", "commodity:NG_US"),
        ),
        event_query_terms=(
            "freeport lng",
            "sabine pass",
            "panama canal",
            "terminal outage",
            "terminal restart",
            "storage report",
            "freeze-off",
            "pipeline outage",
            "import surge",
            "official statement",
        ),
    ),
    "GOLD": CommodityKnowledge(
        commodity="GOLD",
        entities=(
            _entity("producer:china", "producer", "China", "china mine output", "china gold"),
            _entity("producer:australia", "producer", "Australia", "australia", "australian gold"),
            _entity("producer:russia", "producer", "Russia", "russia", "russian gold"),
            _entity("producer:canada", "producer", "Canada", "canada", "canadian gold"),
            _entity("importer:india", "importer", "India", "india", "indian jewelry demand"),
            _entity("importer:china", "importer", "China", "china", "chinese jewelry demand"),
            _entity("importer:turkey", "importer", "Turkey", "turkey", "turkish gold imports"),
            _entity("operator:fed", "operator", "Federal Reserve", "federal reserve", "fed"),
            _entity("operator:ecb", "operator", "ECB", "ecb", "european central bank"),
            _entity("operator:pboc", "operator", "PBoC", "pboc", "people's bank of china"),
            _entity("operator:central_banks", "operator", "Central Banks", "central bank buying", "reserve purchases"),
        ),
        edges=(
            DependencyEdge("operator:fed", "flow:real_yields"),
            DependencyEdge("operator:ecb", "flow:real_yields"),
            DependencyEdge("operator:pboc", "flow:real_yields"),
            DependencyEdge("operator:central_banks", "flow:physical_gold_demand"),
            DependencyEdge("importer:india", "flow:physical_gold_demand"),
            DependencyEdge("importer:china", "flow:physical_gold_demand"),
            DependencyEdge("importer:turkey", "flow:physical_gold_demand"),
            DependencyEdge("producer:china", "flow:mine_supply"),
            DependencyEdge("producer:australia", "flow:mine_supply"),
            DependencyEdge("producer:russia", "flow:mine_supply"),
            DependencyEdge("producer:canada", "flow:mine_supply"),
            DependencyEdge("flow:real_yields", "commodity:GOLD"),
            DependencyEdge("flow:physical_gold_demand", "commodity:GOLD"),
            DependencyEdge("flow:mine_supply", "commodity:GOLD"),
        ),
        event_query_terms=(
            "central bank buying",
            "fed rate cut",
            "real yields",
            "reserve purchases",
            "official statement",
            "sanctions",
            "safe haven demand",
            "mine disruption",
            "import surge",
            "policy meeting",
        ),
    ),
    "SILVER": CommodityKnowledge(
        commodity="SILVER",
        entities=(
            _entity("producer:mexico", "producer", "Mexico", "mexico", "mexican mines"),
            _entity("producer:peru", "producer", "Peru", "peru", "peruvian mines"),
            _entity("producer:china", "producer", "China", "china", "chinese mines"),
            _entity("producer:chile", "producer", "Chile", "chile", "chilean mines"),
            _entity("importer:china", "importer", "China", "china", "chinese industrial demand"),
            _entity("importer:india", "importer", "India", "india", "indian silver imports"),
            _entity("importer:usa", "importer", "United States", "united states", "us industrial demand"),
            _entity("operator:solar", "operator", "Solar Manufacturers", "solar demand", "pv demand"),
            _entity("operator:electronics", "operator", "Electronics Sector", "electronics demand"),
            _entity("operator:auto", "operator", "EV Supply Chain", "ev demand", "battery demand"),
        ),
        edges=(
            DependencyEdge("producer:mexico", "flow:silver_mine_supply"),
            DependencyEdge("producer:peru", "flow:silver_mine_supply"),
            DependencyEdge("producer:china", "flow:silver_mine_supply"),
            DependencyEdge("producer:chile", "flow:silver_mine_supply"),
            DependencyEdge("importer:china", "flow:industrial_silver_demand"),
            DependencyEdge("importer:india", "flow:industrial_silver_demand"),
            DependencyEdge("importer:usa", "flow:industrial_silver_demand"),
            DependencyEdge("operator:solar", "flow:industrial_silver_demand"),
            DependencyEdge("operator:electronics", "flow:industrial_silver_demand"),
            DependencyEdge("operator:auto", "flow:industrial_silver_demand"),
            DependencyEdge("flow:silver_mine_supply", "commodity:SILVER"),
            DependencyEdge("flow:industrial_silver_demand", "commodity:SILVER"),
        ),
        event_query_terms=(
            "solar demand",
            "electronics demand",
            "mine disruption",
            "smelter outage",
            "import surge",
            "output cut",
            "sanctions",
            "official statement",
            "supply disruption",
            "manufacturing rebound",
        ),
    ),
}


def commodity_role_catalog(commodity: str) -> dict[str, tuple[str, ...]]:
    knowledge = _COMMODITY_KNOWLEDGE.get(_normalize_text(commodity).upper())
    if knowledge is None:
        return {}
    by_role: dict[str, list[str]] = {}
    for entity in knowledge.entities:
        by_role.setdefault(entity.role, []).append(entity.canonical)
    return {role: tuple(_unique_preserve(values)) for role, values in by_role.items()}


def build_event_first_query_terms(commodity: str, *, max_terms: int = 14) -> tuple[str, ...]:
    knowledge = _COMMODITY_KNOWLEDGE.get(_normalize_text(commodity).upper())
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
    knowledge = _COMMODITY_KNOWLEDGE.get(commodity_key)
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
