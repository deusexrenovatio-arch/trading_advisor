from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from moex_carry.news_causal import analyze_causal_news
from moex_carry.news_live_causal_ops import augment_query_with_event_terms
from moex_carry.news_live_clients import fetch_newsapi_articles
from moex_carry.news_live_runtime import NewsIngestConfig
from moex_carry.news_live_schema import init_news_live_db
from moex_carry.news_live_scoring import MODEL_NAME_KEYWORD, ModelScorer, ScoringModelConfig, SEVERITY_ORDER
from moex_carry.news_runtime_state import iso_utc, reserve_newsapi_request, utc_now
from moex_carry.news_storage import open_sqlite_connection
from moex_carry.news_topic import build_story_fingerprint


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_url(value: object) -> str:
    url = _normalize_text(value)
    if not url:
        return ""
    lowered = url.lower()
    for marker in ("?utm_", "&utm_", "?fbclid=", "&fbclid="):
        idx = lowered.find(marker)
        if idx >= 0:
            return url[:idx]
    return url


def _safe_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def _article_id(*, provider: str, commodity: str, title: str, url: str, published_at: str) -> str:
    payload = "|".join(
        [
            provider.strip().lower(),
            commodity.strip().upper(),
            _normalize_url(url).lower(),
            _normalize_text(title).lower(),
            _normalize_text(published_at),
        ]
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]
    return f"{provider.lower()}-{commodity.upper()}-{digest}"


def _story_id(*, provider: str, title: str, url: str, published_at: str) -> str:
    return build_story_fingerprint(
        title=title,
        url=url,
        published_at_utc=published_at,
        provider=provider,
    )


def _profile_for_symbol(config: NewsIngestConfig, symbol: str):
    symbol_key = _normalize_text(symbol).upper()
    for profile in config.commodity_profiles:
        if _normalize_text(profile.ticker).upper() == symbol_key:
            return profile
    return None


def _parse_ts_list(values: list[object]) -> list[datetime]:
    out: list[datetime] = []
    for raw in values:
        parsed = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.isna(parsed):
            continue
        if isinstance(parsed, pd.Timestamp):
            out.append(parsed.to_pydatetime())
    unique = sorted({iso_utc(item): item for item in out}.values(), reverse=True)
    return unique


