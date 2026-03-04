from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from moex_carry.news_storage import open_sqlite_connection, sqlite_path_from_url

_DIRECTION_MAP = {
    "up": "up",
    "positive": "up",
    "bull": "up",
    "bullish": "up",
    "down": "down",
    "negative": "down",
    "bear": "down",
    "bearish": "down",
    "hold": "hold",
    "neutral": "hold",
    "flat": "hold",
    "uncertain": "hold",
    "none": "hold",
}

_SYMBOL_HINT_MAP = {
    "NG_US": "NG_US",
    "NATURAL_GAS": "NG_US",
    "NATGAS": "NG_US",
    "GAS": "NG_US",
    "NG": "NG_US",
    "BRN": "BRN",
    "BRENT": "BRN",
    "OIL": "BRN",
    "CRUDE": "BRN",
    "GOLD": "GOLD",
    "XAU": "GOLD",
    "BULLION": "GOLD",
}

_SILVER_TABLE_NAME = "news_silver_labels"


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_direction(value: object) -> str:
    raw = _normalize_text(value).lower()
    if not raw:
        return "hold"
    return _DIRECTION_MAP.get(raw, "hold")


def _normalize_symbol(value: object) -> str:
    raw = _normalize_text(value).replace("-", "_").replace(" ", "_").upper()
    if not raw:
        return ""
    if raw in _SYMBOL_HINT_MAP:
        return _SYMBOL_HINT_MAP[raw]
    return ""


def _extract_symbol_hints_from_text(value: object) -> str:
    text = _normalize_text(value).replace("-", "_").replace(" ", "_").upper()
    if not text:
        return ""
    for token in ("NG_US", "NATURAL_GAS", "GAS", "NG", "BRN", "BRENT", "OIL", "CRUDE", "GOLD", "XAU"):
        if token in text:
            normalized = _normalize_symbol(token)
            if normalized:
                return normalized
    return ""


def _title_key(value: object) -> str:
    text = _normalize_text(value).lower()
    if not text:
        return ""
    cleaned = "".join(ch if ch.isalnum() else " " for ch in text)
    tokens = [token for token in cleaned.split() if len(token) >= 3][:24]
    if not tokens:
        return ""
    payload = " ".join(tokens)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:18]
    return f"title:{digest}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def _label_key(*, event_id: str, symbol: str, title_key: str) -> str:
    if event_id:
        return f"evt:{event_id.lower()}"
    if symbol and title_key:
        return f"ttl:{symbol}:{title_key}"
    if title_key:
        return f"ttl:any:{title_key}"
    return ""


