from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd

from moex_carry.news_storage import write_csv_atomic
from moex_carry.news_topic import build_story_fingerprint


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _score_expr(columns: set[str], name: str, *, default_sql: str) -> str:
    if name in columns:
        return f"s.{name} AS {name}"
    return f"{default_sql} AS {name}"


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]).strip().lower() for row in rows}


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name) = lower(?)",
        (table_name,),
    ).fetchone()
    return row is not None


def _load_shock_rows_for_articles(conn: sqlite3.Connection, article_ids: Iterable[str]) -> pd.DataFrame:
    shock_columns = _table_columns(conn, "news_shock_rows")
    metric_columns = {"shock_ts", "shock_direction", "abs_move_pct", "z_score"}
    id_columns = [name for name in ("selected_event_id", "v2_event_id", "broad_event_id") if name in shock_columns]
    if not metric_columns.issubset(shock_columns) or not id_columns:
        return pd.DataFrame()

    normalized_ids = sorted({str(item or "").strip() for item in article_ids if str(item or "").strip()})
    if not normalized_ids:
        return pd.DataFrame()

    parts: list[pd.DataFrame] = []
    chunk_size = 800
    for offset in range(0, len(normalized_ids), chunk_size):
        chunk = normalized_ids[offset : offset + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        where_expr = " OR ".join(f"{name} IN ({placeholders})" for name in id_columns)
        query_columns = ", ".join([*id_columns, "shock_ts", "shock_direction", "abs_move_pct", "z_score"])
        params = tuple(chunk) * len(id_columns)
        rows = conn.execute(
            f"SELECT {query_columns} FROM news_shock_rows WHERE {where_expr}",
            params,
        ).fetchall()
        if rows:
            raw = pd.DataFrame(rows, columns=[*id_columns, "shock_ts", "shock_direction", "abs_move_pct", "z_score"])
            for name in id_columns:
                part = raw[[name, "shock_ts", "shock_direction", "abs_move_pct", "z_score"]].rename(
                    columns={name: "article_id"}
                )
                parts.append(part)
    if not parts:
        return pd.DataFrame()

    frame = pd.concat(parts, ignore_index=True)
    frame["article_id"] = frame["article_id"].astype(str).str.strip()
    frame = frame[frame["article_id"].ne("")]
    if frame.empty:
        return frame
    frame = frame.drop_duplicates(
        subset=["article_id", "shock_ts", "shock_direction", "abs_move_pct", "z_score"],
        keep="first",
    )
    frame["shock_dt"] = pd.to_datetime(frame["shock_ts"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["shock_dt"])
    frame["shock_direction"] = frame["shock_direction"].astype(str).str.strip().str.lower()
    frame["abs_move_pct"] = pd.to_numeric(frame["abs_move_pct"], errors="coerce").fillna(0.0)
    frame["z_score"] = pd.to_numeric(frame["z_score"], errors="coerce").fillna(0.0)
    return frame.sort_values(["article_id", "shock_dt"]).reset_index(drop=True)


def _attach_shock_verification(conn: sqlite3.Connection, df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    for col, default in (
        ("verified_move_1h", False),
        ("verified_move_1d", False),
        ("max_abs_move_pct_1h", 0.0),
        ("max_abs_move_pct_1d", 0.0),
        ("max_abs_z_1h", 0.0),
        ("max_abs_z_1d", 0.0),
        ("verification_score", 0.0),
    ):
        if col not in df.columns:
            df[col] = default

    if "news_shock_rows" not in {
        str(row[0]).strip().lower()
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }:
        return df

    shocks = _load_shock_rows_for_articles(conn, df["article_id"].astype(str).tolist())
    if shocks.empty:
        return df

    grouped = {key: part.copy() for key, part in shocks.groupby("article_id", sort=False)}
    published = pd.to_datetime(df["published_at_utc"], utc=True, errors="coerce")
    dir_series = df["direction"].astype(str).str.strip().str.lower()

    verified_1h: list[bool] = []
    verified_1d: list[bool] = []
    move_1h: list[float] = []
    move_1d: list[float] = []
    z_1h: list[float] = []
    z_1d: list[float] = []
    verification_score: list[float] = []

    for article_id, published_dt, direction in zip(
        df["article_id"].astype(str),
        published,
        dir_series,
        strict=False,
    ):
        if pd.isna(published_dt):
            verified_1h.append(False)
            verified_1d.append(False)
            move_1h.append(0.0)
            move_1d.append(0.0)
            z_1h.append(0.0)
            z_1d.append(0.0)
            verification_score.append(0.0)
            continue

        part = grouped.get(article_id)
        if part is None or part.empty:
            verified_1h.append(False)
            verified_1d.append(False)
            move_1h.append(0.0)
            move_1d.append(0.0)
            z_1h.append(0.0)
            z_1d.append(0.0)
            verification_score.append(0.0)
            continue

        horizon_1h = published_dt + pd.Timedelta(hours=1)
        horizon_1d = published_dt + pd.Timedelta(days=1)

        after_pub = part[part["shock_dt"] >= published_dt]
        if direction in {"up", "down"}:
            after_pub = after_pub[after_pub["shock_direction"] == direction]

        within_1h = after_pub[after_pub["shock_dt"] <= horizon_1h]
        within_1d = after_pub[after_pub["shock_dt"] <= horizon_1d]

        ok_1h = not within_1h.empty
        ok_1d = not within_1d.empty
        max_move_1h = float(within_1h["abs_move_pct"].max()) if ok_1h else 0.0
        max_move_1d = float(within_1d["abs_move_pct"].max()) if ok_1d else 0.0
        max_z_1h = float(within_1h["z_score"].abs().max()) if ok_1h else 0.0
        max_z_1d = float(within_1d["z_score"].abs().max()) if ok_1d else 0.0

        score = 0.0
        if ok_1h:
            score += 0.45
        if ok_1d:
            score += 0.55
        score += min(max_z_1d / 6.0, 0.25)
        score = min(score, 1.0)

        verified_1h.append(ok_1h)
        verified_1d.append(ok_1d)
        move_1h.append(max_move_1h)
        move_1d.append(max_move_1d)
        z_1h.append(max_z_1h)
        z_1d.append(max_z_1d)
        verification_score.append(score)

    df["verified_move_1h"] = verified_1h
    df["verified_move_1d"] = verified_1d
    df["max_abs_move_pct_1h"] = move_1h
    df["max_abs_move_pct_1d"] = move_1d
    df["max_abs_z_1h"] = z_1h
    df["max_abs_z_1d"] = z_1d
    df["verification_score"] = verification_score
    return df


def build_live_news_feed_frame(
    conn: sqlite3.Connection,
    *,
    feed_role: str = "discovery",
    min_impact_score: float,
    min_confidence: float,
    min_fundamental_score: float = 0.45,
    min_link_score: float = 0.6,
    max_rows: int,
    require_primary_cause: bool = True,
    require_verified_move: bool = False,
    require_verified_both_horizons: bool = True,
) -> pd.DataFrame:
    columns = [
        "feed_role",
        "article_id",
        "story_id",
        "published_at_utc",
        "commodity",
        "commodity_link_score",
        "commodity_scope",
        "story_scope_json",
        "is_multi_commodity",
        "link_reason",
        "link_evidence_json",
        "direction",
        "severity",
        "impact_score",
        "confidence",
        "source_name",
        "provider",
        "title",
        "url",
        "story_key",
        "reason_terms_up",
        "reason_terms_down",
        "cause_classification",
        "cause_bucket",
        "cause_event",
        "transmission_channel",
        "cause_cluster_key",
        "cause_route_key",
        "cause_claim_status",
        "cause_entities_json",
        "cause_confidence",
        "fundamental_score",
        "direction_alignment",
        "is_primary_cause",
        "cause_terms_json",
        "effect_terms_json",
        "verified_move_1h",
        "verified_move_1d",
        "max_abs_move_pct_1h",
        "max_abs_move_pct_1d",
        "max_abs_z_1h",
        "max_abs_z_1d",
        "verification_score",
        "cluster_key",
    ]
    has_link_table = _table_exists(conn, "news_article_commodity_links")
    score_columns = _table_columns(conn, "news_scores")
    cause_exprs = [
        _score_expr(score_columns, "cause_classification", default_sql="'unknown'"),
        _score_expr(score_columns, "cause_bucket", default_sql="''"),
        _score_expr(score_columns, "cause_event", default_sql="''"),
        _score_expr(score_columns, "transmission_channel", default_sql="''"),
        _score_expr(score_columns, "cause_cluster_key", default_sql="''"),
        _score_expr(score_columns, "cause_route_key", default_sql="''"),
        _score_expr(score_columns, "cause_claim_status", default_sql="'unknown'"),
        _score_expr(score_columns, "cause_entities_json", default_sql="'[]'"),
        _score_expr(score_columns, "cause_confidence", default_sql="0.0"),
        _score_expr(score_columns, "fundamental_score", default_sql="0.0"),
        _score_expr(score_columns, "direction_alignment", default_sql="0.5"),
        _score_expr(score_columns, "is_primary_cause", default_sql="0"),
        _score_expr(score_columns, "cause_terms_json", default_sql="'[]'"),
        _score_expr(score_columns, "effect_terms_json", default_sql="'[]'"),
    ]
    if has_link_table:
        link_select = """
            COALESCE(l.commodity, a.commodity) AS commodity,
            COALESCE(l.link_score, 0.65) AS commodity_link_score,
            COALESCE(l.link_reason, 'legacy_article_commodity') AS link_reason,
            COALESCE(l.link_evidence_json, '[]') AS link_evidence_json,
            COALESCE(l.is_primary_link, 0) AS is_primary_link
        """
        from_clause = """
            FROM news_articles a
            JOIN news_scores s ON a.article_id = s.article_id
            LEFT JOIN news_article_commodity_links l ON a.article_id = l.article_id
        """
    else:
        link_select = """
            a.commodity AS commodity,
            0.65 AS commodity_link_score,
            'legacy_article_commodity' AS link_reason,
            '[]' AS link_evidence_json,
            1 AS is_primary_link
        """
        from_clause = """
            FROM news_articles a
            JOIN news_scores s ON a.article_id = s.article_id
        """
    rows = conn.execute(
        f"""
        SELECT
            a.article_id,
            a.story_id,
            a.published_at_utc,
            {link_select},
            s.direction,
            s.severity,
            s.impact_score,
            s.confidence,
            a.source_name,
            a.provider,
            a.title,
            a.url,
            '' AS story_key,
            s.reason_terms_up,
            s.reason_terms_down,
            {", ".join(cause_exprs)}
        {from_clause}
        WHERE s.impact_score >= ?
          AND s.confidence >= ?
        ORDER BY a.published_at_utc DESC
        LIMIT ?
        """,
        (float(min_impact_score), float(min_confidence), int(max_rows) * 5),
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=columns)

    row_columns = [
        "article_id",
        "story_id",
        "published_at_utc",
        "commodity",
        "commodity_link_score",
        "link_reason",
        "link_evidence_json",
        "is_primary_link",
        "direction",
        "severity",
        "impact_score",
        "confidence",
        "source_name",
        "provider",
        "title",
        "url",
        "story_key",
        "reason_terms_up",
        "reason_terms_down",
        "cause_classification",
        "cause_bucket",
        "cause_event",
        "transmission_channel",
        "cause_cluster_key",
        "cause_route_key",
        "cause_claim_status",
        "cause_entities_json",
        "cause_confidence",
        "fundamental_score",
        "direction_alignment",
        "is_primary_cause",
        "cause_terms_json",
        "effect_terms_json",
    ]
    df = pd.DataFrame(rows, columns=row_columns)
    for default_col, default_value in (
        ("verified_move_1h", False),
        ("verified_move_1d", False),
        ("max_abs_move_pct_1h", 0.0),
        ("max_abs_move_pct_1d", 0.0),
        ("max_abs_z_1h", 0.0),
        ("max_abs_z_1d", 0.0),
        ("verification_score", 0.0),
        ("cluster_key", ""),
        ("story_scope_json", "{}"),
        ("commodity_scope", ""),
        ("is_multi_commodity", False),
    ):
        if default_col not in df.columns:
            df[default_col] = default_value

    df["story_key"] = (
        df["story_id"].fillna("").astype(str).str.strip().where(
            df["story_id"].fillna("").astype(str).str.strip().ne(""),
            df.apply(
                lambda row: build_story_fingerprint(
                    title=row.get("title"),
                    url=row.get("url"),
                    published_at_utc=row.get("published_at_utc"),
                    provider=row.get("provider"),
                ),
                axis=1,
            ),
        )
    )
    df = _attach_shock_verification(conn, df)

    df["cause_classification"] = df["cause_classification"].fillna("").astype(str).str.strip().str.lower()
    df["cause_claim_status"] = df["cause_claim_status"].fillna("").astype(str).str.strip().str.lower()
    df["cause_confidence"] = pd.to_numeric(df["cause_confidence"], errors="coerce").fillna(0.0)
    df["fundamental_score"] = pd.to_numeric(df["fundamental_score"], errors="coerce").fillna(0.0)
    df["direction_alignment"] = pd.to_numeric(df["direction_alignment"], errors="coerce").fillna(0.5)
    df["is_primary_cause"] = df["is_primary_cause"].apply(_to_bool)
    df["commodity"] = df["commodity"].fillna("").astype(str).str.strip().str.upper()
    df["commodity_link_score"] = pd.to_numeric(df["commodity_link_score"], errors="coerce").fillna(0.0)
    df["is_primary_link"] = df["is_primary_link"].apply(_to_bool)
    df = df[df["commodity"].ne("")]
    df = df[df["commodity_link_score"] >= float(min_link_score)]
    if df.empty:
        return pd.DataFrame(columns=columns)
    df["cluster_key"] = (
        df["cause_cluster_key"]
        .fillna("")
        .astype(str)
        .str.strip()
        .where(df["cause_cluster_key"].fillna("").astype(str).str.strip().ne(""), df["story_key"])
    )
    story_scope_json: dict[str, str] = {}
    commodity_scope: dict[str, str] = {}
    is_multi_commodity: dict[str, bool] = {}
    for story_key, part in df.groupby("story_key", sort=False):
        scope: dict[str, dict[str, object]] = {}
        ordered = part.sort_values(
            ["commodity_link_score", "impact_score", "confidence"],
            ascending=[False, False, False],
        )
        for _, row in ordered.iterrows():
            commodity = str(row.get("commodity") or "").strip().upper()
            if not commodity or commodity in scope:
                continue
            link_score_value = float(pd.to_numeric(row.get("commodity_link_score"), errors="coerce"))
            if pd.isna(link_score_value):
                link_score_value = 0.0
            scope[commodity] = {
                "commodity_link_score": round(link_score_value, 4),
                "link_reason": str(row.get("link_reason") or ""),
                "is_primary": bool(_to_bool(row.get("is_primary_link"))),
            }
            evidence_raw = str(row.get("link_evidence_json") or "").strip()
            if evidence_raw and evidence_raw not in {"[]", "{}"}:
                scope[commodity]["link_evidence_json"] = evidence_raw
        story_scope_json[story_key] = json.dumps(scope, ensure_ascii=False, sort_keys=True)
        commodity_scope[story_key] = ",".join(scope.keys())
        is_multi_commodity[story_key] = len(scope) > 1

    ranked = df.assign(
        _score=(pd.to_numeric(df["impact_score"], errors="coerce").fillna(0.0) * 2.0)
        + pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)
        + df["cause_confidence"] * 0.9
        + df["fundamental_score"] * 1.4
        + pd.to_numeric(df["verification_score"], errors="coerce").fillna(0.0) * 1.2
        + df["direction_alignment"] * 0.15
        + df["commodity_link_score"] * 1.5
    )
    ranked["_score"] += ranked["cause_classification"].map(
        {"cause": 0.35, "mixed": 0.15, "effect": -0.45, "unknown": -0.2}
    ).fillna(0.0)
    ranked["_score"] += ranked["is_primary_cause"].map({True: 0.25, False: -0.08}).fillna(0.0)
    ranked["_score"] += ranked["is_primary_link"].map({True: 0.08, False: 0.0}).fillna(0.0)

    if bool(require_primary_cause):
        ranked = ranked[
            ranked["is_primary_cause"]
            | (
                ranked["cause_classification"].isin({"cause", "mixed"})
                & (ranked["fundamental_score"] >= float(min_fundamental_score))
            )
        ]
    if bool(require_verified_move):
        if bool(require_verified_both_horizons):
            ranked = ranked[ranked["verified_move_1h"] & ranked["verified_move_1d"]]
        else:
            ranked = ranked[ranked["verified_move_1h"] | ranked["verified_move_1d"]]
    if ranked.empty:
        return pd.DataFrame(columns=columns)

    ranked = ranked.sort_values(["_score", "published_at_utc"], ascending=[False, False])
    ranked = ranked.drop_duplicates(subset=["story_key", "commodity"], keep="first")
    ranked["feed_role"] = str(feed_role or "discovery").strip().lower() or "discovery"
    ranked["commodity_scope"] = ranked["story_key"].map(commodity_scope).fillna(ranked["commodity"])
    ranked["story_scope_json"] = ranked["story_key"].map(story_scope_json).fillna("{}")
    ranked["is_multi_commodity"] = ranked["story_key"].map(is_multi_commodity).fillna(False)
    ranked = ranked.sort_values("published_at_utc", ascending=False)
    if max_rows > 0:
        ranked = ranked.head(int(max_rows))
    return ranked.drop(columns=["_score"]).reset_index(drop=True)[columns]


def export_live_news_feed(
    conn: sqlite3.Connection,
    *,
    feed_path: Path,
    feed_role: str = "discovery",
    min_impact_score: float,
    min_confidence: float,
    min_fundamental_score: float = 0.45,
    min_link_score: float = 0.6,
    max_rows: int,
    require_primary_cause: bool = True,
    require_verified_move: bool = False,
    require_verified_both_horizons: bool = True,
) -> int:
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    df = build_live_news_feed_frame(
        conn,
        feed_role=feed_role,
        min_impact_score=min_impact_score,
        min_confidence=min_confidence,
        min_fundamental_score=min_fundamental_score,
        min_link_score=min_link_score,
        max_rows=max_rows,
        require_primary_cause=require_primary_cause,
        require_verified_move=require_verified_move,
        require_verified_both_horizons=require_verified_both_horizons,
    )
    write_csv_atomic(df, feed_path)
    return int(len(df))
