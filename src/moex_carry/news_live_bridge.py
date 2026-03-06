from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from moex_carry.config import AppSettings
from moex_carry.domain.decision import NewsItem
from moex_carry.news_storage import parse_any_utc, resolve_data_path


logger = logging.getLogger(__name__)


def _normalize_now(as_of_utc: datetime | None) -> datetime:
    now_utc = as_of_utc if as_of_utc is not None else datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        return now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(timezone.utc)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _read_feed(feed_path: Path) -> pd.DataFrame:
    try:
        if not feed_path.exists():
            return pd.DataFrame()
        return pd.read_csv(feed_path)
    except Exception as exc:
        logger.warning("news_live_bridge feed read error: %s (feed=%s)", exc, feed_path)
        return pd.DataFrame()


def _apply_cause_filter(df: pd.DataFrame) -> pd.DataFrame:
    required = {"cause_classification", "fundamental_score", "is_primary_cause"}
    if not required.issubset(set(df.columns)):
        return df
    if "feed_role" in df.columns:
        feed_role = df["feed_role"].fillna("").astype(str).str.strip().str.lower()
        discovery = df.loc[feed_role.eq("discovery")].copy()
        other = df.loc[~feed_role.eq("discovery")].copy()
        if other.empty:
            return discovery
        filtered_other = _apply_cause_filter(other.drop(columns=["feed_role"]))
        if "feed_role" not in filtered_other.columns:
            filtered_other["feed_role"] = other.loc[filtered_other.index, "feed_role"]
        return pd.concat([discovery, filtered_other], ignore_index=False).sort_index()
    classification = (
        df["cause_classification"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )
    fundamental_score = pd.to_numeric(df["fundamental_score"], errors="coerce").fillna(0.0)
    is_primary = df["is_primary_cause"].apply(_as_bool)
    keep = is_primary | (classification.isin({"cause", "mixed"}) & (fundamental_score >= 0.45))
    return df.loc[keep].copy()


def _build_news_item(row: dict[str, object], *, default_title: str) -> NewsItem | None:
    ts = parse_any_utc(row.get("published_at_utc"))
    if ts is None:
        return None
    source = str(row.get("source_name") or row.get("provider") or "news").strip()
    severity = str(row.get("severity") or "low").strip().lower()
    title = str(row.get("title") or row.get("headline") or default_title).strip() or default_title
    item_id = (
        (
            f"{str(row.get('story_id') or row.get('story_key') or '').strip()}:{str(row.get('commodity') or '').strip().upper()}"
            if str(row.get("story_id") or row.get("story_key") or "").strip()
            and str(row.get("commodity") or "").strip()
            else ""
        )
        or str(row.get("article_id") or "").strip()
        or str(row.get("news_id") or "").strip()
        or str(row.get("story_key") or "").strip()
        or str(row.get("id") or "").strip()
    )
    if not item_id:
        item_id = f"{source}:{ts.isoformat()}"
    return NewsItem(
        item_id=item_id,
        timestamp=ts,
        source=source,
        title=title,
        severity=severity,
        impact_score=float(row.get("impact_score") or 0.0),
    )


def load_news_gate_items(settings: AppSettings, *, as_of_utc: datetime | None = None) -> list[NewsItem]:
    if not settings.news_filter.live_ingest_enabled:
        return []
    now_utc = _normalize_now(as_of_utc)
    cutoff = now_utc - timedelta(minutes=max(int(settings.news_filter.lookback_minutes), 1))
    allowed_sources = {item.strip().lower() for item in settings.news_filter.sources if item.strip()}

    feed_path = resolve_data_path(
        getattr(settings.news_filter, "live_feed_path", "data/output/news_live/live_news_discovery.csv"),
        data_dir=settings.data.data_dir,
    )
    feed_df = _read_feed(feed_path)
    if feed_df.empty:
        if bool(getattr(settings.news_filter, "live_db_fallback_enabled", False)):
            logger.warning(
                "news_live_bridge DB fallback is no longer supported; set news feed export and live_feed_path (feed=%s)",
                feed_path,
            )
        return []

    df = feed_df.copy()
    if "published_at_utc" not in df.columns:
        logger.warning("news_live_bridge missing 'published_at_utc' column in feed (%s)", feed_path)
        return []

    if "impact_score" in df.columns:
        impact = pd.to_numeric(df["impact_score"], errors="coerce").fillna(0.0)
        df = df.loc[impact >= float(settings.news_filter.live_min_impact_score)].copy()
    if "confidence" in df.columns:
        confidence = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)
        df = df.loc[confidence >= float(settings.news_filter.live_min_confidence)].copy()
    df = _apply_cause_filter(df)

    if "source_name" not in df.columns:
        if "source" in df.columns:
            df["source_name"] = df["source"]
        elif "provider" in df.columns:
            df["source_name"] = df["provider"]
        else:
            df["source_name"] = "news"

    items: list[NewsItem] = []
    rows = df.sort_values(by="published_at_utc", ascending=False).to_dict(orient="records")
    max_items = max(int(settings.news_filter.live_max_items), 1)
    for row in rows:
        source = str(row.get("source_name") or row.get("provider") or "").strip().lower()
        if allowed_sources and source and source not in allowed_sources:
            continue
        item = _build_news_item(row, default_title=f"{row.get('commodity') or 'commodity'} news")
        if item is None:
            continue
        if item.timestamp < cutoff:
            continue
        items.append(item)
        if len(items) >= max_items:
            break
    return items
