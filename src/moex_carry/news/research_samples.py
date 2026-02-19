from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from moex_carry.news.taxonomy import normalize_direction
from moex_carry.news.research_metrics import (
    _aggregate_samples_to_event_level,
    _label_return,
    _load_quote_point,
    _normalize_target_mode,
    _resolve_quote_lag_limit,
)
from moex_carry.news.research_policy import _label_from_v2_int
from moex_carry.storage import models as db

def _build_backtest_samples_v2(
    session: Session,
    *,
    model_id: str,
    period_from: datetime,
    period_to: datetime,
    horizon: str,
) -> list[dict[str, object]]:
    targets = (
        session.execute(
            select(db.EventTargetV2Model)
            .where(db.EventTargetV2Model.horizon == horizon)
            .where(db.EventTargetV2Model.t0 >= period_from)
            .where(db.EventTargetV2Model.t0 <= period_to)
            .where(db.EventTargetV2Model.leakage_postmove.is_(False))
            .where(db.EventTargetV2Model.is_repost.is_(False))
            .where(db.EventTargetV2Model.is_overlapped.is_(False))
            .order_by(db.EventTargetV2Model.t0.asc(), db.EventTargetV2Model.event_id.asc())
        )
        .scalars()
        .all()
    )
    if not targets:
        return []

    event_ids = sorted({str(row.event_id or "").strip() for row in targets if str(row.event_id or "").strip()})
    if not event_ids:
        return []

    event_family_by_event: dict[str, str] = {}
    event_labels = (
        session.execute(
            select(db.NewsLabelModel)
            .where(db.NewsLabelModel.target_level == "event")
            .where(db.NewsLabelModel.target_id.in_(event_ids))
            .order_by(db.NewsLabelModel.created_at.desc())
        )
        .scalars()
        .all()
    )
    for row in event_labels:
        event_id = str(row.target_id or "").strip()
        if not event_id or event_id in event_family_by_event:
            continue
        code = ""
        if isinstance(row.news_type_json, list):
            for item in row.news_type_json:
                token = str(item or "").strip().upper()
                if token and "_" in token:
                    code = token
                    break
        if not code and isinstance(row.evidence_json, dict):
            code = str(row.evidence_json.get("event_family") or "").strip().upper()
        if code:
            event_family_by_event[event_id] = code

    event_items = (
        session.execute(
            select(db.NewsEventItemModel).where(db.NewsEventItemModel.event_id.in_(event_ids))
        )
        .scalars()
        .all()
    )
    event_to_news: dict[str, list[str]] = {}
    for row in event_items:
        event_id = str(row.event_id or "").strip()
        news_id = str(row.news_id or "").strip()
        if not event_id or not news_id:
            continue
        event_to_news.setdefault(event_id, []).append(news_id)

    news_ids = sorted(
        {
            news_id
            for values in event_to_news.values()
            for news_id in values
            if isinstance(news_id, str) and news_id
        }
    )
    news_rows = (
        session.execute(select(db.NewsItemModel).where(db.NewsItemModel.news_id.in_(news_ids))).scalars().all()
        if news_ids
        else []
    )
    news_by_id = {str(row.news_id): row for row in news_rows if row.news_id}

    # Use earliest known article in event (and before t0 when possible) to avoid post-event leakage.
    primary_news_by_event: dict[str, str] = {}
    for target in targets:
        event_id = str(target.event_id or "").strip()
        if not event_id:
            continue
        rows = [news_by_id.get(news_id) for news_id in event_to_news.get(event_id, [])]
        valid_rows = [row for row in rows if isinstance(row, db.NewsItemModel)]
        if not valid_rows:
            continue
        ontime_rows = [row for row in valid_rows if isinstance(row.published_at, datetime) and row.published_at <= target.t0]
        ranked = ontime_rows if ontime_rows else valid_rows
        ranked = sorted(
            ranked,
            key=lambda row: (
                row.published_at if isinstance(row.published_at, datetime) else datetime.max,
                str(row.news_id or ""),
            ),
        )
        picked = ranked[0]
        if picked.news_id:
            primary_news_by_event[event_id] = str(picked.news_id)

    selected_news_ids = sorted({value for value in primary_news_by_event.values() if value})
    score_by_news: dict[str, db.NewsImpactScoreModel] = {}
    if selected_news_ids:
        news_scores = (
            session.execute(
                select(db.NewsImpactScoreModel)
                .where(db.NewsImpactScoreModel.model_id == model_id)
                .where(db.NewsImpactScoreModel.news_id.in_(selected_news_ids))
                .order_by(db.NewsImpactScoreModel.inference_ts.desc())
            )
            .scalars()
            .all()
        )
        for row in news_scores:
            key = str(row.news_id or "").strip()
            if key:
                score_by_news.setdefault(key, row)

    score_by_event: dict[str, db.NewsImpactScoreModel] = {}
    event_scores = (
        session.execute(
            select(db.NewsImpactScoreModel)
            .where(db.NewsImpactScoreModel.model_id == model_id)
            .where(db.NewsImpactScoreModel.target_level == "event")
            .where(db.NewsImpactScoreModel.target_id.in_(event_ids))
            .order_by(db.NewsImpactScoreModel.inference_ts.desc())
        )
        .scalars()
        .all()
    )
    for row in event_scores:
        key = str(row.target_id or "").strip()
        if key:
            score_by_event.setdefault(key, row)

    samples: list[dict[str, object]] = []
    for target in targets:
        event_id = str(target.event_id or "").strip()
        if not event_id:
            continue
        score = None
        primary_news_id = primary_news_by_event.get(event_id)
        if primary_news_id:
            score = score_by_news.get(primary_news_id)
        if score is None:
            score = score_by_event.get(event_id)
        if score is None:
            continue
        pred_label = normalize_direction(score.direction)
        actual_label = _label_from_v2_int(int(target.label_v2 or 0))
        samples.append(
            {
                "news_id": primary_news_id or "",
                "published_at": target.t0,
                "ticker": str(target.symbol or "").strip().upper(),
                "source": "event_target_v2",
                "pred_label": pred_label,
                "actual_label": actual_label,
                "signed_return": float(target.ar or 0.0),
                "prob_up": float(score.prob_up or 0.0),
                "prob_down": float(score.prob_down or 0.0),
                "prob_neutral": float(score.prob_neutral or 0.0),
                "pred_confidence": max(float(score.prob_up or 0.0), float(score.prob_down or 0.0), float(score.prob_neutral or 0.0)),
                "calibrated": bool(score.calibrated),
                "event_id": event_id,
                "event_family": event_family_by_event.get(event_id, "UNKNOWN"),
                "target_mode": "v2",
            }
        )
    return samples


