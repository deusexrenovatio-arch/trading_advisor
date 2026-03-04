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
from moex_carry.news_silver_store import apply_silver_labels_from_db
from moex_carry.news_storage import open_sqlite_connection, sqlite_path_from_url
from moex_carry.news_topic import build_story_fingerprint, derive_root_topic_key

_SYMBOL_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "NG_US": (
        "natural gas",
        "lng",
        "henry hub",
        "eia storage",
        "pipeline",
        "freeze",
        "hdd",
        "cdd",
        "weather",
    ),
    "BRN": (
        "brent",
        "oil",
        "opec",
        "crude",
        "inventory",
        "stocks",
        "red sea",
        "hormuz",
        "sanctions",
    ),
    "GOLD": (
        "gold",
        "bullion",
        "fed",
        "fomc",
        "yield",
        "dxy",
        "safe haven",
        "inflation",
        "treasury",
    ),
}

_GLOBAL_CONTEXT_KEYWORDS: tuple[str, ...] = (
    "iran",
    "israel",
    "ukraine",
    "russia",
    "china",
    "middle east",
    "attack",
    "strike",
    "conflict",
    "war",
    "sanction",
    "suez",
    "panama canal",
)

_VALID_ASSET_CODE_BY_SYMBOL: dict[str, str] = {
    "BRN": "BR",
    "GOLD": "GOLD",
    "NG_US": "NG",
}


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


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts_utc(value: object) -> datetime | None:
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    if isinstance(ts, pd.Timestamp):
        return ts.to_pydatetime()
    return None


