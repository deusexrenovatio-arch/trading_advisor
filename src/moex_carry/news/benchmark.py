from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from moex_carry.config import AppSettings
from moex_carry.news.inference import apply_inference_runtime_limits, run_dual_model_inference_batch
from moex_carry.storage import models as db


_FALLBACK_SAMPLE_TEXTS = [
    "OPEC+ announced an unexpected production cut that tightens Brent supply outlook.",
    "US natural gas storage build exceeded estimates, suggesting near-term pressure on prices.",
    "Central bank policy easing may support gold demand amid weaker real yields.",
    "Hurricane disruption in Gulf infrastructure may reduce LNG and crude export capacity.",
    "Industrial demand slowdown in major economies could weigh on commodity prices.",
]


def _quiet_ml_loggers() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)


def parse_positive_int_list(raw: str | None, *, default: Sequence[int]) -> list[int]:
    if raw is None:
        return [int(item) for item in default if int(item) > 0]
    parsed: list[int] = []
    for chunk in str(raw).split(","):
        text = chunk.strip()
        if not text:
            continue
        try:
            value = int(text)
        except ValueError:
            continue
        if value > 0:
            parsed.append(value)
    unique_ordered: list[int] = []
    seen: set[int] = set()
    for value in parsed:
        if value in seen:
            continue
        seen.add(value)
        unique_ordered.append(value)
    if unique_ordered:
        return unique_ordered
    return [int(item) for item in default if int(item) > 0]


def choose_recommended_case(cases: Sequence[dict[str, object]]) -> dict[str, object] | None:
    if not cases:
        return None

    def _sort_key(item: dict[str, object]) -> tuple[float, float, int, int, int]:
        throughput = float(item.get("throughput_items_per_sec") or 0.0)
        p95 = float(item.get("latency_ms_p95") or 0.0)
        thread_cap = int(item.get("thread_cap") or 0)
        batch_size = int(item.get("batch_size") or 0)
        text_max_chars = int(item.get("text_max_chars") or 0)
        return (-throughput, p95, thread_cap, batch_size, text_max_chars)

    return sorted(cases, key=_sort_key)[0]


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return ordered[0]
    index = int((len(ordered) - 1) * 0.95)
    return ordered[index]


def _normalize_text_row(news_id: str, title: str | None, content: str | None) -> dict[str, str] | None:
    normalized_id = str(news_id or "").strip()
    if not normalized_id:
        return None
    parts = [str(title or "").strip(), str(content or "").strip()]
    text = " ".join(part for part in parts if part).strip()
    if not text:
        return None
    return {"news_id": normalized_id, "text": text}


def _load_news_samples(
    session: Session,
    *,
    sample_size: int,
    lookback_days: int,
    ticker: str | None,
) -> list[dict[str, str]]:
    query = select(
        db.NewsItemModel.news_id,
        db.NewsItemModel.title,
        db.NewsItemModel.content,
        db.NewsItemModel.published_at,
    )
    normalized_ticker = str(ticker or "").strip().upper()
    if normalized_ticker:
        query = query.join(db.NewsEntityLinkModel, db.NewsEntityLinkModel.news_id == db.NewsItemModel.news_id).where(
            db.NewsEntityLinkModel.ticker == normalized_ticker
        )
    if lookback_days > 0:
        lower_bound = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=lookback_days)
        query = query.where(db.NewsItemModel.published_at >= lower_bound)
    query = query.order_by(db.NewsItemModel.published_at.desc(), db.NewsItemModel.news_id.desc())
    probe_limit = max(int(sample_size), 1) * 10
    rows = session.execute(query.limit(probe_limit)).all()

    samples: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for news_id, title, content, _published_at in rows:
        row = _normalize_text_row(news_id, title, content)
        if row is None:
            continue
        if row["news_id"] in seen_ids:
            continue
        samples.append(row)
        seen_ids.add(row["news_id"])
        if len(samples) >= max(int(sample_size), 1):
            break
    while len(samples) < max(int(sample_size), 1):
        idx = len(samples) % len(_FALLBACK_SAMPLE_TEXTS)
        samples.append(
            {
                "news_id": f"bench-fallback-{len(samples)+1}",
                "text": _FALLBACK_SAMPLE_TEXTS[idx],
            }
        )
    return samples


