from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from moex_carry.config import load_settings
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_news_entity_links,
    load_news_event_items,
    load_news_events,
    load_news_items_by_ids,
    upsert_news_gold_labels,
    upsert_news_labels,
    upsert_news_unmatched_gold,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class EventCandidate:
    event_id: str
    event_ts: datetime
    text: str
    tokens: set[str]


def _parse_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


def _to_iso_z(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _tokens(text: str) -> set[str]:
    lowered = str(text or "").lower()
    return set(_TOKEN_RE.findall(lowered))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    inter = len(left & right)
    union = len(left | right)
    if union <= 0:
        return 0.0
    return float(inter) / float(union)


def _build_ng_event_index(session) -> tuple[list[EventCandidate], list[datetime]]:
    ng_links = load_news_entity_links(session, ticker="NG_US", limit=0)
    ng_news_ids = {str(row.get("news_id") or "").strip() for row in ng_links if row.get("news_id")}
    ng_news_ids.discard("")
    if not ng_news_ids:
        return [], []

    event_items = load_news_event_items(session, news_ids=sorted(ng_news_ids), limit=0)
    event_to_news: dict[str, set[str]] = defaultdict(set)
    for row in event_items:
        event_id = str(row.get("event_id") or "").strip()
        news_id = str(row.get("news_id") or "").strip()
        if event_id and news_id:
            event_to_news[event_id].add(news_id)

    events = load_news_events(session, event_ids=sorted(event_to_news.keys()), limit=0) if event_to_news else []
    all_news_ids = sorted({nid for ids in event_to_news.values() for nid in ids})
    news_rows = load_news_items_by_ids(session, all_news_ids) if all_news_ids else []
    news_title_by_id = {str(row.get("news_id") or ""): str(row.get("title") or "") for row in news_rows}

    candidates: list[EventCandidate] = []
    for event in events:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            continue
        event_ts = _parse_dt(event.get("event_first_published_at_utc"))
        if event_ts is None:
            continue
        parts: list[str] = []
        summary = str(event.get("canonical_summary") or "").strip()
        if summary:
            parts.append(summary)
        related_ids = sorted(event_to_news.get(event_id, set()))
        for news_id in related_ids[:3]:
            title = news_title_by_id.get(news_id, "")
            if title:
                parts.append(title)
        blob = " | ".join(parts)
        tok = _tokens(blob)
        candidates.append(EventCandidate(event_id=event_id, event_ts=event_ts, text=blob, tokens=tok))

    # Also include canonical scheduled anchors even when they currently have no linked news.
    anchor_events = load_news_events(limit=0, session=session)
    for event in anchor_events:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            continue
        if any(item.event_id == event_id for item in candidates):
            continue
        mechanism = str(event.get("canonical_mechanism") or "").lower()
        if "ticker=ng_us" not in mechanism:
            continue
        if "scheduled_anchor" not in mechanism and "event_family=ng_storage_eia" not in mechanism:
            continue
        event_ts = _parse_dt(event.get("event_first_published_at_utc"))
        if event_ts is None:
            continue
        summary = str(event.get("canonical_summary") or "").strip()
        if not summary:
            summary = "EIA weekly natural gas storage report"
        candidates.append(EventCandidate(event_id=event_id, event_ts=event_ts, text=summary, tokens=_tokens(summary)))

    candidates.sort(key=lambda item: item.event_ts)
    timestamps = [item.event_ts for item in candidates]
    return candidates, timestamps


def _match_event(
    *,
    candidates: list[EventCandidate],
    timestamps: list[datetime],
    row_dt: datetime,
    row_tokens: set[str],
    window_hours: int,
    min_score: float,
) -> tuple[str | None, float]:
    if not candidates:
        return None, 0.0
    left = row_dt - timedelta(hours=max(window_hours, 1))
    right = row_dt + timedelta(hours=max(window_hours, 1))
    start = bisect.bisect_left(timestamps, left)
    end = bisect.bisect_right(timestamps, right)
    if start >= end:
        return None, 0.0

    best_id = None
    best_score = 0.0
    for item in candidates[start:end]:
        delta_h = abs((item.event_ts - row_dt).total_seconds()) / 3600.0
        time_score = max(0.0, 1.0 - (delta_h / float(max(window_hours, 1))))
        text_score = _jaccard(row_tokens, item.tokens)
        bonus = 0.0
        if {"henry", "hub"}.issubset(row_tokens) and {"henry", "hub"}.issubset(item.tokens):
            bonus += 0.15
        if {"natural", "gas"}.issubset(row_tokens) and {"natural", "gas"}.issubset(item.tokens):
            bonus += 0.05
        score = 0.55 * time_score + 0.45 * text_score + bonus
        if score > best_score:
            best_score = score
            best_id = item.event_id

    if best_id is None or best_score < float(min_score):
        return None, best_score
    return best_id, best_score


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            payload = json.loads(raw)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _build_event_label(row: dict[str, Any], event_id: str, match_score: float) -> dict[str, Any]:
    confidence = float(row.get("confidence") or 0.0)
    provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
    move_pct = provenance.get("move_pct")
    try:
        magnitude = min(max(float(move_pct) * 5.0, 0.0), 1.0) if move_pct is not None else confidence
    except Exception:
        magnitude = confidence

    commodity = row.get("commodity") if isinstance(row.get("commodity"), list) else ["NG_US"]
    news_type = row.get("news_type") if isinstance(row.get("news_type"), list) else ["MARKET"]
    direction = str(row.get("label_direction") or "neutral").strip().lower()
    if direction not in {"positive", "negative", "neutral", "uncertain"}:
        direction = "neutral"

    return {
        "target_level": "event",
        "target_id": event_id,
        "commodity_json": commodity,
        "market_scope": "futures",
        "instrument_candidates_json": [{"symbol": "NG=F", "exchange": "NYMEX"}],
        "relevance": min(max(confidence, 0.0), 1.0),
        "news_type_json": news_type,
        "direction": direction,
        "magnitude": magnitude,
        "lag_bucket": "short",
        "confidence": min(max(confidence, 0.0), 1.0),
        "uncertainty_type": "none",
        "geo_scope": "US",
        "evidence_json": {
            "gold_id": row.get("gold_id"),
            "source_id": row.get("source_id"),
            "text": row.get("text"),
            "match_score": round(float(match_score), 6),
            "synthetic_event": False,
            "source_url": row.get("source_url"),
        },
        "label_source": "external_gold",
        "label_version": "gold-v1",
        "model_version": str(row.get("source_id") or "external_gold"),
        "prompt_version": "seed-import-v1",
    }


def _build_article_label(row: dict[str, Any]) -> dict[str, Any]:
    confidence = float(row.get("confidence") or 0.0)
    direction = str(row.get("label_direction") or "neutral").strip().lower()
    if direction not in {"positive", "negative", "neutral", "uncertain"}:
        direction = "neutral"
    commodity = row.get("commodity") if isinstance(row.get("commodity"), list) else []
    news_type = row.get("news_type") if isinstance(row.get("news_type"), list) else ["MARKET"]
    target_id = f"gold:{str(row.get('gold_id') or '').strip()}"
    return {
        "target_level": "article",
        "target_id": target_id,
        "commodity_json": commodity,
        "market_scope": "futures",
        "instrument_candidates_json": [],
        "relevance": min(max(confidence, 0.0), 1.0),
        "news_type_json": news_type,
        "direction": direction,
        "magnitude": confidence,
        "lag_bucket": "short",
        "confidence": min(max(confidence, 0.0), 1.0),
        "uncertainty_type": "none",
        "geo_scope": "",
        "evidence_json": {
            "gold_id": row.get("gold_id"),
            "source_id": row.get("source_id"),
            "text": row.get("text"),
            "source_url": row.get("source_url"),
        },
        "label_source": "external_gold",
        "label_version": "gold-v1",
        "model_version": str(row.get("source_id") or "external_gold"),
        "prompt_version": "seed-import-v1",
    }


def _build_gold_label(
    row: dict[str, Any],
    *,
    event_id: str,
    match_score: float,
) -> dict[str, Any]:
    source_id = str(row.get("source_id") or "external_gold").strip() or "external_gold"
    direction = str(row.get("label_direction") or "neutral").strip().lower()
    if direction not in {"positive", "negative", "neutral", "uncertain"}:
        direction = "neutral"
    confidence = float(row.get("confidence") or 0.0)
    provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
    event_family = "NG_STORAGE_EIA" if source_id == "eia_ng_archive" else "MARKET"
    return {
        "target_type": "event",
        "target_id": event_id,
        "event_family": event_family,
        "factors_json": {
            "INVENTORY": "up" if direction == "negative" else ("down" if direction == "positive" else "neutral"),
            "DEMAND": "neutral",
            "SUPPLY": "neutral",
        },
        "phase": "resolved",
        "direction_label": direction,
        "quality": "gold",
        "source": source_id,
        "label_schema_version": "v1",
        "confidence": min(max(confidence, 0.0), 1.0),
        "meta_json": {
            "gold_id": row.get("gold_id"),
            "source_url": row.get("source_url"),
            "match_score": round(float(match_score), 6),
            "synthetic_event": False,
            "provenance": provenance,
        },
    }


def _build_unmatched_gold_row(
    row: dict[str, Any],
    *,
    match_score: float,
    reason: str,
    row_dt: datetime | None,
) -> dict[str, Any]:
    source = str(row.get("source_id") or "external_gold").strip() or "external_gold"
    gold_id = str(row.get("gold_id") or "").strip()
    if not gold_id:
        text = str(row.get("text") or "").strip()
        gold_id = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    confidence = float(row.get("confidence") or 0.0)
    commodity = row.get("commodity") if isinstance(row.get("commodity"), list) else ["NG_US"]
    return {
        "source": source,
        "gold_id": gold_id,
        "published_at_utc": _to_iso_z(row_dt or datetime.now(timezone.utc).replace(tzinfo=None)),
        "commodity_json": commodity,
        "event_family": "NG_STORAGE_EIA" if source == "eia_ng_archive" else "MARKET",
        "confidence": min(max(confidence, 0.0), 1.0),
        "match_score": min(max(float(match_score), 0.0), 1.0),
        "reason": reason,
        "payload_json": {
            "text": row.get("text"),
            "source_url": row.get("source_url"),
            "provenance": row.get("provenance"),
            "label_direction": row.get("label_direction"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import external gold labels into news_labels.")
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    parser.add_argument("--seed-path", type=str, default="data/external/news_gold/news_gold_seed.jsonl")
    parser.add_argument("--window-hours", type=int, default=72)
    parser.add_argument("--min-match-score", type=float, default=0.28)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-path", type=str, default="data/output/news_gold_import_report.json")
    args = parser.parse_args()

    seed_path = Path(args.seed_path)
    if not seed_path.exists():
        raise FileNotFoundError(f"seed file not found: {seed_path}")

    settings = load_settings(args.config)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    rows = _read_jsonl(seed_path)
    if args.max_rows and args.max_rows > 0:
        rows = rows[: args.max_rows]

    event_labels: list[dict[str, Any]] = []
    article_labels: list[dict[str, Any]] = []
    gold_labels: list[dict[str, Any]] = []
    unmatched_rows: list[dict[str, Any]] = []

    eia_rows = 0
    eia_matched = 0
    eia_unmatched = 0
    match_scores: list[float] = []

    with session_factory() as session:
        candidates, timestamps = _build_ng_event_index(session)

        for row in rows:
            source_id = str(row.get("source_id") or "").strip()
            text = str(row.get("text") or "").strip()
            if not text:
                continue

            if source_id == "eia_ng_archive":
                eia_rows += 1
                row_dt = _parse_dt(row.get("published_at_utc"))
                if row_dt is None:
                    row_dt = datetime.now(timezone.utc).replace(tzinfo=None)
                event_id, score = _match_event(
                    candidates=candidates,
                    timestamps=timestamps,
                    row_dt=row_dt,
                    row_tokens=_tokens(text),
                    window_hours=max(int(args.window_hours), 1),
                    min_score=float(args.min_match_score),
                )
                match_scores.append(float(score))
                if event_id is None:
                    unmatched_rows.append(
                        _build_unmatched_gold_row(
                            row,
                            match_score=score,
                            reason="no_event_match_above_threshold",
                            row_dt=row_dt,
                        )
                    )
                    eia_unmatched += 1
                else:
                    event_labels.append(_build_event_label(row, event_id=event_id, match_score=score))
                    gold_labels.append(_build_gold_label(row, event_id=event_id, match_score=score))
                    eia_matched += 1
                continue

            article_labels.append(_build_article_label(row))

        stored_event_labels = 0
        stored_article_labels = 0
        stored_gold_labels = 0
        stored_unmatched = 0
        if not args.dry_run:
            if event_labels:
                stored_event_labels = upsert_news_labels(session, event_labels)
            if article_labels:
                stored_article_labels = upsert_news_labels(session, article_labels)
            if gold_labels:
                stored_gold_labels = upsert_news_gold_labels(session, gold_labels)
            if unmatched_rows:
                stored_unmatched = upsert_news_unmatched_gold(session, unmatched_rows)

    report = {
        "seed_path": str(seed_path),
        "total_seed_rows": len(rows),
        "dry_run": bool(args.dry_run),
        "event_index_size": len(candidates) if 'candidates' in locals() else 0,
        "import": {
            "event_labels_prepared": len(event_labels),
            "article_labels_prepared": len(article_labels),
            "gold_labels_prepared": len(gold_labels),
            "event_labels_stored": int(stored_event_labels),
            "article_labels_stored": int(stored_article_labels),
            "gold_labels_stored": int(stored_gold_labels),
            "unmatched_gold_prepared": len(unmatched_rows),
            "unmatched_gold_stored": int(stored_unmatched),
        },
        "eia_match": {
            "rows": eia_rows,
            "matched_to_existing_events": eia_matched,
            "unmatched_rows": eia_unmatched,
            "min_score": min(match_scores) if match_scores else None,
            "avg_score": (sum(match_scores) / len(match_scores)) if match_scores else None,
            "max_score": max(match_scores) if match_scores else None,
            "threshold": float(args.min_match_score),
            "window_hours": int(args.window_hours),
        },
    }

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
