from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from moex_carry.news.anchors_sources import (
    EpisodicAnchorRecord,
    _fetch_bsee_episodic_records,
    _fetch_fred_release_records,
    _fetch_nhc_episodic_records,
    _fetch_nws_alert_episodic_records,
    _fetch_panama_episodic_records,
    _fetch_suez_episodic_records,
    _fetch_ukmto_episodic_records,
)
from moex_carry.storage.repositories import (
    load_news_entity_links,
    load_news_event_items,
    load_news_events,
    upsert_news_event_items,
    upsert_news_event_links,
    upsert_news_event_updates,
    upsert_news_events,
    upsert_news_labels,
)


@dataclass(frozen=True)
class AnchorSeedReport:
    period_from: str
    period_to: str
    events_prepared: int
    labels_prepared: int
    events_stored: int
    labels_stored: int


@dataclass(frozen=True)
class AnchorLinkReport:
    linked_news: int
    event_item_links: int
    event_cross_links: int
    unmatched_news: int
    window_minutes: int


@dataclass(frozen=True)
class EpisodicAnchorSeedReport:
    sources_requested: list[str]
    sources_completed: list[str]
    events_prepared: int
    labels_prepared: int
    updates_prepared: int
    events_stored: int
    labels_stored: int
    updates_stored: int
    errors: list[str]


@dataclass(frozen=True)
class ScheduledAnchorSpec:
    family: str
    ticker: str
    source: str
    weekday: int
    release_time_utc: time
    summary: str
    mechanism: str