def run_news_inference_benchmark(
    session: Session,
    settings: AppSettings,
    *,
    sample_size: int = 60,
    lookback_days: int = 365 * 3,
    ticker: str | None = None,
    batch_sizes: Sequence[int] = (1, 2, 4, 8),
    thread_caps: Sequence[int] = (2, 4, 6),
    text_caps: Sequence[int] = (1200, 1500, 2000),
    warmup_runs: int = 1,
    repeat_runs: int = 2,
) -> dict[str, object]:
    _quiet_ml_loggers()
    normalized_sample_size = max(int(sample_size), 1)
    warmup = max(int(warmup_runs), 0)
    repeats = max(int(repeat_runs), 1)
    samples = _load_news_samples(
        session,
        sample_size=normalized_sample_size,
        lookback_days=max(int(lookback_days), 0),
        ticker=ticker,
    )
    enabled_models = [str(item).strip().lower() for item in settings.news_models.enabled_models if str(item).strip()]
    if not enabled_models:
        enabled_models = ["finbert", "nli"]

    cases: list[dict[str, object]] = []
    for thread_cap in [max(int(item), 1) for item in thread_caps]:
        for text_cap in [max(int(item), 1) for item in text_caps]:
            for batch_size in [max(int(item), 1) for item in batch_sizes]:
                apply_inference_runtime_limits(thread_cap=thread_cap, force=True)
                for _ in range(warmup):
                    run_dual_model_inference_batch(
                        news_items=samples,
                        enabled_models=enabled_models,
                        finbert_model_name=settings.news_models.finbert_model_name,
                        nli_model_name=settings.news_models.nli_model_name,
                        model_version=settings.news_models.model_version,
                        batch_size=batch_size,
                        text_max_chars=text_cap,
                        thread_cap=thread_cap,
                    )

                durations: list[float] = []
                score_count = 0
                for _ in range(repeats):
                    started = perf_counter()
                    rows = run_dual_model_inference_batch(
                        news_items=samples,
                        enabled_models=enabled_models,
                        finbert_model_name=settings.news_models.finbert_model_name,
                        nli_model_name=settings.news_models.nli_model_name,
                        model_version=settings.news_models.model_version,
                        batch_size=batch_size,
                        text_max_chars=text_cap,
                        thread_cap=thread_cap,
                    )
                    elapsed = max(perf_counter() - started, 1e-9)
                    durations.append(elapsed)
                    score_count = max(score_count, len(rows))

                avg_seconds = sum(durations) / len(durations)
                avg_ms = avg_seconds * 1000.0
                p95_ms = _p95([value * 1000.0 for value in durations])
                throughput_items = float(normalized_sample_size) / avg_seconds
                throughput_scores = float(max(score_count, 1)) / avg_seconds
                cases.append(
                    {
                        "thread_cap": thread_cap,
                        "batch_size": batch_size,
                        "text_max_chars": text_cap,
                        "latency_ms_avg": round(avg_ms, 3),
                        "latency_ms_p95": round(p95_ms, 3),
                        "throughput_items_per_sec": round(throughput_items, 3),
                        "throughput_scores_per_sec": round(throughput_scores, 3),
                        "repeat_runs": repeats,
                        "warmup_runs": warmup,
                        "sample_size": normalized_sample_size,
                        "score_count": score_count,
                    }
                )

    recommended = choose_recommended_case(cases)
    return {
        "sample_size": normalized_sample_size,
        "sample_ticker": str(ticker or "").strip().upper() or None,
        "lookback_days": max(int(lookback_days), 0),
        "enabled_models": enabled_models,
        "cases": cases,
        "recommended": recommended,
        "recommended_profile": (
            {
                "news_models": {
                    "inference_batch_size": int(recommended.get("batch_size") or 1),
                    "inference_text_max_chars": int(recommended.get("text_max_chars") or 1500),
                    "inference_thread_cap": int(recommended.get("thread_cap") or 4),
                }
            }
            if recommended
            else {}
        ),
    }
