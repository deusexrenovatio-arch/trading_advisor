from __future__ import annotations

from collections import defaultdict
import functools
import importlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from moex_carry.news.factor_rules import COMMODITY_RULES, FactorRule
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
class FactorAutolabelReport:
    horizon: str
    symbol_filter: str | None
    events_seen: int
    events_scored: int
    factor_rows_upserted: int
    labels_upserted: int
    unknown_primary_count: int
    nli_used: bool
    nli_events_requested: int = 0
    nli_events_skipped: int = 0
    nli_pipeline_calls: int = 0
    nli_batch_groups: int = 0


_WORD_RE = re.compile(r"[a-z0-9_]{2,}")


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


@functools.lru_cache(maxsize=8)
def _get_nli_pipeline(model_name: str, nli_device: str = "auto"):
    transformers = _safe_import("transformers")
    if transformers is None:
        return None
    torch_mod = _safe_import("torch")
    normalized_device = str(nli_device or "auto").strip().lower()
    device_id = -1
    if normalized_device in {"auto", "cuda", "gpu"}:
        if torch_mod is not None and bool(getattr(getattr(torch_mod, "cuda", None), "is_available", lambda: False)()):
            device_id = 0
    elif normalized_device.startswith("cuda:"):
        if torch_mod is not None and bool(getattr(getattr(torch_mod, "cuda", None), "is_available", lambda: False)()):
            try:
                parsed = int(normalized_device.split(":", 1)[1].strip())
                device_id = max(parsed, 0)
            except Exception:
                device_id = 0
    elif normalized_device not in {"cpu", "-1"}:
        try:
            device_id = int(normalized_device)
        except Exception:
            device_id = -1
    try:
        if device_id >= 0 and torch_mod is not None and hasattr(torch_mod, "float16"):
            return transformers.pipeline(
                "zero-shot-classification",
                model=model_name,
                device=device_id,
                dtype=torch_mod.float16,
            )
        return transformers.pipeline("zero-shot-classification", model=model_name, device=device_id)
    except Exception:
        try:
            return transformers.pipeline("zero-shot-classification", model=model_name)
        except Exception:
            return None


def _nli_scores(
    *,
    text: str,
    rules: list[FactorRule],
    model_name: str,
    batch_size: int = 16,
    nli_device: str = "auto",
) -> dict[str, float]:
    if not rules:
        return {}
    pipeline = _get_nli_pipeline(model_name, nli_device)
    if pipeline is None:
        return {}
    hypotheses = [item.hypothesis for item in rules]
    try:
        result = pipeline(
            text,
            candidate_labels=hypotheses,
            multi_label=True,
            batch_size=max(int(batch_size), 1),
            truncation=True,
        )
    except Exception:
        return {}
    return _map_nli_result(result, rules)


def _map_nli_result(result: Any, rules: list[FactorRule]) -> dict[str, float]:
    labels = list((result or {}).get("labels") or [])
    scores = list((result or {}).get("scores") or [])
    hypothesis_to_factor = {item.hypothesis: item.factor for item in rules}
    mapped: dict[str, float] = {}
    for label, score in zip(labels, scores):
        factor = hypothesis_to_factor.get(str(label))
        if not factor:
            continue
        mapped[factor] = max(mapped.get(factor, 0.0), float(score))
    return mapped


def _nli_scores_batch(
    *,
    texts: list[str],
    rules: list[FactorRule],
    model_name: str,
    batch_size: int,
    nli_device: str = "auto",
) -> tuple[list[dict[str, float]], int]:
    normalized = [str(item or "").strip() for item in texts if str(item or "").strip()]
    if not normalized or not rules:
        return [], 0
    if len(normalized) == 1:
        return [
            _nli_scores(
                text=normalized[0],
                rules=rules,
                model_name=model_name,
                batch_size=batch_size,
                nli_device=nli_device,
            )
        ], 1
    pipeline = _get_nli_pipeline(model_name, nli_device)
    if pipeline is None:
        return [{} for _ in normalized], 0
    hypotheses = [item.hypothesis for item in rules]
    mapped_results: list[dict[str, float]] = []
    calls = 0
    step = max(int(batch_size), 1)
    for offset in range(0, len(normalized), step):
        chunk = normalized[offset : offset + step]
        try:
            result = pipeline(
                chunk,
                candidate_labels=hypotheses,
                multi_label=True,
                batch_size=step,
                truncation=True,
            )
            calls += 1
        except Exception:
            mapped_results.extend({} for _ in chunk)
            continue
        rows = result if isinstance(result, list) else [result]
        if len(rows) != len(chunk):
            # Defensive fallback in case pipeline returns an unexpected shape.
            rows = [rows[0] if rows else {} for _ in chunk]
        for row in rows:
            mapped_results.append(_map_nli_result(row, rules))
    return mapped_results, calls


def _build_pre_scores(text: str, rules: tuple[FactorRule, ...]) -> list[dict[str, Any]]:
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
    return raw_scores


def _select_nli_input_rules(
    raw_scores: list[dict[str, Any]],
    *,
    top_k: int,
    skip_top_score: float = 0.90,
    skip_margin: float = 0.20,
) -> tuple[list[FactorRule], bool]:
    if not raw_scores:
        return [], False
    ranked = sorted(raw_scores, key=lambda row: float(row.get("pre_score") or 0.0), reverse=True)
    candidates = ranked[: max(int(top_k), 3)]
    top_pre = float(candidates[0].get("pre_score") or 0.0) if candidates else 0.0
    second_pre = float(candidates[1].get("pre_score") or 0.0) if len(candidates) > 1 else 0.0
    should_run_nli = not (top_pre >= float(skip_top_score) and (top_pre - second_pre) >= float(skip_margin))
    selected = [item["rule"] for item in candidates if isinstance(item.get("rule"), FactorRule)]
    return selected, bool(should_run_nli and selected)


