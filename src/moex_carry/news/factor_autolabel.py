from __future__ import annotations

import functools
import importlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from moex_carry.storage.repositories import (
    load_event_target_v2,
    load_news_event_items,
    load_news_events,
    load_news_items_by_ids,
    upsert_event_factor_scores_v2,
    upsert_news_labels,
)


def _safe_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception:
        return None


@dataclass(frozen=True)
class FactorRule:
    factor: str
    keywords: tuple[str, ...]
    prototypes: tuple[str, ...]
    hypothesis: str
    prior_bullish_tokens: tuple[str, ...]
    prior_bearish_tokens: tuple[str, ...]


@dataclass(frozen=True)
class FactorAutolabelReport:
    horizon: str
    symbol_filter: str | None
    events_seen: int
    events_scored: int
    factor_rows_upserted: int
    labels_upserted: int
    unknown_primary_count: int
    nli_used: bool


_WORD_RE = re.compile(r"[a-z0-9_]{2,}")

_COMMODITY_RULES: dict[str, tuple[FactorRule, ...]] = {
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


def _tokenize(text: str) -> set[str]:
    lowered = str(text or "").lower()
    return {token for token in _WORD_RE.findall(lowered)}


def _keyword_score(text: str, rule: FactorRule) -> tuple[float, list[str]]:
    lowered = str(text or "").lower()
    matched: list[str] = []
    score = 0.0
    for keyword in rule.keywords:
        needle = keyword.lower().strip()
        if not needle:
            continue
        if needle in lowered:
            matched.append(needle)
            score += 1.0
    return score, matched


def _prototype_score(text: str, rule: FactorRule) -> float:
    if not rule.prototypes:
        return 0.0
    text_tokens = _tokenize(text)
    if not text_tokens:
        return 0.0
    best = 0.0
    for prototype in rule.prototypes:
        prototype_tokens = _tokenize(prototype)
        if not prototype_tokens:
            continue
        overlap = len(text_tokens & prototype_tokens) / float(len(prototype_tokens))
        if overlap > best:
            best = overlap
    return float(best)


def _infer_prior(text: str, rule: FactorRule) -> tuple[int, float]:
    lowered = str(text or "").lower()
    bull_hits = sum(1 for token in rule.prior_bullish_tokens if token and token in lowered)
    bear_hits = sum(1 for token in rule.prior_bearish_tokens if token and token in lowered)
    if bull_hits == 0 and bear_hits == 0:
        return 0, 0.0
    if bull_hits > bear_hits:
        return 1, min(1.0, 0.20 + 0.15 * bull_hits)
    if bear_hits > bull_hits:
        return -1, min(1.0, 0.20 + 0.15 * bear_hits)
    return 0, 0.30


@functools.lru_cache(maxsize=2)
def _get_nli_pipeline(model_name: str):
    transformers = _safe_import("transformers")
    if transformers is None:
        return None
    try:
        return transformers.pipeline("zero-shot-classification", model=model_name)
    except Exception:
        return None


def _nli_scores(
    *,
    text: str,
    rules: list[FactorRule],
    model_name: str,
) -> dict[str, float]:
    if not rules:
        return {}
    pipeline = _get_nli_pipeline(model_name)
    if pipeline is None:
        return {}
    hypotheses = [item.hypothesis for item in rules]
    try:
        result = pipeline(text, candidate_labels=hypotheses, multi_label=True)
    except Exception:
        return {}
    labels = list(result.get("labels") or [])
    scores = list(result.get("scores") or [])
    hypothesis_to_factor = {item.hypothesis: item.factor for item in rules}
    mapped: dict[str, float] = {}
    for label, score in zip(labels, scores):
        factor = hypothesis_to_factor.get(str(label))
        if not factor:
            continue
        mapped[factor] = max(mapped.get(factor, 0.0), float(score))
    return mapped


def _direction_from_prior(prior: int) -> str:
    if prior > 0:
        return "positive"
    if prior < 0:
        return "negative"
    return "uncertain"


def _build_event_texts(session: Session, *, event_ids: list[str], max_chars: int) -> dict[str, str]:
    if not event_ids:
        return {}
    events = load_news_events(session, event_ids=event_ids, limit=0)
    items = load_news_event_items(session, event_ids=event_ids, limit=max(len(event_ids) * 20, 5000))
    news_ids = sorted({str(row.get("news_id") or "").strip() for row in items if str(row.get("news_id") or "").strip()})
    news_rows = load_news_items_by_ids(session, news_ids)
    news_by_id = {str(row.get("news_id") or "").strip(): row for row in news_rows}

    news_ids_by_event: dict[str, list[str]] = {}
    for row in items:
        event_id = str(row.get("event_id") or "").strip()
        news_id = str(row.get("news_id") or "").strip()
        if not event_id or not news_id:
            continue
        news_ids_by_event.setdefault(event_id, []).append(news_id)

    event_texts: dict[str, str] = {}
    for event in events:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            continue
        fragments: list[str] = []
        summary = str(event.get("canonical_summary") or "").strip()
        mechanism = str(event.get("canonical_mechanism") or "").strip()
        if summary:
            fragments.append(summary)
        if mechanism:
            fragments.append(mechanism)
        for news_id in news_ids_by_event.get(event_id, [])[:8]:
            row = news_by_id.get(news_id)
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            content = str(row.get("content") or "").strip()
            if title:
                fragments.append(title)
            if content:
                fragments.append(content[:300])
        text = " | ".join(fragment for fragment in fragments if fragment).strip()
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars]
        event_texts[event_id] = text
    return event_texts