_ANCHOR_SPECS: tuple[ScheduledAnchorSpec, ...] = (
    ScheduledAnchorSpec(
        family="NG_STORAGE_EIA",
        ticker="NG_US",
        source="EIA",
        weekday=3,  # Thu
        release_time_utc=time(hour=15, minute=30),
        summary="EIA weekly natural gas storage report",
        mechanism="scheduled_anchor|anchor_source=EIA|event_family=NG_STORAGE_EIA|ticker=NG_US",
    ),
    ScheduledAnchorSpec(
        family="OIL_INVENTORIES_EIA",
        ticker="BRN",
        source="EIA",
        weekday=2,  # Wed
        release_time_utc=time(hour=15, minute=30),
        summary="EIA weekly petroleum status report",
        mechanism="scheduled_anchor|anchor_source=EIA|event_family=OIL_INVENTORIES_EIA|ticker=BRN",
    ),
)


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _to_iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def _safe_text(value: object, *, limit: int = 240) -> str:
    text = str(value or "").strip()
    if limit > 0 and len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _stable_hash(*parts: object, length: int = 20) -> str:
    raw = "|".join(str(item or "").strip() for item in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[: max(int(length), 8)]


def _iter_weekly_points(
    *,
    period_from: datetime,
    period_to: datetime,
    weekday: int,
    release_time_utc: time,
) -> list[datetime]:
    start_date = period_from.date()
    end_date = period_to.date()
    delta_days = (weekday - start_date.weekday()) % 7
    cursor = start_date + timedelta(days=delta_days)
    points: list[datetime] = []
    while cursor <= end_date:
        points.append(datetime.combine(cursor, release_time_utc))
        cursor += timedelta(days=7)
    return points


def _anchor_event_id(spec: ScheduledAnchorSpec, ts: datetime, cluster_version: str) -> str:
    family = spec.family.lower().replace("_", "-")
    suffix = ts.strftime("%Y%m%dT%H%MZ")
    return f"evt-{cluster_version}-{family}-{suffix}"


def _extract_anchor_ticker(event_row: dict[str, object]) -> str | None:
    mechanism = str(event_row.get("canonical_mechanism") or "").strip()
    for chunk in mechanism.split("|"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        if key.strip().lower() == "ticker":
            ticker = value.strip().upper()
            return ticker or None
    return None


def seed_canonical_scheduled_events(
    session: Session,
    *,
    period_from: datetime,
    period_to: datetime,
    cluster_version: str = "anchor-scheduled-v1",
    padding_days: int = 2,
    commit: bool = True,
) -> AnchorSeedReport:
    start = period_from - timedelta(days=max(int(padding_days), 0))
    end = period_to + timedelta(days=max(int(padding_days), 0))
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    event_rows: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    for spec in _ANCHOR_SPECS:
        for release_ts in _iter_weekly_points(
            period_from=start,
            period_to=end,
            weekday=spec.weekday,
            release_time_utc=spec.release_time_utc,
        ):
            event_id = _anchor_event_id(spec, release_ts, cluster_version)
            event_rows.append(
                {
                    "event_id": event_id,
                    "event_first_published_at_utc": _to_iso_z(release_ts),
                    "event_first_ingested_at_utc": _to_iso_z(release_ts),
                    "event_last_published_at_utc": _to_iso_z(release_ts),
                    "event_status": "resolved" if release_ts <= now else "active",
                    "canonical_summary": spec.summary,
                    "canonical_mechanism": spec.mechanism,
                    "cluster_version": cluster_version,
                    "created_at": _to_iso_z(now),
                    "updated_at": _to_iso_z(now),
                }
            )
            label_rows.append(
                {
                    "target_level": "event",
                    "target_id": event_id,
                    "commodity_json": [spec.ticker],
                    "market_scope": "futures",
                    "instrument_candidates_json": [{"symbol": spec.ticker}],
                    "relevance": 1.0,
                    "news_type_json": [spec.family],
                    "direction": "uncertain",
                    "magnitude": 0.0,
                    "lag_bucket": "immediate",
                    "confidence": 1.0,
                    "uncertainty_type": "forecast",
                    "geo_scope": "US",
                    "evidence_json": {
                        "anchor_source": spec.source,
                        "event_family": spec.family,
                        "scheduled_release_ts": _to_iso_z(release_ts),
                    },
                    "label_source": "anchor_schedule",
                    "label_version": "v1",
                    "model_version": "schedule-v1",
                    "prompt_version": "schedule-v1",
                    "created_at": _to_iso_z(now),
                }
            )

    events_stored = upsert_news_events(session, event_rows, commit=commit) if event_rows else 0
    labels_stored = upsert_news_labels(session, label_rows, commit=commit) if label_rows else 0
    return AnchorSeedReport(
        period_from=_to_iso_z(period_from) or "",
        period_to=_to_iso_z(period_to) or "",
        events_prepared=len(event_rows),
        labels_prepared=len(label_rows),
        events_stored=events_stored,
        labels_stored=labels_stored,
    )


def _build_episodic_event_id(
    *,
    source: str,
    anchor_id: str,
    family: str,
    ticker: str,
    cluster_version: str,
) -> str:
    digest = _stable_hash(source, anchor_id, family, ticker, cluster_version, length=24)
    return f"evt-{cluster_version}-{digest}"


def _episodic_label_row(
    *,
    event_id: str,
    ticker: str,
    family: str,
    source: str,
    event_ts: datetime,
    summary: str,
    confidence: float = 0.95,
) -> dict[str, object]:
    return {
        "target_level": "event",
        "target_id": event_id,
        "commodity_json": [ticker],
        "market_scope": "futures",
        "instrument_candidates_json": [{"symbol": ticker}],
        "relevance": min(max(float(confidence), 0.0), 1.0),
        "news_type_json": [family],
        "direction": "uncertain",
        "magnitude": 0.0,
        "lag_bucket": "immediate",
        "confidence": min(max(float(confidence), 0.0), 1.0),
        "uncertainty_type": "forecast",
        "geo_scope": "GLOBAL",
        "evidence_json": {
            "anchor_source": source,
            "event_family": family,
            "event_ts": _to_iso_z(event_ts),
            "summary": summary,
        },
        "label_source": "anchor_episode",
        "label_version": "v1",
        "model_version": "episodic-v1",
        "prompt_version": "episodic-v1",
        "created_at": _to_iso_z(datetime.now(timezone.utc).replace(tzinfo=None)),
    }


def seed_episodic_anchor_events(
    session: Session,
    *,
    cluster_version: str = "anchor-episodic-v1",
    sources: Iterable[str] = ("nws_alerts", "nhc", "ukmto"),
    timeout_sec: int = 20,
    user_agent: str = "moex-carry/0.1 (+news-anchor)",
    nws_url: str = "https://api.weather.gov/alerts/active?event=Hurricane%20Warning,Storm%20Warning,Tropical%20Storm%20Warning",
    nhc_url: str = "https://www.nhc.noaa.gov/CurrentStorms.json",
    ukmto_url: str = "https://www.ukmto.org/recent-incidents",
    bsee_url: str = "https://www.bsee.gov/resources-tools/planning-preparedness/hurricane/hurricane-history",
    panama_url: str = "https://pancanal.com/en/maritime-services/advisory-to-shipping/",
    suez_url: str = "https://www.suezcanal.gov.eg/English/Navigation/NavigationCirculars/Pages/default.aspx",
    fred_release_url: str = "https://api.stlouisfed.org/fred/release/dates",
    fred_release_ids: Iterable[int] = (),
    fred_api_key_env: str = "FRED_API_KEY",
    commit: bool = True,
) -> EpisodicAnchorSeedReport:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    requested = [str(item or "").strip().lower() for item in sources if str(item or "").strip()]
    completed: list[str] = []
    errors: list[str] = []

    collected: list[EpisodicAnchorRecord] = []
    for source in requested:
        if source in {"nws", "nws_alerts"}:
            try:
                rows = _fetch_nws_alert_episodic_records(
                    url=nws_url,
                    timeout_sec=timeout_sec,
                    now=now,
                    user_agent=user_agent,
                )
                collected.extend(rows)
                completed.append(source)
            except Exception as exc:
                errors.append(str(exc))
            continue
        if source == "nhc":
            try:
                rows = _fetch_nhc_episodic_records(
                    url=nhc_url,
                    timeout_sec=timeout_sec,
                    now=now,
                    user_agent=user_agent,
                )
                collected.extend(rows)
                completed.append(source)
            except Exception as exc:
                errors.append(str(exc))
            continue
        if source == "ukmto":
            try:
                rows = _fetch_ukmto_episodic_records(
                    url=ukmto_url,
                    timeout_sec=timeout_sec,
                    now=now,
                    user_agent=user_agent,
                )
                collected.extend(rows)
                completed.append(source)
            except Exception as exc:
                errors.append(str(exc))
            continue
        if source == "bsee":
            try:
                rows = _fetch_bsee_episodic_records(
                    url=bsee_url,
                    timeout_sec=timeout_sec,
                    now=now,
                    user_agent=user_agent,
                )
                collected.extend(rows)
                completed.append(source)
            except Exception as exc:
                errors.append(str(exc))
            continue
        if source == "panama":
            try:
                rows = _fetch_panama_episodic_records(
                    url=panama_url,
                    timeout_sec=timeout_sec,
                    now=now,
                    user_agent=user_agent,
                )
                collected.extend(rows)
                completed.append(source)
            except Exception as exc:
                errors.append(str(exc))
            continue
        if source == "suez":
            try:
                rows = _fetch_suez_episodic_records(
                    url=suez_url,
                    timeout_sec=timeout_sec,
                    now=now,
                    user_agent=user_agent,
                )
                collected.extend(rows)
                completed.append(source)
            except Exception as exc:
                errors.append(str(exc))
            continue
        if source in {"fred", "fred_release"}:
            try:
                rows = _fetch_fred_release_records(
                    url=fred_release_url,
                    timeout_sec=timeout_sec,
                    now=now,
                    user_agent=user_agent,
                    release_ids=fred_release_ids,
                    api_key_env=fred_api_key_env,
                )
                collected.extend(rows)
                completed.append(source)
            except Exception as exc:
                errors.append(str(exc))
            continue
        errors.append(f"unsupported_source:{source}")

    dedup: dict[str, EpisodicAnchorRecord] = {}
    for record in collected:
        event_id = _build_episodic_event_id(
            source=record.source,
            anchor_id=record.anchor_id,
            family=record.family,
            ticker=record.ticker,
            cluster_version=cluster_version,
        )
        dedup[event_id] = record

    event_rows: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    update_rows: list[dict[str, object]] = []
    for event_id, record in dedup.items():
        event_rows.append(
            {
                "event_id": event_id,
                "event_first_published_at_utc": _to_iso_z(record.event_ts),
                "event_first_ingested_at_utc": _to_iso_z(now),
                "event_last_published_at_utc": _to_iso_z(record.event_ts),
                "event_status": record.event_status,
                "canonical_summary": record.summary,
                "canonical_mechanism": record.mechanism,
                "cluster_version": cluster_version,
                "created_at": _to_iso_z(now),
                "updated_at": _to_iso_z(now),
            }
        )
        label_rows.append(
            _episodic_label_row(
                event_id=event_id,
                ticker=record.ticker,
                family=record.family,
                source=record.source,
                event_ts=record.event_ts,
                summary=record.summary,
            )
        )
        source_hash = _stable_hash(record.source, record.anchor_id, record.summary, length=20)
        update_rows.append(
            {
                "event_id": event_id,
                "ts_update": _to_iso_z(record.event_ts),
                "phase": "emerging" if record.event_status == "active" else "resolved",
                "severity": 0.7 if record.family == "MARITIME_SECURITY_UKMTO" else 0.8,
                "facts_json": record.facts_json,
                "factor_delta_json": {
                    "RISK_PREMIUM": "up",
                    "SUPPLY": "down" if record.family == "HURRICANE_GOM_SHUTINS" else "neutral",
                },
                "source_url": (
                    nhc_url
                    if record.source == "NHC"
                    else (
                        nws_url
                        if record.source == "NWS"
                        else (
                            ukmto_url
                            if record.source == "UKMTO"
                            else (
                                bsee_url
                                if record.source == "BSEE"
                                else (
                                    panama_url
                                    if record.source == "PANAMA"
                                    else (
                                        suez_url
                                        if record.source == "SUEZ"
                                        else fred_release_url
                                    )
                                )
                            )
                        )
                    )
                ),
                "source_hash": source_hash,
                "created_at": _to_iso_z(now),
            }
        )

    events_stored = upsert_news_events(session, event_rows, commit=commit) if event_rows else 0
    labels_stored = upsert_news_labels(session, label_rows, commit=commit) if label_rows else 0
    updates_stored = upsert_news_event_updates(session, update_rows, commit=commit) if update_rows else 0
    return EpisodicAnchorSeedReport(
        sources_requested=requested,
        sources_completed=completed,
        events_prepared=len(event_rows),
        labels_prepared=len(label_rows),
        updates_prepared=len(update_rows),
        events_stored=events_stored,
        labels_stored=labels_stored,
        updates_stored=updates_stored,
        errors=errors,
    )


def link_news_to_scheduled_anchors(
    session: Session,
    *,
    news_rows: Iterable[dict[str, object]],
    cluster_version: str = "anchor-scheduled-v1",
    window_minutes: int = 90,
    link_role: str = "scheduled_anchor",
    link_type: str = "scheduled_anchor",
    commit: bool = True,
) -> AnchorLinkReport:
    normalized_news: list[dict[str, object]] = []
    for row in news_rows:
        if not isinstance(row, dict):
            continue
        news_id = str(row.get("news_id") or "").strip()
        published_at = _parse_datetime(row.get("published_at"))
        if not news_id or published_at is None:
            continue
        normalized_news.append({"news_id": news_id, "published_at": published_at})
    if not normalized_news:
        return AnchorLinkReport(linked_news=0, event_item_links=0, event_cross_links=0, unmatched_news=0, window_minutes=window_minutes)

    news_ids = [str(item["news_id"]) for item in normalized_news]
    link_rows = load_news_entity_links(session, news_ids=news_ids, limit=max(len(news_ids) * 8, 200))
    tickers_by_news: dict[str, dict[str, float]] = {}
    for row in link_rows:
        news_id = str(row.get("news_id") or "").strip()
        ticker = str(row.get("ticker") or row.get("entity_id") or "").strip().upper()
        confidence = float(row.get("link_confidence") or 0.0)
        if not news_id or not ticker:
            continue
        tickers = tickers_by_news.setdefault(news_id, {})
        prev_conf = float(tickers.get(ticker) or 0.0)
        if confidence >= prev_conf:
            tickers[ticker] = confidence

    min_ts = min(item["published_at"] for item in normalized_news) - timedelta(minutes=max(int(window_minutes), 1))
    max_ts = max(item["published_at"] for item in normalized_news) + timedelta(minutes=max(int(window_minutes), 1))
    candidate_events = load_news_events(
        session,
        published_from=_to_iso_z(min_ts),
        published_to=_to_iso_z(max_ts),
        limit=0,
    )
    anchor_events: dict[str, list[dict[str, object]]] = {}
    anchor_ids: set[str] = set()
    for row in candidate_events:
        if str(row.get("cluster_version") or "") != cluster_version:
            continue
        event_id = str(row.get("event_id") or "").strip()
        ticker = _extract_anchor_ticker(row)
        published_at = _parse_datetime(row.get("event_first_published_at_utc"))
        if not event_id or ticker is None or published_at is None:
            continue
        anchor_ids.add(event_id)
        anchor_events.setdefault(ticker, []).append(
            {"event_id": event_id, "published_at": published_at}
        )
    if not anchor_events:
        return AnchorLinkReport(linked_news=0, event_item_links=0, event_cross_links=0, unmatched_news=len(normalized_news), window_minutes=window_minutes)

    max_delta = timedelta(minutes=max(int(window_minutes), 1))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    event_item_rows: list[dict[str, object]] = []
    matched_anchor_by_news: dict[str, tuple[str, float]] = {}
    unmatched_news = 0

    for news in normalized_news:
        news_id = str(news["news_id"])
        published_at = news["published_at"]
        ticker_candidates = tickers_by_news.get(news_id)
        if not ticker_candidates:
            unmatched_news += 1
            continue
        best_event_id: str | None = None
        best_delta = None
        best_confidence = 0.0
        for ticker, confidence in ticker_candidates.items():
            candidates = anchor_events.get(ticker, [])
            if not candidates:
                continue
            for event in candidates:
                delta = abs(event["published_at"] - published_at)
                if delta > max_delta:
                    continue
                if (
                    best_delta is None
                    or delta < best_delta
                    or (delta == best_delta and confidence > best_confidence)
                ):
                    best_delta = delta
                    best_event_id = str(event["event_id"])
                    best_confidence = float(confidence)
        if best_event_id is None or best_delta is None:
            unmatched_news += 1
            continue
        time_score = max(0.0, 1.0 - (best_delta.total_seconds() / max_delta.total_seconds()))
        matched_anchor_by_news[news_id] = (best_event_id, time_score)
        event_item_rows.append(
            {
                "event_id": best_event_id,
                "news_id": news_id,
                "link_role": link_role,
                "similarity_score": round(float(time_score), 6),
                "added_at": _to_iso_z(now),
            }
        )

    event_item_links = upsert_news_event_items(session, event_item_rows, commit=commit) if event_item_rows else 0
    existing_items = load_news_event_items(session, news_ids=news_ids, limit=max(len(news_ids) * 8, 500))
    event_ids_by_news: dict[str, set[str]] = {}
    for row in existing_items:
        news_id = str(row.get("news_id") or "").strip()
        event_id = str(row.get("event_id") or "").strip()
        if not news_id or not event_id:
            continue
        event_ids_by_news.setdefault(news_id, set()).add(event_id)

    cross_rows: list[dict[str, object]] = []
    for news_id, anchor_info in matched_anchor_by_news.items():
        anchor_event_id, confidence = anchor_info
        event_ids = event_ids_by_news.get(news_id, set())
        for linked_event_id in event_ids:
            if linked_event_id == anchor_event_id or linked_event_id in anchor_ids:
                continue
            cross_rows.append(
                {
                    "src_event_id": anchor_event_id,
                    "dst_event_id": linked_event_id,
                    "link_type": link_type,
                    "confidence": round(float(confidence), 6),
                    "evidence_json": {"news_id": news_id},
                    "created_at": _to_iso_z(now),
                }
            )

    event_cross_links = upsert_news_event_links(session, cross_rows, commit=commit) if cross_rows else 0
    return AnchorLinkReport(
        linked_news=len(matched_anchor_by_news),
        event_item_links=event_item_links,
        event_cross_links=event_cross_links,
        unmatched_news=unmatched_news,
        window_minutes=max(int(window_minutes), 1),
    )
