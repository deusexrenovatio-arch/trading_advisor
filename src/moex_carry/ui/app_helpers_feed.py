from __future__ import annotations

import json
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from moex_carry.news.taxonomy import impact_to_severity
from moex_carry.storage.repositories import (
    load_news_entity_links,
    load_news_event_items,
    load_news_events,
    load_news_impact_scores,
    load_news_item_tags,
    load_news_items,
    load_news_items_by_ids,
    load_news_labels,
    load_news_llm_runs,
    load_news_signal_links,
    load_primary_news_scores,
)
from moex_carry.ui.app_helpers_base import _contains_nan, _normalize_datetime, _stable_id

def _parse_daily_time(raw: str | None) -> dt_time | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            return dt_time(parsed.hour, parsed.minute, parsed.second)
        except ValueError:
            continue
    return None


def _resolve_tz(raw: str | None, fallback: str) -> timezone:
    name = raw or fallback or "UTC"
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def _next_daily_run(now_utc: datetime, target: dt_time, tzinfo: timezone) -> datetime:
    local_now = now_utc.astimezone(tzinfo)
    target_local = local_now.replace(
        hour=target.hour,
        minute=target.minute,
        second=target.second,
        microsecond=0,
    )
    if target_local <= local_now:
        target_local = target_local + timedelta(days=1)
    return target_local.astimezone(timezone.utc)


def _parse_date_bound(raw: str, bound: str) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        if "T" not in raw and " " not in raw:
            day = datetime.fromisoformat(raw).date()
            if bound == "end":
                return datetime.combine(day, datetime.max.time())
            return datetime.combine(day, datetime.min.time())
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _normalize_datetime(parsed)


def _parse_iso_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _normalize_datetime(parsed)


def _isoformat_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def _load_news_bundle(
    session,
    *,
    from_ts: datetime | None,
    to_ts: datetime | None,
    limit: int,
    preferred_models: list[str],
) -> dict[str, object]:
    item_rows = load_news_items(
        session,
        limit=limit,
        published_from=_isoformat_utc(from_ts),
        published_to=_isoformat_utc(to_ts),
    )
    news_ids = [str(item.get("news_id") or "").strip() for item in item_rows if item.get("news_id")]
    entity_links = load_news_entity_links(session, news_ids=news_ids, limit=max(limit * 10, 1000))
    tag_rows = load_news_item_tags(session, news_ids=news_ids, limit=max(limit * 10, 1000))
    score_rows = load_news_impact_scores(session, news_ids=news_ids, limit=max(limit * 10, 1000))
    primary_scores = load_primary_news_scores(
        session,
        news_ids=news_ids,
        preferred_models=preferred_models,
    )
    signal_links = load_news_signal_links(session, news_ids=news_ids, limit=max(limit * 10, 1000))

    entity_by_news: dict[str, list[dict[str, object]]] = {}
    tickers_by_news: dict[str, set[str]] = {}
    for row in entity_links:
        news_id = str(row.get("news_id") or "").strip()
        if not news_id:
            continue
        entity_by_news.setdefault(news_id, []).append(row)
        ticker_value = str(row.get("ticker") or row.get("entity_id") or "").strip().upper()
        if ticker_value:
            tickers_by_news.setdefault(news_id, set()).add(ticker_value)

    tags_by_news: dict[str, list[str]] = {}
    for row in tag_rows:
        news_id = str(row.get("news_id") or "").strip()
        tag_code = str(row.get("tag_code") or "").strip()
        if not news_id or not tag_code:
            continue
        tags_by_news.setdefault(news_id, []).append(tag_code)

    model_scores_by_news: dict[str, list[dict[str, object]]] = {}
    for row in score_rows:
        news_id = str(row.get("news_id") or "").strip()
        if not news_id:
            continue
        model_scores_by_news.setdefault(news_id, []).append(row)

    signal_links_by_news: dict[str, list[dict[str, object]]] = {}
    for row in signal_links:
        news_id = str(row.get("news_id") or "").strip()
        if not news_id:
            continue
        signal_links_by_news.setdefault(news_id, []).append(row)

    return {
        "items": item_rows,
        "entity_by_news": entity_by_news,
        "tickers_by_news": tickers_by_news,
        "tags_by_news": tags_by_news,
        "model_scores_by_news": model_scores_by_news,
        "primary_scores": primary_scores,
        "signal_links_by_news": signal_links_by_news,
    }


