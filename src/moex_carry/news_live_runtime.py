from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from moex_carry.news_live_causal_ops import (
    augment_query_with_event_terms,
)
from moex_carry.news_live_feed import export_live_news_feed
from moex_carry.news_live_clients import (
    fetch_gdelt_articles as _fetch_gdelt_articles,
    fetch_newsapi_articles as _fetch_newsapi_articles,
)
from moex_carry.news_live_scoring import (
    ModelScorer,
    ScoringModelConfig,
)
from moex_carry.news_live_runtime_ops import (
    article_id as _article_id_impl,
    backfill_missing_causal as _backfill_missing_causal_impl,
    backfill_story_ids as _backfill_story_ids_impl,
    init_db as _init_db_impl,
    insert_articles as _insert_articles_impl,
    normalize_text as _normalize_text_impl,
    normalize_url as _normalize_url_impl,
    retry_fetch as _retry_fetch_impl,
    safe_json as _safe_json_impl,
    score_new_articles as _score_new_articles_impl,
    story_id as _story_id_impl,
    upsert_article_links as _upsert_article_links_impl,
)
from moex_carry.news_storage import (
    open_sqlite_connection,
    parse_any_utc,
    resolve_data_path,
    sqlite_path_from_url,
)
from moex_carry.news_runtime_state import (
    get_state,
    iso_utc,
    newsapi_usage,
    reserve_newsapi_request,
    set_state,
    should_poll_newsapi_live,
    utc_now,
)


@dataclass(frozen=True)
class CommodityProfile:
    ticker: str
    name: str
    gdelt_query: str
    newsapi_query: str
    language: str = "en"