def _ensure_silver_table(conn: Any) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_SILVER_TABLE_NAME} (
            label_key TEXT PRIMARY KEY,
            event_id TEXT,
            title_key TEXT,
            symbol TEXT,
            direction TEXT NOT NULL,
            confidence REAL NOT NULL,
            is_causal INTEGER NOT NULL,
            relevance REAL,
            magnitude REAL,
            source_tag TEXT NOT NULL,
            source_ref TEXT,
            labeled_at_utc TEXT,
            raw_json TEXT,
            updated_at_utc TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{_SILVER_TABLE_NAME}_event
        ON {_SILVER_TABLE_NAME} (event_id, updated_at_utc DESC)
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{_SILVER_TABLE_NAME}_title
        ON {_SILVER_TABLE_NAME} (title_key, symbol, updated_at_utc DESC)
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{_SILVER_TABLE_NAME}_symbol
        ON {_SILVER_TABLE_NAME} (symbol, updated_at_utc DESC)
        """
    )
    conn.commit()


def _select_best_record(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    work = df.copy()
    work["is_causal"] = pd.to_numeric(work.get("is_causal"), errors="coerce").fillna(0).astype(int)
    work["confidence"] = pd.to_numeric(work.get("confidence"), errors="coerce").fillna(0.0)
    work = work.sort_values(
        ["is_causal", "confidence"],
        ascending=[False, False],
    )
    return work.drop_duplicates(subset=["label_key"], keep="first")


def upsert_silver_records(
    *,
    database_url: str,
    data_dir: str | Path,
    records: pd.DataFrame,
) -> int:
    if records.empty:
        return 0
    db_path = sqlite_path_from_url(database_url, data_dir=data_dir)
    payload = _select_best_record(records)
    payload = payload[payload["label_key"].astype(str).str.strip().ne("")]
    if payload.empty:
        return 0

    conn = open_sqlite_connection(db_path, timeout_sec=15.0, write=True)
    try:
        _ensure_silver_table(conn)
        rows = [
            (
                _normalize_text(row.get("label_key")),
                _normalize_text(row.get("event_id")),
                _normalize_text(row.get("title_key")),
                _normalize_text(row.get("symbol")).upper(),
                _normalize_direction(row.get("direction")),
                float(pd.to_numeric(row.get("confidence"), errors="coerce") or 0.0),
                int(pd.to_numeric(row.get("is_causal"), errors="coerce") or 0),
                pd.to_numeric(row.get("relevance"), errors="coerce"),
                pd.to_numeric(row.get("magnitude"), errors="coerce"),
                _normalize_text(row.get("source_tag")) or "unknown",
                _normalize_text(row.get("source_ref")),
                _normalize_text(row.get("labeled_at_utc")),
                _safe_json(row.get("raw_json")),
                _normalize_text(row.get("updated_at_utc")) or _utc_now_iso(),
            )
            for _, row in payload.iterrows()
        ]
        conn.executemany(
            f"""
            INSERT INTO {_SILVER_TABLE_NAME} (
                label_key,
                event_id,
                title_key,
                symbol,
                direction,
                confidence,
                is_causal,
                relevance,
                magnitude,
                source_tag,
                source_ref,
                labeled_at_utc,
                raw_json,
                updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(label_key) DO UPDATE SET
                event_id = excluded.event_id,
                title_key = excluded.title_key,
                symbol = excluded.symbol,
                direction = excluded.direction,
                confidence = excluded.confidence,
                is_causal = excluded.is_causal,
                relevance = excluded.relevance,
                magnitude = excluded.magnitude,
                source_tag = excluded.source_tag,
                source_ref = excluded.source_ref,
                labeled_at_utc = excluded.labeled_at_utc,
                raw_json = excluded.raw_json,
                updated_at_utc = excluded.updated_at_utc
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return int(len(rows))


def _tasks_by_event_id(tasks_jsonl: Path | None) -> dict[str, dict[str, Any]]:
    if tasks_jsonl is None or not tasks_jsonl.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with tasks_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            event_id = _normalize_text(item.get("event_id") or item.get("input_payload", {}).get("event_id"))
            if not event_id:
                continue
            payload = item.get("input_payload") or {}
            linked = payload.get("linked_news") or []
            linked_title = ""
            if isinstance(linked, list) and linked:
                first = linked[0] if isinstance(linked[0], dict) else {}
                linked_title = _normalize_text(first.get("title"))
            rows[event_id] = {
                "event_id": event_id,
                "title": _normalize_text(payload.get("canonical_summary")) or linked_title,
                "published_at_utc": _normalize_text(item.get("published_at") or payload.get("published_at")),
                "symbol_hint": _extract_symbol_hints_from_text(payload.get("canonical_mechanism")),
            }
    return rows


def ingest_event_labels_jsonl_to_db(
    *,
    labels_jsonl: Path,
    database_url: str,
    data_dir: str | Path,
    tasks_jsonl: Path | None = None,
    source_tag: str = "chatpro_event",
    min_confidence: float = 0.60,
    min_relevance: float = 0.50,
) -> dict[str, Any]:
    if not labels_jsonl.exists():
        raise FileNotFoundError(f"Labels JSONL not found: {labels_jsonl}")
    task_map = _tasks_by_event_id(tasks_jsonl)
    rows: list[dict[str, Any]] = []

    with labels_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            event_id = _normalize_text(item.get("event_id") or item.get("id"))
            label = item.get("label") if isinstance(item.get("label"), dict) else item
            direction = _normalize_direction(label.get("direction"))
            confidence = float(pd.to_numeric(label.get("confidence"), errors="coerce") or 0.0)
            relevance = float(pd.to_numeric(label.get("relevance"), errors="coerce") or 0.0)
            magnitude = float(pd.to_numeric(label.get("magnitude"), errors="coerce") or 0.0)

            symbol = ""
            commodities = label.get("commodity")
            if isinstance(commodities, list):
                for token in commodities:
                    symbol = _normalize_symbol(token)
                    if symbol:
                        break
            if not symbol and event_id in task_map:
                symbol = _normalize_symbol(task_map[event_id].get("symbol_hint"))

            title = ""
            published_at = ""
            if event_id in task_map:
                title = _normalize_text(task_map[event_id].get("title"))
                published_at = _normalize_text(task_map[event_id].get("published_at_utc"))
            if not title:
                spans = label.get("evidence_spans")
                if isinstance(spans, list) and spans:
                    first = spans[0] if isinstance(spans[0], dict) else {}
                    title = _normalize_text(first.get("text"))
            title_key = _title_key(title)
            is_causal = int(
                direction in {"up", "down"}
                and confidence >= float(min_confidence)
                and relevance >= float(min_relevance)
            )

            now = _utc_now_iso()
            base = {
                "event_id": event_id,
                "title_key": title_key,
                "symbol": symbol,
                "direction": direction,
                "confidence": confidence,
                "is_causal": is_causal,
                "relevance": relevance,
                "magnitude": magnitude,
                "source_tag": _normalize_text(source_tag) or "chatpro_event",
                "source_ref": str(labels_jsonl),
                "labeled_at_utc": published_at or now,
                "raw_json": item,
                "updated_at_utc": now,
            }
            key_evt = _label_key(event_id=event_id, symbol=symbol, title_key=title_key)
            if key_evt:
                row_evt = dict(base)
                row_evt["label_key"] = key_evt
                rows.append(row_evt)
            if title_key:
                key_title = _label_key(event_id="", symbol=symbol, title_key=title_key)
                row_title = dict(base)
                row_title["label_key"] = key_title
                rows.append(row_title)

    frame = pd.DataFrame(rows)
    stored = upsert_silver_records(
        database_url=database_url,
        data_dir=data_dir,
        records=frame,
    )
    return {
        "labels_jsonl": str(labels_jsonl),
        "records_parsed": int(len(rows)),
        "records_stored": int(stored),
        "unique_event_ids": int(frame["event_id"].astype(str).str.strip().ne("").sum()) if not frame.empty else 0,
        "high_conf_causal": int(
            (
                (pd.to_numeric(frame.get("is_causal"), errors="coerce").fillna(0) == 1)
                & (pd.to_numeric(frame.get("confidence"), errors="coerce").fillna(0.0) >= float(min_confidence))
            ).sum()
        )
        if not frame.empty
        else 0,
    }


def persist_task_merged_labels_to_db(
    *,
    merged: pd.DataFrame,
    database_url: str,
    data_dir: str | Path,
    source_tag: str = "chatpro_task",
    source_ref: str = "",
) -> int:
    if merged.empty:
        return 0
    work = merged.copy()
    work["event_id"] = work.get("primary_event_id", pd.Series("", index=work.index)).fillna("").astype(str).str.strip()
    work["title_key"] = work.get("primary_title", pd.Series("", index=work.index)).map(_title_key)
    work["symbol"] = work.get("symbol", pd.Series("", index=work.index)).map(_normalize_symbol)
    work["direction"] = work.get("label_direction", pd.Series("hold", index=work.index)).map(_normalize_direction)
    work["confidence"] = pd.to_numeric(work.get("label_confidence"), errors="coerce").fillna(0.0)
    work["is_causal"] = pd.to_numeric(work.get("label_is_causal"), errors="coerce").fillna(0).astype(int)
    work = work[
        (work["event_id"].astype(str).str.strip().ne(""))
        | (work["title_key"].astype(str).str.strip().ne(""))
    ].copy()
    if work.empty:
        return 0

    now = _utc_now_iso()
    work["label_key"] = work.apply(
        lambda row: _label_key(
            event_id=_normalize_text(row.get("event_id")),
            symbol=_normalize_text(row.get("symbol")).upper(),
            title_key=_normalize_text(row.get("title_key")),
        ),
        axis=1,
    )
    work["source_tag"] = _normalize_text(source_tag) or "chatpro_task"
    work["source_ref"] = _normalize_text(source_ref)
    work["labeled_at_utc"] = work.get("shock_ts_utc", pd.Series(now, index=work.index)).fillna(now).astype(str)
    work["updated_at_utc"] = now
    work["raw_json"] = work.apply(lambda row: _safe_json({"task_id": row.get("task_id")}), axis=1)
    records = work[
        [
            "label_key",
            "event_id",
            "title_key",
            "symbol",
            "direction",
            "confidence",
            "is_causal",
            "source_tag",
            "source_ref",
            "labeled_at_utc",
            "updated_at_utc",
            "raw_json",
        ]
    ].copy()
    records["relevance"] = pd.NA
    records["magnitude"] = pd.NA
    return upsert_silver_records(
        database_url=database_url,
        data_dir=data_dir,
        records=records,
    )


def apply_silver_labels_from_db(
    *,
    df: pd.DataFrame,
    database_url: str,
    data_dir: str | Path,
) -> pd.DataFrame:
    if df.empty:
        return df

    work = df.copy()
    for column, default in (
        ("label_has_any", 0),
        ("label_has_silver", 0),
        ("label_silver_direction", ""),
        ("silver_direction_match", pd.NA),
    ):
        if column not in work.columns:
            work[column] = default

    event_ids = (
        work.get("selected_event_id", pd.Series("", index=work.index))
        .fillna("")
        .astype(str)
        .str.strip()
    )
    title_text = (
        work.get("selected_title", pd.Series("", index=work.index))
        .fillna("")
        .astype(str)
        .str.strip()
    )
    symbols = work.get("symbol", pd.Series("", index=work.index)).fillna("").astype(str).str.upper()
    title_keys = title_text.map(_title_key)

    unique_events = sorted(item.lower() for item in event_ids.unique().tolist() if item)
    unique_title_keys = sorted(item for item in title_keys.unique().tolist() if item)
    if not unique_events and not unique_title_keys:
        return work

    db_path = sqlite_path_from_url(database_url, data_dir=data_dir)
    if not db_path.exists():
        return work
    conn = open_sqlite_connection(db_path, timeout_sec=10.0, write=False)
    try:
        _ensure_silver_table(conn)
        clauses: list[str] = []
        params: list[Any] = []
        if unique_events:
            placeholders = ",".join("?" for _ in unique_events)
            clauses.append(f"LOWER(event_id) IN ({placeholders})")
            params.extend(unique_events)
        if unique_title_keys:
            placeholders = ",".join("?" for _ in unique_title_keys)
            clauses.append(f"title_key IN ({placeholders})")
            params.extend(unique_title_keys)
        if not clauses:
            return work
        sql = f"""
            SELECT
                label_key,
                event_id,
                title_key,
                symbol,
                direction,
                confidence,
                is_causal,
                updated_at_utc
            FROM {_SILVER_TABLE_NAME}
            WHERE {' OR '.join(clauses)}
        """
        labels = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
    if labels.empty:
        return work

    labels["direction"] = labels["direction"].map(_normalize_direction)
    labels["confidence"] = pd.to_numeric(labels["confidence"], errors="coerce").fillna(0.0)
    labels["is_causal"] = pd.to_numeric(labels["is_causal"], errors="coerce").fillna(0).astype(int)
    labels["event_id_norm"] = labels["event_id"].fillna("").astype(str).str.strip().str.lower()
    labels["title_key_norm"] = labels["title_key"].fillna("").astype(str).str.strip()
    labels["symbol_norm"] = labels["symbol"].fillna("").astype(str).str.strip().str.upper()

    labels = labels.sort_values(
        ["is_causal", "confidence", "updated_at_utc"],
        ascending=[False, False, False],
    )
    event_best = labels[labels["event_id_norm"].ne("")].drop_duplicates(subset=["event_id_norm"], keep="first")
    title_best = labels[labels["title_key_norm"].ne("")].drop_duplicates(
        subset=["title_key_norm", "symbol_norm"],
        keep="first",
    )
    title_any_best = labels[
        (labels["title_key_norm"].ne(""))
        & (labels["symbol_norm"].eq(""))
    ].drop_duplicates(subset=["title_key_norm"], keep="first")

    event_map = {
        str(row["event_id_norm"]): row
        for _, row in event_best.iterrows()
    }
    title_map = {
        (str(row["title_key_norm"]), str(row["symbol_norm"])): row
        for _, row in title_best.iterrows()
    }
    title_any_map = {
        str(row["title_key_norm"]): row
        for _, row in title_any_best.iterrows()
    }

    for idx in work.index:
        event_id = str(event_ids.loc[idx] or "").strip().lower()
        symbol = str(symbols.loc[idx] or "").strip().upper()
        t_key = str(title_keys.loc[idx] or "").strip()
        matched = None
        if event_id:
            matched = event_map.get(event_id)
        if matched is None and t_key:
            matched = title_map.get((t_key, symbol))
        if matched is None and t_key:
            matched = title_any_map.get(t_key)
        if matched is None:
            continue

        direction = _normalize_direction(matched.get("direction"))
        is_causal = int(pd.to_numeric(matched.get("is_causal"), errors="coerce") or 0)
        work.at[idx, "label_has_any"] = 1
        work.at[idx, "label_has_silver"] = 1 if is_causal == 1 else 0
        work.at[idx, "label_silver_direction"] = direction
        shock_direction = _normalize_direction(work.at[idx, "shock_direction"])
        if direction in {"up", "down"} and shock_direction in {"up", "down"}:
            work.at[idx, "silver_direction_match"] = 1 if direction == shock_direction else 0
        else:
            work.at[idx, "silver_direction_match"] = pd.NA

    return work


def upsert_silver_from_shock_rows(
    *,
    shocks_df: pd.DataFrame,
    database_url: str,
    data_dir: str | Path,
    source_tag: str = "shock_backfill_auto",
    min_abs_z: float = 2.5,
    max_delay_min: float = 120.0,
    min_samples_per_event: int = 2,
    min_direction_confidence: float = 0.60,
) -> dict[str, Any]:
    if shocks_df.empty:
        return {
            "source_tag": source_tag,
            "rows_input": 0,
            "rows_candidate": 0,
            "events_derived": 0,
            "records_stored": 0,
        }

    work = shocks_df.copy()
    work["symbol"] = work.get("symbol", pd.Series("", index=work.index)).map(_normalize_symbol)
    work["event_id"] = (
        work.get("selected_event_id", pd.Series("", index=work.index))
        .fillna("")
        .astype(str)
        .str.strip()
    )
    work["shock_direction_norm"] = (
        work.get("shock_direction", pd.Series("", index=work.index))
        .map(_normalize_direction)
    )
    work["z_abs"] = pd.to_numeric(work.get("z_score"), errors="coerce").abs().fillna(0.0)
    work["abs_move_pct"] = pd.to_numeric(work.get("abs_move_pct"), errors="coerce").fillna(0.0)
    work["selected_delay_min"] = pd.to_numeric(work.get("selected_delay_min"), errors="coerce")
    work["selected_title"] = (
        work.get("selected_title", pd.Series("", index=work.index))
        .fillna("")
        .astype(str)
        .str.strip()
    )
    work = work[
        work["event_id"].ne("")
        & work["symbol"].ne("")
        & work["shock_direction_norm"].isin({"up", "down"})
        & work["z_abs"].ge(float(min_abs_z))
    ].copy()
    if max_delay_min >= 0:
        work = work[
            work["selected_delay_min"].isna()
            | ((work["selected_delay_min"] >= 0.0) & (work["selected_delay_min"] <= float(max_delay_min)))
        ]
    if work.empty:
        return {
            "source_tag": source_tag,
            "rows_input": int(len(shocks_df)),
            "rows_candidate": 0,
            "events_derived": 0,
            "records_stored": 0,
        }

    work["up_w"] = work.apply(
        lambda row: float(row["z_abs"]) * (1.0 + float(abs(row["abs_move_pct"])) / 100.0)
        if str(row["shock_direction_norm"]) == "up"
        else 0.0,
        axis=1,
    )
    work["down_w"] = work.apply(
        lambda row: float(row["z_abs"]) * (1.0 + float(abs(row["abs_move_pct"])) / 100.0)
        if str(row["shock_direction_norm"]) == "down"
        else 0.0,
        axis=1,
    )
    agg = (
        work.groupby(["symbol", "event_id"], as_index=False)
        .agg(
            sample_count=("event_id", "size"),
            up_weight=("up_w", "sum"),
            down_weight=("down_w", "sum"),
            avg_abs_z=("z_abs", "mean"),
            latest_title=("selected_title", "last"),
        )
    )
    if agg.empty:
        return {
            "source_tag": source_tag,
            "rows_input": int(len(shocks_df)),
            "rows_candidate": int(len(work)),
            "events_derived": 0,
            "records_stored": 0,
        }

    agg["total_weight"] = agg["up_weight"] + agg["down_weight"]
    agg["direction"] = agg.apply(
        lambda row: "up"
        if float(row["up_weight"]) > float(row["down_weight"])
        else ("down" if float(row["down_weight"]) > float(row["up_weight"]) else "hold"),
        axis=1,
    )
    agg["confidence"] = agg.apply(
        lambda row: (max(float(row["up_weight"]), float(row["down_weight"])) / float(row["total_weight"]))
        if float(row["total_weight"]) > 0.0
        else 0.0,
        axis=1,
    )
    agg["is_causal"] = (
        (agg["sample_count"] >= int(max(min_samples_per_event, 1)))
        & (agg["direction"].isin(["up", "down"]))
        & (agg["confidence"] >= float(min_direction_confidence))
    ).astype(int)
    agg["title_key"] = agg["latest_title"].map(_title_key)

    now = _utc_now_iso()
    records: list[dict[str, Any]] = []
    for _, row in agg.iterrows():
        event_id = _normalize_text(row.get("event_id"))
        symbol = _normalize_text(row.get("symbol")).upper()
        title_key = _normalize_text(row.get("title_key"))
        base = {
            "event_id": event_id,
            "title_key": title_key,
            "symbol": symbol,
            "direction": _normalize_direction(row.get("direction")),
            "confidence": float(pd.to_numeric(row.get("confidence"), errors="coerce") or 0.0),
            "is_causal": int(pd.to_numeric(row.get("is_causal"), errors="coerce") or 0),
            "relevance": pd.NA,
            "magnitude": float(pd.to_numeric(row.get("avg_abs_z"), errors="coerce") or 0.0),
            "source_tag": _normalize_text(source_tag) or "shock_backfill_auto",
            "source_ref": "derived_from_shocks",
            "labeled_at_utc": now,
            "raw_json": {
                "sample_count": int(pd.to_numeric(row.get("sample_count"), errors="coerce") or 0),
                "up_weight": float(pd.to_numeric(row.get("up_weight"), errors="coerce") or 0.0),
                "down_weight": float(pd.to_numeric(row.get("down_weight"), errors="coerce") or 0.0),
            },
            "updated_at_utc": now,
        }
        key_evt = _label_key(event_id=event_id, symbol=symbol, title_key=title_key)
        if key_evt:
            evt_record = dict(base)
            evt_record["label_key"] = key_evt
            records.append(evt_record)
        if title_key:
            ttl_record = dict(base)
            ttl_record["label_key"] = _label_key(event_id="", symbol=symbol, title_key=title_key)
            records.append(ttl_record)

    stored = upsert_silver_records(
        database_url=database_url,
        data_dir=data_dir,
        records=pd.DataFrame(records),
    )
    return {
        "source_tag": source_tag,
        "rows_input": int(len(shocks_df)),
        "rows_candidate": int(len(work)),
        "events_derived": int(len(agg)),
        "records_stored": int(stored),
        "causal_events": int((agg["is_causal"] == 1).sum()),
    }