def _build_news_feed_events(
    *,
    bundle: dict[str, object],
    severity_filter: str | None,
    ticker_filter: str | None,
    entity_filter: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
) -> list[dict[str, object]]:
    items = bundle.get("items")
    if not isinstance(items, list):
        return []

    entity_by_news = bundle.get("entity_by_news") if isinstance(bundle.get("entity_by_news"), dict) else {}
    tickers_by_news = bundle.get("tickers_by_news") if isinstance(bundle.get("tickers_by_news"), dict) else {}
    tags_by_news = bundle.get("tags_by_news") if isinstance(bundle.get("tags_by_news"), dict) else {}
    model_scores_by_news = (
        bundle.get("model_scores_by_news") if isinstance(bundle.get("model_scores_by_news"), dict) else {}
    )
    primary_scores = bundle.get("primary_scores") if isinstance(bundle.get("primary_scores"), dict) else {}
    signal_links_by_news = (
        bundle.get("signal_links_by_news") if isinstance(bundle.get("signal_links_by_news"), dict) else {}
    )

    events: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        news_id = str(item.get("news_id") or "").strip()
        if not news_id:
            continue
        published_at_raw = str(item.get("published_at") or "").strip()
        published_at = _parse_iso_datetime(published_at_raw)
        if published_at is None:
            continue
        if from_ts is not None and published_at < from_ts:
            continue
        if to_ts is not None and published_at > to_ts:
            continue

        primary_score = primary_scores.get(news_id) if isinstance(primary_scores, dict) else None
        impact_score = float(primary_score.get("impact_score") or 0.0) if isinstance(primary_score, dict) else 0.0
        severity = impact_to_severity(impact_score)
        if severity_filter and severity != severity_filter:
            continue

        row_tickers_raw = tickers_by_news.get(news_id, set())
        row_tickers = (
            row_tickers_raw
            if isinstance(row_tickers_raw, set)
            else {str(value).strip().upper() for value in row_tickers_raw if str(value).strip()}
        )
        if ticker_filter and ticker_filter not in row_tickers:
            continue

        entity_rows = entity_by_news.get(news_id, [])
        if entity_filter:
            matched_entity = any(
                str(entity.get("entity_id") or "").strip() == entity_filter
                for entity in entity_rows
                if isinstance(entity, dict)
            )
            if not matched_entity:
                continue

        title = str(item.get("title") or "").strip() or "news"
        summary = str(item.get("content") or "").strip()
        if summary:
            summary = summary[:300]
        else:
            direction = str((primary_score or {}).get("direction") or "neutral")
            summary = f"model:{direction}"
        event_id = _stable_id("news", news_id, published_at_raw, severity, title, summary, length=20)
        signal_links = signal_links_by_news.get(news_id, [])
        signal_refs = [
            {
                "signal_id": link.get("signal_id"),
                "decision_id": link.get("decision_id"),
                "link_type": link.get("link_type"),
                "gate_action": link.get("gate_action"),
            }
            for link in signal_links
            if isinstance(link, dict)
        ]
        decision_id = next(
            (
                str(link.get("decision_id") or "").strip()
                for link in signal_links
                if isinstance(link, dict) and str(link.get("decision_id") or "").strip()
            ),
            None,
        )

        events.append(
            {
                "news_event_id": event_id,
                "news_id": news_id,
                "published_at": published_at_raw,
                "ingested_at": item.get("ingested_at"),
                "source": item.get("source"),
                "language": item.get("language"),
                "url": item.get("url"),
                "severity": severity,
                "headline": title,
                "summary": summary,
                "headline_count": 1,
                "decision_ref": {"decision_id": decision_id},
                "entity_links": [
                    {
                        "entity_type": entity.get("entity_type"),
                        "entity_id": entity.get("entity_id"),
                        "ticker": entity.get("ticker"),
                    }
                    for entity in entity_rows
                    if isinstance(entity, dict)
                ],
                "tags": tags_by_news.get(news_id, []),
                "model_scores": model_scores_by_news.get(news_id, []),
                "signal_refs": signal_refs,
            }
        )
    events.sort(key=lambda row: str(row.get("published_at") or ""), reverse=True)
    return events