def _autolabel_event(
    *,
    text: str,
    rules: tuple[FactorRule, ...],
    min_confidence: float,
    top_k: int,
    nli_model_name: str,
    nli_enabled: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not text or not rules:
        return [], {"factor_primary": "UNKNOWN", "factor_secondary": None, "factor_confidence": 0.0}

    raw_scores: list[dict[str, Any]] = []
    max_keyword = 0.0
    max_proto = 0.0
    for rule in rules:
        keyword_score, matched_terms = _keyword_score(text, rule)
        prototype_score = _prototype_score(text, rule)
        max_keyword = max(max_keyword, keyword_score)
        max_proto = max(max_proto, prototype_score)
        raw_scores.append(
            {
                "factor_name": rule.factor,
                "keyword_score": keyword_score,
                "prototype_score": prototype_score,
                "matched_terms": matched_terms,
                "rule": rule,
            }
        )
    for item in raw_scores:
        item["keyword_norm"] = float(item["keyword_score"] / max(max_keyword, 1.0))
        item["prototype_norm"] = float(item["prototype_score"] / max(max_proto, 1.0))
        item["pre_score"] = 0.7 * item["keyword_norm"] + 0.3 * item["prototype_norm"]

    candidates = sorted(raw_scores, key=lambda row: row["pre_score"], reverse=True)[: max(int(top_k), 3)]
    nli_input_rules = [item["rule"] for item in candidates if isinstance(item.get("rule"), FactorRule)]
    nli_score_map = _nli_scores(text=text, rules=nli_input_rules, model_name=nli_model_name) if nli_enabled else {}

    ranked: list[dict[str, Any]] = []
    for item in raw_scores:
        rule = item["rule"]
        nli_score = float(nli_score_map.get(rule.factor, 0.0))
        final_score = 0.5 * item["keyword_norm"] + 0.2 * item["prototype_norm"] + 0.3 * nli_score
        prior, prior_conf = _infer_prior(text, rule)
        p_bull = final_score if prior > 0 else max(nli_score * 0.5, 0.0)
        p_bear = final_score if prior < 0 else max(nli_score * 0.5, 0.0)
        ranked.append(
            {
                "factor_name": rule.factor,
                "keyword_norm": float(item["keyword_norm"]),
                "prototype_norm": float(item["prototype_norm"]),
                "nli_score": nli_score,
                "factor_conf": float(final_score),
                "factor_score": float(final_score * float(prior)),
                "p_entail_bull": float(p_bull),
                "p_entail_bear": float(p_bear),
                "matched_terms": item["matched_terms"],
                "polarity_prior": int(prior),
                "polarity_conf": float(prior_conf),
            }
        )

    ranked.sort(key=lambda row: row["factor_conf"], reverse=True)
    top = ranked[0] if ranked else None
    second = ranked[1] if len(ranked) > 1 else None
    if top is None or float(top.get("factor_conf") or 0.0) < float(min_confidence):
        summary = {"factor_primary": "UNKNOWN", "factor_secondary": None, "factor_confidence": 0.0}
    else:
        secondary = None
        if second is not None and float(second.get("factor_conf") or 0.0) >= float(min_confidence) * 0.8:
            secondary = str(second.get("factor_name") or "")
        summary = {
            "factor_primary": str(top.get("factor_name") or "UNKNOWN"),
            "factor_secondary": secondary,
            "factor_confidence": float(top.get("factor_conf") or 0.0),
            "polarity_prior": int(top.get("polarity_prior") or 0),
            "polarity_conf": float(top.get("polarity_conf") or 0.0),
        }
    return ranked[: max(int(top_k), 1)], summary


def run_factor_autolabel_v2(
    session: Session,
    *,
    horizon: str = "5m",
    symbol: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    min_confidence: float = 0.35,
    top_k: int = 3,
    include_overlapped: bool = False,
    nli_enabled: bool = True,
    nli_model_name: str = "facebook/bart-large-mnli",
    label_version: str = "autolabel-v2",
    text_max_chars: int = 4000,
    max_events: int = 0,
) -> FactorAutolabelReport:
    normalized_symbol = str(symbol or "").strip().upper() or None
    rows = load_event_target_v2(
        session,
        symbol=normalized_symbol,
        horizon=str(horizon or "5m").strip().lower(),
        from_ts=from_ts.isoformat() + "Z" if isinstance(from_ts, datetime) else None,
        to_ts=to_ts.isoformat() + "Z" if isinstance(to_ts, datetime) else None,
        clean_only=not bool(include_overlapped),
        limit=0,
    )
    event_to_row: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            continue
        current = event_to_row.get(event_id)
        if current is None:
            event_to_row[event_id] = row
            continue
        if abs(float(row.get("impact_score") or 0.0)) > abs(float(current.get("impact_score") or 0.0)):
            event_to_row[event_id] = row

    ranked_event_rows = sorted(
        event_to_row.values(),
        key=lambda item: (
            -abs(float(item.get("impact_score") or 0.0)),
            str(item.get("t0") or ""),
            str(item.get("event_id") or ""),
        ),
    )
    if int(max_events) > 0:
        ranked_event_rows = ranked_event_rows[: int(max_events)]
    event_ids = [str(item.get("event_id") or "").strip() for item in ranked_event_rows if str(item.get("event_id") or "").strip()]
    event_texts = _build_event_texts(session, event_ids=event_ids, max_chars=max(int(text_max_chars), 0))
    factor_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    unknown_primary = 0
    scored = 0
    now = datetime.utcnow().replace(microsecond=0)

    for event_id in event_ids:
        row = event_to_row.get(event_id, {})
        ticker = str(row.get("symbol") or "").strip().upper()
        if not ticker:
            continue
        rules = _COMMODITY_RULES.get(ticker)
        if not rules:
            continue
        text = str(event_texts.get(event_id) or "").strip()
        scored_rows, summary = _autolabel_event(
            text=text,
            rules=rules,
            min_confidence=float(min_confidence),
            top_k=max(int(top_k), 1),
            nli_model_name=nli_model_name,
            nli_enabled=bool(nli_enabled),
        )
        if not scored_rows:
            continue
        scored += 1
        primary = str(summary.get("factor_primary") or "UNKNOWN")
        if primary == "UNKNOWN":
            unknown_primary += 1
        secondary = summary.get("factor_secondary")
        for item in scored_rows:
            factor_rows.append(
                {
                    "event_id": event_id,
                    "symbol": ticker,
                    "factor_name": item["factor_name"],
                    "p_entail_bull": item["p_entail_bull"],
                    "p_entail_bear": item["p_entail_bear"],
                    "factor_score": item["factor_score"],
                    "factor_conf": item["factor_conf"],
                    "model_name": "autolabel-v2",
                    "computed_at": now.isoformat() + "Z",
                }
            )
        top = scored_rows[0]
        label_rows.append(
            {
                "target_level": "event",
                "target_id": event_id,
                "commodity_json": [ticker],
                "market_scope": "futures",
                "instrument_candidates_json": [{"symbol": ticker}],
                "relevance": max(min(float(row.get("confidence") or 0.0), 1.0), 0.0),
                "news_type_json": [primary] + ([str(secondary)] if isinstance(secondary, str) and secondary else []),
                "direction": _direction_from_prior(int(summary.get("polarity_prior") or 0)),
                "magnitude": float(top.get("factor_conf") or 0.0),
                "lag_bucket": "immediate",
                "confidence": float(summary.get("factor_confidence") or 0.0),
                "uncertainty_type": "auto",
                "geo_scope": "GLOBAL",
                "evidence_json": {
                    "factor_primary": primary,
                    "factor_secondary": secondary,
                    "impact_score": float(row.get("impact_score") or 0.0),
                    "impact_bin": int(row.get("impact_bin") or 0),
                    "factor_scores": [
                        {
                            "factor_name": item.get("factor_name"),
                            "factor_conf": item.get("factor_conf"),
                            "keyword_norm": item.get("keyword_norm"),
                            "prototype_norm": item.get("prototype_norm"),
                            "nli_score": item.get("nli_score"),
                            "matched_terms": item.get("matched_terms"),
                            "polarity_prior": item.get("polarity_prior"),
                            "polarity_conf": item.get("polarity_conf"),
                        }
                        for item in scored_rows
                    ],
                },
                "label_source": "auto_factor_v2",
                "label_version": str(label_version or "autolabel-v2"),
                "model_version": "autolabel-v2",
                "prompt_version": "nli-factor-hypothesis-v1",
                "created_at": now.isoformat() + "Z",
            }
        )

    factor_rows_upserted = upsert_event_factor_scores_v2(session, factor_rows) if factor_rows else 0
    labels_upserted = upsert_news_labels(session, label_rows) if label_rows else 0
    return FactorAutolabelReport(
        horizon=str(horizon or "5m").strip().lower(),
        symbol_filter=normalized_symbol,
        events_seen=len(event_ids),
        events_scored=scored,
        factor_rows_upserted=factor_rows_upserted,
        labels_upserted=labels_upserted,
        unknown_primary_count=unknown_primary,
        nli_used=bool(nli_enabled),
    )
