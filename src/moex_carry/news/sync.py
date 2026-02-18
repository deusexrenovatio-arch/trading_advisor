from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import sleep

from sqlalchemy.orm import Session

from moex_carry.config import AppSettings
from moex_carry.news.anchors import (
    link_news_to_scheduled_anchors,
    seed_canonical_scheduled_events,
    seed_episodic_anchor_events,
)
from moex_carry.news.bridge import run_news_gate
from moex_carry.news.events import EventClusteringReport, cluster_news_events
from moex_carry.news.ingestion import fetch_rss_news
from moex_carry.news.inference import run_dual_model_inference_batch
from moex_carry.news.llm_gateway import NewsLlmPassReport, run_news_llm_full_pass
from moex_carry.news.linking import default_tag_rows, link_news_item
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_news_items,
    load_primary_news_scores,
    upsert_news_entity_links,
    upsert_news_impact_scores,
    upsert_news_item_tags,
    upsert_news_items,
    upsert_news_tags,
)
from moex_carry.strategy.news_filter import NewsGateResult


@dataclass(frozen=True)
class NewsSyncSnapshot:
    ingested_count: int
    processed_count: int
    entity_link_count: int
    tag_link_count: int
    score_count: int
    event_link_count: int
    event_created_count: int
    event_updated_count: int
    event_refuted_count: int
    event_resolved_count: int
    cluster_version: str
    llm_processed_count: int
    llm_completed_count: int
    llm_skipped_count: int
    llm_failed_count: int
    llm_labeled_count: int
    recent_news_rows: list[dict[str, object]]
    score_by_news: dict[str, dict[str, object]]
    matched_score_rows: list[dict[str, object]]
    news_gate: NewsGateResult


def _resolve_recent_limit(settings: AppSettings, recent_limit: int | None) -> int:
    if recent_limit is not None and recent_limit > 0:
        return int(recent_limit)
    return max(int(settings.news_ingest.max_items_per_run), 300)


def _should_run_inference(settings: AppSettings, value: bool | None) -> bool:
    if value is not None:
        return bool(value)
    return bool(settings.ui.ff_news_model_advisory_enabled or settings.ui.ff_news_bridge_enabled)


def _collect_rss_urls(settings: AppSettings) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for raw in list(settings.news_ingest.rss_urls) + [
        item
        for profile in settings.news_ingest.commodity_profiles
        for item in profile.rss_urls
    ]:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        urls.append(value)
    return urls


def _source_profile_map(settings: AppSettings) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for profile in settings.news_ingest.commodity_profiles:
        ticker = str(profile.ticker or "").strip().upper()
        if not ticker:
            continue
        for url in profile.rss_urls:
            key = str(url or "").strip()
            if not key:
                continue
            mapping[key] = ticker
    return mapping


