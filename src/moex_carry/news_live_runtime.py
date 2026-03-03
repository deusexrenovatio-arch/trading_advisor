from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml
from moex_carry.news_live_clients import (
    fetch_gdelt_articles as _fetch_gdelt_articles,
    fetch_newsapi_articles as _fetch_newsapi_articles,
)
from moex_carry.news_live_scoring import (
    MODEL_NAME_KEYWORD,
    SEVERITY_ORDER,
    ModelScorer,
    ScoringModelConfig,
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
    gdelt_enabled: bool = True
    gdelt_max_records_per_call: int = 80
    gdelt_min_request_interval_sec: float = 2.0
    gdelt_request_timeout_sec: float = 30.0
    gdelt_retry_attempts: int = 3
    gdelt_retry_backoff_sec: float = 1.5
    live_lookback_minutes: int = 120
    backfill_chunk_days: int = 30
    backfill_max_windows_per_commodity: int = 20
    feed_path: str = "data/output/news_live/live_news_signals.csv"
    feed_min_impact_score: float = 0.35
    feed_min_confidence: float = 0.9
    feed_max_rows: int = 5000
    newsapi_enabled: bool = True
    newsapi_api_key: str | None = None
    newsapi_timeout_sec: float = 30.0
    newsapi_page_size: int = 100
    newsapi_sort_by: str = "publishedAt"
    newsapi_retry_attempts: int = 2
    newsapi_retry_backoff_sec: float = 1.0
    newsapi_live_min_interval_minutes: int = 90
    newsapi_daily_quota: int = 100
    newsapi_realtime_budget: int = 55
    newsapi_backfill_budget: int = 35
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
            feed_path=str(ingest.get("feed_path") or "data/output/news_live/live_news_signals.csv"),
            feed_min_impact_score=float(ingest.get("feed_min_impact_score", 0.35)),
            feed_min_confidence=float(ingest.get("feed_min_confidence", 0.9)),
            feed_max_rows=int(ingest.get("feed_max_rows", 5000)),
            newsapi_enabled=bool(newsapi.get("enabled", True)),
            newsapi_api_key=api_key,
            newsapi_timeout_sec=float(newsapi.get("timeout_sec", 30.0)),
            newsapi_page_size=max(1, min(int(newsapi.get("page_size", 100)), 100)),
            newsapi_sort_by=str(newsapi.get("sort_by") or "publishedAt"),
            newsapi_retry_attempts=max(1, int(newsapi.get("retry_attempts", 2))),
            newsapi_retry_backoff_sec=max(0.0, float(newsapi.get("retry_backoff_sec", 1.0))),
            newsapi_live_min_interval_minutes=max(0, int(newsapi.get("live_min_interval_minutes", 90))),
            newsapi_daily_quota=max(1, int(newsapi.get("daily_quota", 100))),
            newsapi_realtime_budget=max(0, int(newsapi.get("realtime_budget", 55))),
            newsapi_backfill_budget=max(0, int(newsapi.get("backfill_budget", 35))),
            newsapi_emergency_buffer=max(0, int(newsapi.get("emergency_buffer", 10))),
            model_mode=str(models.get("primary_model") or "keyword").strip().lower(),
            nli_model_name=str(models.get("nli_model_name") or "facebook/bart-large-mnli"),
            finbert_model_name=str(models.get("finbert_model_name") or "ProsusAI/finbert"),
            model_device=str(models.get("device") or "auto").strip().lower(),
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_any_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    raw = str(value).strip()
    if not raw:
        return None
    parsed = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _sqlite_path_from_url(database_url: str) -> Path:
    normalized = str(database_url or "").strip()
    if normalized.startswith("sqlite:///"):
        path = normalized[len("sqlite:///") :]
        return Path(path)
    if normalized.startswith("sqlite://"):
        path = normalized[len("sqlite://") :]
        return Path(path)
    raise ValueError(f"Only sqlite database URL is supported for news ingest: {database_url}")


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


def _safe_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "{}"




def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_articles (
            article_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            commodity TEXT NOT NULL,
            source_name TEXT,
            published_at_utc TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            content TEXT,
            url TEXT,
            language TEXT,
            query_text TEXT,
            raw_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_articles_commodity_ts
        ON news_articles (commodity, published_at_utc DESC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_scores (
            article_id TEXT PRIMARY KEY,
            model_name TEXT NOT NULL,
            scored_at_utc TEXT NOT NULL,
            direction TEXT NOT NULL,
            impact_score REAL NOT NULL,
            confidence REAL NOT NULL,
            severity TEXT NOT NULL,
            reason_terms_up TEXT,
            reason_terms_down TEXT,
            FOREIGN KEY (article_id) REFERENCES news_articles(article_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_state (
            state_key TEXT PRIMARY KEY,
            state_value TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS newsapi_usage (
            day_utc TEXT PRIMARY KEY,
            used_live INTEGER NOT NULL DEFAULT 0,
            used_backfill INTEGER NOT NULL DEFAULT 0,
            updated_at_utc TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_fetch_runs (
            run_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            started_at_utc TEXT NOT NULL,
            finished_at_utc TEXT NOT NULL,
            fetched_total INTEGER NOT NULL,
            inserted_total INTEGER NOT NULL,
            scored_total INTEGER NOT NULL,
            provider_counts_json TEXT NOT NULL,
            commodity_counts_json TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _get_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT state_value FROM news_state WHERE state_key = ?", (key,)).fetchone()
    if row is None:
        return None
    return str(row[0])


def _set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO news_state (state_key, state_value, updated_at_utc)
        VALUES (?, ?, ?)
        ON CONFLICT(state_key) DO UPDATE SET
            state_value = excluded.state_value,
            updated_at_utc = excluded.updated_at_utc
        """,
        (key, value, _iso_utc(_utc_now())),
    )
    conn.commit()


def _newsapi_usage(conn: sqlite3.Connection, day_utc: str) -> tuple[int, int]:
    row = conn.execute(
        "SELECT used_live, used_backfill FROM newsapi_usage WHERE day_utc = ?",
        (day_utc,),
    ).fetchone()
    if row is None:
        return (0, 0)
    return (int(row[0] or 0), int(row[1] or 0))


def _reserve_newsapi_request(conn: sqlite3.Connection, cfg: NewsIngestConfig, *, mode: str) -> bool:
    day_utc = _utc_now().strftime("%Y-%m-%d")
    used_live, used_backfill = _newsapi_usage(conn, day_utc)
    used_total = used_live + used_backfill
    max_non_emergency = max(cfg.newsapi_daily_quota - cfg.newsapi_emergency_buffer, 0)
    if used_total >= max_non_emergency:
        return False
    if mode == "live" and used_live >= cfg.newsapi_realtime_budget:
        return False
    if mode == "backfill" and used_backfill >= cfg.newsapi_backfill_budget:
        return False

    if mode == "live":
        used_live += 1
    elif mode == "backfill":
        used_backfill += 1

    conn.execute(
        """
        INSERT INTO newsapi_usage (day_utc, used_live, used_backfill, updated_at_utc)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(day_utc) DO UPDATE SET
            used_live = excluded.used_live,
            used_backfill = excluded.used_backfill,
            updated_at_utc = excluded.updated_at_utc
        """,
        (day_utc, used_live, used_backfill, _iso_utc(_utc_now())),
    )
    conn.commit()
    return True


def _retry_fetch(
    fetch_fn,
    *,
    attempts: int,
    backoff_sec: float,
) -> list[dict[str, Any]]:
    last_exc: Exception | None = None
    total = max(int(attempts), 1)
    for idx in range(total):
        try:
            return fetch_fn()
        except Exception as exc:  # pragma: no cover - retry behavior is covered via call counting tests
            last_exc = exc
            if idx < total - 1 and backoff_sec > 0:
                time.sleep(backoff_sec * float(idx + 1))
    if last_exc is not None:
        raise last_exc
    return []


def _should_poll_newsapi_live(
    conn: sqlite3.Connection,
    *,
    commodity: str,
    now_utc: datetime,
    min_interval_minutes: int,
) -> bool:
    interval = max(int(min_interval_minutes), 0)
    if interval <= 0:
        return True
    state_key = f"newsapi_live_last_utc:{commodity.upper()}"
    raw = _get_state(conn, state_key)
    last_dt = _parse_any_utc(raw) if raw else None
    if last_dt is not None:
        elapsed = now_utc - last_dt
        if elapsed < timedelta(minutes=interval):
            return False
    _set_state(conn, state_key, _iso_utc(now_utc))
    return True


def _insert_articles(
    conn: sqlite3.Connection,
    *,
    commodity: str,
    query_text: str,
    fetched_at_utc: str,
    items: list[dict[str, Any]],
) -> tuple[int, int]:
    fetched = 0
    inserted = 0
    for item in items:
        title = _normalize_text(item.get("title"))
        url = _normalize_url(item.get("url"))
        published_at_utc = _normalize_text(item.get("published_at_utc"))
        if not title and not url:
            continue
        article_id = _article_id(
            provider=str(item.get("provider") or "unknown"),
            commodity=commodity,
            title=title,
            url=url,
            published_at=published_at_utc,
        )
        fetched += 1
        exists = conn.execute(
            "SELECT 1 FROM news_articles WHERE article_id = ?",
            (article_id,),
        ).fetchone()
        if exists is not None:
            conn.execute(
                "UPDATE news_articles SET fetched_at_utc = ?, raw_json = ? WHERE article_id = ?",
                (fetched_at_utc, _safe_json(item.get("raw")), article_id),
            )
            continue
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
                raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                str(item.get("provider") or ""),
                commodity,
                _normalize_text(item.get("source_name")),
                published_at_utc or fetched_at_utc,
                fetched_at_utc,
                title or "(untitled)",
                _normalize_text(item.get("description")),
                _normalize_text(item.get("content")),
                url,
                _normalize_text(item.get("language")),
                query_text,
                _safe_json(item.get("raw")),
            ),
        )
        inserted += 1
    conn.commit()
    return fetched, inserted


def _score_new_articles(conn: sqlite3.Connection, scorer: ModelScorer) -> int:
    rows = conn.execute(
        """
        SELECT a.article_id, a.commodity, a.title, a.description, a.content
        FROM news_articles a
        LEFT JOIN news_scores s ON a.article_id = s.article_id
        WHERE s.article_id IS NULL
        ORDER BY a.published_at_utc DESC
        """
    ).fetchall()
    if not rows:
        return 0
    scored_at_utc = _iso_utc(_utc_now())
    for row in rows:
        article_id, commodity, title, description, content = row
        score = scorer.score(
            commodity=str(commodity),
            title=str(title or ""),
            description=str(description or ""),
            content=str(content or ""),
        )
        severity = str(score["severity"]).lower()
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
                reason_terms_down
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(article_id),
                str(score.get("model_name") or MODEL_NAME_KEYWORD),
                scored_at_utc,
                str(score["direction"]),
                float(score["impact_score"]),
                float(score["confidence"]),
                severity,
                _safe_json(score.get("reason_terms_up") or []),
                _safe_json(score.get("reason_terms_down") or []),
            ),
        )
    conn.commit()
    return len(rows)


def _export_feed(
    conn: sqlite3.Connection,
    *,
    feed_path: Path,
    min_impact_score: float,
    min_confidence: float,
    max_rows: int,
) -> int:
    rows = conn.execute(
        """
        SELECT
            a.published_at_utc,
            a.commodity,
            s.direction,
            s.severity,
            s.impact_score,
            s.confidence,
            a.source_name,
            a.provider,
            a.title,
            a.url,
            s.reason_terms_up,
            s.reason_terms_down
        FROM news_articles a
        JOIN news_scores s ON a.article_id = s.article_id
        WHERE s.impact_score >= ?
          AND s.confidence >= ?
        ORDER BY a.published_at_utc DESC
        LIMIT ?
        """,
        (float(min_impact_score), float(min_confidence), int(max_rows)),
    ).fetchall()
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "published_at_utc",
        "commodity",
        "direction",
        "severity",
        "impact_score",
        "confidence",
        "source_name",
        "provider",
        "title",
        "url",
        "reason_terms_up",
        "reason_terms_down",
    ]
    if not rows:
        pd.DataFrame(columns=columns).to_csv(feed_path, index=False)
        return 0
    df = pd.DataFrame(rows, columns=columns)
    df.to_csv(feed_path, index=False)
    return int(len(df))


def run_news_ingest_cycle(
    *,
    config: NewsIngestConfig,
    mode: str,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"live", "backfill"}:
        raise ValueError(f"Unsupported mode: {mode}")
    ts_now = now_utc.astimezone(timezone.utc) if now_utc is not None else _utc_now()
    started_at = _iso_utc(ts_now)

    db_path = _sqlite_path_from_url(config.database_url)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        _init_db(conn)
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

        for profile in config.commodity_profiles:
            commodity_inserted = 0
            for provider in ("gdelt", "newsapi"):
                if provider == "gdelt":
                    if not config.gdelt_enabled:
                        continue
                    if normalized_mode == "live":
                        end_utc = ts_now
                        start_utc = end_utc - timedelta(minutes=max(config.live_lookback_minutes, 1))
                        windows = [(start_utc, end_utc)]
                    else:
                        cursor_key = f"backfill_cursor_utc:gdelt:{profile.ticker}"
                        cursor_raw = _get_state(conn, cursor_key)
                        cursor_dt = _parse_any_utc(cursor_raw) if cursor_raw else ts_now
                        if cursor_dt is None:
                            cursor_dt = ts_now
                        windows = []
                        for _ in range(max(config.backfill_max_windows_per_commodity, 1)):
                            end_utc = cursor_dt
                            start_utc = end_utc - timedelta(days=max(config.backfill_chunk_days, 1))
                            windows.append((start_utc, end_utc))
                            cursor_dt = start_utc
                        _set_state(conn, cursor_key, _iso_utc(cursor_dt))

                    for start_utc, end_utc in windows:
                        try:
                            fetched = _retry_fetch(
                                lambda: _fetch_gdelt_articles(
                                    session,
                                    query=profile.gdelt_query,
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
                        got, inserted = _insert_articles(
                            conn,
                            commodity=profile.ticker,
                            query_text=profile.gdelt_query,
                            fetched_at_utc=started_at,
                            items=fetched,
                        )
                        fetched_total += got
                        inserted_total += inserted
                        commodity_inserted += inserted
                        provider_counts["gdelt"] = provider_counts.get("gdelt", 0) + inserted
                        if config.gdelt_min_request_interval_sec > 0:
                            time.sleep(config.gdelt_min_request_interval_sec)
                else:
                    if not config.newsapi_enabled or not config.newsapi_api_key:
                        continue
                    if normalized_mode == "live" and not _should_poll_newsapi_live(
                        conn,
                        commodity=profile.ticker,
                        now_utc=ts_now,
                        min_interval_minutes=config.newsapi_live_min_interval_minutes,
                    ):
                        continue
                    if not _reserve_newsapi_request(conn, config, mode=normalized_mode):
                        continue
                    if normalized_mode == "live":
                        end_utc = ts_now
                        start_utc = end_utc - timedelta(minutes=max(config.live_lookback_minutes, 1))
                    else:
                        cursor_key = f"backfill_cursor_utc:newsapi:{profile.ticker}"
                        cursor_raw = _get_state(conn, cursor_key)
                        cursor_dt = _parse_any_utc(cursor_raw) if cursor_raw else ts_now
                        if cursor_dt is None:
                            cursor_dt = ts_now
                        end_utc = cursor_dt
                        start_utc = end_utc - timedelta(days=max(config.backfill_chunk_days, 1))
                        _set_state(conn, cursor_key, _iso_utc(start_utc))
                    try:
                        fetched = _retry_fetch(
                            lambda: _fetch_newsapi_articles(
                                session,
                                api_key=config.newsapi_api_key,
                                query=profile.newsapi_query,
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
                    got, inserted = _insert_articles(
                        conn,
                        commodity=profile.ticker,
                        query_text=profile.newsapi_query,
                        fetched_at_utc=started_at,
                        items=fetched,
                    )
                    fetched_total += got
                    inserted_total += inserted
                    commodity_inserted += inserted
                    provider_counts["newsapi"] = provider_counts.get("newsapi", 0) + inserted

            commodity_counts[profile.ticker] = commodity_inserted

        scored_total = _score_new_articles(conn, scorer)
        feed_rows = _export_feed(
            conn,
            feed_path=Path(config.feed_path),
            min_impact_score=config.feed_min_impact_score,
            min_confidence=config.feed_min_confidence,
            max_rows=max(config.feed_max_rows, 1),
        )
        run_id = f"news-ingest-{ts_now.strftime('%Y%m%d%H%M%S')}-{normalized_mode}"
        finished_at = _iso_utc(_utc_now())
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

        day_utc = _utc_now().strftime("%Y-%m-%d")
        used_live, used_backfill = _newsapi_usage(conn, day_utc)
        return {
            "run_id": run_id,
            "mode": normalized_mode,
            "database_path": str(db_path),
            "feed_path": str(Path(config.feed_path)),
            "fetched_total": int(fetched_total),
            "inserted_total": int(inserted_total),
            "scored_total": int(scored_total),
            "feed_rows": int(feed_rows),
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