def _build_backtest_samples(
    session: Session,
    *,
    model_id: str,
    period_from: datetime,
    period_to: datetime,
    delta: timedelta,
    epsilon: float,
    strict_anchor_window_minutes: int = 120,
    evaluation_level: str = "article",
    target_mode: str = "legacy",
    horizon: str | None = None,
) -> list[dict[str, object]]:
    if _normalize_target_mode(target_mode) == "v2":
        normalized_horizon = str(horizon or "1d").strip().lower()
        return _build_backtest_samples_v2(
            session,
            model_id=model_id,
            period_from=period_from,
            period_to=period_to,
            horizon=normalized_horizon,
        )

    news_rows = (
        session.execute(
            select(db.NewsItemModel)
            .where(db.NewsItemModel.published_at >= period_from)
            .where(db.NewsItemModel.published_at <= period_to)
            .order_by(db.NewsItemModel.published_at.asc())
        )
        .scalars()
        .all()
    )
    if not news_rows:
        return []

    news_ids = [item.news_id for item in news_rows if item.news_id]
    if not news_ids:
        return []

    links_by_news: dict[str, list[db.NewsEntityLinkModel]] = {}
    for link in (
        session.execute(
            select(db.NewsEntityLinkModel)
            .where(db.NewsEntityLinkModel.news_id.in_(news_ids))
            .order_by(db.NewsEntityLinkModel.id.asc())
        )
        .scalars()
        .all()
    ):
        links_by_news.setdefault(link.news_id, []).append(link)

    scores_by_news: dict[str, db.NewsImpactScoreModel] = {}
    query = (
        select(db.NewsImpactScoreModel)
        .where(db.NewsImpactScoreModel.model_id == model_id)
        .where(db.NewsImpactScoreModel.news_id.in_(news_ids))
        .order_by(db.NewsImpactScoreModel.inference_ts.desc())
    )
    for score in session.execute(query).scalars().all():
        scores_by_news.setdefault(score.news_id, score)

    news_published_by_id = {str(item.news_id): item.published_at for item in news_rows if item.news_id}
    event_items = (
        session.execute(
            select(db.NewsEventItemModel)
            .where(db.NewsEventItemModel.news_id.in_(news_ids))
            .order_by(db.NewsEventItemModel.added_at.desc())
        )
        .scalars()
        .all()
    )
    event_candidates_by_news: dict[str, list[db.NewsEventItemModel]] = {}
    for row in event_items:
        news_id = str(row.news_id or "").strip()
        event_id = str(row.event_id or "").strip()
        if not news_id or not event_id:
            continue
        event_candidates_by_news.setdefault(news_id, []).append(row)

    event_ids = sorted(
        {
            str(item.event_id or "").strip()
            for rows in event_candidates_by_news.values()
            for item in rows
            if str(item.event_id or "").strip()
        }
    )
    event_family_by_event: dict[str, str] = {}
    event_meta_by_event: dict[str, dict[str, object]] = {}
    if event_ids:
        event_labels = (
            session.execute(
                select(db.NewsLabelModel)
                .where(db.NewsLabelModel.target_level == "event")
                .where(db.NewsLabelModel.target_id.in_(event_ids))
                .order_by(db.NewsLabelModel.created_at.desc())
            )
            .scalars()
            .all()
        )
        for row in event_labels:
            event_id = str(row.target_id or "").strip()
            if not event_id or event_id in event_family_by_event:
                continue
            code = ""
            if isinstance(row.news_type_json, list):
                for item in row.news_type_json:
                    token = str(item or "").strip().upper()
                    if token and "_" in token:
                        code = token
                        break
            if not code and isinstance(row.evidence_json, dict):
                code = str(row.evidence_json.get("event_family") or "").strip().upper()
            if code:
                event_family_by_event[event_id] = code

        event_rows = (
            session.execute(select(db.NewsEventModel).where(db.NewsEventModel.event_id.in_(event_ids)))
            .scalars()
            .all()
        )
        for row in event_rows:
            event_id = str(row.event_id or "").strip()
            mechanism = str(row.canonical_mechanism or "").strip()
            mechanism_lower = mechanism.lower()
            event_meta_by_event[event_id] = {
                "event_ts": row.event_first_published_at_utc,
                "is_scheduled_anchor": "scheduled_anchor" in mechanism_lower,
            }
            if event_id in event_family_by_event:
                continue
            code = ""
            for chunk in mechanism.split("|"):
                if "=" not in chunk:
                    continue
                key, value = chunk.split("=", 1)
                if key.strip().lower() == "event_family":
                    code = value.strip().upper()
                    break
            if code:
                event_family_by_event[event_id] = code

    strict_anchor_window = timedelta(minutes=max(int(strict_anchor_window_minutes), 0))
    role_priority = {
        "primary": 0,
        "update": 1,
        "duplicate": 2,
        "scheduled_anchor": 3,
        "episodic_anchor": 4,
    }
    primary_event_by_news: dict[str, str] = {}
    for news_id, candidates in event_candidates_by_news.items():
        news_ts = news_published_by_id.get(news_id)
        ranked: list[tuple[tuple[float, float, float], str]] = []
        for candidate in candidates:
            event_id = str(candidate.event_id or "").strip()
            if not event_id:
                continue
            meta = event_meta_by_event.get(event_id) or {}
            event_ts = meta.get("event_ts")
            is_scheduled_anchor = bool(meta.get("is_scheduled_anchor"))
            if (
                strict_anchor_window.total_seconds() > 0
                and is_scheduled_anchor
                and isinstance(news_ts, datetime)
                and isinstance(event_ts, datetime)
                and abs((news_ts - event_ts).total_seconds()) > strict_anchor_window.total_seconds()
            ):
                continue

            role = str(candidate.link_role or "").strip().lower()
            role_rank = float(role_priority.get(role, 9))
            similarity = float(candidate.similarity_score or 0.0)
            added_at = candidate.added_at.timestamp() if isinstance(candidate.added_at, datetime) else 0.0
            ranked.append(((role_rank, -similarity, -added_at), event_id))
        if not ranked:
            continue
        ranked.sort(key=lambda item: item[0])
        primary_event_by_news[news_id] = ranked[0][1]

    samples: list[dict[str, object]] = []
    lag_limit = _resolve_quote_lag_limit(delta)

    for item in news_rows:
        score = scores_by_news.get(item.news_id)
        if score is None:
            continue
        links = links_by_news.get(item.news_id, [])
        if not links:
            continue
        ticker = str(links[0].ticker or links[0].entity_id or "").strip().upper()
        if not ticker:
            continue

        published_at = item.published_at
        start_point = _load_quote_point(session, ticker=ticker, ts=published_at)
        end_target_ts = published_at + delta
        end_point = _load_quote_point(session, ticker=ticker, ts=end_target_ts)
        if start_point is None or end_point is None:
            continue
        start_ts, start_price = start_point
        end_ts, end_price = end_point
        if (
            (start_ts - published_at) > lag_limit
            or (end_ts - end_target_ts) > lag_limit
            or start_price == 0
            or end_ts <= start_ts
        ):
            continue

        signed_return = (float(end_price) - float(start_price)) / float(start_price)
        actual_label = _label_return(signed_return, epsilon)
        pred_label = normalize_direction(score.direction)
        pred_confidence = max(float(score.prob_up), float(score.prob_down), float(score.prob_neutral))
        event_id = primary_event_by_news.get(item.news_id, "")
        event_family = event_family_by_event.get(event_id, "UNKNOWN")
        samples.append(
            {
                "news_id": item.news_id,
                "published_at": published_at,
                "ticker": ticker,
                "source": item.source,
                "pred_label": pred_label,
                "actual_label": actual_label,
                "signed_return": signed_return,
                "prob_up": float(score.prob_up),
                "prob_down": float(score.prob_down),
                "prob_neutral": float(score.prob_neutral),
                "pred_confidence": pred_confidence,
                "calibrated": bool(score.calibrated),
                "event_id": event_id,
                "event_family": event_family,
            }
        )
    normalized_level = str(evaluation_level or "article").strip().lower()
    if normalized_level == "event":
        return _aggregate_samples_to_event_level(samples, epsilon=epsilon)
    return samples

__all__ = [
    "_build_backtest_samples_v2",
    "_build_backtest_samples",
]
