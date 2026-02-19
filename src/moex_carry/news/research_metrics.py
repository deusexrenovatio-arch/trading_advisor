from __future__ import annotations

from collections import Counter
import importlib
from datetime import datetime, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

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


def _normalize_target_mode(value: str | None) -> str:
    raw = str(value or "legacy").strip().lower()
    if raw in {"legacy", "v2"}:
        return raw
    return "legacy"


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
            "balanced_accuracy": 0.0,
            "precision_up": 0.0,
            "precision_down": 0.0,
            "recall_up": 0.0,
            "recall_down": 0.0,
            "recall_neutral": 0.0,
            "f1_up": 0.0,
            "f1_down": 0.0,
            "f1_non_hold": 0.0,
            "brier": 0.0,
            "ece_15": 0.0,
            "coverage": 0.0,
            "neutral_rate": 0.0,
            "calibrated_rate": 0.0,
            "reliability_bins": [],
        }

    total = len(samples)
    correct = sum(1 for item in samples if item["pred_label"] == item["actual_label"])

    pred_up = [item for item in samples if item["pred_label"] == "up"]
    pred_down = [item for item in samples if item["pred_label"] == "down"]
    pred_neutral = [item for item in samples if item["pred_label"] == "neutral"]
    act_up = [item for item in samples if item["actual_label"] == "up"]
    act_down = [item for item in samples if item["actual_label"] == "down"]
    act_neutral = [item for item in samples if item["actual_label"] == "neutral"]

    tp_up = sum(1 for item in pred_up if item["actual_label"] == "up")
    tp_down = sum(1 for item in pred_down if item["actual_label"] == "down")
    tp_neutral = sum(1 for item in pred_neutral if item["actual_label"] == "neutral")

    precision_up = _safe_div(tp_up, len(pred_up))
    precision_down = _safe_div(tp_down, len(pred_down))
    recall_up = _safe_div(tp_up, len(act_up))
    recall_down = _safe_div(tp_down, len(act_down))
    recall_neutral = _safe_div(tp_neutral, len(act_neutral))

    f1_up = _safe_div(2 * precision_up * recall_up, precision_up + recall_up)
    f1_down = _safe_div(2 * precision_down * recall_down, precision_down + recall_down)
    f1_non_hold = (f1_up + f1_down) / 2.0

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

    # ECE over 15 bins for confidence quality monitoring in promotion gates.
    ece_15 = 0.0
    for idx in range(15):
        low = idx / 15.0
        high = (idx + 1) / 15.0
        bucket = [
            item
            for item in samples
            if low <= float(item.get("pred_confidence") or 0.0) < high
            or (idx == 14 and float(item.get("pred_confidence") or 0.0) == 1.0)
        ]
        if not bucket:
            continue
        avg_conf = mean(float(item.get("pred_confidence") or 0.0) for item in bucket)
        acc = _safe_div(
            sum(1 for item in bucket if item["pred_label"] == item["actual_label"]),
            len(bucket),
        )
        ece_15 += (len(bucket) / float(total)) * abs(avg_conf - acc)

    balanced_accuracy = (recall_up + recall_down + recall_neutral) / 3.0

    return {
        "sample_count": total,
        "accuracy": _safe_div(correct, total),
        "balanced_accuracy": balanced_accuracy,
        "precision_up": precision_up,
        "precision_down": precision_down,
        "recall_up": recall_up,
        "recall_down": recall_down,
        "recall_neutral": recall_neutral,
        "f1_up": f1_up,
        "f1_down": f1_down,
        "f1_non_hold": f1_non_hold,
        "brier": mean(brier_values) if brier_values else 0.0,
        "ece_15": ece_15,
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

__all__ = [
    "_safe_import",
    "_horizon_to_delta",
    "_normalize_calibration_mode",
    "_normalize_target_mode",
    "_label_return",
    "_safe_div",
    "_normalize_prob_triplet",
    "_classification_metrics",
    "_sample_group_key",
    "_resolve_group_event_family",
    "_aggregate_samples_to_event_level",
    "_resolve_quote_lag_limit",
    "_load_quote_point",
    "_slice_metrics",
    "_normalize_label_direction",
    "_direction_triplet",
    "_build_calendar_direction_by_news",
    "_apply_baseline_no_news",
    "_apply_baseline_majority_class",
    "_apply_baseline_calendar_only",
    "_apply_baseline_calendar_plus_text",
    "_build_ablation_reports",
]
