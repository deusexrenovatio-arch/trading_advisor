from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from moex_carry.config import AppSettings
from moex_carry.data.moex_iss import MoexIssClient
from moex_carry.news_live_runtime import NewsIngestConfig
from moex_carry.news_shock_enrichment import enrich_newsapi_for_symbol_candidates
from moex_carry.news_shock_live_input_helpers import (
    iso_utc as _iso_utc_impl,
    load_front_contract_prices as _load_front_contract_prices_impl,
    normalize_text as _normalize_text_impl,
    parse_date as _parse_date_impl,
    root_candidate_score as _root_candidate_score_impl,
    to_bool as _to_bool_impl,
    topic_relevance as _topic_relevance_impl,
)
from moex_carry.news_shock_schema import EMPTY_SHOCK_COLUMNS
from moex_carry.news_silver_store import apply_silver_labels_from_db
from moex_carry.news_storage import open_sqlite_connection, sqlite_path_from_url
from moex_carry.news_shock_symbol_map import VALID_ASSET_CODE_BY_SYMBOL
from moex_carry.news_topic import build_story_fingerprint, derive_root_topic_key


@dataclass(frozen=True)
class LiveShockInputConfig:
    lookback_hours: int = 6
    bar_minutes: int = 5
    min_abs_z: float = 2.0
    rolling_window_bars: int = 96
    rolling_min_bars: int = 24
    max_delay_minutes: float = 60.0
    strict_pre_shock_minutes: float = 10.0
    broad_context_lookback_minutes: float = 2880.0
    v2_min_relevance: float = 0.4
    broad_min_relevance: float = 0.2
    cross_commodity_min_relevance: float = 0.8
    news_min_impact_score: float = 0.35
    news_min_confidence: float = 0.55
    news_max_items_per_symbol: int = 3000
    front_contract_candidates: int = 4
    history_padding_days: int = 10
    root_reuse_lookback_minutes: float = 2880.0
    root_min_fundamental_score: float = 0.45
    root_min_cause_confidence: float = 0.45
    min_link_score: float = 0.6
    aftershock_max_gap_minutes: float = 2880.0
    enable_candidate_newsapi_enrichment: bool = False
    enrichment_window_minutes: int = 90
    enrichment_max_requests_per_symbol: int = 4


def _iso_utc(value: datetime) -> str:
    return _iso_utc_impl(value)


def _parse_date(value: object) -> datetime.date | None:
    return _parse_date_impl(value)


def _normalize_text(value: object) -> str:
    return _normalize_text_impl(value)


def _topic_relevance(symbol: str, text: str, *, candidate_commodity: str = "") -> float:
    return _topic_relevance_impl(symbol, text, candidate_commodity=candidate_commodity)


def _to_bool(value: object) -> bool:
    return _to_bool_impl(value)


def _root_candidate_score(row: pd.Series, cfg: LiveShockInputConfig) -> float:
    return _root_candidate_score_impl(row, cfg)


