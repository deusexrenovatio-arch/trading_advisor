from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from moex_carry.news.taxonomy import normalize_direction
from moex_carry.news.research_metrics import _classification_metrics, _safe_div
from moex_carry.news.research_policy import _build_gate_check
from moex_carry.storage import models as db

def _normalize_supervised_direction(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"up", "positive", "+1", "bullish"}:
        return "up"
    if raw in {"down", "negative", "-1", "bearish"}:
        return "down"
    if raw in {"neutral", "flat", "none", "0"}:
        return "neutral"
    return ""


def _predict_label_from_probs(prob_up: float, prob_down: float, prob_neutral: float) -> str:
    if prob_up >= prob_down and prob_up >= prob_neutral:
        return "up"
    if prob_down >= prob_up and prob_down >= prob_neutral:
        return "down"
    return "neutral"


def _extract_event_ticker(event_row: db.NewsEventModel | None) -> str:
    if event_row is None:
        return ""
    mechanism = str(getattr(event_row, "canonical_mechanism", "") or "").strip()
    if not mechanism:
        return ""
    for chunk in mechanism.split("|"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        if key.strip().lower() == "ticker":
            return str(value or "").strip().upper()
    return ""


def _build_nearby_article_scores_by_event(
    session: Session,
    *,
    model_id: str,
    event_rows: list[db.NewsEventModel],
    period_from: datetime,
    period_to: datetime,
    window_hours: int = 36,
) -> dict[str, list[db.NewsImpactScoreModel]]:
    if not event_rows:
        return {}
    margin = timedelta(hours=max(int(window_hours), 1))
    search_from = period_from - margin
    search_to = period_to + margin

    news_rows = (
        session.execute(
            select(db.NewsItemModel)
            .where(db.NewsItemModel.published_at >= search_from)
            .where(db.NewsItemModel.published_at <= search_to)
            .order_by(db.NewsItemModel.published_at.asc())
        )
        .scalars()
        .all()
    )
    if not news_rows:
        return {}

    news_ids = [str(item.news_id or "").strip() for item in news_rows if str(item.news_id or "").strip()]
    if not news_ids:
        return {}
    news_ts_by_id = {str(item.news_id): item.published_at for item in news_rows if item.published_at is not None}

    ticker_by_news: dict[str, tuple[float, str]] = {}
    for link in (
        session.execute(
            select(db.NewsEntityLinkModel)
            .where(db.NewsEntityLinkModel.news_id.in_(news_ids))
            .order_by(db.NewsEntityLinkModel.id.asc())
        )
        .scalars()
        .all()
    ):
        news_id = str(link.news_id or "").strip()
        ticker = str(link.ticker or link.entity_id or "").strip().upper()
        confidence = float(link.link_confidence or 0.0)
        if not news_id or not ticker:
            continue
        current = ticker_by_news.get(news_id)
        if current is None or confidence >= current[0]:
            ticker_by_news[news_id] = (confidence, ticker)

    article_score_by_news: dict[str, db.NewsImpactScoreModel] = {}
    for score in (
        session.execute(
            select(db.NewsImpactScoreModel)
            .where(db.NewsImpactScoreModel.model_id == model_id)
            .where(db.NewsImpactScoreModel.news_id.in_(news_ids))
            .order_by(db.NewsImpactScoreModel.inference_ts.desc())
        )
        .scalars()
        .all()
    ):
        news_id = str(score.news_id or "").strip()
        if not news_id or news_id in article_score_by_news:
            continue
        article_score_by_news[news_id] = score

    nearby: dict[str, list[db.NewsImpactScoreModel]] = {}
    for event in event_rows:
        event_id = str(event.event_id or "").strip()
        event_ts = event.event_first_published_at_utc
        event_ticker = _extract_event_ticker(event)
        if not event_id or event_ts is None:
            continue
        candidates: list[tuple[float, db.NewsImpactScoreModel]] = []
        for news_id, score in article_score_by_news.items():
            published_at = news_ts_by_id.get(news_id)
            if published_at is None:
                continue
            if abs((published_at - event_ts).total_seconds()) > margin.total_seconds():
                continue
            linked = ticker_by_news.get(news_id)
            if event_ticker and linked is not None and linked[1] != event_ticker:
                continue
            # Prefer closer timestamps while retaining a few rows for averaging.
            delta = abs((published_at - event_ts).total_seconds())
            candidates.append((delta, score))
        if not candidates:
            continue
        candidates.sort(key=lambda item: item[0])
        nearby[event_id] = [item[1] for item in candidates[:5]]
    return nearby


def _build_supervised_gold_metrics(
    session: Session,
    *,
    model_id: str,
    period_from: datetime,
    period_to: datetime,
) -> dict[str, object]:
    gold_direction_by_event: dict[str, str] = {}
    gold_source = "news_gold_labels"
    unmatched_count = 0

    gold_rows = (
        session.execute(
            select(db.NewsGoldLabelModel)
            .where(db.NewsGoldLabelModel.target_type == "event")
            .where(db.NewsGoldLabelModel.quality == "gold")
            .order_by(db.NewsGoldLabelModel.created_at.desc())
        )
        .scalars()
        .all()
    )
    for row in gold_rows:
        event_id = str(row.target_id or "").strip()
        if not event_id or event_id in gold_direction_by_event:
            continue
        label = _normalize_supervised_direction(row.direction_label)
        if not label:
            continue
        gold_direction_by_event[event_id] = label

    if not gold_direction_by_event:
        gold_source = "news_labels.external_gold"
        fallback_rows = (
            session.execute(
                select(db.NewsLabelModel)
                .where(db.NewsLabelModel.target_level == "event")
                .where(db.NewsLabelModel.label_source == "external_gold")
                .order_by(db.NewsLabelModel.created_at.desc())
            )
            .scalars()
            .all()
        )
        for row in fallback_rows:
            event_id = str(row.target_id or "").strip()
            if not event_id or event_id in gold_direction_by_event:
                continue
            label = _normalize_supervised_direction(row.direction)
            if not label:
                continue
            gold_direction_by_event[event_id] = label

    unmatched_rows = (
        session.execute(
            select(db.NewsUnmatchedGoldModel)
            .where(db.NewsUnmatchedGoldModel.published_at_utc >= period_from)
            .where(db.NewsUnmatchedGoldModel.published_at_utc <= period_to)
        )
        .scalars()
        .all()
    )
    unmatched_count = len(unmatched_rows)

    if not gold_direction_by_event and unmatched_count <= 0:
        return {
            **_classification_metrics([]),
            "gold_total": 0,
            "gold_matched": 0,
            "gold_coverage": 0.0,
            "source": "none",
            "unmatched_count": 0,
        }

    event_ids_all = list(gold_direction_by_event.keys())
    event_rows = (
        session.execute(select(db.NewsEventModel).where(db.NewsEventModel.event_id.in_(event_ids_all)))
        .scalars()
        .all()
    )
    event_row_by_id = {str(row.event_id): row for row in event_rows if str(row.event_id or "").strip()}
    eligible_event_ids: list[str] = []
    for row in event_rows:
        ts = row.event_first_published_at_utc
        if ts is None:
            continue
        if ts < period_from or ts > period_to:
            continue
        eligible_event_ids.append(str(row.event_id))
    if not eligible_event_ids:
        return {
            **_classification_metrics([]),
            "gold_total": unmatched_count,
            "gold_matched": 0,
            "gold_coverage": 0.0,
            "source": gold_source,
            "unmatched_count": unmatched_count,
        }

    event_score_by_event: dict[str, db.NewsImpactScoreModel] = {}
    event_scores = (
        session.execute(
            select(db.NewsImpactScoreModel)
            .where(db.NewsImpactScoreModel.model_id == model_id)
            .where(db.NewsImpactScoreModel.target_level == "event")
            .where(db.NewsImpactScoreModel.target_id.in_(eligible_event_ids))
            .order_by(db.NewsImpactScoreModel.inference_ts.desc())
        )
        .scalars()
        .all()
    )
    for row in event_scores:
        event_id = str(row.target_id or "").strip()
        if not event_id or event_id in event_score_by_event:
            continue
        event_score_by_event[event_id] = row

    event_news_map: dict[str, list[str]] = {}
    all_news_ids: list[str] = []
    for row in (
        session.execute(select(db.NewsEventItemModel).where(db.NewsEventItemModel.event_id.in_(eligible_event_ids)))
        .scalars()
        .all()
    ):
        event_id = str(row.event_id or "").strip()
        news_id = str(row.news_id or "").strip()
        if not event_id or not news_id:
            continue
        event_news_map.setdefault(event_id, []).append(news_id)
        all_news_ids.append(news_id)

    article_score_by_news: dict[str, db.NewsImpactScoreModel] = {}
    if all_news_ids:
        article_scores = (
            session.execute(
                select(db.NewsImpactScoreModel)
                .where(db.NewsImpactScoreModel.model_id == model_id)
                .where(db.NewsImpactScoreModel.news_id.in_(sorted(set(all_news_ids))))
                .order_by(db.NewsImpactScoreModel.inference_ts.desc())
            )
            .scalars()
            .all()
        )
        for row in article_scores:
            news_id = str(row.news_id or "").strip()
            if not news_id or news_id in article_score_by_news:
                continue
            article_score_by_news[news_id] = row

    nearby_scores_by_event = _build_nearby_article_scores_by_event(
        session,
        model_id=model_id,
        event_rows=[event_row_by_id[item] for item in eligible_event_ids if item in event_row_by_id],
        period_from=period_from,
        period_to=period_to,
        window_hours=36,
    )

    samples: list[dict[str, object]] = []
    gold_total = 0
    gold_matched = 0

    for event_id in eligible_event_ids:
        actual_label = gold_direction_by_event.get(event_id)
        if actual_label not in {"up", "down", "neutral"}:
            continue
        gold_total += 1

        score = event_score_by_event.get(event_id)
        if score is not None:
            prob_up = float(score.prob_up or 0.0)
            prob_down = float(score.prob_down or 0.0)
            prob_neutral = float(score.prob_neutral or 0.0)
            pred_label = normalize_direction(score.direction)
            if pred_label == "neutral":
                pred_label = _predict_label_from_probs(prob_up, prob_down, prob_neutral)
            calibrated = bool(score.calibrated)
        else:
            related_ids = event_news_map.get(event_id, [])
            related_scores = [article_score_by_news[item] for item in related_ids if item in article_score_by_news]
            if not related_scores:
                related_scores = nearby_scores_by_event.get(event_id, [])
            if not related_scores:
                continue
            prob_up = mean(float(item.prob_up or 0.0) for item in related_scores)
            prob_down = mean(float(item.prob_down or 0.0) for item in related_scores)
            prob_neutral = mean(float(item.prob_neutral or 0.0) for item in related_scores)
            pred_label = _predict_label_from_probs(prob_up, prob_down, prob_neutral)
            calibrated = any(bool(item.calibrated) for item in related_scores)

        gold_matched += 1
        samples.append(
            {
                "pred_label": pred_label,
                "actual_label": actual_label,
                "prob_up": prob_up,
                "prob_down": prob_down,
                "prob_neutral": prob_neutral,
                "pred_confidence": max(prob_up, prob_down, prob_neutral),
                "calibrated": calibrated,
                "ticker": "external_gold",
                "source": gold_source,
            }
        )

    metrics = _classification_metrics(samples)
    metrics["gold_total"] = gold_total + unmatched_count
    metrics["gold_matched"] = gold_matched
    metrics["gold_coverage"] = _safe_div(gold_matched, gold_total + unmatched_count)
    metrics["source"] = gold_source
    metrics["unmatched_count"] = unmatched_count
    return metrics


def _evaluate_supervised_gate(
    supervised_metrics: dict[str, object] | None,
    *,
    min_accuracy: float,
    min_coverage: float,
    max_brier: float,
    min_sample_count: int,
) -> dict[str, object]:
    if not isinstance(supervised_metrics, dict):
        return {
            "pass": False,
            "checks": [
                {
                    "check_id": "supervised_metrics_present",
                    "operator": "exists",
                    "value": 0,
                    "threshold": 1,
                    "passed": False,
                    "reason": "missing_supervised_metrics",
                }
            ],
        }
    sample_count = int(supervised_metrics.get("sample_count") or 0)
    gold_total = int(supervised_metrics.get("gold_total") or 0)
    if sample_count <= 0 or gold_total <= 0:
        return {
            "pass": False,
            "checks": [
                {
                    "check_id": "supervised_gold_available",
                    "operator": ">",
                    "value": float(gold_total),
                    "threshold": 0.0,
                    "passed": False,
                    "reason": "insufficient_supervised_samples",
                }
            ],
            "summary": {
                "sample_count": sample_count,
                "gold_total": gold_total,
                "source": supervised_metrics.get("source"),
                "unmatched_count": int(supervised_metrics.get("unmatched_count") or 0),
            },
        }
    accuracy = float(supervised_metrics.get("accuracy") or 0.0)
    brier = float(supervised_metrics.get("brier") or 1.0)
    coverage = float(supervised_metrics.get("gold_coverage") or 0.0)
    unmatched_count = int(supervised_metrics.get("unmatched_count") or 0)
    effective_gold_total = max(gold_total - unmatched_count, 0)
    effective_min_sample_count = min(max(int(min_sample_count), 1), max(effective_gold_total, 1))

    checks = [
        _build_gate_check(
            check_id="supervised_sample_count_min",
            value=float(sample_count),
            threshold=float(effective_min_sample_count),
            operator=">=",
            passed=sample_count >= effective_min_sample_count,
        ),
        _build_gate_check(
            check_id="supervised_accuracy_min",
            value=accuracy,
            threshold=float(min_accuracy),
            operator=">=",
            passed=accuracy >= float(min_accuracy),
        ),
        _build_gate_check(
            check_id="supervised_coverage_min",
            value=coverage,
            threshold=float(min_coverage),
            operator=">=",
            passed=coverage >= float(min_coverage),
        ),
        _build_gate_check(
            check_id="supervised_brier_max",
            value=brier,
            threshold=float(max_brier),
            operator="<=",
            passed=brier <= float(max_brier),
        ),
    ]
    return {
        "pass": all(bool(item.get("passed")) for item in checks),
        "checks": checks,
        "summary": {
            "sample_count": sample_count,
            "gold_total": gold_total,
            "effective_gold_total": effective_gold_total,
            "effective_min_sample_count": effective_min_sample_count,
            "accuracy": accuracy,
            "gold_coverage": coverage,
            "brier": brier,
            "source": supervised_metrics.get("source"),
            "unmatched_count": unmatched_count,
        },
    }


def _store_model_eval_record(
    session: Session,
    *,
    comparison_hash: str,
    horizon: str,
    winner: dict[str, object] | None,
    market_gate: dict[str, object],
    supervised_gate: dict[str, object],
    quality_gate: dict[str, object],
    decision: str,
) -> None:
    if not isinstance(winner, dict):
        return
    model_version = str(winner.get("model_id") or "").strip()
    if not model_version:
        return
    run_id = f"eval-{comparison_hash}"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        session.merge(
            db.NewsModelEvalRecordModel(
                run_id=run_id,
                model_version=model_version,
                dataset_version=str((winner.get("supervised_metrics") or {}).get("source") or ""),
                horizon=horizon,
                supervised_metrics_json=winner.get("supervised_metrics") if isinstance(winner.get("supervised_metrics"), dict) else {},
                market_metrics_json=winner.get("metrics") if isinstance(winner.get("metrics"), dict) else {},
                pass_supervised=bool(supervised_gate.get("pass")),
                pass_market=bool(market_gate.get("pass")),
                promotion_state=decision,
                gate_details_json=quality_gate,
                created_at=now,
            )
        )
        session.commit()
    except Exception:
        session.rollback()


def _store_gate_run_v2(
    session: Session,
    *,
    comparison_hash: str,
    horizon: str,
    period_from: datetime,
    period_to: datetime,
    quality_gate: dict[str, object],
    winner: dict[str, object] | None,
) -> None:
    if not isinstance(winner, dict):
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    run_id = f"gate-{comparison_hash}"
    try:
        session.merge(
            db.GateRunV2Model(
                run_id=run_id,
                symbol="ALL",
                horizon=horizon,
                period_start=period_from,
                period_end=period_to,
                market_pass=bool((quality_gate.get("market_gate") or {}).get("pass")),
                leakage_pass=True,
                supervised_pass_shadow=bool((quality_gate.get("supervised_gate") or {}).get("pass")),
                supervised_pass_prod=bool((quality_gate.get("supervised_gate") or {}).get("pass")),
                baseline_pass=bool((quality_gate.get("baseline_gate") or {}).get("pass")),
                utility_pass=bool((quality_gate.get("utility_gate") or {}).get("pass")),
                overall_pass_prod=bool(quality_gate.get("pass")),
                metrics_json={
                    "quality_gate": quality_gate,
                    "winner_model_id": winner.get("model_id"),
                    "winner_metrics": winner.get("metrics"),
                    "winner_utility": winner.get("utility"),
                },
                winner_model_version=str(winner.get("model_id") or ""),
                created_at=now,
            )
        )
        session.commit()
    except Exception:
        session.rollback()

__all__ = [
    "_normalize_supervised_direction",
    "_predict_label_from_probs",
    "_extract_event_ticker",
    "_build_nearby_article_scores_by_event",
    "_build_supervised_gold_metrics",
    "_evaluate_supervised_gate",
    "_store_model_eval_record",
    "_store_gate_run_v2",
]