def _select_primary_model_score(
    model_scores: list[dict[str, object]],
    preferred_models: list[str],
) -> dict[str, object] | None:
    for model_name in preferred_models:
        selected = next(
            (
                score
                for score in model_scores
                if isinstance(score, dict) and str(score.get("model_id") or "").strip() == model_name
            ),
            None,
        )
        if selected is not None:
            return selected
    return next((score for score in model_scores if isinstance(score, dict)), None)


def _build_news_feed_events_from_event_layer(
    session,
    *,
    severity_filter: str | None,
    ticker_filter: str | None,
    entity_filter: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    limit: int,
    preferred_models: list[str],
) -> list[dict[str, object]]:
    event_rows = load_news_events(
        session,
        event_status=None,
        published_from=_isoformat_utc(from_ts),
        published_to=_isoformat_utc(to_ts),
        limit=max(limit, 200),
    )
    if not event_rows:
        return []

    event_ids = [str(row.get("event_id") or "").strip() for row in event_rows if row.get("event_id")]
    if not event_ids:
        return []
    event_item_rows = load_news_event_items(
        session,
        event_ids=event_ids,
        limit=max(len(event_ids) * 30, 1000),
    )
    event_to_news_ids: dict[str, list[str]] = {}
    for row in event_item_rows:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id") or "").strip()
        news_id = str(row.get("news_id") or "").strip()
        if not event_id or not news_id:
            continue
        event_to_news_ids.setdefault(event_id, []).append(news_id)

    news_ids = sorted(
        {
            news_id
            for values in event_to_news_ids.values()
            for news_id in values
            if isinstance(news_id, str) and news_id
        }
    )
    news_by_id: dict[str, dict[str, object]] = {}
    for row in load_news_items_by_ids(session, news_ids):
        if not isinstance(row, dict):
            continue
        news_id = str(row.get("news_id") or "").strip()
        if news_id:
            news_by_id[news_id] = row

    entity_links = load_news_entity_links(session, news_ids=news_ids, limit=max(len(news_ids) * 10, 1000))
    tags = load_news_item_tags(session, news_ids=news_ids, limit=max(len(news_ids) * 10, 1000))
    signal_links = load_news_signal_links(session, event_ids=event_ids, limit=max(len(event_ids) * 10, 1000))
    score_rows = load_news_impact_scores(
        session,
        target_level="event",
        target_ids=event_ids,
        limit=max(len(event_ids) * 10, 1000),
    )
    labels = load_news_labels(session, target_level="event", target_ids=event_ids, limit=max(len(event_ids) * 5, 500))
    llm_rows = load_news_llm_runs(session, target_level="event", limit=max(len(event_ids) * 10, 1000))

    entities_by_news: dict[str, list[dict[str, object]]] = {}
    for row in entity_links:
        news_id = str(row.get("news_id") or "").strip()
        if not news_id:
            continue
        entities_by_news.setdefault(news_id, []).append(row)

    tags_by_news: dict[str, list[str]] = {}
    for row in tags:
        news_id = str(row.get("news_id") or "").strip()
        tag_code = str(row.get("tag_code") or "").strip()
        if not news_id or not tag_code:
            continue
        tags_by_news.setdefault(news_id, []).append(tag_code)

    scores_by_event: dict[str, list[dict[str, object]]] = {}
    for row in score_rows:
        event_id = str(row.get("target_id") or "").strip()
        if not event_id:
            continue
        scores_by_event.setdefault(event_id, []).append(row)

    signal_refs_by_event: dict[str, list[dict[str, object]]] = {}
    for row in signal_links:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            continue
        signal_refs_by_event.setdefault(event_id, []).append(
            {
                "signal_id": row.get("signal_id"),
                "decision_id": row.get("decision_id"),
                "link_type": row.get("link_type"),
                "gate_action": row.get("gate_action"),
            }
        )

    label_direction_by_event: dict[str, str] = {}
    for row in labels:
        event_id = str(row.get("target_id") or "").strip()
        direction = str(row.get("direction") or "").strip().lower()
        if not event_id or direction not in {"positive", "negative", "neutral", "uncertain"}:
            continue
        label_direction_by_event.setdefault(event_id, direction)
    llm_status_by_event: dict[str, str] = {}
    for row in llm_rows:
        event_id = str(row.get("target_id") or "").strip()
        if not event_id or event_id not in event_ids:
            continue
        status = str(row.get("status") or "").strip().lower()
        if not status:
            continue
        llm_status_by_event.setdefault(event_id, status)

    events: list[dict[str, object]] = []
    for event_row in event_rows:
        event_id = str(event_row.get("event_id") or "").strip()
        if not event_id:
            continue
        linked_news_ids = event_to_news_ids.get(event_id, [])
        first_news = next((news_by_id.get(news_id) for news_id in linked_news_ids if news_by_id.get(news_id)), None)
        event_entities: list[dict[str, object]] = []
        seen_entity_keys: set[str] = set()
        event_tags: set[str] = set()
        event_tickers: set[str] = set()
        for news_id in linked_news_ids:
            for entity in entities_by_news.get(news_id, []):
                if not isinstance(entity, dict):
                    continue
                entity_type = str(entity.get("entity_type") or "").strip()
                entity_id_value = str(entity.get("entity_id") or "").strip()
                ticker = str(entity.get("ticker") or entity_id_value).strip().upper()
                if ticker:
                    event_tickers.add(ticker)
                entity_key = f"{entity_type}|{entity_id_value}|{ticker}"
                if entity_key in seen_entity_keys:
                    continue
                seen_entity_keys.add(entity_key)
                event_entities.append(
                    {
                        "entity_type": entity_type or "instrument",
                        "entity_id": entity_id_value or ticker,
                        "ticker": ticker or None,
                    }
                )
            for tag_code in tags_by_news.get(news_id, []):
                if tag_code:
                    event_tags.add(str(tag_code))

        if ticker_filter and ticker_filter not in event_tickers:
            continue
        if entity_filter:
            if not any(str(entity.get("entity_id") or "").strip() == entity_filter for entity in event_entities):
                continue

        model_scores = scores_by_event.get(event_id, [])
        primary_score = _select_primary_model_score(model_scores, preferred_models)
        impact_score = float(primary_score.get("impact_score") or 0.0) if isinstance(primary_score, dict) else 0.0
        severity = impact_to_severity(impact_score)
        if severity_filter and severity != severity_filter:
            continue

        decision_id = next(
            (
                str(link.get("decision_id") or "").strip()
                for link in signal_refs_by_event.get(event_id, [])
                if isinstance(link, dict) and str(link.get("decision_id") or "").strip()
            ),
            None,
        )
        headline = str(event_row.get("canonical_summary") or "").strip()
        if not headline:
            headline = str((first_news or {}).get("title") or event_id).strip() or event_id
        summary = str(event_row.get("canonical_mechanism") or "").strip()
        if not summary:
            raw_summary = str((first_news or {}).get("content") or "").strip()
            summary = raw_summary[:300] if raw_summary else f"event:{event_id}"

        result_row = {
            "news_event_id": event_id,
            "news_id": str(linked_news_ids[0]) if linked_news_ids else event_id,
            "published_at": event_row.get("event_first_published_at_utc"),
            "ingested_at": event_row.get("event_first_ingested_at_utc"),
            "source": (first_news or {}).get("source") or "event_cluster",
            "language": (first_news or {}).get("language"),
            "url": (first_news or {}).get("url"),
            "severity": severity,
            "headline": headline,
            "summary": summary,
            "headline_count": len(linked_news_ids),
            "decision_ref": {"decision_id": decision_id},
            "entity_links": event_entities,
            "tags": sorted(event_tags),
            "model_scores": model_scores,
            "signal_refs": signal_refs_by_event.get(event_id, []),
            "event_status": event_row.get("event_status"),
            "cluster_version": event_row.get("cluster_version"),
            "label_direction": label_direction_by_event.get(event_id),
            "llm_status": llm_status_by_event.get(event_id),
        }
        events.append(result_row)

    events.sort(key=lambda row: str(row.get("published_at") or ""), reverse=True)
    if limit > 0:
        return events[:limit]
    return events