def _dedupe_news(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    work = df.copy()
    story_id = work.get("story_id")
    if story_id is None:
        story_id = pd.Series("", index=work.index, dtype="object")
    story_id = story_id.fillna("").astype(str).str.strip()
    generated = work.apply(
        lambda row: build_story_fingerprint(
            title=row.get("title"),
            url=row.get("url"),
            published_at_utc=row.get("published_at_utc"),
            provider=row.get("provider"),
        ),
        axis=1,
    )
    work["story_key"] = story_id.where(story_id.ne(""), generated)
    ranked = work.assign(
        _rank=(pd.to_numeric(work["impact_score"], errors="coerce").fillna(0.0) * 2.0)
        + pd.to_numeric(work["confidence"], errors="coerce").fillna(0.0)
        + pd.to_numeric(work["relevance"], errors="coerce").fillna(0.0)
    ).sort_values(["_rank", "published_at_utc"], ascending=[False, False])
    ranked = ranked.drop_duplicates(subset=["story_key"], keep="first")
    commodity_scope = (
        work.groupby("story_key")["commodity"]
        .apply(
            lambda values: ",".join(
                sorted(dict.fromkeys(str(item).strip().upper() for item in values if str(item).strip()))
            )
        )
        .to_dict()
    )
    ranked["commodity_scope"] = ranked["story_key"].map(commodity_scope).fillna(ranked.get("commodity", ""))
    return ranked.drop(columns=["_rank"]).reset_index(drop=True)


def _load_news_rows(
    *,
    db_path: Path,
    symbol: str,
    start_utc: datetime,
    end_utc: datetime,
    cfg: LiveShockInputConfig,
) -> pd.DataFrame:
    output_columns = [
        "article_id",
        "story_id",
        "commodity",
        "published_at_utc",
        "title",
        "description",
        "url",
        "source_name",
        "provider",
        "impact_score",
        "confidence",
        "commodity_link_score",
        "link_reason",
        "link_evidence_json",
        "direction",
        "severity",
        "cause_classification",
        "cause_event",
        "cause_route_key",
        "cause_claim_status",
        "cause_confidence",
        "fundamental_score",
        "direction_alignment",
        "is_primary_cause",
    ]

    def score_expr(columns: set[str], name: str, default_sql: str) -> str:
        if name in columns:
            return f"s.{name} AS {name}"
        return f"{default_sql} AS {name}"

    if not db_path.exists():
        return pd.DataFrame(columns=output_columns)
    conn = open_sqlite_connection(db_path, timeout_sec=5.0, write=False)
    try:
        article_cols = {
            str(row[1]).strip().lower()
            for row in conn.execute("PRAGMA table_info(news_articles)").fetchall()
        }
        score_cols = {
            str(row[1]).strip().lower()
            for row in conn.execute("PRAGMA table_info(news_scores)").fetchall()
        }
        link_table_exists = bool(
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name) = 'news_article_commodity_links'"
            ).fetchone()
        )
        story_select = "a.story_id AS story_id" if "story_id" in article_cols else "'' AS story_id"
        cause_exprs = [
            score_expr(score_cols, "cause_classification", "'unknown'"),
            score_expr(score_cols, "cause_event", "''"),
            score_expr(score_cols, "cause_route_key", "''"),
            score_expr(score_cols, "cause_claim_status", "'unknown'"),
            score_expr(score_cols, "cause_confidence", "0.0"),
            score_expr(score_cols, "fundamental_score", "0.0"),
            score_expr(score_cols, "direction_alignment", "0.5"),
            score_expr(score_cols, "is_primary_cause", "0"),
        ]
        if link_table_exists:
            rows = conn.execute(
                f"""
                SELECT
                    a.article_id,
                    {story_select},
                    COALESCE(l.commodity, a.commodity) AS commodity,
                    a.published_at_utc,
                    a.title,
                    a.description,
                    a.url,
                    a.source_name,
                    a.provider,
                    s.impact_score,
                    s.confidence,
                    COALESCE(l.link_score, 0.65) AS commodity_link_score,
                    COALESCE(l.link_reason, 'legacy_article_commodity') AS link_reason,
                    COALESCE(l.link_evidence_json, '[]') AS link_evidence_json,
                    s.direction,
                    s.severity,
                    {", ".join(cause_exprs)}
                FROM news_articles a
                JOIN news_scores s ON a.article_id = s.article_id
                LEFT JOIN news_article_commodity_links l ON a.article_id = l.article_id
                WHERE a.published_at_utc >= ?
                  AND a.published_at_utc <= ?
                  AND s.impact_score >= ?
                  AND s.confidence >= ?
                  AND COALESCE(l.commodity, a.commodity) = ?
                ORDER BY a.published_at_utc DESC
                LIMIT ?
                """,
                (
                    _iso_utc(start_utc),
                    _iso_utc(end_utc),
                    float(cfg.news_min_impact_score),
                    max(float(cfg.news_min_confidence), 0.25),
                    symbol.upper(),
                    int(max(cfg.news_max_items_per_symbol, 1) * 4),
                ),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT
                    a.article_id,
                    {story_select},
                    a.commodity,
                    a.published_at_utc,
                    a.title,
                    a.description,
                    a.url,
                    a.source_name,
                    a.provider,
                    s.impact_score,
                    s.confidence,
                    0.65 AS commodity_link_score,
                    'legacy_article_commodity' AS link_reason,
                    '[]' AS link_evidence_json,
                    s.direction,
                    s.severity,
                    {", ".join(cause_exprs)}
                FROM news_articles a
                JOIN news_scores s ON a.article_id = s.article_id
                WHERE a.published_at_utc >= ?
                  AND a.published_at_utc <= ?
                  AND s.impact_score >= ?
                  AND s.confidence >= ?
                  AND a.commodity = ?
                ORDER BY a.published_at_utc DESC
                LIMIT ?
                """,
                (
                    _iso_utc(start_utc),
                    _iso_utc(end_utc),
                    float(cfg.news_min_impact_score),
                    max(float(cfg.news_min_confidence), 0.25),
                    symbol.upper(),
                    int(max(cfg.news_max_items_per_symbol, 1) * 4),
                ),
            ).fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame(columns=output_columns)
    frame = pd.DataFrame(
        rows,
        columns=output_columns,
    )
    frame["published_dt"] = pd.to_datetime(frame["published_at_utc"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["published_dt"])
    frame["commodity"] = frame["commodity"].fillna("").astype(str).str.strip().str.upper()
    frame["commodity_link_score"] = pd.to_numeric(frame["commodity_link_score"], errors="coerce").fillna(0.0)
    frame = frame[frame["commodity_link_score"] >= float(cfg.min_link_score)]
    frame["text_blob"] = (
        frame["title"].fillna("").astype(str).str.strip()
        + " "
        + frame["description"].fillna("").astype(str).str.strip()
    ).str.strip()
    frame["relevance"] = frame.apply(
        lambda row: _topic_relevance(
            symbol,
            str(row.get("text_blob") or ""),
            candidate_commodity=str(row.get("commodity") or ""),
        ),
        axis=1,
    )
    frame["is_same_commodity"] = True
    frame = frame[
        pd.to_numeric(frame["confidence"], errors="coerce").fillna(0.0) >= float(cfg.news_min_confidence)
    ]
    if frame.empty:
        return frame.reset_index(drop=True)
    frame["cause_classification"] = frame["cause_classification"].fillna("").astype(str).str.strip().str.lower()
    frame["cause_event"] = frame["cause_event"].fillna("").astype(str).str.strip()
    frame["cause_route_key"] = frame["cause_route_key"].fillna("").astype(str).str.strip()
    frame["cause_claim_status"] = frame["cause_claim_status"].fillna("").astype(str).str.strip().str.lower()
    frame["cause_confidence"] = pd.to_numeric(frame["cause_confidence"], errors="coerce").fillna(0.0)
    frame["fundamental_score"] = pd.to_numeric(frame["fundamental_score"], errors="coerce").fillna(0.0)
    frame["direction_alignment"] = pd.to_numeric(frame["direction_alignment"], errors="coerce").fillna(0.5)
    frame["is_primary_cause"] = frame["is_primary_cause"].apply(_to_bool)
    frame = _dedupe_news(frame)
    return frame.reset_index(drop=True)


def _load_front_contract_prices(
    *,
    settings: AppSettings,
    client: MoexIssClient,
    asset_code: str,
    start_utc: datetime,
    end_utc: datetime,
    cfg: LiveShockInputConfig,
) -> pd.DataFrame:
    return _load_front_contract_prices_impl(
        settings=settings,
        client=client,
        asset_code=asset_code,
        start_utc=start_utc,
        end_utc=end_utc,
        cfg=cfg,
    )


def _build_shocks_for_symbol(
    *,
    symbol: str,
    prices: pd.DataFrame,
    news_rows: pd.DataFrame,
    start_utc: datetime,
    end_utc: datetime,
    cfg: LiveShockInputConfig,
) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    work = prices.copy()
    work = work.set_index("ts").sort_index()
    bar_rule = f"{max(int(cfg.bar_minutes), 1)}min"
    bars = work["price"].resample(bar_rule).last().dropna().to_frame("price")
    bars["prev_price"] = bars["price"].shift(1)
    bars["logret"] = np.log(bars["price"] / bars["prev_price"])
    bars["rolling_sigma"] = (
        bars["logret"].rolling(window=max(int(cfg.rolling_window_bars), 2), min_periods=max(int(cfg.rolling_min_bars), 2)).std(ddof=0)
    )
    bars["z_score"] = bars["logret"] / bars["rolling_sigma"]
    bars["abs_move_pct"] = np.abs(np.expm1(bars["logret"])) * 100.0
    bars = bars.dropna(subset=["prev_price", "logret", "rolling_sigma", "z_score"])
    bars = bars[(bars.index >= start_utc) & (bars.index <= end_utc)]
    bars = bars[np.abs(bars["z_score"]) >= float(cfg.min_abs_z)]
    if bars.empty:
        return pd.DataFrame()

    news_sorted = news_rows.sort_values("published_dt").reset_index(drop=True) if not news_rows.empty else news_rows
    if news_sorted is not None and not news_sorted.empty:
        defaults: tuple[tuple[str, object], ...] = (
            ("is_primary_cause", False),
            ("cause_classification", "unknown"),
            ("cause_event", ""),
            ("cause_route_key", ""),
            ("cause_claim_status", "unknown"),
            ("cause_confidence", 0.0),
            ("fundamental_score", 0.0),
            ("direction_alignment", 0.5),
            ("is_same_commodity", False),
            ("relevance", 0.0),
        )
        for name, default in defaults:
            if name not in news_sorted.columns:
                news_sorted[name] = default

    last_root_topic_id = ""
    last_root_ts: pd.Timestamp | None = None
    last_root_signature: dict[str, str] = {}
    topic_state: dict[str, dict[str, object]] = {}

    def _candidate_from_row(candidate_row: pd.Series) -> dict[str, Any]:
        return {
            "event_id": _normalize_text(candidate_row.get("article_id")),
            "story_id": _normalize_text(candidate_row.get("story_id")),
            "event_ts": _normalize_text(candidate_row.get("published_at_utc")),
            "delay_min": float(pd.to_numeric(candidate_row.get("delay_min"), errors="coerce")),
            "title": _normalize_text(candidate_row.get("title")),
            "url": _normalize_text(candidate_row.get("url")),
            "commodity_link_score": float(pd.to_numeric(candidate_row.get("commodity_link_score"), errors="coerce") or 0.0),
            "link_reason": _normalize_text(candidate_row.get("link_reason")),
            "cause_event": _normalize_text(candidate_row.get("cause_event")),
            "cause_route_key": _normalize_text(candidate_row.get("cause_route_key")),
            "cause_claim_status": _normalize_text(candidate_row.get("cause_claim_status")).lower(),
            "cause_classification": _normalize_text(candidate_row.get("cause_classification")).lower(),
            "cause_confidence": float(pd.to_numeric(candidate_row.get("cause_confidence"), errors="coerce") or 0.0),
            "fundamental_score": float(pd.to_numeric(candidate_row.get("fundamental_score"), errors="coerce") or 0.0),
            "direction_alignment": float(pd.to_numeric(candidate_row.get("direction_alignment"), errors="coerce") or 0.5),
            "is_primary_cause": _to_bool(candidate_row.get("is_primary_cause")),
        }

    rows: list[dict[str, Any]] = []
    for ts, row in bars.iterrows():
        direction = "up" if float(row["logret"]) > 0 else "down"
        broad = {
            "event_id": "",
            "story_id": "",
            "event_ts": "",
            "delay_min": np.nan,
            "title": "",
            "url": "",
            "commodity_link_score": 0.0,
            "link_reason": "",
            "cause_event": "",
            "cause_route_key": "",
            "cause_claim_status": "unknown",
            "cause_classification": "unknown",
            "cause_confidence": 0.0,
            "fundamental_score": 0.0,
            "direction_alignment": 0.5,
            "is_primary_cause": False,
        }
        v2 = dict(broad)
        root = dict(broad)
        selected_source = "none"
        selected = dict(broad)
        selected_match_mode = "none"
        root_reuse_reason = ""
        strict = pd.DataFrame()
        context = pd.DataFrame()
        if news_sorted is not None and not news_sorted.empty:
            candidates = news_sorted.copy()
            candidates["delay_min"] = (ts - candidates["published_dt"]).dt.total_seconds() / 60.0
            candidates = candidates[candidates["delay_min"] >= 0.0]
            strict_window_min = float(cfg.max_delay_minutes)
            if int(cfg.bar_minutes) <= 5 and float(cfg.strict_pre_shock_minutes) > 0:
                strict_window_min = min(strict_window_min, float(cfg.strict_pre_shock_minutes))
            strict = candidates[candidates["delay_min"] <= strict_window_min]
            context = candidates[candidates["delay_min"] <= float(cfg.broad_context_lookback_minutes)]

            broad_candidates = strict[
                (pd.to_numeric(strict["relevance"], errors="coerce").fillna(0.0) >= float(cfg.broad_min_relevance))
                | strict["is_same_commodity"]
            ]
            if broad_candidates.empty:
                broad_candidates = context[
                    pd.to_numeric(context["relevance"], errors="coerce").fillna(0.0)
                    >= float(cfg.cross_commodity_min_relevance)
                ]
                selected_match_mode = "broad_context" if not broad_candidates.empty else selected_match_mode
            if not broad_candidates.empty:
                broad_row = broad_candidates.sort_values(
                    ["is_same_commodity", "relevance", "confidence", "impact_score", "delay_min"],
                    ascending=[False, False, False, False, True],
                ).iloc[0]
                broad = _candidate_from_row(broad_row)
                if selected_match_mode == "none":
                    selected_match_mode = "broad_strict"
                v2_candidates = strict[
                    pd.to_numeric(strict["relevance"], errors="coerce").fillna(0.0)
                    >= float(cfg.v2_min_relevance)
                ]
                if not v2_candidates.empty:
                    v2_row = v2_candidates.sort_values(
                        ["is_same_commodity", "relevance", "confidence", "impact_score", "delay_min"],
                        ascending=[False, False, False, False, True],
                    ).iloc[0]
                    v2 = _candidate_from_row(v2_row)
                if v2["event_id"]:
                    selected_source = "v2_clean"
                    selected = v2
                    selected_match_mode = "v2_strict"
                elif broad["event_id"]:
                    selected_source = "broad"
                    selected = broad

            for pool_name, pool in (("root_strict", strict), ("root_context", context)):
                if pool.empty:
                    continue
                pool_work = pool.copy()
                pool_work["is_primary_cause"] = pool_work["is_primary_cause"].apply(_to_bool)
                pool_work["cause_classification"] = (
                    pool_work["cause_classification"].fillna("").astype(str).str.strip().str.lower()
                )
                pool_work["cause_event"] = pool_work["cause_event"].fillna("").astype(str).str.strip()
                pool_work["cause_route_key"] = pool_work["cause_route_key"].fillna("").astype(str).str.strip()
                pool_work["cause_confidence"] = pd.to_numeric(pool_work["cause_confidence"], errors="coerce").fillna(0.0)
                pool_work["fundamental_score"] = pd.to_numeric(pool_work["fundamental_score"], errors="coerce").fillna(0.0)
                root_candidates = pool_work[
                    (
                        pool_work["is_primary_cause"]
                        | (
                            (pool_work["fundamental_score"] >= float(cfg.root_min_fundamental_score))
                            & (pool_work["cause_confidence"] >= float(cfg.root_min_cause_confidence))
                        )
                    )
                    & pool_work["cause_classification"].isin({"cause", "mixed"})
                    & (
                        pool_work["cause_event"].ne("")
                        | pool_work["cause_route_key"].ne("")
                    )
                    & (
                        pool_work["is_same_commodity"]
                        | (
                            pd.to_numeric(pool_work["relevance"], errors="coerce").fillna(0.0)
                            >= float(cfg.broad_min_relevance)
                        )
                    )
                ]
                if root_candidates.empty:
                    continue
                root_candidates["_root_rank"] = root_candidates.apply(
                    lambda item: _root_candidate_score(item, cfg),
                    axis=1,
                )
                root_row = root_candidates.sort_values(
                    ["_root_rank", "is_primary_cause", "fundamental_score", "cause_confidence", "delay_min"],
                    ascending=[False, False, False, False, True],
                ).iloc[0]
                root = _candidate_from_row(root_row)
                selected_source = "root"
                selected = root
                selected_match_mode = pool_name
                break

        if selected["event_id"]:
            root_topic_id = derive_root_topic_key(
                symbol=symbol,
                headline=selected["title"],
                url=selected["url"],
                selected_event_id=selected["event_id"],
                selected_source=selected_source,
                explicit_root_topic_id="",
            )
            last_root_topic_id = root_topic_id
            last_root_ts = ts if isinstance(ts, pd.Timestamp) else pd.Timestamp(ts, tz="UTC")
            last_root_signature = {
                "story_id": str(selected.get("story_id") or "").strip(),
                "cause_event": str(selected.get("cause_event") or "").strip(),
                "cause_route_key": str(selected.get("cause_route_key") or "").strip(),
            }
        else:
            reuse_lookback_min = max(float(cfg.root_reuse_lookback_minutes), 0.0)
            can_reuse_window = (
                bool(last_root_topic_id)
                and last_root_ts is not None
                and ((ts - last_root_ts).total_seconds() / 60.0) <= reuse_lookback_min
            )
            semantic_pool = context.copy() if not context.empty else strict.copy()
            if can_reuse_window and not semantic_pool.empty and last_root_signature:
                story_id = str(last_root_signature.get("story_id") or "").strip()
                cause_event = str(last_root_signature.get("cause_event") or "").strip()
                cause_route_key = str(last_root_signature.get("cause_route_key") or "").strip()
                semantic_mask = pd.Series(False, index=semantic_pool.index)
                if story_id:
                    semantic_mask = semantic_mask | (
                        semantic_pool["story_id"].fillna("").astype(str).str.strip() == story_id
                    )
                if cause_event:
                    semantic_mask = semantic_mask | (
                        semantic_pool["cause_event"].fillna("").astype(str).str.strip() == cause_event
                    )
                if cause_route_key:
                    semantic_mask = semantic_mask | (
                        semantic_pool["cause_route_key"].fillna("").astype(str).str.strip() == cause_route_key
                    )
                semantic_pool = semantic_pool.loc[semantic_mask]
            else:
                semantic_pool = pd.DataFrame()
            if not semantic_pool.empty:
                semantic_pool["_reuse_rank"] = semantic_pool.apply(
                    lambda item: _root_candidate_score(item, cfg),
                    axis=1,
                )
                reuse_row = semantic_pool.sort_values(
                    ["_reuse_rank", "commodity_link_score", "confidence", "impact_score", "delay_min"],
                    ascending=[False, False, False, False, True],
                ).iloc[0]
                selected = _candidate_from_row(reuse_row)
                root_topic_id = str(last_root_topic_id)
                selected_source = "root_reuse"
                selected_match_mode = "root_reuse_semantic"
                root_reuse_reason = "shared_signature"
                last_root_ts = ts if isinstance(ts, pd.Timestamp) else pd.Timestamp(ts, tz="UTC")
            else:
                root_topic_id = derive_root_topic_key(
                    symbol=symbol,
                    headline=selected["title"],
                    url=selected["url"],
                    selected_event_id=selected["event_id"],
                    selected_source=selected_source,
                    explicit_root_topic_id="",
                )
        root_link_type = "orphan"
        root_primary_shock_ts = ""
        root_episode_event_index = 0
        if root_topic_id:
            prev_state = topic_state.get(root_topic_id)
            if prev_state is None:
                root_link_type = "primary"
                root_primary_shock_ts = _iso_utc(ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts)
                root_episode_event_index = 1
                topic_state[root_topic_id] = {
                    "primary_ts": ts,
                    "last_ts": ts,
                    "event_index": 1,
                }
            else:
                last_ts = prev_state.get("last_ts")
                gap_min = (
                    ((ts - last_ts).total_seconds() / 60.0)
                    if isinstance(last_ts, pd.Timestamp)
                    else float("inf")
                )
                if gap_min <= max(float(cfg.aftershock_max_gap_minutes), 0.0):
                    root_link_type = "aftershock"
                    root_episode_event_index = int(prev_state.get("event_index") or 0) + 1
                    primary_ts = prev_state.get("primary_ts")
                    if isinstance(primary_ts, pd.Timestamp):
                        root_primary_shock_ts = _iso_utc(primary_ts.to_pydatetime())
                    topic_state[root_topic_id] = {
                        "primary_ts": primary_ts if isinstance(primary_ts, pd.Timestamp) else ts,
                        "last_ts": ts,
                        "event_index": root_episode_event_index,
                    }
                else:
                    root_link_type = "primary"
                    root_primary_shock_ts = _iso_utc(ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts)
                    root_episode_event_index = 1
                    topic_state[root_topic_id] = {
                        "primary_ts": ts,
                        "last_ts": ts,
                        "event_index": 1,
                    }
        rows.append(
            {
                "symbol": symbol,
                "shock_ts": _iso_utc(ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts),
                "prev_ts": _iso_utc((ts - timedelta(minutes=max(int(cfg.bar_minutes), 1))).to_pydatetime() if isinstance(ts, pd.Timestamp) else ts - timedelta(minutes=max(int(cfg.bar_minutes), 1))),
                "bar_minutes": int(cfg.bar_minutes),
                "prev_price": float(row["prev_price"]),
                "price": float(row["price"]),
                "logret": float(row["logret"]),
                "abs_move_pct": float(row["abs_move_pct"]),
                "shock_direction": direction,
                "rolling_sigma": float(row["rolling_sigma"]),
                "z_score": float(row["z_score"]),
                "broad_event_id": broad["event_id"],
                "broad_event_ts": broad["event_ts"],
                "broad_delay_min": broad["delay_min"],
                "broad_title": broad["title"],
                "broad_url": broad["url"],
                "v2_event_id": v2["event_id"],
                "v2_event_ts": v2["event_ts"],
                "v2_delay_min": v2["delay_min"],
                "v2_title": v2["title"],
                "v2_url": v2["url"],
                "selected_event_source": selected_source,
                "selected_event_id": selected["event_id"],
                "selected_event_ts": selected["event_ts"],
                "selected_delay_min": selected["delay_min"],
                "selected_match_mode": selected_match_mode,
                "selected_title": selected["title"],
                "selected_url": selected["url"],
                "selected_story_id": selected["story_id"],
                "selected_link_score": selected["commodity_link_score"],
                "selected_link_reason": selected["link_reason"],
                "selected_cause_event": selected["cause_event"],
                "selected_cause_route_key": selected["cause_route_key"],
                "selected_cause_claim_status": selected["cause_claim_status"],
                "selected_cause_classification": selected["cause_classification"],
                "selected_cause_confidence": selected["cause_confidence"],
                "selected_fundamental_score": selected["fundamental_score"],
                "selected_direction_alignment": selected["direction_alignment"],
                "selected_is_primary_cause": int(bool(selected["is_primary_cause"])),
                "root_link_type": root_link_type,
                "root_reuse_reason": root_reuse_reason,
                "root_primary_shock_ts": root_primary_shock_ts,
                "root_episode_event_index": int(root_episode_event_index),
                "root_topic_id": root_topic_id,
                "label_has_any": 0,
                "label_has_gold": 0,
                "label_has_silver": 0,
                "label_gold_direction": "",
                "label_silver_direction": "",
                "gold_direction_match": np.nan,
                "silver_direction_match": np.nan,
            }
        )
    return pd.DataFrame(rows)


def build_live_shock_input(
    *,
    settings: AppSettings,
    news_config: NewsIngestConfig,
    cfg: LiveShockInputConfig,
    end_utc: datetime | None = None,
) -> pd.DataFrame:
    end_ts = end_utc.astimezone(timezone.utc) if end_utc is not None else datetime.now(timezone.utc)
    start_ts = end_ts - timedelta(hours=max(int(cfg.lookback_hours), 1))
    db_path = sqlite_path_from_url(news_config.database_url, data_dir=news_config.data_dir)
    client = MoexIssClient(
        settings.moex.base_url,
        settings.moex.request_timeout_sec,
        max_retries=settings.moex.request_max_retries,
        retry_backoff_sec=settings.moex.request_retry_backoff_sec,
        retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
        fallback_ips=settings.moex.fallback_ips,
        force_fallback=settings.moex.force_fallback,
    )

    frames: list[pd.DataFrame] = []
    for symbol, asset_code in VALID_ASSET_CODE_BY_SYMBOL.items():
        prices = _load_front_contract_prices(
            settings=settings,
            client=client,
            asset_code=asset_code,
            start_utc=start_ts,
            end_utc=end_ts,
            cfg=cfg,
        )
        news_start = start_ts - timedelta(hours=max(int(cfg.lookback_hours), 1))
        news_rows = _load_news_rows(
            db_path=db_path,
            symbol=symbol,
            start_utc=news_start,
            end_utc=end_ts,
            cfg=cfg,
        )
        shocks = _build_shocks_for_symbol(
            symbol=symbol,
            prices=prices,
            news_rows=news_rows,
            start_utc=start_ts,
            end_utc=end_ts,
            cfg=cfg,
        )
        if bool(cfg.enable_candidate_newsapi_enrichment):
            weak = shocks[
                shocks["selected_event_source"].fillna("").astype(str).str.lower().isin({"none", "broad"})
            ] if not shocks.empty else pd.DataFrame()
            candidate_ts = weak["shock_ts"].astype(str).tolist() if not weak.empty else []
            if candidate_ts:
                enrich_report = enrich_newsapi_for_symbol_candidates(
                    db_path=db_path,
                    news_config=news_config,
                    symbol=symbol,
                    candidate_ts_utc=candidate_ts,
                    window_minutes=cfg.enrichment_window_minutes,
                    max_requests_per_symbol=cfg.enrichment_max_requests_per_symbol,
                )
                if int(enrich_report.get("inserted_total") or 0) > 0:
                    news_rows = _load_news_rows(
                        db_path=db_path,
                        symbol=symbol,
                        start_utc=news_start,
                        end_utc=end_ts,
                        cfg=cfg,
                    )
                    shocks = _build_shocks_for_symbol(
                        symbol=symbol,
                        prices=prices,
                        news_rows=news_rows,
                        start_utc=start_ts,
                        end_utc=end_ts,
                        cfg=cfg,
                    )
        if not shocks.empty:
            frames.append(shocks)

    if not frames:
        return pd.DataFrame(columns=list(EMPTY_SHOCK_COLUMNS))
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values(["shock_ts", "symbol"]).reset_index(drop=True)
    merged = apply_silver_labels_from_db(
        df=merged,
        database_url=news_config.database_url,
        data_dir=news_config.data_dir,
    )
    return merged