def _batch_nli_scores_by_candidates(
    *,
    requests: list[dict[str, Any]],
    model_name: str,
    batch_size: int = 16,
    nli_device: str = "auto",
) -> tuple[dict[str, dict[str, float]], int, int]:
    if not requests:
        return {}, 0, 0
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in requests:
        event_id = str(item.get("event_id") or "").strip()
        text = str(item.get("text") or "").strip()
        rules = item.get("rules")
        if not event_id or not text or not isinstance(rules, list) or not rules:
            continue
        key = tuple(str(rule.hypothesis) for rule in rules if isinstance(rule, FactorRule))
        if not key:
            continue
        groups[key].append({"event_id": event_id, "text": text, "rules": rules})
    if not groups:
        return {}, 0, 0

    score_map_by_event: dict[str, dict[str, float]] = {}
    total_calls = 0
    for group_rows in groups.values():
        rules = group_rows[0]["rules"]
        dedup_text_to_event_ids: dict[str, list[str]] = defaultdict(list)
        for row in group_rows:
            event_id = str(row.get("event_id") or "").strip()
            text = str(row.get("text") or "").strip()
            if not event_id or not text:
                continue
            dedup_text_to_event_ids[text].append(event_id)
        texts = list(dedup_text_to_event_ids.keys())
        if not texts:
            continue
        scores, calls = _nli_scores_batch(
            texts=texts,
            rules=rules,
            model_name=model_name,
            batch_size=max(int(batch_size), 1),
            nli_device=nli_device,
        )
        total_calls += int(calls)
        for text, score_map in zip(texts, scores):
            for event_id in dedup_text_to_event_ids.get(text, []):
                score_map_by_event[event_id] = score_map
    return score_map_by_event, total_calls, len(groups)


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
    nli_score_map: dict[str, float] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not text or not rules:
        return [], {"factor_primary": "UNKNOWN", "factor_secondary": None, "factor_confidence": 0.0}

    raw_scores = _build_pre_scores(text, rules)

    if nli_score_map is None:
        nli_score_map = {}
        if nli_enabled:
            nli_input_rules, should_run_nli = _select_nli_input_rules(raw_scores, top_k=top_k)
            if should_run_nli and nli_input_rules:
                nli_score_map = _nli_scores(text=text, rules=nli_input_rules, model_name=nli_model_name)

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
    nli_device: str = "cuda:0",
    nli_batch_size: int = 64,
    nli_text_max_chars: int = 800,
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

    event_payloads: list[dict[str, Any]] = []
    for event_id in event_ids:
        row = event_to_row.get(event_id, {})
        ticker = str(row.get("symbol") or "").strip().upper()
        if not ticker:
            continue
        rules = COMMODITY_RULES.get(ticker)
        if not rules:
            continue
        event_payloads.append(
            {
                "event_id": event_id,
                "row": row,
                "ticker": ticker,
                "rules": rules,
                "text": str(event_texts.get(event_id) or "").strip(),
            }
        )

    nli_score_map_by_event: dict[str, dict[str, float]] = {}
    nli_events_requested = 0
    nli_events_skipped = 0
    nli_pipeline_calls = 0
    nli_batch_groups = 0
    if bool(nli_enabled):
        nli_requests: list[dict[str, Any]] = []
        for payload in event_payloads:
            event_id = str(payload.get("event_id") or "").strip()
            text = str(payload.get("text") or "").strip()
            rules = payload.get("rules")
            if not event_id or not isinstance(rules, tuple):
                continue
            if not text:
                nli_events_skipped += 1
                nli_score_map_by_event[event_id] = {}
                continue
            nli_text = text[: max(int(nli_text_max_chars), 0)] if int(nli_text_max_chars) > 0 else text
            if not nli_text:
                nli_events_skipped += 1
                nli_score_map_by_event[event_id] = {}
                continue
            raw_scores = _build_pre_scores(text, rules)
            nli_input_rules, should_run_nli = _select_nli_input_rules(raw_scores, top_k=max(int(top_k), 1))
            if should_run_nli and nli_input_rules:
                nli_requests.append({"event_id": event_id, "text": nli_text, "rules": nli_input_rules})
                continue
            nli_events_skipped += 1
            nli_score_map_by_event[event_id] = {}
        nli_events_requested = len(nli_requests)
        batch_scores, nli_pipeline_calls, nli_batch_groups = _batch_nli_scores_by_candidates(
            requests=nli_requests,
            model_name=nli_model_name,
            batch_size=max(int(nli_batch_size), 1),
            nli_device=str(nli_device or "auto").strip(),
        )
        nli_score_map_by_event.update(batch_scores)

    factor_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    unknown_primary = 0
    scored = 0
    now = datetime.utcnow().replace(microsecond=0)

    for payload in event_payloads:
        event_id = str(payload.get("event_id") or "").strip()
        row = payload.get("row") if isinstance(payload.get("row"), dict) else {}
        ticker = str(payload.get("ticker") or "").strip().upper()
        rules = payload.get("rules")
        text = str(payload.get("text") or "").strip()
        if not event_id or not ticker or not isinstance(rules, tuple):
            continue
        scored_rows, summary = _autolabel_event(
            text=text,
            rules=rules,
            min_confidence=float(min_confidence),
            top_k=max(int(top_k), 1),
            nli_model_name=nli_model_name,
            nli_enabled=bool(nli_enabled),
            nli_score_map=nli_score_map_by_event.get(event_id, {}),
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
        nli_events_requested=nli_events_requested,
        nli_events_skipped=nli_events_skipped,
        nli_pipeline_calls=nli_pipeline_calls,
        nli_batch_groups=nli_batch_groups,
    )
