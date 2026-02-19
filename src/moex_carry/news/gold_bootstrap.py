from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import mean
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from moex_carry.config import AppSettings
from moex_carry.news.inference import run_dual_model_inference_batch
from moex_carry.news.taxonomy import normalize_direction
from moex_carry.news.target_v2_event_text import ticker_has_text_support
from moex_carry.storage import models as db
from moex_carry.storage.repositories import upsert_news_gold_labels, upsert_news_impact_scores


def _to_direction_label(raw: str | None) -> str:
    token = str(raw or "").strip().lower()
    if token in {"up", "positive", "bullish"}:
        return "up"
    if token in {"down", "negative", "bearish"}:
        return "down"
    return "neutral"


def _event_family_from_news_type(value: object) -> str | None:
    if isinstance(value, list):
        for item in value:
            token = str(item or "").strip().upper()
            if token and "_" in token:
                return token
    return None


def _event_family_by_event_id(session: Session, *, event_ids: Iterable[str]) -> dict[str, str]:
    normalized = [str(item).strip() for item in event_ids if str(item).strip()]
    if not normalized:
        return {}
    rows = (
        session.execute(
            select(db.NewsLabelModel)
            .where(db.NewsLabelModel.target_level == "event")
            .where(db.NewsLabelModel.target_id.in_(normalized))
            .order_by(db.NewsLabelModel.created_at.desc())
        )
        .scalars()
        .all()
    )
    result: dict[str, str] = {}
    for row in rows:
        event_id = str(row.target_id or "").strip()
        if not event_id or event_id in result:
            continue
        family = _event_family_from_news_type(row.news_type_json)
        if family:
            result[event_id] = family
    return result


def _select_primary_news_id(
    session: Session,
    *,
    event_id: str,
    t0: datetime | None,
) -> str | None:
    link_rows = (
        session.execute(
            select(db.NewsEventItemModel).where(db.NewsEventItemModel.event_id == event_id)
        )
        .scalars()
        .all()
    )
    if not link_rows:
        return None
    news_ids = [str(row.news_id or "").strip() for row in link_rows if str(row.news_id or "").strip()]
    if not news_ids:
        return None
    news_rows = (
        session.execute(
            select(db.NewsItemModel).where(db.NewsItemModel.news_id.in_(news_ids))
        )
        .scalars()
        .all()
    )
    if not news_rows:
        return None
    ontime_rows = [
        row
        for row in news_rows
        if isinstance(row.published_at, datetime) and (t0 is None or row.published_at <= t0)
    ]
    ranked = ontime_rows if ontime_rows else news_rows
    ranked = sorted(
        ranked,
        key=lambda row: (
            row.published_at if isinstance(row.published_at, datetime) else datetime.max,
            str(row.news_id or ""),
        ),
    )
    picked = ranked[0]
    news_id = str(picked.news_id or "").strip()
    return news_id or None


def _load_news_item(
    session: Session,
    *,
    news_id: str,
) -> db.NewsItemModel | None:
    normalized = str(news_id or "").strip()
    if not normalized:
        return None
    row = (
        session.execute(
            select(db.NewsItemModel)
            .where(db.NewsItemModel.news_id == normalized)
            .limit(1)
        )
        .scalars()
        .first()
    )
    return row


def _is_primary_news_relevant(
    *,
    news_row: db.NewsItemModel | None,
    symbol: str,
    allowed_languages: set[str],
    blocked_source_tokens: tuple[str, ...],
    min_title_chars: int,
    min_text_chars: int,
    require_ticker_text_support: bool,
) -> bool:
    if news_row is None:
        return False
    language = str(news_row.language or "").strip().lower()
    if allowed_languages and language and language not in allowed_languages:
        return False
    source = str(news_row.source or "").strip().lower()
    if source and any(token in source for token in blocked_source_tokens):
        return False
    title = str(news_row.title or "").strip()
    content = str(news_row.content or "").strip()
    if len(title) < max(int(min_title_chars), 0):
        return False
    text = " ".join(part for part in (title, content) if part).strip()
    if len(text) < max(int(min_text_chars), 0):
        return False
    if require_ticker_text_support and not ticker_has_text_support(ticker=str(symbol or "").strip().upper(), text=text.lower()):
        return False
    return True