def enrich_newsapi_for_symbol_candidates(
    *,
    db_path: Path,
    news_config: NewsIngestConfig,
    symbol: str,
    candidate_ts_utc: list[object],
    window_minutes: int,
    max_requests_per_symbol: int,
) -> dict[str, Any]:
    profile = _profile_for_symbol(news_config, symbol)
    if profile is None:
        return {"symbol": symbol, "requests_used": 0, "fetched_total": 0, "inserted_total": 0, "scored_total": 0}
    if not news_config.newsapi_enabled or not news_config.newsapi_api_key:
        return {"symbol": symbol, "requests_used": 0, "fetched_total": 0, "inserted_total": 0, "scored_total": 0}
    if not candidate_ts_utc:
        return {"symbol": symbol, "requests_used": 0, "fetched_total": 0, "inserted_total": 0, "scored_total": 0}

    timestamps = _parse_ts_list(candidate_ts_utc)[: max(int(max_requests_per_symbol), 0)]
    if not timestamps:
        return {"symbol": symbol, "requests_used": 0, "fetched_total": 0, "inserted_total": 0, "scored_total": 0}

    conn = open_sqlite_connection(db_path, timeout_sec=15.0, write=True)
    try:
        init_news_live_db(conn)
        session = requests.Session()
        scorer = ModelScorer(
            ScoringModelConfig(
                mode=news_config.model_mode,
                nli_model_name=news_config.nli_model_name,
                finbert_model_name=news_config.finbert_model_name,
                model_device=news_config.model_device,
            )
        )
        query = augment_query_with_event_terms(
            profile.newsapi_query,
            commodity=symbol,
            max_terms=8,
        )
        fetched_total = 0
        inserted_total = 0
        scored_total = 0
        requests_used = 0
        started_at = iso_utc(utc_now())
        window = timedelta(minutes=max(int(window_minutes), 1))

        for anchor_ts in timestamps:
            if not reserve_newsapi_request(
                conn,
                mode="backfill",
                daily_quota=news_config.newsapi_daily_quota,
                realtime_budget=news_config.newsapi_realtime_budget,
                backfill_budget=news_config.newsapi_backfill_budget,
                emergency_buffer=news_config.newsapi_emergency_buffer,
            ):
                break
            requests_used += 1
            start_utc = anchor_ts - window
            end_utc = anchor_ts + window
            fetched = fetch_newsapi_articles(
                session,
                api_key=news_config.newsapi_api_key,
                query=query,
                start_utc=start_utc,
                end_utc=end_utc,
                language=profile.language,
                page_size=news_config.newsapi_page_size,
                sort_by=news_config.newsapi_sort_by,
                timeout_sec=max(news_config.newsapi_timeout_sec, 1.0),
            )
            fetched_total += len(fetched)
            for item in fetched:
                title = _normalize_text(item.get("title"))
                url = _normalize_url(item.get("url"))
                published_at_utc = _normalize_text(item.get("published_at_utc"))
                if not title and not url:
                    continue
                article_id = _article_id(
                    provider="newsapi",
                    commodity=symbol,
                    title=title,
                    url=url,
                    published_at=published_at_utc,
                )
                exists = conn.execute(
                    "SELECT 1 FROM news_articles WHERE article_id = ?",
                    (article_id,),
                ).fetchone()
                if exists is not None:
                    continue
                story_id = _story_id(
                    provider="newsapi",
                    title=title,
                    url=url,
                    published_at=published_at_utc,
                )
                conn.execute(
                    """
                    INSERT INTO news_articles (
                        article_id,
                        provider,
                        commodity,
                        source_name,
                        published_at_utc,
                        fetched_at_utc,
                        title,
                        description,
                        content,
                        url,
                        language,
                        query_text,
                        story_id,
                        raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        article_id,
                        "newsapi",
                        symbol,
                        _normalize_text(item.get("source_name") or "newsapi"),
                        published_at_utc or started_at,
                        started_at,
                        title,
                        _normalize_text(item.get("description")),
                        _normalize_text(item.get("content")),
                        url,
                        _normalize_text(item.get("language") or profile.language or "en"),
                        query,
                        story_id,
                        _safe_json(item.get("raw")),
                    ),
                )
                inserted_total += 1
                score = scorer.score(
                    commodity=symbol,
                    title=title,
                    description=_normalize_text(item.get("description")),
                    content=_normalize_text(item.get("content")),
                )
                causal = analyze_causal_news(
                    commodity=symbol,
                    title=title,
                    description=_normalize_text(item.get("description")),
                    content=_normalize_text(item.get("content")),
                    direction=str(score.get("direction") or "hold"),
                    reason_terms_up=score.get("reason_terms_up") or [],
                    reason_terms_down=score.get("reason_terms_down") or [],
                )
                severity = str(score.get("severity") or "medium").lower()
                if severity not in SEVERITY_ORDER:
                    severity = "medium"
                conn.execute(
                    """
                    INSERT OR REPLACE INTO news_scores (
                        article_id,
                        model_name,
                        scored_at_utc,
                        direction,
                        impact_score,
                        confidence,
                        severity,
                        reason_terms_up,
                        reason_terms_down,
                        cause_classification,
                        cause_bucket,
                        cause_event,
                        transmission_channel,
                        cause_cluster_key,
                        cause_confidence,
                        fundamental_score,
                        direction_alignment,
                        is_primary_cause,
                        cause_route_key,
                        cause_claim_status,
                        cause_entities_json,
                        cause_terms_json,
                        effect_terms_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        article_id,
                        str(score.get("model_name") or MODEL_NAME_KEYWORD),
                        started_at,
                        str(score.get("direction") or "hold"),
                        float(score.get("impact_score") or 0.0),
                        float(score.get("confidence") or 0.0),
                        severity,
                        _safe_json(score.get("reason_terms_up") or []),
                        _safe_json(score.get("reason_terms_down") or []),
                        str(causal.get("cause_classification") or "unknown"),
                        str(causal.get("cause_bucket") or ""),
                        str(causal.get("cause_event") or ""),
                        str(causal.get("transmission_channel") or ""),
                        str(causal.get("cause_cluster_key") or ""),
                        float(causal.get("cause_confidence") or 0.0),
                        float(causal.get("fundamental_score") or 0.0),
                        float(causal.get("direction_alignment") or 0.5),
                        1 if bool(causal.get("is_primary_cause")) else 0,
                        str(causal.get("cause_route_key") or ""),
                        str(causal.get("cause_claim_status") or "unknown"),
                        _safe_json(causal.get("cause_entities") or []),
                        _safe_json(causal.get("cause_terms") or []),
                        _safe_json(causal.get("effect_terms") or []),
                    ),
                )
                scored_total += 1
            conn.commit()
    finally:
        conn.close()

    return {
        "symbol": symbol,
        "requests_used": int(requests_used),
        "fetched_total": int(fetched_total),
        "inserted_total": int(inserted_total),
        "scored_total": int(scored_total),
    }