def _parse_date(value: object) -> datetime.date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _topic_relevance(symbol: str, text: str, *, candidate_commodity: str = "") -> float:
    lowered = _normalize_text(text).lower()
    if not lowered:
        return 0.0
    score = 0.0
    for token in _SYMBOL_TOPIC_KEYWORDS.get(symbol, ()):
        if token in lowered:
            score += 1.0
    for token in _GLOBAL_CONTEXT_KEYWORDS:
        if token in lowered:
            score += 0.4
    if _normalize_text(candidate_commodity).upper() == symbol.upper():
        score += 0.35
    return score


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
    if not db_path.exists():
        return pd.DataFrame(
            columns=[
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
                "direction",
                "severity",
            ]
        )
    conn = open_sqlite_connection(db_path, timeout_sec=5.0, write=False)
    try:
        article_cols = {
            str(row[1]).strip().lower()
            for row in conn.execute("PRAGMA table_info(news_articles)").fetchall()
        }
        story_select = "a.story_id AS story_id" if "story_id" in article_cols else "'' AS story_id"
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
                s.direction,
                s.severity
            FROM news_articles a
            JOIN news_scores s ON a.article_id = s.article_id
            WHERE a.published_at_utc >= ?
              AND a.published_at_utc <= ?
              AND s.impact_score >= ?
              AND s.confidence >= ?
            ORDER BY a.published_at_utc DESC
            LIMIT ?
            """,
            (
                _iso_utc(start_utc),
                _iso_utc(end_utc),
                float(cfg.news_min_impact_score),
                max(float(cfg.news_min_confidence), 0.25),
                int(max(cfg.news_max_items_per_symbol, 1) * 4),
            ),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame(
            columns=[
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
                "direction",
                "severity",
            ]
        )
    frame = pd.DataFrame(
        rows,
        columns=[
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
            "direction",
            "severity",
        ],
    )
    frame["published_dt"] = pd.to_datetime(frame["published_at_utc"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["published_dt"])
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
    frame["is_same_commodity"] = (
        frame["commodity"].fillna("").astype(str).str.upper() == symbol.upper()
    )
    frame = frame[
        frame["is_same_commodity"]
        | (pd.to_numeric(frame["relevance"], errors="coerce").fillna(0.0) >= float(cfg.cross_commodity_min_relevance))
    ]
    frame = frame[
        pd.to_numeric(frame["confidence"], errors="coerce").fillna(0.0) >= float(cfg.news_min_confidence)
    ]
    if frame.empty:
        return frame.reset_index(drop=True)
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
    specs = client.get_futures_specs(settings.moex.futures_board)
    rows: list[dict[str, Any]] = []
    for item in specs:
        if str(item.get("ASSETCODE") or "").strip().upper() != asset_code.upper():
            continue
        expiry = _parse_date(item.get("LASTTRADEDATE"))
        secid = str(item.get("SECID") or "").strip().upper()
        if not secid or expiry is None:
            continue
        rows.append({"secid": secid, "expiry": expiry})
    if not rows:
        return pd.DataFrame(columns=["ts", "price", "secid"])

    start_date = (start_utc - timedelta(days=max(int(cfg.history_padding_days), 0))).date()
    end_date = end_utc.date()
    contracts = pd.DataFrame(rows).drop_duplicates(subset=["secid"]).sort_values("expiry")
    eligible = contracts[contracts["expiry"] >= (start_date - timedelta(days=max(int(cfg.history_padding_days), 0)))]
    if eligible.empty:
        eligible = contracts.tail(1)
    eligible = eligible.head(max(int(cfg.front_contract_candidates), 1))

    frames: list[pd.DataFrame] = []
    for _, row in eligible.iterrows():
        secid = str(row["secid"])
        expiry = row["expiry"]
        raw = client.get_candles(
            settings.moex.engine_futures,
            settings.moex.market_futures,
            secid,
            settings.moex.futures_board,
            from_date=start_date,
            till_date=end_date,
            interval=1,
        )
        if not raw:
            continue
        frame = pd.DataFrame(raw)
        if frame.empty:
            continue
        frame["ts"] = pd.to_datetime(frame.get("begin"), utc=True, errors="coerce")
        frame["price"] = pd.to_numeric(frame.get("close"), errors="coerce")
        frame = frame.dropna(subset=["ts", "price"])
        if frame.empty:
            continue
        frame["expiry"] = pd.to_datetime(str(expiry), utc=True).date()
        frame["secid"] = secid
        frame["days_to_expiry"] = (pd.to_datetime(frame["expiry"]).dt.date - frame["ts"].dt.date).apply(lambda val: val.days)
        frame["_expiry_penalty"] = frame["days_to_expiry"].map(lambda d: 0 if d >= 0 else 1)
        frame["_distance"] = frame["days_to_expiry"].abs()
        frames.append(frame[["ts", "price", "secid", "_expiry_penalty", "_distance"]])

    if not frames:
        return pd.DataFrame(columns=["ts", "price", "secid"])

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values(["ts", "_expiry_penalty", "_distance"])
    merged = merged.drop_duplicates(subset=["ts"], keep="first")
    merged = merged[(merged["ts"] >= start_utc - timedelta(days=max(int(cfg.history_padding_days), 0))) & (merged["ts"] <= end_utc)]
    return merged[["ts", "price", "secid"]].sort_values("ts").reset_index(drop=True)


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

    last_root_topic_id = ""
    last_root_ts: pd.Timestamp | None = None
    rows: list[dict[str, Any]] = []
    for ts, row in bars.iterrows():
        direction = "up" if float(row["logret"]) > 0 else "down"
        broad = {
            "event_id": "",
            "event_ts": "",
            "delay_min": np.nan,
            "title": "",
            "url": "",
        }
        v2 = dict(broad)
        selected_source = "none"
        selected = dict(broad)
        selected_match_mode = "none"
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
                broad = {
                    "event_id": _normalize_text(broad_row.get("article_id")),
                    "event_ts": _normalize_text(broad_row.get("published_at_utc")),
                    "delay_min": float(pd.to_numeric(broad_row.get("delay_min"), errors="coerce")),
                    "title": _normalize_text(broad_row.get("title")),
                    "url": _normalize_text(broad_row.get("url")),
                }
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
                    v2 = {
                        "event_id": _normalize_text(v2_row.get("article_id")),
                        "event_ts": _normalize_text(v2_row.get("published_at_utc")),
                        "delay_min": float(pd.to_numeric(v2_row.get("delay_min"), errors="coerce")),
                        "title": _normalize_text(v2_row.get("title")),
                        "url": _normalize_text(v2_row.get("url")),
                    }
                if v2["event_id"]:
                    selected_source = "v2_clean"
                    selected = v2
                    selected_match_mode = "v2_strict"
                elif broad["event_id"]:
                    selected_source = "broad"
                    selected = broad

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
        else:
            reuse_lookback_min = max(float(cfg.root_reuse_lookback_minutes), 0.0)
            can_reuse = (
                bool(last_root_topic_id)
                and last_root_ts is not None
                and ((ts - last_root_ts).total_seconds() / 60.0) <= reuse_lookback_min
            )
            if can_reuse:
                root_topic_id = str(last_root_topic_id)
                selected_match_mode = "root_reuse"
            else:
                root_topic_id = derive_root_topic_key(
                    symbol=symbol,
                    headline=selected["title"],
                    url=selected["url"],
                    selected_event_id=selected["event_id"],
                    selected_source=selected_source,
                    explicit_root_topic_id="",
                )
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
    for symbol, asset_code in _VALID_ASSET_CODE_BY_SYMBOL.items():
        prices = _load_front_contract_prices(
            settings=settings,
            client=client,
            asset_code=asset_code,
            start_utc=start_ts,
            end_utc=end_ts,
            cfg=cfg,
        )
        news_rows = _load_news_rows(
            db_path=db_path,
            symbol=symbol,
            start_utc=start_ts - timedelta(hours=max(int(cfg.lookback_hours), 1)),
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
        return pd.DataFrame(
            columns=[
                "symbol",
                "shock_ts",
                "prev_ts",
                "bar_minutes",
                "prev_price",
                "price",
                "logret",
                "abs_move_pct",
                "shock_direction",
                "rolling_sigma",
                "z_score",
                "broad_event_id",
                "broad_event_ts",
                "broad_delay_min",
                "broad_title",
                "broad_url",
                "v2_event_id",
                "v2_event_ts",
                "v2_delay_min",
                "v2_title",
                "v2_url",
                "selected_event_source",
                "selected_event_id",
                "selected_event_ts",
                "selected_delay_min",
                "selected_match_mode",
                "selected_title",
                "selected_url",
                "root_topic_id",
                "label_has_any",
                "label_has_gold",
                "label_has_silver",
                "label_gold_direction",
                "label_silver_direction",
                "gold_direction_match",
                "silver_direction_match",
            ]
        )
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values(["shock_ts", "symbol"]).reset_index(drop=True)
    merged = apply_silver_labels_from_db(
        df=merged,
        database_url=news_config.database_url,
        data_dir=news_config.data_dir,
    )
    return merged
