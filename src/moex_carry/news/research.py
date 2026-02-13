from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from moex_carry.news.taxonomy import normalize_direction
from moex_carry.storage import models as db


def _horizon_to_delta(horizon: str) -> timedelta:
    raw = str(horizon or "1d").strip().lower()
    mapping = {
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
        "5d": timedelta(days=5),
    }
    return mapping.get(raw, timedelta(days=1))


def _label_return(value: float, epsilon: float) -> str:
    if value > epsilon:
        return "up"
    if value < -epsilon:
        return "down"
    return "neutral"


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _classification_metrics(samples: list[dict[str, object]]) -> dict[str, object]:
    if not samples:
        return {
            "accuracy": 0.0,
            "precision_up": 0.0,
            "precision_down": 0.0,
            "recall_up": 0.0,
            "recall_down": 0.0,
            "f1_up": 0.0,
            "f1_down": 0.0,
            "brier": 0.0,
            "coverage": 0.0,
            "neutral_rate": 0.0,
            "reliability_bins": [],
        }

    total = len(samples)
    correct = sum(1 for item in samples if item["pred_label"] == item["actual_label"])

    pred_up = [item for item in samples if item["pred_label"] == "up"]
    pred_down = [item for item in samples if item["pred_label"] == "down"]
    act_up = [item for item in samples if item["actual_label"] == "up"]
    act_down = [item for item in samples if item["actual_label"] == "down"]

    tp_up = sum(1 for item in pred_up if item["actual_label"] == "up")
    tp_down = sum(1 for item in pred_down if item["actual_label"] == "down")

    precision_up = _safe_div(tp_up, len(pred_up))
    precision_down = _safe_div(tp_down, len(pred_down))
    recall_up = _safe_div(tp_up, len(act_up))
    recall_down = _safe_div(tp_down, len(act_down))

    f1_up = _safe_div(2 * precision_up * recall_up, precision_up + recall_up)
    f1_down = _safe_div(2 * precision_down * recall_down, precision_down + recall_down)

    brier_values: list[float] = []
    for item in samples:
        prob_up = float(item.get("prob_up") or 0.0)
        prob_down = float(item.get("prob_down") or 0.0)
        prob_neutral = float(item.get("prob_neutral") or 0.0)
        y_up = 1.0 if item["actual_label"] == "up" else 0.0
        y_down = 1.0 if item["actual_label"] == "down" else 0.0
        y_neutral = 1.0 if item["actual_label"] == "neutral" else 0.0
        brier_values.append(
            ((prob_up - y_up) ** 2 + (prob_down - y_down) ** 2 + (prob_neutral - y_neutral) ** 2) / 3.0
        )

    directional_predictions = [item for item in samples if item["pred_label"] in {"up", "down"}]
    neutral_predictions = [item for item in samples if item["pred_label"] == "neutral"]

    reliability_bins: list[dict[str, object]] = []
    for idx in range(10):
        low = idx / 10.0
        high = (idx + 1) / 10.0
        bucket = [
            item
            for item in samples
            if low <= float(item.get("pred_confidence") or 0.0) < high
            or (idx == 9 and float(item.get("pred_confidence") or 0.0) == 1.0)
        ]
        if not bucket:
            continue
        reliability_bins.append(
            {
                "bin": f"{low:.1f}-{high:.1f}",
                "count": len(bucket),
                "avg_confidence": mean(float(item.get("pred_confidence") or 0.0) for item in bucket),
                "accuracy": _safe_div(
                    sum(1 for item in bucket if item["pred_label"] == item["actual_label"]),
                    len(bucket),
                ),
            }
        )

    return {
        "accuracy": _safe_div(correct, total),
        "precision_up": precision_up,
        "precision_down": precision_down,
        "recall_up": recall_up,
        "recall_down": recall_down,
        "f1_up": f1_up,
        "f1_down": f1_down,
        "brier": mean(brier_values) if brier_values else 0.0,
        "coverage": _safe_div(len(directional_predictions), total),
        "neutral_rate": _safe_div(len(neutral_predictions), total),
        "reliability_bins": reliability_bins,
    }


