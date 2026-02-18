from __future__ import annotations

from collections import Counter
import hashlib
import importlib
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from moex_carry.news.taxonomy import normalize_direction
from moex_carry.storage import models as db


def _safe_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _horizon_to_delta(horizon: str) -> timedelta:
    raw = str(horizon or "1d").strip().lower()
    mapping = {
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
        "5d": timedelta(days=5),
    }
    if raw in mapping:
        return mapping[raw]
    try:
        if raw.endswith("m"):
            return timedelta(minutes=max(int(raw[:-1]), 1))
        if raw.endswith("h"):
            return timedelta(hours=max(int(raw[:-1]), 1))
        if raw.endswith("d"):
            return timedelta(days=max(int(raw[:-1]), 1))
    except ValueError:
        pass
    return timedelta(days=1)


def _normalize_calibration_mode(value: str | None) -> str:
    raw = str(value or "none").strip().lower()
    if raw in {"platt", "isotonic", "none"}:
        return raw
    return "none"


def _label_return(value: float, epsilon: float) -> str:
    if value > epsilon:
        return "up"
    if value < -epsilon:
        return "down"
    return "neutral"


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _normalize_prob_triplet(prob_up: float, prob_down: float, prob_neutral: float) -> tuple[float, float, float]:
    values = [max(float(prob_up), 0.0), max(float(prob_down), 0.0), max(float(prob_neutral), 0.0)]
    total = sum(values)
    if total <= 0.0:
        return 0.0, 0.0, 1.0
    return values[0] / total, values[1] / total, values[2] / total


def _classification_metrics(samples: list[dict[str, object]]) -> dict[str, object]:
    if not samples:
        return {
            "sample_count": 0,
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
            "calibrated_rate": 0.0,
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
    calibrated_predictions = [item for item in samples if bool(item.get("calibrated"))]

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
        "sample_count": total,
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
        "calibrated_rate": _safe_div(len(calibrated_predictions), total),
        "reliability_bins": reliability_bins,
    }


def _sample_group_key(sample: dict[str, object]) -> str:
    event_id = str(sample.get("event_id") or "").strip()
    if event_id:
        return f"event:{event_id}"
    ticker = str(sample.get("ticker") or "").strip().upper()
    published_at = sample.get("published_at")
    if isinstance(published_at, datetime):
        return f"ts:{ticker}:{published_at.isoformat()}"
    news_id = str(sample.get("news_id") or "").strip()
    return f"news:{news_id}"


def _resolve_group_event_family(rows: list[dict[str, object]]) -> str:
    families = [
        str(item.get("event_family") or "").strip().upper()
        for item in rows
        if str(item.get("event_family") or "").strip()
    ]
    if not families:
        return "UNKNOWN"
    non_unknown = [value for value in families if value != "UNKNOWN"]
    chosen = non_unknown if non_unknown else families
    return Counter(chosen).most_common(1)[0][0]


def _aggregate_samples_to_event_level(
    samples: list[dict[str, object]],
    *,
    epsilon: float,
) -> list[dict[str, object]]:
    if not samples:
        return []
    grouped: dict[str, list[dict[str, object]]] = {}
    for item in samples:
        grouped.setdefault(_sample_group_key(item), []).append(item)

    collapsed: list[dict[str, object]] = []
    for rows in grouped.values():
        ordered = sorted(
            rows,
            key=lambda row: (
                row.get("published_at") if isinstance(row.get("published_at"), datetime) else datetime.min,
                str(row.get("news_id") or ""),
            ),
        )
        ref = dict(ordered[0])
        avg_return = mean(float(item.get("signed_return") or 0.0) for item in rows)
        avg_prob_up = mean(float(item.get("prob_up") or 0.0) for item in rows)
        avg_prob_down = mean(float(item.get("prob_down") or 0.0) for item in rows)
        avg_prob_neutral = mean(float(item.get("prob_neutral") or 0.0) for item in rows)
        prob_up, prob_down, prob_neutral = _normalize_prob_triplet(
            avg_prob_up,
            avg_prob_down,
            avg_prob_neutral,
        )
        pred_label = "neutral"
        if prob_up >= prob_down and prob_up >= prob_neutral:
            pred_label = "up"
        elif prob_down >= prob_up and prob_down >= prob_neutral:
            pred_label = "down"
        ref["signed_return"] = avg_return
        ref["actual_label"] = _label_return(avg_return, epsilon)
        ref["prob_up"] = prob_up
        ref["prob_down"] = prob_down
        ref["prob_neutral"] = prob_neutral
        ref["pred_label"] = pred_label
        ref["pred_confidence"] = max(prob_up, prob_down, prob_neutral)
        ref["calibrated"] = any(bool(item.get("calibrated")) for item in rows)
        ref["event_family"] = _resolve_group_event_family(rows)
        ref["event_sample_size"] = len(rows)
        collapsed.append(ref)

    return sorted(
        collapsed,
        key=lambda row: (
            row.get("published_at") if isinstance(row.get("published_at"), datetime) else datetime.min,
            str(row.get("news_id") or ""),
        ),
    )