def _latest_score_for_news(
    session: Session,
    *,
    news_id: str,
    model_id: str,
) -> db.NewsImpactScoreModel | None:
    row = (
        session.execute(
            select(db.NewsImpactScoreModel)
            .where(db.NewsImpactScoreModel.model_id == model_id)
            .where(db.NewsImpactScoreModel.news_id == news_id)
            .order_by(db.NewsImpactScoreModel.inference_ts.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    return row


def _latest_score_for_event(
    session: Session,
    *,
    event_id: str,
    model_id: str,
) -> db.NewsImpactScoreModel | None:
    row = (
        session.execute(
            select(db.NewsImpactScoreModel)
            .where(db.NewsImpactScoreModel.model_id == model_id)
            .where(db.NewsImpactScoreModel.target_level == "event")
            .where(db.NewsImpactScoreModel.target_id == event_id)
            .order_by(db.NewsImpactScoreModel.inference_ts.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    return row


@dataclass(frozen=True)
class HumanToGoldReport:
    scanned: int
    accepted: int
    stored: int


@dataclass(frozen=True)
class V2SilverBootstrapReport:
    scanned: int
    eligible_targets: int
    accepted: int
    stored: int
    skipped_no_primary_news: int
    skipped_missing_scores: int
    skipped_confidence: int
    skipped_disagreement: int
    skipped_relevance: int


@dataclass(frozen=True)
class EventScoreBackfillReport:
    scanned_labels: int
    candidate_events: int
    scored_events: int
    stored_scores: int
    skipped_existing_complete: int
    skipped_no_text: int


def _collect_event_text(
    session: Session,
    *,
    event_id: str,
    text_max_chars: int,
    max_linked_news: int = 3,
) -> str:
    event_row = (
        session.execute(
            select(db.NewsEventModel).where(db.NewsEventModel.event_id == event_id).limit(1)
        )
        .scalars()
        .first()
    )
    if event_row is None:
        return ""
    chunks: list[str] = []
    canonical_summary = str(event_row.canonical_summary or "").strip()
    canonical_mechanism = str(event_row.canonical_mechanism or "").strip()
    if canonical_summary:
        chunks.append(canonical_summary)
    if canonical_mechanism:
        chunks.append(canonical_mechanism)

    link_rows = (
        session.execute(
            select(db.NewsEventItemModel)
            .where(db.NewsEventItemModel.event_id == event_id)
            .order_by(db.NewsEventItemModel.added_at.asc())
        )
        .scalars()
        .all()
    )
    news_ids = [str(row.news_id or "").strip() for row in link_rows if str(row.news_id or "").strip()]
    if news_ids:
        news_rows = (
            session.execute(
                select(db.NewsItemModel).where(db.NewsItemModel.news_id.in_(news_ids[: max(int(max_linked_news), 1) * 4]))
            )
            .scalars()
            .all()
        )
        news_map = {str(row.news_id or "").strip(): row for row in news_rows if str(row.news_id or "").strip()}
        picked = 0
        for news_id in news_ids:
            row = news_map.get(news_id)
            if row is None:
                continue
            title = str(row.title or "").strip()
            content = str(row.content or "").strip()
            text = title
            if content and content != title:
                text = f"{title}\n{content}" if title else content
            if text:
                chunks.append(text)
                picked += 1
            if picked >= max(int(max_linked_news), 1):
                break

    raw = "\n\n".join(chunks).strip()
    if not raw:
        return ""
    limit = max(int(text_max_chars), 0)
    return raw[:limit] if limit and len(raw) > limit else raw


def backfill_event_scores_for_gold(
    session: Session,
    settings: AppSettings,
    *,
    quality: str = "gold",
    source: str | None = None,
    label_schema_version: str | None = None,
    max_events: int = 500,
    include_existing: bool = False,
    model_ids: Iterable[str] | None = None,
    text_max_chars: int | None = None,
) -> EventScoreBackfillReport:
    query = (
        select(db.NewsGoldLabelModel)
        .where(db.NewsGoldLabelModel.target_type == "event")
        .order_by(db.NewsGoldLabelModel.created_at.desc())
    )
    normalized_quality = str(quality or "").strip().lower()
    if normalized_quality and normalized_quality != "any":
        query = query.where(db.NewsGoldLabelModel.quality == normalized_quality)
    if source:
        query = query.where(db.NewsGoldLabelModel.source == str(source).strip())
    if label_schema_version:
        query = query.where(db.NewsGoldLabelModel.label_schema_version == str(label_schema_version).strip())
    fetch_limit = max(int(max_events), 0)
    if fetch_limit > 0:
        query = query.limit(max(fetch_limit * 4, 100))
    rows = session.execute(query).scalars().all()
    scanned_labels = len(rows)

    event_ids: list[str] = []
    seen_ids: set[str] = set()
    for row in rows:
        event_id = str(row.target_id or "").strip()
        if not event_id or event_id in seen_ids:
            continue
        seen_ids.add(event_id)
        event_ids.append(event_id)
        if fetch_limit > 0 and len(event_ids) >= fetch_limit:
            break
    if not event_ids:
        return EventScoreBackfillReport(
            scanned_labels=scanned_labels,
            candidate_events=0,
            scored_events=0,
            stored_scores=0,
            skipped_existing_complete=0,
            skipped_no_text=0,
        )

    selected_models = [str(item).strip().lower() for item in (model_ids or settings.news_models.enabled_models) if str(item).strip()]
    selected_models = [item for item in selected_models if item in {"finbert", "nli"}]
    if not selected_models:
        selected_models = ["finbert", "nli"]

    existing_scores = (
        session.execute(
            select(db.NewsImpactScoreModel)
            .where(db.NewsImpactScoreModel.target_level == "event")
            .where(db.NewsImpactScoreModel.target_id.in_(event_ids))
            .where(db.NewsImpactScoreModel.model_id.in_(selected_models))
            .order_by(db.NewsImpactScoreModel.inference_ts.desc())
        )
        .scalars()
        .all()
    )
    existing_by_event_model: dict[tuple[str, str], db.NewsImpactScoreModel] = {}
    for row in existing_scores:
        event_id = str(row.target_id or "").strip()
        model_id = str(row.model_id or "").strip().lower()
        key = (event_id, model_id)
        if event_id and model_id and key not in existing_by_event_model:
            existing_by_event_model[key] = row

    effective_text_cap = int(text_max_chars) if text_max_chars is not None else int(settings.news_models.inference_text_max_chars)
    event_text_by_id: dict[str, str] = {}
    skipped_no_text = 0
    skipped_existing_complete = 0
    missing_models_by_event: dict[str, list[str]] = {}

    for event_id in event_ids:
        missing = [model for model in selected_models if (event_id, model) not in existing_by_event_model]
        if not missing and not include_existing:
            skipped_existing_complete += 1
            continue
        if include_existing and not missing:
            missing = list(selected_models)
        text = _collect_event_text(
            session,
            event_id=event_id,
            text_max_chars=effective_text_cap,
            max_linked_news=3,
        )
        if not text:
            skipped_no_text += 1
            continue
        event_text_by_id[event_id] = text
        missing_models_by_event[event_id] = missing

    if not missing_models_by_event:
        return EventScoreBackfillReport(
            scanned_labels=scanned_labels,
            candidate_events=len(event_ids),
            scored_events=0,
            stored_scores=0,
            skipped_existing_complete=skipped_existing_complete,
            skipped_no_text=skipped_no_text,
        )

    rows_to_upsert: list[dict[str, object]] = []
    batch_size = max(int(settings.news_models.inference_batch_size), 1)
    thread_cap = int(settings.news_models.inference_thread_cap)
    model_version = str(settings.news_models.model_version or "v1")

    for model in selected_models:
        candidates = [
            {"news_id": event_id, "text": event_text_by_id[event_id]}
            for event_id, missing in missing_models_by_event.items()
            if model in missing
        ]
        if not candidates:
            continue
        scored_rows = run_dual_model_inference_batch(
            news_items=candidates,
            enabled_models=[model],
            finbert_model_name=settings.news_models.finbert_model_name,
            nli_model_name=settings.news_models.nli_model_name,
            model_version=model_version,
            batch_size=batch_size,
            text_max_chars=effective_text_cap,
            thread_cap=thread_cap,
        )
        for row in scored_rows:
            target_id = str(row.get("news_id") or "").strip()
            if not target_id:
                continue
            row["target_level"] = "event"
            row["target_id"] = target_id
            rows_to_upsert.append(row)

    stored_scores = upsert_news_impact_scores(session, rows_to_upsert) if rows_to_upsert else 0
    scored_events = len({str(row.get("target_id") or "").strip() for row in rows_to_upsert if str(row.get("target_id") or "").strip()})
    return EventScoreBackfillReport(
        scanned_labels=scanned_labels,
        candidate_events=len(event_ids),
        scored_events=scored_events,
        stored_scores=int(stored_scores),
        skipped_existing_complete=skipped_existing_complete,
        skipped_no_text=skipped_no_text,
    )


def promote_human_labels_to_gold(
    session: Session,
    *,
    source: str = "human_hitl",
    quality: str = "gold",
    label_schema_version: str = "v1",
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    max_rows: int = 0,
) -> HumanToGoldReport:
    query = (
        select(db.NewsLabelModel)
        .where(db.NewsLabelModel.target_level == "event")
        .where(db.NewsLabelModel.label_source == "human")
        .order_by(db.NewsLabelModel.created_at.desc())
    )
    if created_from is not None:
        query = query.where(db.NewsLabelModel.created_at >= created_from)
    if created_to is not None:
        query = query.where(db.NewsLabelModel.created_at <= created_to)
    if max_rows > 0:
        query = query.limit(max_rows)
    rows = session.execute(query).scalars().all()

    unique_event_ids: set[str] = set()
    upserts: list[dict[str, object]] = []
    for row in rows:
        event_id = str(row.target_id or "").strip()
        if not event_id or event_id in unique_event_ids:
            continue
        unique_event_ids.add(event_id)
        direction_label = _to_direction_label(row.direction)
        event_family = _event_family_from_news_type(row.news_type_json)
        upserts.append(
            {
                "target_type": "event",
                "target_id": event_id,
                "event_family": event_family,
                "factors_json": None,
                "phase": None,
                "direction_label": direction_label,
                "quality": str(quality or "gold"),
                "source": str(source or "human_hitl"),
                "label_schema_version": str(label_schema_version or "v1"),
                "confidence": float(row.confidence or 0.0),
                "meta_json": {
                    "derived_from": "news_labels.human",
                    "label_version": row.label_version,
                    "prompt_version": row.prompt_version,
                },
                "created_at": row.created_at,
            }
        )

    stored = upsert_news_gold_labels(session, upserts) if upserts else 0
    return HumanToGoldReport(
        scanned=len(rows),
        accepted=len(upserts),
        stored=int(stored),
    )


def bootstrap_silver_from_v2_targets(
    session: Session,
    *,
    horizon: str,
    symbol: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    min_model_confidence: float = 0.62,
    require_both_models: bool = True,
    require_direction_match_to_target: bool = True,
    allow_no_model_scores: bool = False,
    model_ids: tuple[str, str] = ("finbert", "nli"),
    source: str = "auto_target_v2",
    quality: str = "silver",
    label_schema_version: str = "v2",
    max_events: int = 0,
    include_overlapped: bool = False,
    target_selector: str = "hi_conf",
    min_target_confidence: float = 0.0,
    min_impact_bin: int = 1,
    min_abs_z_post: float = 0.0,
    min_abs_ar: float = 0.0,
    require_primary_news_relevance: bool = True,
    allowed_languages: tuple[str, ...] = ("en",),
    blocked_source_tokens: tuple[str, ...] = ("blog", "opinion", "analysis", "newsletter", "finance.yahoo"),
    min_primary_title_chars: int = 16,
    min_primary_text_chars: int = 40,
    require_ticker_text_support: bool = True,
    allow_target_only_fallback: bool = False,
) -> V2SilverBootstrapReport:
    normalized_horizon = str(horizon or "1h").strip().lower()
    model_a, model_b = model_ids
    selector_mode = str(target_selector or "hi_conf").strip().lower()
    if selector_mode not in {"hi_conf", "impact", "hybrid"}:
        selector_mode = "hi_conf"
    min_impact = max(int(min_impact_bin), 0)
    min_target_conf = max(float(min_target_confidence), 0.0)
    min_z = max(float(min_abs_z_post), 0.0)
    min_ar = max(float(min_abs_ar), 0.0)
    allowed_lang_set = {str(item or "").strip().lower() for item in allowed_languages if str(item or "").strip()}
    blocked_tokens = tuple(str(item or "").strip().lower() for item in blocked_source_tokens if str(item or "").strip())

    query = (
        select(db.EventTargetV2Model)
        .where(db.EventTargetV2Model.horizon == normalized_horizon)
        .where(db.EventTargetV2Model.leakage_postmove.is_(False))
        .where(db.EventTargetV2Model.is_repost.is_(False))
        .order_by(db.EventTargetV2Model.t0.desc())
    )
    impact_condition = (
        (db.EventTargetV2Model.impact_bin >= min_impact)
        & (db.EventTargetV2Model.confidence >= min_target_conf)
        & (func.abs(db.EventTargetV2Model.z_post) >= min_z)
        & (func.abs(db.EventTargetV2Model.ar) >= min_ar)
    )
    if selector_mode == "hi_conf":
        query = query.where(db.EventTargetV2Model.is_hi_conf.is_(True))
    elif selector_mode == "impact":
        query = query.where(impact_condition)
    else:
        query = query.where(or_(db.EventTargetV2Model.is_hi_conf.is_(True), impact_condition))
    if not bool(include_overlapped):
        query = query.where(db.EventTargetV2Model.is_overlapped.is_(False))
    if symbol:
        query = query.where(db.EventTargetV2Model.symbol == str(symbol).strip().upper())
    if published_from is not None:
        query = query.where(db.EventTargetV2Model.t0 >= published_from)
    if published_to is not None:
        query = query.where(db.EventTargetV2Model.t0 <= published_to)
    if max_events > 0:
        query = query.limit(max_events)

    targets = session.execute(query).scalars().all()
    scanned = len(targets)
    if not targets:
        return V2SilverBootstrapReport(
            scanned=0,
            eligible_targets=0,
            accepted=0,
            stored=0,
            skipped_no_primary_news=0,
            skipped_missing_scores=0,
            skipped_confidence=0,
            skipped_disagreement=0,
            skipped_relevance=0,
        )

    event_ids = [str(row.event_id or "").strip() for row in targets if str(row.event_id or "").strip()]
    event_family_map = _event_family_by_event_id(session, event_ids=event_ids)
    upserts: list[dict[str, object]] = []

    skipped_no_primary_news = 0
    skipped_missing_scores = 0
    skipped_confidence = 0
    skipped_disagreement = 0
    skipped_relevance = 0
    eligible_targets = 0

    for row in targets:
        event_id = str(row.event_id or "").strip()
        if not event_id:
            continue
        eligible_targets += 1
        target_direction = _to_direction_label(
            "up" if int(row.label_v2 or 0) > 0 else "down" if int(row.label_v2 or 0) < 0 else "neutral"
        )

        primary_news_id = _select_primary_news_id(session, event_id=event_id, t0=row.t0)
        primary_news = _load_news_item(session, news_id=primary_news_id or "")
        if require_primary_news_relevance:
            if not _is_primary_news_relevant(
                news_row=primary_news,
                symbol=str(row.symbol or "").strip().upper(),
                allowed_languages=allowed_lang_set,
                blocked_source_tokens=blocked_tokens,
                min_title_chars=max(int(min_primary_title_chars), 0),
                min_text_chars=max(int(min_primary_text_chars), 0),
                require_ticker_text_support=bool(require_ticker_text_support),
            ):
                skipped_relevance += 1
                continue

        score_source = "news"
        if primary_news_id:
            score_a = _latest_score_for_news(session, news_id=primary_news_id, model_id=model_a)
            score_b = _latest_score_for_news(session, news_id=primary_news_id, model_id=model_b)
        else:
            skipped_no_primary_news += 1
            score_a = _latest_score_for_event(session, event_id=event_id, model_id=model_a)
            score_b = _latest_score_for_event(session, event_id=event_id, model_id=model_b)
            score_source = "event"

        if score_a is None or score_b is None:
            if not allow_no_model_scores:
                skipped_missing_scores += 1
                continue
            if not allow_target_only_fallback:
                skipped_missing_scores += 1
                continue
            pred_a = target_direction
            pred_b = target_direction
            conf_a = 0.70
            conf_b = 0.70
            score_source = "target_only"
            resolved_direction = target_direction
        else:
            pred_a = normalize_direction(score_a.direction)
            pred_b = normalize_direction(score_b.direction)
            conf_a = max(float(score_a.prob_up or 0.0), float(score_a.prob_down or 0.0), float(score_a.prob_neutral or 0.0))
            conf_b = max(float(score_b.prob_up or 0.0), float(score_b.prob_down or 0.0), float(score_b.prob_neutral or 0.0))
            if conf_a < float(min_model_confidence) or conf_b < float(min_model_confidence):
                skipped_confidence += 1
                continue

            if require_both_models and pred_a != pred_b:
                skipped_disagreement += 1
                continue

            resolved_direction = pred_a if require_both_models else target_direction
            resolved_direction = _to_direction_label(resolved_direction)

            if require_direction_match_to_target and resolved_direction != target_direction:
                skipped_disagreement += 1
                continue

        upserts.append(
            {
                "target_type": "event",
                "target_id": event_id,
                "event_family": event_family_map.get(event_id),
                "factors_json": None,
                "phase": None,
                "direction_label": target_direction,
                "quality": str(quality or "silver"),
                "source": str(source or "auto_target_v2"),
                "label_schema_version": str(label_schema_version or "v2"),
                "confidence": float(mean([conf_a, conf_b])),
                "meta_json": {
                    "derived_from": "event_target_v2",
                    "horizon": normalized_horizon,
                    "target_selector": selector_mode,
                    "target_filters": {
                        "min_target_confidence": min_target_conf,
                        "min_impact_bin": min_impact,
                        "min_abs_z_post": min_z,
                        "min_abs_ar": min_ar,
                    },
                    "symbol": str(row.symbol or "").strip().upper(),
                    "label_v2": int(row.label_v2 or 0),
                    "primary_news_id": primary_news_id,
                    "score_source": score_source,
                    "primary_news_meta": (
                        {
                            "source": str(primary_news.source or "").strip(),
                            "language": str(primary_news.language or "").strip(),
                            "title_chars": len(str(primary_news.title or "").strip()),
                            "content_chars": len(str(primary_news.content or "").strip()),
                        }
                        if primary_news is not None
                        else None
                    ),
                    "model_checks": {
                        model_a: {"pred": pred_a, "confidence": conf_a},
                        model_b: {"pred": pred_b, "confidence": conf_b},
                    },
                },
                "created_at": row.updated_at or row.created_at,
            }
        )

    stored = upsert_news_gold_labels(session, upserts) if upserts else 0
    return V2SilverBootstrapReport(
        scanned=scanned,
        eligible_targets=eligible_targets,
        accepted=len(upserts),
        stored=int(stored),
        skipped_no_primary_news=skipped_no_primary_news,
        skipped_missing_scores=skipped_missing_scores,
        skipped_confidence=skipped_confidence,
        skipped_disagreement=skipped_disagreement,
        skipped_relevance=skipped_relevance,
    )