def _load_quote_price(session: Session, *, ticker: str, ts: datetime) -> float | None:
    row = (
        session.execute(
            select(db.QuoteModel)
            .where(db.QuoteModel.secid == ticker)
            .where(db.QuoteModel.timestamp >= ts)
            .order_by(db.QuoteModel.timestamp.asc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if row is None:
        return None
    candidates = [row.last, row.bid, row.ask]
    for value in candidates:
        if value is not None:
            return float(value)
    return None


def _slice_metrics(samples: list[dict[str, object]], key: str) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for item in samples:
        value = str(item.get(key) or "unknown")
        grouped.setdefault(value, []).append(item)
    return {
        item_key: _classification_metrics(item_samples)
        for item_key, item_samples in sorted(grouped.items(), key=lambda kv: kv[0])
    }


def run_news_backtest(
    session: Session,
    *,
    model_id: str,
    horizon: str,
    period_from: datetime,
    period_to: datetime,
    epsilon: float,
) -> dict[str, object]:
    delta = _horizon_to_delta(horizon)
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
        return {
            "model_id": model_id,
            "horizon": horizon,
            "period": {
                "from": period_from.isoformat() + "Z",
                "to": period_to.isoformat() + "Z",
            },
            "sample_count": 0,
            "metrics": _classification_metrics([]),
            "slices": {
                "ticker": {},
                "source": {},
            },
        }

    links_by_news: dict[str, list[db.NewsEntityLinkModel]] = {}
    for link in (
        session.execute(select(db.NewsEntityLinkModel).order_by(db.NewsEntityLinkModel.id.asc()))
        .scalars()
        .all()
    ):
        links_by_news.setdefault(link.news_id, []).append(link)

    scores_by_news: dict[str, db.NewsImpactScoreModel] = {}
    query = (
        select(db.NewsImpactScoreModel)
        .where(db.NewsImpactScoreModel.model_id == model_id)
        .order_by(db.NewsImpactScoreModel.inference_ts.desc())
    )
    for score in session.execute(query).scalars().all():
        scores_by_news.setdefault(score.news_id, score)

    samples: list[dict[str, object]] = []
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
        start_price = _load_quote_price(session, ticker=ticker, ts=published_at)
        end_price = _load_quote_price(session, ticker=ticker, ts=published_at + delta)
        if start_price is None or end_price is None or start_price == 0:
            continue

        signed_return = (float(end_price) - float(start_price)) / float(start_price)
        actual_label = _label_return(signed_return, epsilon)
        pred_label = normalize_direction(score.direction)
        pred_confidence = max(float(score.prob_up), float(score.prob_down), float(score.prob_neutral))
        samples.append(
            {
                "news_id": item.news_id,
                "ticker": ticker,
                "source": item.source,
                "pred_label": pred_label,
                "actual_label": actual_label,
                "signed_return": signed_return,
                "prob_up": float(score.prob_up),
                "prob_down": float(score.prob_down),
                "prob_neutral": float(score.prob_neutral),
                "pred_confidence": pred_confidence,
            }
        )

    metrics = _classification_metrics(samples)
    return {
        "model_id": model_id,
        "horizon": horizon,
        "period": {
            "from": period_from.isoformat() + "Z",
            "to": period_to.isoformat() + "Z",
        },
        "sample_count": len(samples),
        "epsilon": epsilon,
        "metrics": metrics,
        "slices": {
            "ticker": _slice_metrics(samples, "ticker"),
            "source": _slice_metrics(samples, "source"),
        },
    }


def compare_news_models(
    session: Session,
    *,
    model_ids: list[str],
    horizon: str,
    period_from: datetime,
    period_to: datetime,
    epsilon: float,
) -> dict[str, object]:
    reports: list[dict[str, object]] = []
    for model_id in model_ids:
        reports.append(
            run_news_backtest(
                session,
                model_id=model_id,
                horizon=horizon,
                period_from=period_from,
                period_to=period_to,
                epsilon=epsilon,
            )
        )

    def _score(report: dict[str, object]) -> tuple[float, float, int]:
        metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
        accuracy = float(metrics.get("accuracy") or 0.0)
        brier = float(metrics.get("brier") or 0.0)
        sample_count = int(report.get("sample_count") or 0)
        return (accuracy, -brier, sample_count)

    sorted_reports = sorted(reports, key=_score, reverse=True)
    winner = sorted_reports[0] if sorted_reports else None

    comparison = {
        "horizon": horizon,
        "period": {
            "from": period_from.isoformat() + "Z",
            "to": period_to.isoformat() + "Z",
        },
        "epsilon": epsilon,
        "reports": reports,
        "winner": {
            "model_id": winner.get("model_id") if isinstance(winner, dict) else None,
            "reason": "best_oos_accuracy_then_brier",
        },
        "audit": {
            "decision": "promote" if isinstance(winner, dict) and int(winner.get("sample_count") or 0) > 0 else "hold",
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "comparison_hash": hashlib.sha1(
                f"{horizon}|{period_from.isoformat()}|{period_to.isoformat()}|{','.join(model_ids)}".encode(
                    "utf-8"
                )
            ).hexdigest()[:20],
        },
    }
    return comparison