def sync_news_runtime(
    session: Session,
    settings: AppSettings,
    *,
    enable_ingest: bool = True,
    enable_inference: bool | None = None,
    gate_enabled: bool | None = None,
    recent_limit: int | None = None,
) -> NewsSyncSnapshot:
    upsert_news_tags(session, default_tag_rows())

    ingested_count = 0
    rss_urls = _collect_rss_urls(settings)
    if enable_ingest and settings.news_ingest.enabled and rss_urls:
        ingested_rows = fetch_rss_news(
            rss_urls,
            max_items=settings.news_ingest.max_items_per_run,
        )
        if ingested_rows:
            ingested_count = upsert_news_items(session, ingested_rows)

    effective_limit = _resolve_recent_limit(settings, recent_limit)
    recent_news_rows = load_news_items(session, limit=effective_limit)
    should_run_inference = _should_run_inference(settings, enable_inference)

    entity_rows: list[dict[str, object]] = []
    tag_rows: list[dict[str, object]] = []
    score_rows: list[dict[str, object]] = []
    inference_items: list[dict[str, str]] = []
    source_profile_by_url = _source_profile_map(settings)
    for news_row in recent_news_rows:
        news_id = str(news_row.get("news_id") or "").strip()
        if not news_id:
            continue
        linking = link_news_item(
            news_id=news_id,
            title=str(news_row.get("title") or ""),
            content=str(news_row.get("content") or ""),
        )
        source_url = str(news_row.get("source") or "").strip()
        source_profile_ticker = source_profile_by_url.get(source_url)
        if source_profile_ticker:
            primary_id = source_profile_ticker
            resolution_stage = "source_profile"
            confidence = max(linking.confidence, 0.95)
        else:
            primary_id = linking.primary_commodity_id or "UNKNOWN"
            resolution_stage = linking.resolution_stage
            confidence = linking.confidence
        entity_rows.append(
            {
                "news_id": news_id,
                "entity_type": "commodity",
                "entity_id": primary_id,
                "ticker": primary_id if primary_id != "UNKNOWN" else None,
                "link_confidence": confidence,
                "link_stage": resolution_stage,
            }
        )
        for secondary_id in linking.secondary_commodity_ids:
            entity_rows.append(
                {
                    "news_id": news_id,
                    "entity_type": "commodity",
                    "entity_id": secondary_id,
                    "ticker": secondary_id,
                    "link_confidence": max(confidence - 0.1, 0.0),
                    "link_stage": resolution_stage,
                }
            )
        for tag_code in linking.tag_codes:
            tag_rows.append(
                {
                    "news_id": news_id,
                    "tag_code": tag_code,
                    "score": confidence,
                }
            )
        if should_run_inference:
            text = " ".join(
                [
                    str(news_row.get("title") or ""),
                    str(news_row.get("content") or ""),
                ]
            ).strip()
            if text:
                inference_items.append({"news_id": news_id, "text": text})

    if should_run_inference and inference_items:
        score_rows.extend(
            run_dual_model_inference_batch(
                news_items=inference_items,
                enabled_models=settings.news_models.enabled_models,
                finbert_model_name=settings.news_models.finbert_model_name,
                nli_model_name=settings.news_models.nli_model_name,
                model_version=settings.news_models.model_version,
                batch_size=settings.news_models.inference_batch_size,
                text_max_chars=settings.news_models.inference_text_max_chars,
                thread_cap=settings.news_models.inference_thread_cap,
            )
        )

    entity_link_count = upsert_news_entity_links(session, entity_rows) if entity_rows else 0
    tag_link_count = upsert_news_item_tags(session, tag_rows) if tag_rows else 0
    score_count = upsert_news_impact_scores(session, score_rows) if score_rows else 0
    if settings.news_events.enabled:
        event_report = cluster_news_events(
            session,
            news_rows=recent_news_rows,
            cluster_window_hours=settings.news_events.cluster_window_hours,
            similarity_threshold=settings.news_events.similarity_threshold,
            resolve_after_hours=settings.news_events.resolve_after_hours,
            cluster_version=settings.news_events.cluster_version,
        )
        published_values = [
            _parse_published_dt(row.get("published_at"))
            for row in recent_news_rows
            if _parse_published_dt(row.get("published_at")) is not None
        ]
        if published_values and settings.news_events.anchor_seed_enabled:
            seed_canonical_scheduled_events(
                session,
                period_from=min(published_values),
                period_to=max(published_values),
                cluster_version=settings.news_events.anchor_cluster_version,
                padding_days=settings.news_events.anchor_seed_padding_days,
            )
        if recent_news_rows and settings.news_events.anchor_link_enabled:
            link_news_to_scheduled_anchors(
                session,
                news_rows=recent_news_rows,
                cluster_version=settings.news_events.anchor_cluster_version,
                window_minutes=settings.news_events.anchor_match_window_minutes,
            )
        if settings.news_events.anchor_episode_seed_enabled:
            seed_episodic_anchor_events(
                session,
                cluster_version=settings.news_events.anchor_episode_cluster_version,
                sources=settings.news_events.anchor_episode_sources,
                timeout_sec=settings.news_events.anchor_request_timeout_sec,
                user_agent=settings.news_events.anchor_user_agent,
                nws_url=settings.news_events.anchor_nws_url,
                nhc_url=settings.news_events.anchor_nhc_url,
                ukmto_url=settings.news_events.anchor_ukmto_url,
                bsee_url=settings.news_events.anchor_bsee_url,
                panama_url=settings.news_events.anchor_panama_url,
                suez_url=settings.news_events.anchor_suez_url,
                fred_release_url=settings.news_events.anchor_fred_release_url,
                fred_release_ids=settings.news_events.anchor_fred_release_ids,
                fred_api_key_env=settings.news_events.anchor_fred_api_key_env,
            )
        if recent_news_rows and settings.news_events.anchor_link_enabled:
            link_news_to_scheduled_anchors(
                session,
                news_rows=recent_news_rows,
                cluster_version=settings.news_events.anchor_episode_cluster_version,
                window_minutes=settings.news_events.anchor_episode_match_window_minutes,
                link_role="episodic_anchor",
                link_type="episodic_anchor",
            )
    else:
        event_report = EventClusteringReport(
            processed_news=len(recent_news_rows),
            linked_news=0,
            created_events=0,
            updated_events=0,
            refuted_events=0,
            resolved_events=0,
            duplicate_links=0,
            update_links=0,
            refute_links=0,
            primary_links=0,
            cluster_version=settings.news_events.cluster_version,
        )
    llm_report: NewsLlmPassReport
    if settings.news_llm.enabled and settings.news_llm.full_pass_enabled:
        llm_report = run_news_llm_full_pass(
            session,
            settings,
            max_items=settings.news_llm.max_items_per_run,
        )
    else:
        llm_report = NewsLlmPassReport(
            processed_count=0,
            completed_count=0,
            skipped_count=0,
            failed_count=0,
            labeled_count=0,
            provider=settings.news_llm.provider,
            model_id=settings.news_llm.model_id,
            prompt_version=settings.news_llm.prompt_version,
        )

    primary_models = [settings.news_models.primary_model] + list(settings.news_models.enabled_models)
    score_by_news = load_primary_news_scores(
        session,
        news_ids=[str(row.get("news_id") or "") for row in recent_news_rows],
        preferred_models=primary_models,
    )
    apply_gate = settings.ui.ff_news_bridge_enabled if gate_enabled is None else bool(gate_enabled)
    news_gate = run_news_gate(
        recent_news_rows if apply_gate else [],
        score_by_news=score_by_news,
        lookback_minutes=settings.news_filter.lookback_minutes,
        block_severity_threshold=settings.news_filter.block_severity_threshold,
        reduce_severity_threshold=settings.news_filter.reduce_severity_threshold,
    )
    matched_score_rows = [
        score_by_news[item.item_id]
        for item in news_gate.matched_items
        if item.item_id in score_by_news
    ]

    return NewsSyncSnapshot(
        ingested_count=ingested_count,
        processed_count=len(recent_news_rows),
        entity_link_count=entity_link_count,
        tag_link_count=tag_link_count,
        score_count=score_count,
        event_link_count=event_report.linked_news,
        event_created_count=event_report.created_events,
        event_updated_count=event_report.updated_events,
        event_refuted_count=event_report.refuted_events,
        event_resolved_count=event_report.resolved_events,
        cluster_version=event_report.cluster_version,
        llm_processed_count=llm_report.processed_count,
        llm_completed_count=llm_report.completed_count,
        llm_skipped_count=llm_report.skipped_count,
        llm_failed_count=llm_report.failed_count,
        llm_labeled_count=llm_report.labeled_count,
        recent_news_rows=recent_news_rows,
        score_by_news=score_by_news,
        matched_score_rows=matched_score_rows,
        news_gate=news_gate,
    )