def _resolve_quote_lag_limit(delta: timedelta) -> timedelta:
    minutes = int(max(delta.total_seconds() / 60.0, 1.0))
    if minutes <= 5:
        return timedelta(minutes=10)
    if minutes <= 60:
        return timedelta(minutes=60)
    if minutes <= 240:
        return timedelta(minutes=240)
    if minutes <= 24 * 60:
        return timedelta(hours=18)
    return timedelta(days=3)


def _load_quote_point(session: Session, *, ticker: str, ts: datetime) -> tuple[datetime, float] | None:
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
            return row.timestamp, float(value)
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


def _normalize_label_direction(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"up", "positive", "bullish"}:
        return "up"
    if raw in {"down", "negative", "bearish"}:
        return "down"
    if raw in {"neutral", "uncertain"}:
        return "neutral"
    return "neutral"


def _direction_triplet(label: str) -> tuple[float, float, float]:
    if label == "up":
        return 0.75, 0.10, 0.15
    if label == "down":
        return 0.10, 0.75, 0.15
    return 0.10, 0.10, 0.80


def _build_calendar_direction_by_news(session: Session, *, news_ids: list[str]) -> dict[str, str]:
    if not news_ids:
        return {}

    event_items = (
        session.execute(
            select(db.NewsEventItemModel)
            .where(db.NewsEventItemModel.news_id.in_(news_ids))
            .order_by(db.NewsEventItemModel.added_at.desc())
        )
        .scalars()
        .all()
    )
    event_by_news: dict[str, str] = {}
    for row in event_items:
        news_id = str(row.news_id or "").strip()
        event_id = str(row.event_id or "").strip()
        if not news_id or not event_id:
            continue
        event_by_news.setdefault(news_id, event_id)
    if not event_by_news:
        return {}

    event_ids = sorted({value for value in event_by_news.values() if value})
    label_rows = (
        session.execute(
            select(db.NewsLabelModel)
            .where(db.NewsLabelModel.target_level == "event")
            .where(db.NewsLabelModel.target_id.in_(event_ids))
            .order_by(db.NewsLabelModel.created_at.desc())
        )
        .scalars()
        .all()
    )
    priority = {
        "external_gold": 1,
        "anchor_schedule": 2,
        "anchor_episode": 3,
        "llm": 4,
        "model": 5,
        "rules": 6,
        "human": 7,
    }
    by_event: dict[str, tuple[int, str]] = {}
    for row in label_rows:
        event_id = str(row.target_id or "").strip()
        if not event_id:
            continue
        source = str(row.label_source or "").strip().lower()
        rank = int(priority.get(source, 99))
        direction = _normalize_label_direction(row.direction)
        current = by_event.get(event_id)
        if current is None or rank < current[0]:
            by_event[event_id] = (rank, direction)

    result: dict[str, str] = {}
    for news_id, event_id in event_by_news.items():
        picked = by_event.get(event_id)
        if picked is None:
            continue
        result[news_id] = picked[1]
    return result