@dataclass(frozen=True)
class NewsIngestConfig:
    database_url: str
    commodity_profiles: tuple[CommodityProfile, ...]
    data_dir: str = "./data"
    gdelt_enabled: bool = True
    gdelt_max_records_per_call: int = 80
    gdelt_min_request_interval_sec: float = 2.0
    gdelt_request_timeout_sec: float = 30.0
    gdelt_retry_attempts: int = 3
    gdelt_retry_backoff_sec: float = 1.5
    live_lookback_minutes: int = 120
    backfill_chunk_days: int = 30
    backfill_max_windows_per_commodity: int = 20
    feed_path: str | None = None
    feed_min_impact_score: float = 0.35
    feed_min_confidence: float = 0.9
    feed_min_fundamental_score: float = 0.45
    feed_max_rows: int = 5000
    feed_require_primary_cause: bool = True
    feed_require_verified_move: bool = False
    feed_require_verified_both_horizons: bool = True
    discovery_feed_path: str = "data/output/news_live/live_news_discovery.csv"
    discovery_feed_min_impact_score: float = 0.35
    discovery_feed_min_confidence: float = 0.55
    discovery_feed_min_fundamental_score: float = 0.35
    discovery_feed_max_rows: int = 5000
    discovery_feed_require_primary_cause: bool = False
    discovery_min_link_score: float = 0.6
    verified_feed_path: str = "data/output/news_live/live_news_verified.csv"
    verified_feed_min_impact_score: float = 0.35
    verified_feed_min_confidence: float = 0.9
    verified_feed_min_fundamental_score: float = 0.45
    verified_feed_max_rows: int = 5000
    verified_feed_require_primary_cause: bool = True
    verified_feed_require_verified_move: bool = True
    verified_feed_require_verified_both_horizons: bool = True
    verified_min_link_score: float = 0.7
    causal_profile: str = "discovery"
    newsapi_enabled: bool = True
    newsapi_api_key: str | None = None
    newsapi_timeout_sec: float = 30.0
    newsapi_page_size: int = 100
    newsapi_sort_by: str = "publishedAt"
    newsapi_retry_attempts: int = 2
    newsapi_retry_backoff_sec: float = 1.0
    newsapi_live_min_interval_minutes: int = 90
    newsapi_backfill_chunk_days: int = 1
    newsapi_daily_quota: int = 100
    newsapi_realtime_budget: int = 55
    newsapi_backfill_budget: int = 35
    newsapi_backfill_windows_per_commodity: int = 3
    newsapi_emergency_buffer: int = 10
    model_mode: str = "keyword"
    nli_model_name: str = "facebook/bart-large-mnli"
    finbert_model_name: str = "ProsusAI/finbert"
    model_device: str = "auto"

    @staticmethod
    def from_yaml(path: Path) -> "NewsIngestConfig":
        if not path.exists():
            raise FileNotFoundError(f"News config not found: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("News config must be a mapping")

        database = raw.get("database") if isinstance(raw.get("database"), dict) else {}
        ingest = raw.get("news_ingest") if isinstance(raw.get("news_ingest"), dict) else {}
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        newsapi = ingest.get("newsapi") if isinstance(ingest.get("newsapi"), dict) else {}
        models = raw.get("news_models") if isinstance(raw.get("news_models"), dict) else {}

        profiles: list[CommodityProfile] = []
        for item in ingest.get("commodity_profiles") or []:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").strip().upper()
            gdelt_query = str(item.get("gdelt_query") or "").strip()
            if not ticker or not gdelt_query:
                continue
            newsapi_query = str(item.get("newsapi_query") or gdelt_query).strip()
            language = str(item.get("language") or "en").strip() or "en"
            profiles.append(
                CommodityProfile(
                    ticker=ticker,
                    name=str(item.get("name") or ticker).strip() or ticker,
                    gdelt_query=gdelt_query,
                    newsapi_query=newsapi_query,
                    language=language,
                )
            )
        if not profiles:
            raise ValueError("news_ingest.commodity_profiles is empty")

        api_key = str(newsapi.get("api_key") or "").strip() or None
        env_key_name = str(newsapi.get("api_key_env") or "NEWS_API_KEY").strip() or "NEWS_API_KEY"
        env_key = str(os.environ.get(env_key_name) or "").strip()
        if env_key:
            api_key = env_key

        return NewsIngestConfig(
            database_url=str(database.get("url") or "sqlite:///./data/news_livecheck_ng.db"),
            data_dir=str(data.get("data_dir") or "./data"),
            commodity_profiles=tuple(profiles),
            gdelt_enabled=bool(ingest.get("gdelt_enabled", True)),
            gdelt_max_records_per_call=int(ingest.get("gdelt_max_records_per_call", 80)),
            gdelt_min_request_interval_sec=float(ingest.get("gdelt_min_request_interval_sec", 2.0)),
            gdelt_request_timeout_sec=float(ingest.get("gdelt_request_timeout_sec", 30.0)),
            gdelt_retry_attempts=max(1, int(ingest.get("gdelt_retry_attempts", 3))),
            gdelt_retry_backoff_sec=max(0.0, float(ingest.get("gdelt_retry_backoff_sec", 1.5))),
            live_lookback_minutes=int(ingest.get("live_lookback_minutes", 120)),
            backfill_chunk_days=int(ingest.get("backfill_chunk_days", 30)),
            backfill_max_windows_per_commodity=int(ingest.get("backfill_max_windows_per_commodity", 20)),
            feed_path=str(ingest.get("feed_path") or "").strip() or None,
            feed_min_impact_score=float(ingest.get("feed_min_impact_score", 0.35)),
            feed_min_confidence=float(ingest.get("feed_min_confidence", 0.9)),
            feed_min_fundamental_score=float(ingest.get("feed_min_fundamental_score", 0.45)),
            feed_max_rows=int(ingest.get("feed_max_rows", 5000)),
            feed_require_primary_cause=bool(ingest.get("feed_require_primary_cause", True)),
            feed_require_verified_move=bool(ingest.get("feed_require_verified_move", False)),
            feed_require_verified_both_horizons=bool(ingest.get("feed_require_verified_both_horizons", True)),
            discovery_feed_path=str(
                ingest.get("discovery_feed_path")
                or ingest.get("feed_path")
                or "data/output/news_live/live_news_discovery.csv"
            ),
            discovery_feed_min_impact_score=float(ingest.get("discovery_feed_min_impact_score", 0.35)),
            discovery_feed_min_confidence=float(ingest.get("discovery_feed_min_confidence", 0.55)),
            discovery_feed_min_fundamental_score=float(ingest.get("discovery_feed_min_fundamental_score", 0.35)),
            discovery_feed_max_rows=int(ingest.get("discovery_feed_max_rows", 5000)),
            discovery_feed_require_primary_cause=bool(ingest.get("discovery_feed_require_primary_cause", False)),
            discovery_min_link_score=float(ingest.get("discovery_min_link_score", 0.6)),
            verified_feed_path=str(
                ingest.get("verified_feed_path")
                or "data/output/news_live/live_news_verified.csv"
            ),
            verified_feed_min_impact_score=float(
                ingest.get("verified_feed_min_impact_score", ingest.get("feed_min_impact_score", 0.35))
            ),
            verified_feed_min_confidence=float(
                ingest.get("verified_feed_min_confidence", ingest.get("feed_min_confidence", 0.9))
            ),
            verified_feed_min_fundamental_score=float(
                ingest.get("verified_feed_min_fundamental_score", ingest.get("feed_min_fundamental_score", 0.45))
            ),
            verified_feed_max_rows=int(ingest.get("verified_feed_max_rows", ingest.get("feed_max_rows", 5000))),
            verified_feed_require_primary_cause=bool(
                ingest.get("verified_feed_require_primary_cause", ingest.get("feed_require_primary_cause", True))
            ),
            verified_feed_require_verified_move=bool(
                ingest.get("verified_feed_require_verified_move", ingest.get("feed_require_verified_move", True))
            ),
            verified_feed_require_verified_both_horizons=bool(
                ingest.get(
                    "verified_feed_require_verified_both_horizons",
                    ingest.get("feed_require_verified_both_horizons", True),
                )
            ),
            verified_min_link_score=float(ingest.get("verified_min_link_score", 0.7)),
            causal_profile=str(ingest.get("causal_profile") or "discovery").strip().lower() or "discovery",
            newsapi_enabled=bool(newsapi.get("enabled", True)),
            newsapi_api_key=api_key,
            newsapi_timeout_sec=float(newsapi.get("timeout_sec", 30.0)),
            newsapi_page_size=max(1, min(int(newsapi.get("page_size", 100)), 100)),
            newsapi_sort_by=str(newsapi.get("sort_by") or "publishedAt"),
            newsapi_retry_attempts=max(1, int(newsapi.get("retry_attempts", 2))),
            newsapi_retry_backoff_sec=max(0.0, float(newsapi.get("retry_backoff_sec", 1.0))),
            newsapi_live_min_interval_minutes=max(0, int(newsapi.get("live_min_interval_minutes", 90))),
            newsapi_backfill_chunk_days=max(
                1,
                int(newsapi.get("backfill_chunk_days", 1)),
            ),
            newsapi_daily_quota=max(1, int(newsapi.get("daily_quota", 100))),
            newsapi_realtime_budget=max(0, int(newsapi.get("realtime_budget", 55))),
            newsapi_backfill_budget=max(0, int(newsapi.get("backfill_budget", 35))),
            newsapi_backfill_windows_per_commodity=max(
                1,
                int(newsapi.get("backfill_windows_per_commodity", 3)),
            ),
            newsapi_emergency_buffer=max(0, int(newsapi.get("emergency_buffer", 10))),
            model_mode=str(models.get("primary_model") or "keyword").strip().lower(),
            nli_model_name=str(models.get("nli_model_name") or "facebook/bart-large-mnli"),
            finbert_model_name=str(models.get("finbert_model_name") or "ProsusAI/finbert"),
            model_device=str(models.get("device") or "auto").strip().lower(),
        )

def _normalize_text(value: object) -> str:
    return _normalize_text_impl(value)


def _normalize_url(value: object) -> str:
    return _normalize_url_impl(value)


def _article_id(*, provider: str, title: str, url: str, published_at: str) -> str:
    return _article_id_impl(provider=provider, title=title, url=url, published_at=published_at)


def _story_id(*, provider: str, title: str, url: str, published_at: str) -> str:
    return _story_id_impl(provider=provider, title=title, url=url, published_at=published_at)


def _safe_json(value: object) -> str:
    return _safe_json_impl(value)


def _init_db(conn: sqlite3.Connection) -> None:
    _init_db_impl(conn)


def _backfill_story_ids(conn: sqlite3.Connection) -> None:
    _backfill_story_ids_impl(conn)


def _retry_fetch(
    fetch_fn,
    *,
    attempts: int,
    backoff_sec: float,
) -> list[dict[str, Any]]:
    return _retry_fetch_impl(fetch_fn, attempts=attempts, backoff_sec=backoff_sec)


def _insert_articles(
    conn: sqlite3.Connection,
    *,
    commodity: str,
    query_text: str,
    fetched_at_utc: str,
    items: list[dict[str, Any]],
    allowed_commodities: tuple[str, ...],
) -> tuple[int, int]:
    return _insert_articles_impl(
        conn,
        commodity=commodity,
        query_text=query_text,
        fetched_at_utc=fetched_at_utc,
        items=items,
        allowed_commodities=allowed_commodities,
    )


def _score_new_articles(
    conn: sqlite3.Connection,
    scorer: ModelScorer,
    *,
    causal_profile: str,
) -> int:
    return _score_new_articles_impl(conn, scorer, causal_profile=causal_profile)


def _upsert_article_links(
    conn: sqlite3.Connection,
    *,
    article_id: str,
    seed_commodity: str,
    title: str,
    description: str,
    content: str,
    fetched_at_utc: str,
    allowed_commodities: tuple[str, ...],
) -> None:
    _upsert_article_links_impl(
        conn,
        article_id=article_id,
        seed_commodity=seed_commodity,
        title=title,
        description=description,
        content=content,
        fetched_at_utc=fetched_at_utc,
        allowed_commodities=allowed_commodities,
    )


def run_news_ingest_cycle(
    *,
    config: NewsIngestConfig,
    mode: str,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"live", "backfill"}:
        raise ValueError(f"Unsupported mode: {mode}")
    ts_now = now_utc.astimezone(timezone.utc) if now_utc is not None else utc_now()
    started_at = iso_utc(ts_now)

    db_path = sqlite_path_from_url(config.database_url, data_dir=config.data_dir)
    discovery_feed_path = resolve_data_path(
        config.feed_path or config.discovery_feed_path or "data/output/news_live/live_news_discovery.csv",
        data_dir=config.data_dir,
    )
    verified_feed_path = resolve_data_path(
        config.verified_feed_path or "data/output/news_live/live_news_verified.csv",
        data_dir=config.data_dir,
    )
    conn = open_sqlite_connection(db_path, timeout_sec=15.0, write=True)
    try:
        _init_db(conn)
        _backfill_story_ids(conn)
        session = requests.Session()
        scorer = ModelScorer(
            ScoringModelConfig(
                mode=config.model_mode,
                nli_model_name=config.nli_model_name,
                finbert_model_name=config.finbert_model_name,
                model_device=config.model_device,
            )
        )
        fetched_total = 0
        inserted_total = 0
        provider_counts: dict[str, int] = {}
        commodity_counts: dict[str, int] = {}
        allowed_commodities = tuple(profile.ticker for profile in config.commodity_profiles)

        for profile in config.commodity_profiles:
            commodity_inserted = 0
            gdelt_query = augment_query_with_event_terms(
                profile.gdelt_query,
                commodity=profile.ticker,
                max_terms=8,
            )
            newsapi_query = augment_query_with_event_terms(
                profile.newsapi_query,
                commodity=profile.ticker,
                max_terms=8,
            )
            for provider in ("gdelt", "newsapi"):
                if provider == "gdelt":
                    if not config.gdelt_enabled:
                        continue
                    if normalized_mode == "live":
                        end_utc = ts_now
                        start_utc = end_utc - timedelta(minutes=max(config.live_lookback_minutes, 1))
                        windows = [(start_utc, end_utc)]
                        cursor_key: str | None = None
                    else:
                        cursor_key = f"backfill_cursor_utc:gdelt:{profile.ticker}"
                        cursor_raw = get_state(conn, cursor_key)
                        cursor_dt = parse_any_utc(cursor_raw) if cursor_raw else ts_now
                        if cursor_dt is None:
                            cursor_dt = ts_now
                        windows = []
                        for _ in range(max(config.backfill_max_windows_per_commodity, 1)):
                            end_utc = cursor_dt
                            start_utc = end_utc - timedelta(days=max(config.backfill_chunk_days, 1))
                            windows.append((start_utc, end_utc))
                            cursor_dt = start_utc

                    for start_utc, end_utc in windows:
                        fetch_ok = True
                        try:
                            fetched = _retry_fetch(
                                lambda: _fetch_gdelt_articles(
                                    session,
                                    query=gdelt_query,
                                    start_utc=start_utc,
                                    end_utc=end_utc,
                                    max_records=max(config.gdelt_max_records_per_call, 1),
                                    timeout_sec=max(config.gdelt_request_timeout_sec, 1.0),
                                ),
                                attempts=config.gdelt_retry_attempts,
                                backoff_sec=config.gdelt_retry_backoff_sec,
                            )
                        except Exception:
                            fetched = []
                            fetch_ok = False
                        got, inserted = _insert_articles(
                            conn,
                            commodity=profile.ticker,
                            query_text=gdelt_query,
                            fetched_at_utc=started_at,
                            items=fetched,
                            allowed_commodities=allowed_commodities,
                        )
                        fetched_total += got
                        inserted_total += inserted
                        commodity_inserted += inserted
                        provider_counts["gdelt"] = provider_counts.get("gdelt", 0) + inserted
                        if cursor_key is not None and fetch_ok:
                            set_state(conn, cursor_key, iso_utc(start_utc))
                        if cursor_key is not None and not fetch_ok:
                            break
                        if config.gdelt_min_request_interval_sec > 0:
                            time.sleep(config.gdelt_min_request_interval_sec)
                else:
                    if not config.newsapi_enabled or not config.newsapi_api_key:
                        continue
                    if normalized_mode == "live" and not should_poll_newsapi_live(
                        conn,
                        commodity=profile.ticker,
                        now_utc=ts_now,
                        min_interval_minutes=config.newsapi_live_min_interval_minutes,
                    ):
                        continue
                    if normalized_mode == "live":
                        windows = [
                            (
                                ts_now - timedelta(minutes=max(config.live_lookback_minutes, 1)),
                                ts_now,
                            )
                        ]
                        cursor_key = None
                    else:
                        cursor_key = f"backfill_cursor_utc:newsapi:{profile.ticker}"
                        cursor_raw = get_state(conn, cursor_key)
                        cursor_dt = parse_any_utc(cursor_raw) if cursor_raw else ts_now
                        if cursor_dt is None:
                            cursor_dt = ts_now
                        windows = []
                        for _ in range(max(config.newsapi_backfill_windows_per_commodity, 1)):
                            end_utc = cursor_dt
                            start_utc = end_utc - timedelta(days=max(config.newsapi_backfill_chunk_days, 1))
                            windows.append((start_utc, end_utc))
                            cursor_dt = start_utc

                    for start_utc, end_utc in windows:
                        if not reserve_newsapi_request(
                            conn,
                            mode=normalized_mode,
                            daily_quota=config.newsapi_daily_quota,
                            realtime_budget=config.newsapi_realtime_budget,
                            backfill_budget=config.newsapi_backfill_budget,
                            emergency_buffer=config.newsapi_emergency_buffer,
                        ):
                            break
                        fetch_ok = True
                        try:
                            fetched = _retry_fetch(
                                lambda: _fetch_newsapi_articles(
                                    session,
                                    api_key=config.newsapi_api_key,
                                    query=newsapi_query,
                                    start_utc=start_utc,
                                    end_utc=end_utc,
                                    language=profile.language,
                                    page_size=config.newsapi_page_size,
                                    sort_by=config.newsapi_sort_by,
                                    timeout_sec=max(config.newsapi_timeout_sec, 1.0),
                                ),
                                attempts=config.newsapi_retry_attempts,
                                backoff_sec=config.newsapi_retry_backoff_sec,
                            )
                        except Exception:
                            fetched = []
                            fetch_ok = False
                        got, inserted = _insert_articles(
                            conn,
                            commodity=profile.ticker,
                            query_text=newsapi_query,
                            fetched_at_utc=started_at,
                            items=fetched,
                            allowed_commodities=allowed_commodities,
                        )
                        fetched_total += got
                        inserted_total += inserted
                        commodity_inserted += inserted
                        provider_counts["newsapi"] = provider_counts.get("newsapi", 0) + inserted
                        if cursor_key is not None and fetch_ok:
                            set_state(conn, cursor_key, iso_utc(start_utc))
                        if cursor_key is not None and not fetch_ok:
                            break

            commodity_counts[profile.ticker] = commodity_inserted

        scored_total = _score_new_articles(
            conn,
            scorer,
            causal_profile=config.causal_profile,
        )
        causal_backfilled_total = _backfill_missing_causal_impl(conn)
        discovery_feed_rows = export_live_news_feed(
            conn,
            feed_path=discovery_feed_path,
            feed_role="discovery",
            min_impact_score=config.discovery_feed_min_impact_score,
            min_confidence=config.discovery_feed_min_confidence,
            min_fundamental_score=config.discovery_feed_min_fundamental_score,
            min_link_score=config.discovery_min_link_score,
            max_rows=max(config.discovery_feed_max_rows, 1),
            require_primary_cause=bool(config.discovery_feed_require_primary_cause),
            require_verified_move=False,
            require_verified_both_horizons=False,
        )
        verified_feed_rows = export_live_news_feed(
            conn,
            feed_path=verified_feed_path,
            feed_role="verified",
            min_impact_score=config.verified_feed_min_impact_score,
            min_confidence=config.verified_feed_min_confidence,
            min_fundamental_score=config.verified_feed_min_fundamental_score,
            min_link_score=config.verified_min_link_score,
            max_rows=max(config.verified_feed_max_rows, 1),
            require_primary_cause=bool(config.verified_feed_require_primary_cause),
            require_verified_move=bool(config.verified_feed_require_verified_move),
            require_verified_both_horizons=bool(config.verified_feed_require_verified_both_horizons),
        )
        run_id = f"news-ingest-{ts_now.strftime('%Y%m%d%H%M%S')}-{int(time.time() * 1000)}-{normalized_mode}"
        finished_at = iso_utc(utc_now())
        conn.execute(
            """
            INSERT INTO news_fetch_runs (
                run_id,
                mode,
                started_at_utc,
                finished_at_utc,
                fetched_total,
                inserted_total,
                scored_total,
                provider_counts_json,
                commodity_counts_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                normalized_mode,
                started_at,
                finished_at,
                int(fetched_total),
                int(inserted_total),
                int(scored_total),
                _safe_json(provider_counts),
                _safe_json(commodity_counts),
            ),
        )
        conn.commit()

        day_utc = utc_now().strftime("%Y-%m-%d")
        used_live, used_backfill = newsapi_usage(conn, day_utc)
        return {
            "run_id": run_id,
            "mode": normalized_mode,
            "database_path": str(db_path),
            "feed_path": str(discovery_feed_path),
            "discovery_feed_path": str(discovery_feed_path),
            "verified_feed_path": str(verified_feed_path),
            "fetched_total": int(fetched_total),
            "inserted_total": int(inserted_total),
            "scored_total": int(scored_total),
            "causal_backfilled_total": int(causal_backfilled_total),
            "feed_rows": int(discovery_feed_rows),
            "discovery_feed_rows": int(discovery_feed_rows),
            "verified_feed_rows": int(verified_feed_rows),
            "provider_counts": provider_counts,
            "commodity_counts": commodity_counts,
            "newsapi_usage": {
                "day_utc": day_utc,
                "used_live": int(used_live),
                "used_backfill": int(used_backfill),
                "used_total": int(used_live + used_backfill),
                "daily_quota": int(config.newsapi_daily_quota),
                "realtime_budget": int(config.newsapi_realtime_budget),
                "backfill_budget": int(config.newsapi_backfill_budget),
                "emergency_buffer": int(config.newsapi_emergency_buffer),
            },
        }
    finally:
        conn.close()