def _parse_published_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def run_news_sync_worker(
    settings: AppSettings,
    *,
    once: bool = False,
    interval_sec: int = 300,
    recent_limit: int | None = None,
    run_inference: bool = True,
) -> None:
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    poll_interval = max(int(interval_sec), 1)
    cycle = 0
    while True:
        cycle += 1
        started_at = datetime.now(timezone.utc)
        with session_factory() as session:
            snapshot = sync_news_runtime(
                session,
                settings,
                enable_ingest=True,
                enable_inference=run_inference,
                gate_enabled=settings.ui.ff_news_bridge_enabled,
                recent_limit=recent_limit,
            )
        elapsed_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000.0)
        print(
            "[news_sync] "
            f"cycle={cycle} ingested={snapshot.ingested_count} processed={snapshot.processed_count} "
            f"entity_links={snapshot.entity_link_count} tags={snapshot.tag_link_count} "
            f"scores={snapshot.score_count} events={snapshot.event_link_count} "
            f"created={snapshot.event_created_count} updated={snapshot.event_updated_count} "
            f"refuted={snapshot.event_refuted_count} resolved={snapshot.event_resolved_count} "
            f"llm_processed={snapshot.llm_processed_count} llm_done={snapshot.llm_completed_count} "
            f"llm_skipped={snapshot.llm_skipped_count} llm_failed={snapshot.llm_failed_count} "
            f"cluster={snapshot.cluster_version} gate={snapshot.news_gate.action}/{snapshot.news_gate.highest_severity} "
            f"matched={len(snapshot.news_gate.matched_items)} elapsed_ms={elapsed_ms}",
            flush=True,
        )
        if once:
            break
        sleep(poll_interval)