def _future_scale_from_raw(path, secid: str) -> float:
    if not path.exists():
        return 1.0
    try:
        futures_df = pd.read_csv(path)
    except Exception:
        return 1.0
    if futures_df.empty or "SECID" not in futures_df.columns:
        return 1.0
    rows = futures_df[futures_df["SECID"].astype(str) == str(secid)]
    if rows.empty:
        return 1.0
    row = rows.iloc[0]
    lot = pd.to_numeric(row.get("LOTVOLUME"), errors="coerce")
    multiplier = pd.to_numeric(row.get("MULTIPLIER"), errors="coerce")
    lot_value = float(lot) if pd.notna(lot) and float(lot) > 0 else 1.0
    mult_value = float(multiplier) if pd.notna(multiplier) and float(multiplier) > 0 else 1.0
    return lot_value * mult_value


def _read_cache(path, ttl_minutes: int) -> list[dict[str, object]] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    generated_at = payload.get("generated_at")
    if not generated_at:
        return None
    try:
        generated_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if datetime.now(timezone.utc) - generated_dt > timedelta(minutes=ttl_minutes):
        return None
    series = payload.get("series")
    if not isinstance(series, list):
        return None
    if series and isinstance(series[0], dict):
        if not {
            "zscore",
            "z_entry",
            "z_exit",
            "entry_flag",
            "exit_flag",
            "entry_cycle",
            "exit_cycle",
            "cycle_return_pct",
        }.issubset(series[0].keys()):
            return None
    if _contains_nan(series):
        return None
    return series