def _apply_baseline_no_news(samples: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for sample in samples:
        prob_up, prob_down, prob_neutral = _direction_triplet("neutral")
        rows.append(
            {
                **sample,
                "pred_label": "neutral",
                "prob_up": prob_up,
                "prob_down": prob_down,
                "prob_neutral": prob_neutral,
                "pred_confidence": max(prob_up, prob_down, prob_neutral),
                "baseline": "no_news",
            }
        )
    return rows


def _apply_baseline_majority_class(samples: list[dict[str, object]]) -> list[dict[str, object]]:
    if not samples:
        return []
    actual_counter = Counter(str(item.get("actual_label") or "neutral") for item in samples)
    majority_label = actual_counter.most_common(1)[0][0] if actual_counter else "neutral"
    prob_up, prob_down, prob_neutral = _direction_triplet(majority_label)
    rows: list[dict[str, object]] = []
    for sample in samples:
        rows.append(
            {
                **sample,
                "pred_label": majority_label,
                "prob_up": prob_up,
                "prob_down": prob_down,
                "prob_neutral": prob_neutral,
                "pred_confidence": max(prob_up, prob_down, prob_neutral),
                "baseline": "majority_class",
            }
        )
    return rows


def _apply_baseline_calendar_only(
    samples: list[dict[str, object]],
    *,
    direction_by_news: dict[str, str],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for sample in samples:
        news_id = str(sample.get("news_id") or "").strip()
        label = direction_by_news.get(news_id, "neutral")
        prob_up, prob_down, prob_neutral = _direction_triplet(label)
        rows.append(
            {
                **sample,
                "pred_label": label,
                "prob_up": prob_up,
                "prob_down": prob_down,
                "prob_neutral": prob_neutral,
                "pred_confidence": max(prob_up, prob_down, prob_neutral),
                "baseline": "calendar_only",
            }
        )
    return rows


def _apply_baseline_calendar_plus_text(
    samples: list[dict[str, object]],
    *,
    direction_by_news: dict[str, str],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for sample in samples:
        news_id = str(sample.get("news_id") or "").strip()
        direction = direction_by_news.get(news_id)
        prob_up = float(sample.get("prob_up") or 0.0)
        prob_down = float(sample.get("prob_down") or 0.0)
        prob_neutral = float(sample.get("prob_neutral") or 0.0)
        if direction == "up":
            prob_up += 0.25
        elif direction == "down":
            prob_down += 0.25
        elif direction == "neutral":
            prob_neutral += 0.25
        prob_up, prob_down, prob_neutral = _normalize_prob_triplet(prob_up, prob_down, prob_neutral)
        pred_label = "neutral"
        if prob_up >= prob_down and prob_up >= prob_neutral:
            pred_label = "up"
        elif prob_down >= prob_up and prob_down >= prob_neutral:
            pred_label = "down"
        rows.append(
            {
                **sample,
                "pred_label": pred_label,
                "prob_up": prob_up,
                "prob_down": prob_down,
                "prob_neutral": prob_neutral,
                "pred_confidence": max(prob_up, prob_down, prob_neutral),
                "baseline": "calendar_plus_text",
            }
        )
    return rows


def _build_ablation_reports(samples: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    if not samples:
        return {}
    ordered = sorted(samples, key=lambda row: str(row.get("news_id") or ""))
    shifted: list[dict[str, object]] = []
    for idx, sample in enumerate(ordered):
        donor = ordered[(idx + 1) % len(ordered)]
        shifted.append(
            {
                **sample,
                "pred_label": donor.get("pred_label"),
                "prob_up": donor.get("prob_up"),
                "prob_down": donor.get("prob_down"),
                "prob_neutral": donor.get("prob_neutral"),
                "pred_confidence": donor.get("pred_confidence"),
            }
        )

    permuted = list(reversed(ordered))
    permuted_rows: list[dict[str, object]] = []
    for sample, donor in zip(ordered, permuted):
        permuted_rows.append(
            {
                **sample,
                "pred_label": donor.get("pred_label"),
                "prob_up": donor.get("prob_up"),
                "prob_down": donor.get("prob_down"),
                "prob_neutral": donor.get("prob_neutral"),
                "pred_confidence": donor.get("pred_confidence"),
            }
        )

    by_ticker: dict[str, list[dict[str, object]]] = {}
    for sample in ordered:
        ticker = str(sample.get("ticker") or "").strip()
        by_ticker.setdefault(ticker, []).append(sample)
    tickers = sorted([ticker for ticker in by_ticker.keys() if ticker])
    negative_rows: list[dict[str, object]] = []
    if len(tickers) >= 2:
        for idx, ticker in enumerate(tickers):
            donor_ticker = tickers[(idx + 1) % len(tickers)]
            donors = by_ticker.get(donor_ticker, [])
            if not donors:
                continue
            for sample_idx, sample in enumerate(by_ticker.get(ticker, [])):
                donor = donors[sample_idx % len(donors)]
                negative_rows.append(
                    {
                        **sample,
                        "pred_label": donor.get("pred_label"),
                        "prob_up": donor.get("prob_up"),
                        "prob_down": donor.get("prob_down"),
                        "prob_neutral": donor.get("prob_neutral"),
                        "pred_confidence": donor.get("pred_confidence"),
                    }
                )

    reports = {
        "time_shift_placebo": _classification_metrics(shifted),
        "permutation_placebo": _classification_metrics(permuted_rows),
    }
    if negative_rows:
        reports["negative_control_commodity"] = _classification_metrics(negative_rows)
    else:
        reports["negative_control_commodity"] = {
            "sample_count": 0,
            "reason": "insufficient_ticker_diversity",
        }
    return reports


def _build_report_from_samples(
    *,
    model_id: str,
    horizon: str,
    period_from: datetime,
    period_to: datetime,
    epsilon: float,
    samples: list[dict[str, object]],
) -> dict[str, object]:
    metrics = _classification_metrics(samples)
    return {
        "model_id": model_id,
        "horizon": horizon,
        "period": {
            "from": period_from.isoformat() + "Z",
            "to": period_to.isoformat() + "Z",
        },
        "protocol": {
            "mode": "single_pass",
            "folds": 1,
            "embargo_minutes": 0,
            "horizon_minutes": int(_horizon_to_delta(horizon).total_seconds() // 60),
            "calibration_mode": "none",
            "calibration_min_train_samples": 0,
        },
        "fold_reports": [],
        "total_samples": len(samples),
        "dropped_by_embargo": 0,
        "sample_count": len(samples),
        "epsilon": epsilon,
        "metrics": metrics,
        "slices": {
            "ticker": _slice_metrics(samples, "ticker"),
            "source": _slice_metrics(samples, "source"),
            "event_family": _slice_metrics(samples, "event_family"),
        },
    }


def _evaluate_baseline_superiority_gate(
    winner: dict[str, object] | None,
    baseline_reports: list[dict[str, object]],
    *,
    min_accuracy_delta: float = 0.0,
    max_brier_delta: float = 0.0,
    required_baselines: tuple[str, ...] = ("baseline_majority_class", "baseline_calendar_only"),
) -> dict[str, object]:
    if not isinstance(winner, dict):
        return {
            "pass": False,
            "checks": [
                {
                    "check_id": "winner_present_for_baseline_gate",
                    "operator": "exists",
                    "value": 0,
                    "threshold": 1,
                    "passed": False,
                    "reason": "missing_winner",
                }
            ],
        }

    winner_metrics = winner.get("metrics") if isinstance(winner.get("metrics"), dict) else {}
    winner_accuracy = float(winner_metrics.get("accuracy") or 0.0)
    winner_brier = float(winner_metrics.get("brier") or 1.0)

    baseline_map = {
        str(item.get("model_id") or "").strip(): item
        for item in baseline_reports
        if isinstance(item, dict)
    }
    checks: list[dict[str, object]] = []
    for baseline_id in required_baselines:
        baseline = baseline_map.get(baseline_id)
        if not isinstance(baseline, dict):
            checks.append(
                {
                    "check_id": f"{baseline_id}_present",
                    "operator": "exists",
                    "value": 0,
                    "threshold": 1,
                    "passed": False,
                    "reason": "baseline_missing",
                }
            )
            continue

        baseline_metrics = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else {}
        baseline_accuracy = float(baseline_metrics.get("accuracy") or 0.0)
        baseline_brier = float(baseline_metrics.get("brier") or 1.0)
        checks.append(
            _build_gate_check(
                check_id=f"{baseline_id}_accuracy_superiority",
                value=winner_accuracy,
                threshold=baseline_accuracy + float(min_accuracy_delta),
                operator=">",
                passed=winner_accuracy > (baseline_accuracy + float(min_accuracy_delta)),
            )
        )
        checks.append(
            _build_gate_check(
                check_id=f"{baseline_id}_brier_not_worse",
                value=winner_brier,
                threshold=baseline_brier + float(max_brier_delta),
                operator="<=",
                passed=winner_brier <= (baseline_brier + float(max_brier_delta)),
            )
        )

    return {
        "pass": all(bool(item.get("passed")) for item in checks),
        "checks": checks,
        "summary": {
            "winner_accuracy": winner_accuracy,
            "winner_brier": winner_brier,
            "required_baselines": list(required_baselines),
            "min_accuracy_delta": float(min_accuracy_delta),
            "max_brier_delta": float(max_brier_delta),
        },
    }


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
) -> list[dict[str, object]]:
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


def _build_fold_windows(
    *,
    period_from: datetime,
    period_to: datetime,
    folds: int,
) -> list[tuple[datetime, datetime]]:
    normalized_folds = max(int(folds), 1)
    if normalized_folds == 1 or period_to <= period_from:
        return [(period_from, period_to)]
    total_seconds = (period_to - period_from).total_seconds()
    if total_seconds <= 0.0:
        return [(period_from, period_to)]

    step_seconds = total_seconds / float(normalized_folds)
    windows: list[tuple[datetime, datetime]] = []
    for idx in range(normalized_folds):
        start = period_from + timedelta(seconds=step_seconds * idx)
        if idx == normalized_folds - 1:
            end = period_to
        else:
            end = period_from + timedelta(seconds=step_seconds * (idx + 1))
        if end < start:
            continue
        windows.append((start, end))
    return windows or [(period_from, period_to)]


def _fit_binary_calibrator(mode: str, train_x: list[float], train_y: list[int]):
    if len(train_x) == 0 or len(train_y) == 0 or len(train_x) != len(train_y):
        return None, "empty_train"
    if len(set(train_y)) < 2:
        return None, "single_class_train"

    if mode == "isotonic":
        sklearn_isotonic = _safe_import("sklearn.isotonic")
        if sklearn_isotonic is None:
            return None, "sklearn_missing"
        try:
            calibrator = sklearn_isotonic.IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            calibrator.fit(train_x, train_y)
            return calibrator, "ok"
        except Exception:
            return None, "fit_failed"

    if mode == "platt":
        sklearn_linear = _safe_import("sklearn.linear_model")
        if sklearn_linear is None:
            return None, "sklearn_missing"
        try:
            calibrator = sklearn_linear.LogisticRegression(solver="lbfgs")
            calibrator.fit([[float(value)] for value in train_x], train_y)
            return calibrator, "ok"
        except Exception:
            return None, "fit_failed"

    return None, "unsupported_mode"


def _predict_binary_calibrator(mode: str, calibrator, test_x: list[float]) -> list[float] | None:
    try:
        if mode == "isotonic":
            raw = calibrator.transform(test_x)
            return [min(max(float(value), 0.0), 1.0) for value in raw]
        if mode == "platt":
            raw = calibrator.predict_proba([[float(value)] for value in test_x])
            return [min(max(float(row[1]), 0.0), 1.0) for row in raw]
    except Exception:
        return None
    return None


def _calibrate_fold_probabilities(
    *,
    train_samples: list[dict[str, object]],
    test_samples: list[dict[str, object]],
    calibration_mode: str,
    min_train_samples: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if not test_samples:
        return [], {
            "calibration_mode": calibration_mode,
            "calibration_applied": False,
            "calibration_reason": "empty_test",
            "calibrated_classes": [],
        }

    if calibration_mode == "none":
        return [dict(sample) for sample in test_samples], {
            "calibration_mode": "none",
            "calibration_applied": False,
            "calibration_reason": "disabled",
            "calibrated_classes": [],
        }

    if len(train_samples) < max(int(min_train_samples), 1):
        return [dict(sample) for sample in test_samples], {
            "calibration_mode": calibration_mode,
            "calibration_applied": False,
            "calibration_reason": "insufficient_train_samples",
            "calibrated_classes": [],
        }

    class_order = ("up", "down", "neutral")
    raw_test = {
        label: [float(sample.get(f"prob_{label}") or 0.0) for sample in test_samples]
        for label in class_order
    }
    transformed = dict(raw_test)
    class_meta: dict[str, str] = {}
    calibrated_classes: list[str] = []

    for label in class_order:
        train_x = [float(sample.get(f"prob_{label}") or 0.0) for sample in train_samples]
        train_y = [1 if str(sample.get("actual_label") or "") == label else 0 for sample in train_samples]
        calibrator, status = _fit_binary_calibrator(calibration_mode, train_x, train_y)
        if calibrator is None:
            class_meta[label] = status
            continue
        predicted = _predict_binary_calibrator(calibration_mode, calibrator, raw_test[label])
        if predicted is None:
            class_meta[label] = "predict_failed"
            continue
        transformed[label] = predicted
        class_meta[label] = "ok"
        calibrated_classes.append(label)

    if not calibrated_classes:
        return [dict(sample) for sample in test_samples], {
            "calibration_mode": calibration_mode,
            "calibration_applied": False,
            "calibration_reason": "no_class_calibrated",
            "calibrated_classes": [],
            "class_status": class_meta,
        }

    calibrated_rows: list[dict[str, object]] = []
    for idx, sample in enumerate(test_samples):
        prob_up, prob_down, prob_neutral = _normalize_prob_triplet(
            transformed["up"][idx],
            transformed["down"][idx],
            transformed["neutral"][idx],
        )
        row = dict(sample)
        row["prob_up"] = prob_up
        row["prob_down"] = prob_down
        row["prob_neutral"] = prob_neutral
        row["pred_confidence"] = max(prob_up, prob_down, prob_neutral)
        row["calibrated"] = True
        row["calibration_mode"] = calibration_mode
        calibrated_rows.append(row)

    return calibrated_rows, {
        "calibration_mode": calibration_mode,
        "calibration_applied": True,
        "calibration_reason": "ok",
        "calibrated_classes": calibrated_classes,
        "class_status": class_meta,
    }


def _evaluate_walk_forward(
    *,
    samples: list[dict[str, object]],
    period_from: datetime,
    period_to: datetime,
    folds: int,
    embargo_minutes: int,
    calibration_mode: str,
    calibration_min_train_samples: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if not samples:
        return [], []

    embargo = timedelta(minutes=max(int(embargo_minutes), 0))
    windows = _build_fold_windows(period_from=period_from, period_to=period_to, folds=folds)
    ordered = sorted(samples, key=lambda row: row["published_at"])

    oos_samples: list[dict[str, object]] = []
    fold_reports: list[dict[str, object]] = []
    for idx, (test_from, test_to) in enumerate(windows, start=1):
        effective_test_from = test_from + embargo
        if effective_test_from > test_to:
            continue
        effective_train_to = test_from - embargo
        train_samples = [
            sample
            for sample in ordered
            if period_from <= sample["published_at"] <= effective_train_to
        ]
        test_samples_raw = [
            sample
            for sample in ordered
            if effective_test_from <= sample["published_at"] <= test_to
        ]
        if not test_samples_raw:
            continue

        test_samples, calibration_meta = _calibrate_fold_probabilities(
            train_samples=train_samples,
            test_samples=test_samples_raw,
            calibration_mode=calibration_mode,
            min_train_samples=calibration_min_train_samples,
        )

        oos_samples.extend(test_samples)
        fold_reports.append(
            {
                "fold_index": idx,
                "train_period": {
                    "from": period_from.isoformat() + "Z",
                    "to": effective_train_to.isoformat() + "Z",
                },
                "test_period": {
                    "from": effective_test_from.isoformat() + "Z",
                    "to": test_to.isoformat() + "Z",
                },
                "train_sample_count": len(train_samples),
                "sample_count": len(test_samples),
                "metrics": _classification_metrics(test_samples),
                **calibration_meta,
            }
        )
    return oos_samples, fold_reports


def _ticker_stability_score(report: dict[str, object]) -> float:
    slices_raw = report.get("slices") if isinstance(report.get("slices"), dict) else {}
    ticker_slices = slices_raw.get("ticker") if isinstance(slices_raw.get("ticker"), dict) else {}
    per_ticker: list[float] = []
    for metrics in ticker_slices.values():
        if not isinstance(metrics, dict):
            continue
        sample_count = int(metrics.get("sample_count") or 0)
        if sample_count < 3:
            continue
        per_ticker.append(float(metrics.get("accuracy") or 0.0))
    if per_ticker:
        return min(per_ticker)
    top_metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    return float(top_metrics.get("accuracy") or 0.0)


def _build_gate_check(*, check_id: str, value: float, threshold: float, operator: str, passed: bool) -> dict[str, object]:
    return {
        "check_id": check_id,
        "value": value,
        "threshold": threshold,
        "operator": operator,
        "passed": bool(passed),
    }


def _evaluate_promotion_gate(
    report: dict[str, object] | None,
    *,
    min_accuracy: float,
    min_coverage: float,
    max_brier: float,
    min_sample_count: int,
    min_ticker_stability: float,
) -> dict[str, object]:
    if not isinstance(report, dict):
        return {
            "pass": False,
            "checks": [
                {
                    "check_id": "winner_present",
                    "passed": False,
                    "operator": "exists",
                    "value": 0,
                    "threshold": 1,
                }
            ],
        }

    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    accuracy = float(metrics.get("accuracy") or 0.0)
    coverage = float(metrics.get("coverage") or 0.0)
    brier = float(metrics.get("brier") or 1.0)
    sample_count = int(report.get("sample_count") or metrics.get("sample_count") or 0)
    stability = _ticker_stability_score(report)

    checks = [
        _build_gate_check(
            check_id="sample_count_min",
            value=float(sample_count),
            threshold=float(min_sample_count),
            operator=">=",
            passed=sample_count >= max(int(min_sample_count), 0),
        ),
        _build_gate_check(
            check_id="accuracy_min",
            value=accuracy,
            threshold=float(min_accuracy),
            operator=">=",
            passed=accuracy >= float(min_accuracy),
        ),
        _build_gate_check(
            check_id="coverage_min",
            value=coverage,
            threshold=float(min_coverage),
            operator=">=",
            passed=coverage >= float(min_coverage),
        ),
        _build_gate_check(
            check_id="brier_max",
            value=brier,
            threshold=float(max_brier),
            operator="<=",
            passed=brier <= float(max_brier),
        ),
        _build_gate_check(
            check_id="ticker_stability_min",
            value=stability,
            threshold=float(min_ticker_stability),
            operator=">=",
            passed=stability >= float(min_ticker_stability),
        ),
    ]

    return {
        "pass": all(bool(item.get("passed")) for item in checks),
        "checks": checks,
        "summary": {
            "sample_count": sample_count,
            "accuracy": accuracy,
            "coverage": coverage,
            "brier": brier,
            "ticker_stability": stability,
        },
    }


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


def run_news_backtest(
    session: Session,
    *,
    model_id: str,
    horizon: str,
    period_from: datetime,
    period_to: datetime,
    epsilon: float,
    folds: int = 5,
    embargo_minutes: int = 0,
    walk_forward: bool = True,
    calibration_mode: str = "none",
    calibration_min_train_samples: int = 30,
    evaluation_level: str = "event",
    strict_anchor_window_minutes: int = 120,
) -> dict[str, object]:
    delta = _horizon_to_delta(horizon)
    normalized_folds = max(int(folds), 1)
    normalized_embargo = max(int(embargo_minutes), 0)
    normalized_calibration_mode = _normalize_calibration_mode(calibration_mode)
    normalized_calibration_min_train = max(int(calibration_min_train_samples), 1)

    samples = _build_backtest_samples(
        session,
        model_id=model_id,
        period_from=period_from,
        period_to=period_to,
        delta=delta,
        epsilon=epsilon,
        strict_anchor_window_minutes=strict_anchor_window_minutes,
        evaluation_level=evaluation_level,
    )

    if not samples:
        return {
            "model_id": model_id,
            "horizon": horizon,
            "period": {
                "from": period_from.isoformat() + "Z",
                "to": period_to.isoformat() + "Z",
            },
            "protocol": {
                "mode": "walk_forward" if walk_forward else "single_pass",
                "folds": normalized_folds,
                "embargo_minutes": normalized_embargo,
                "horizon_minutes": int(delta.total_seconds() // 60),
                "calibration_mode": normalized_calibration_mode,
                "calibration_min_train_samples": normalized_calibration_min_train,
                "evaluation_level": str(evaluation_level or "event").strip().lower(),
                "strict_anchor_window_minutes": max(int(strict_anchor_window_minutes), 0),
            },
            "fold_reports": [],
            "total_samples": 0,
            "dropped_by_embargo": 0,
            "sample_count": 0,
            "metrics": _classification_metrics([]),
            "slices": {
                "ticker": {},
                "source": {},
            },
        }

    if walk_forward:
        oos_samples, fold_reports = _evaluate_walk_forward(
            samples=samples,
            period_from=period_from,
            period_to=period_to,
            folds=normalized_folds,
            embargo_minutes=normalized_embargo,
            calibration_mode=normalized_calibration_mode,
            calibration_min_train_samples=normalized_calibration_min_train,
        )
    else:
        oos_samples = sorted((dict(sample) for sample in samples), key=lambda row: row["published_at"])
        fold_reports = [
            {
                "fold_index": 1,
                "train_period": {
                    "from": period_from.isoformat() + "Z",
                    "to": period_to.isoformat() + "Z",
                },
                "test_period": {
                    "from": period_from.isoformat() + "Z",
                    "to": period_to.isoformat() + "Z",
                },
                "train_sample_count": len(samples),
                "sample_count": len(oos_samples),
                "metrics": _classification_metrics(oos_samples),
                "calibration_mode": normalized_calibration_mode,
                "calibration_applied": False,
                "calibration_reason": "disabled_single_pass",
                "calibrated_classes": [],
            }
        ]

    metrics = _classification_metrics(oos_samples)
    dropped_by_embargo = max(len(samples) - len(oos_samples), 0)
    return {
        "model_id": model_id,
        "horizon": horizon,
        "period": {
            "from": period_from.isoformat() + "Z",
            "to": period_to.isoformat() + "Z",
        },
        "protocol": {
            "mode": "walk_forward" if walk_forward else "single_pass",
            "folds": normalized_folds,
            "embargo_minutes": normalized_embargo,
            "horizon_minutes": int(delta.total_seconds() // 60),
            "calibration_mode": normalized_calibration_mode,
            "calibration_min_train_samples": normalized_calibration_min_train,
            "evaluation_level": str(evaluation_level or "event").strip().lower(),
            "strict_anchor_window_minutes": max(int(strict_anchor_window_minutes), 0),
        },
        "fold_reports": fold_reports,
        "total_samples": len(samples),
        "dropped_by_embargo": dropped_by_embargo,
        "sample_count": len(oos_samples),
        "epsilon": epsilon,
        "metrics": metrics,
        "slices": {
            "ticker": _slice_metrics(oos_samples, "ticker"),
            "source": _slice_metrics(oos_samples, "source"),
            "event_family": _slice_metrics(oos_samples, "event_family"),
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
    folds: int = 5,
    embargo_minutes: int = 0,
    walk_forward: bool = True,
    calibration_mode: str = "none",
    calibration_min_train_samples: int = 30,
    promotion_min_accuracy: float = 0.70,
    promotion_min_coverage: float = 0.20,
    promotion_max_brier: float = 0.25,
    promotion_min_sample_count: int = 30,
    promotion_min_ticker_stability: float = 0.55,
    evaluation_level: str = "event",
    strict_anchor_window_minutes: int = 120,
    promotion_require_baseline_superiority: bool = True,
    promotion_baseline_min_accuracy_delta: float = 0.0,
    promotion_baseline_max_brier_delta: float = 0.0,
) -> dict[str, object]:
    reports: list[dict[str, object]] = []
    for model_id in model_ids:
        report = run_news_backtest(
                session,
                model_id=model_id,
                horizon=horizon,
                period_from=period_from,
                period_to=period_to,
                epsilon=epsilon,
                folds=folds,
                embargo_minutes=embargo_minutes,
                walk_forward=walk_forward,
                calibration_mode=calibration_mode,
                calibration_min_train_samples=calibration_min_train_samples,
                evaluation_level=evaluation_level,
                strict_anchor_window_minutes=strict_anchor_window_minutes,
            )
        report["supervised_metrics"] = _build_supervised_gold_metrics(
            session,
            model_id=model_id,
            period_from=period_from,
            period_to=period_to,
        )
        reports.append(report)

    baseline_reports: list[dict[str, object]] = []
    ablation_reports: dict[str, dict[str, object]] = {}

    def _score(report: dict[str, Any]) -> tuple[float, float, float, float, int]:
        metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
        accuracy = float(metrics.get("accuracy") or 0.0)
        stability = _ticker_stability_score(report)
        brier = float(metrics.get("brier") or 0.0)
        coverage = float(metrics.get("coverage") or 0.0)
        sample_count = int(report.get("sample_count") or 0)
        return (accuracy, stability, coverage, -brier, sample_count)

    sorted_reports = sorted(reports, key=_score, reverse=True)
    winner = sorted_reports[0] if sorted_reports else None

    reference_model_id = str(winner.get("model_id") or "").strip() if isinstance(winner, dict) else ""
    if not reference_model_id and model_ids:
        reference_model_id = str(model_ids[0] or "").strip()
    if reference_model_id:
        reference_samples = _build_backtest_samples(
            session,
            model_id=reference_model_id,
            period_from=period_from,
            period_to=period_to,
            delta=_horizon_to_delta(horizon),
            epsilon=epsilon,
            strict_anchor_window_minutes=strict_anchor_window_minutes,
            evaluation_level=evaluation_level,
        )
        if reference_samples:
            news_ids = [str(item.get("news_id") or "").strip() for item in reference_samples if item.get("news_id")]
            calendar_direction_by_news = _build_calendar_direction_by_news(session, news_ids=news_ids)
            majority_samples = _apply_baseline_majority_class(reference_samples)
            no_news_samples = _apply_baseline_no_news(reference_samples)
            calendar_only_samples = _apply_baseline_calendar_only(
                reference_samples,
                direction_by_news=calendar_direction_by_news,
            )
            calendar_plus_text_samples = _apply_baseline_calendar_plus_text(
                reference_samples,
                direction_by_news=calendar_direction_by_news,
            )
            baseline_reports = [
                _build_report_from_samples(
                    model_id="baseline_majority_class",
                    horizon=horizon,
                    period_from=period_from,
                    period_to=period_to,
                    epsilon=epsilon,
                    samples=majority_samples,
                ),
                _build_report_from_samples(
                    model_id="baseline_no_news",
                    horizon=horizon,
                    period_from=period_from,
                    period_to=period_to,
                    epsilon=epsilon,
                    samples=no_news_samples,
                ),
                _build_report_from_samples(
                    model_id="baseline_calendar_only",
                    horizon=horizon,
                    period_from=period_from,
                    period_to=period_to,
                    epsilon=epsilon,
                    samples=calendar_only_samples,
                ),
                _build_report_from_samples(
                    model_id="baseline_text_only",
                    horizon=horizon,
                    period_from=period_from,
                    period_to=period_to,
                    epsilon=epsilon,
                    samples=reference_samples,
                ),
                _build_report_from_samples(
                    model_id="baseline_calendar_plus_text",
                    horizon=horizon,
                    period_from=period_from,
                    period_to=period_to,
                    epsilon=epsilon,
                    samples=calendar_plus_text_samples,
                ),
            ]
            ablation_reports = _build_ablation_reports(reference_samples)

    market_gate = _evaluate_promotion_gate(
        winner,
        min_accuracy=promotion_min_accuracy,
        min_coverage=promotion_min_coverage,
        max_brier=promotion_max_brier,
        min_sample_count=promotion_min_sample_count,
        min_ticker_stability=promotion_min_ticker_stability,
    )
    supervised_gate = _evaluate_supervised_gate(
        winner.get("supervised_metrics") if isinstance(winner, dict) else None,
        min_accuracy=promotion_min_accuracy,
        min_coverage=promotion_min_coverage,
        max_brier=promotion_max_brier,
        min_sample_count=promotion_min_sample_count,
    )
    baseline_gate = (
        _evaluate_baseline_superiority_gate(
            winner if isinstance(winner, dict) else None,
            baseline_reports,
            min_accuracy_delta=promotion_baseline_min_accuracy_delta,
            max_brier_delta=promotion_baseline_max_brier_delta,
        )
        if promotion_require_baseline_superiority
        else {
            "pass": True,
            "checks": [],
            "summary": {
                "enabled": False,
                "reason": "promotion_require_baseline_superiority_disabled",
            },
        }
    )
    quality_gate = {
        "pass": bool(market_gate.get("pass")) and bool(supervised_gate.get("pass")) and bool(baseline_gate.get("pass")),
        "market_gate": market_gate,
        "supervised_gate": supervised_gate,
        "baseline_gate": baseline_gate,
        "checks": [
            *(market_gate.get("checks") if isinstance(market_gate.get("checks"), list) else []),
            *(supervised_gate.get("checks") if isinstance(supervised_gate.get("checks"), list) else []),
            *(baseline_gate.get("checks") if isinstance(baseline_gate.get("checks"), list) else []),
        ],
    }
    decision = "promote" if bool(quality_gate.get("pass")) else "hold"
    comparison_hash = hashlib.sha1(
        f"{horizon}|{period_from.isoformat()}|{period_to.isoformat()}|{','.join(model_ids)}".encode("utf-8")
    ).hexdigest()[:20]
    _store_model_eval_record(
        session,
        comparison_hash=comparison_hash,
        horizon=horizon,
        winner=winner if isinstance(winner, dict) else None,
        market_gate=market_gate,
        supervised_gate=supervised_gate,
        quality_gate=quality_gate,
        decision=decision,
    )

    comparison = {
        "horizon": horizon,
        "period": {
            "from": period_from.isoformat() + "Z",
            "to": period_to.isoformat() + "Z",
        },
        "epsilon": epsilon,
        "protocol": {
            "mode": "walk_forward" if walk_forward else "single_pass",
            "folds": max(int(folds), 1),
            "embargo_minutes": max(int(embargo_minutes), 0),
            "calibration_mode": _normalize_calibration_mode(calibration_mode),
            "calibration_min_train_samples": max(int(calibration_min_train_samples), 1),
            "evaluation_level": str(evaluation_level or "event").strip().lower(),
            "strict_anchor_window_minutes": max(int(strict_anchor_window_minutes), 0),
            "require_baseline_superiority": bool(promotion_require_baseline_superiority),
            "baseline_min_accuracy_delta": float(promotion_baseline_min_accuracy_delta),
            "baseline_max_brier_delta": float(promotion_baseline_max_brier_delta),
        },
        "reports": reports,
        "baselines": baseline_reports,
        "ablations": ablation_reports,
        "winner": {
            "model_id": winner.get("model_id") if isinstance(winner, dict) else None,
            "reason": "best_oos_accuracy_stability_coverage_then_brier",
        },
        "audit": {
            "decision": decision,
            "quality_gate": quality_gate,
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "comparison_hash": comparison_hash,
        },
    }
    return comparison