def _write_cache(path, series: list[dict[str, object]]) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "series": series,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def _apply_query_filters(df: pd.DataFrame, args) -> pd.DataFrame:
    if df.empty:
        return df
    filters = {
        "strategy_type": args.get("strategy_type"),
        "primary_instrument": args.get("primary_instrument"),
        "risk_state": args.get("risk_state"),
        "news_severity": args.get("news_severity"),
    }
    for column, value in filters.items():
        if value:
            df = df[df[column] == value]
    created_from = args.get("created_from")
    created_to = args.get("created_to")
    if created_from or created_to:
        df = df.copy()
        df["created_at_parsed"] = pd.to_datetime(df.get("created_at"), errors="coerce")
        if created_from:
            df = df[df["created_at_parsed"] >= pd.to_datetime(created_from, errors="coerce")]
        if created_to:
            df = df[df["created_at_parsed"] <= pd.to_datetime(created_to, errors="coerce")]
        df = df.drop(columns=["created_at_parsed"])
    return df


DECISION_STYLE = [
    {"if": {"column_id": "decision_id"}, "fontFamily": "monospace"},
    {"if": {"column_id": "action", "filter_query": "{action} = 'approve'"}, "color": "#116329"},
    {"if": {"column_id": "action", "filter_query": "{action} = 'reject'"}, "color": "#9b1c1c"},
    {"if": {"column_id": "risk_state", "filter_query": "{risk_state} = 'green'"}, "color": "#116329"},
    {"if": {"column_id": "risk_state", "filter_query": "{risk_state} = 'yellow'"}, "color": "#a16207"},
    {"if": {"column_id": "risk_state", "filter_query": "{risk_state} = 'red'"}, "color": "#9b1c1c"},
    {"if": {"column_id": "news_severity", "filter_query": "{news_severity} = 'high'"}, "color": "#9b1c1c"},
    {"if": {"column_id": "news_severity", "filter_query": "{news_severity} = 'critical'"}, "color": "#7f1d1d"},
]

