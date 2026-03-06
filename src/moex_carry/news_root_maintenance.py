from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from moex_carry.news_shock_store import read_live_shock_rows
from moex_carry.news_storage import open_sqlite_connection, sqlite_path_from_url

_LINK_TABLE = "news_root_links"
_REGISTRY_TABLE = "news_root_registry"
_EDGE_TABLE = "news_root_route_edges"


@dataclass(frozen=True)
class RootMaintenanceConfig:
    bar_minutes: int = 5
    max_rows: int = 0
    start_ts: str | None = None
    end_ts: str | None = None


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _safe_float(value: object) -> float:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return 0.0
    return float(num)


def _safe_int(value: object) -> int:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return 0
    return int(num)


def _init_tables(conn: Any) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_LINK_TABLE} (
            symbol TEXT NOT NULL,
            shock_ts TEXT NOT NULL,
            bar_minutes INTEGER NOT NULL,
            root_topic_id TEXT NOT NULL,
            root_link_type TEXT,
            root_primary_shock_ts TEXT,
            root_episode_event_index INTEGER,
            selected_event_source TEXT,
            selected_event_id TEXT,
            selected_match_mode TEXT,
            selected_cause_event TEXT,
            selected_cause_route_key TEXT,
            selected_cause_claim_status TEXT,
            selected_cause_classification TEXT,
            selected_cause_confidence REAL,
            selected_fundamental_score REAL,
            selected_is_primary_cause INTEGER,
            shock_direction TEXT,
            abs_move_pct REAL,
            z_score REAL,
            updated_at_utc TEXT NOT NULL,
            PRIMARY KEY (symbol, shock_ts, bar_minutes)
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_REGISTRY_TABLE} (
            root_topic_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            first_shock_ts TEXT NOT NULL,
            last_shock_ts TEXT NOT NULL,
            shock_count INTEGER NOT NULL,
            primary_count INTEGER NOT NULL,
            aftershock_count INTEGER NOT NULL,
            max_abs_z REAL NOT NULL,
            avg_abs_move_pct REAL NOT NULL,
            last_cause_event TEXT,
            last_cause_route_key TEXT,
            updated_at_utc TEXT NOT NULL,
            PRIMARY KEY (root_topic_id, symbol)
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_EDGE_TABLE} (
            symbol TEXT NOT NULL,
            cause_route_key TEXT NOT NULL,
            source_node TEXT NOT NULL,
            target_node TEXT NOT NULL,
            edge_weight INTEGER NOT NULL,
            last_shock_ts TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            PRIMARY KEY (symbol, cause_route_key, source_node, target_node)
        )
        """
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{_LINK_TABLE}_root ON {_LINK_TABLE} (root_topic_id, symbol, shock_ts DESC)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{_REGISTRY_TABLE}_symbol ON {_REGISTRY_TABLE} (symbol, last_shock_ts DESC)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{_EDGE_TABLE}_symbol ON {_EDGE_TABLE} (symbol, edge_weight DESC, last_shock_ts DESC)"
    )
    conn.commit()


def _route_edges(route_key: str) -> list[tuple[str, str]]:
    parts = [item for item in _normalize_text(route_key).split("->") if item]
    if len(parts) < 2:
        return []
    return [(parts[idx], parts[idx + 1]) for idx in range(len(parts) - 1)]


def refresh_root_maintenance(
    *,
    database_url: str,
    data_dir: str | Path,
    cfg: RootMaintenanceConfig | None = None,
) -> dict[str, Any]:
    config = cfg or RootMaintenanceConfig()
    shocks = read_live_shock_rows(
        database_url=database_url,
        data_dir=data_dir,
        start_ts=config.start_ts,
        end_ts=config.end_ts,
        bar_minutes=config.bar_minutes,
        max_rows=config.max_rows,
    )
    if shocks.empty:
        return {"rows_scanned": 0, "links_upserted": 0, "registry_upserted": 0, "edges_upserted": 0}

    work = shocks.copy()
    work["symbol"] = work.get("symbol", pd.Series("", index=work.index)).astype(str).str.strip().str.upper()
    work["shock_ts"] = work.get("shock_ts", pd.Series("", index=work.index)).astype(str).str.strip()
    work["bar_minutes"] = pd.to_numeric(work.get("bar_minutes"), errors="coerce").fillna(0).astype(int)
    work["root_topic_id"] = work.get("root_topic_id", pd.Series("", index=work.index)).astype(str).str.strip()
    work = work[work["root_topic_id"].ne("")]
    if work.empty:
        return {"rows_scanned": int(len(shocks)), "links_upserted": 0, "registry_upserted": 0, "edges_upserted": 0}

    work["shock_dt"] = pd.to_datetime(work["shock_ts"], utc=True, errors="coerce")
    work = work.dropna(subset=["shock_dt"])
    if work.empty:
        return {"rows_scanned": int(len(shocks)), "links_upserted": 0, "registry_upserted": 0, "edges_upserted": 0}

    now_utc = pd.Timestamp.utcnow().isoformat().replace("+00:00", "Z")
    db_path = sqlite_path_from_url(database_url, data_dir=data_dir)
    conn = open_sqlite_connection(db_path, timeout_sec=15.0, write=True)
    try:
        _init_tables(conn)
        link_rows: list[tuple[Any, ...]] = []
        edge_accumulator: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for _, row in work.sort_values(["shock_dt", "symbol"]).iterrows():
            symbol = _normalize_text(row.get("symbol")).upper()
            shock_ts = _normalize_text(row.get("shock_ts"))
            bar_minutes = _safe_int(row.get("bar_minutes"))
            root_topic_id = _normalize_text(row.get("root_topic_id"))
            route_key = _normalize_text(row.get("selected_cause_route_key"))
            link_rows.append(
                (
                    symbol,
                    shock_ts,
                    bar_minutes,
                    root_topic_id,
                    _normalize_text(row.get("root_link_type")),
                    _normalize_text(row.get("root_primary_shock_ts")),
                    _safe_int(row.get("root_episode_event_index")),
                    _normalize_text(row.get("selected_event_source")),
                    _normalize_text(row.get("selected_event_id")),
                    _normalize_text(row.get("selected_match_mode")),
                    _normalize_text(row.get("selected_cause_event")),
                    route_key,
                    _normalize_text(row.get("selected_cause_claim_status")),
                    _normalize_text(row.get("selected_cause_classification")),
                    _safe_float(row.get("selected_cause_confidence")),
                    _safe_float(row.get("selected_fundamental_score")),
                    _safe_int(row.get("selected_is_primary_cause")),
                    _normalize_text(row.get("shock_direction")).lower(),
                    _safe_float(row.get("abs_move_pct")),
                    _safe_float(row.get("z_score")),
                    now_utc,
                )
            )
            for source_node, target_node in _route_edges(route_key):
                edge_key = (symbol, route_key, source_node, target_node)
                current = edge_accumulator.get(edge_key)
                if current is None:
                    edge_accumulator[edge_key] = {"weight": 1, "last_shock_ts": shock_ts}
                else:
                    current["weight"] = int(current["weight"]) + 1
                    if str(shock_ts) > str(current["last_shock_ts"]):
                        current["last_shock_ts"] = shock_ts

        conn.executemany(
            f"""
            INSERT INTO {_LINK_TABLE} (
                symbol, shock_ts, bar_minutes, root_topic_id, root_link_type, root_primary_shock_ts,
                root_episode_event_index, selected_event_source, selected_event_id, selected_match_mode,
                selected_cause_event, selected_cause_route_key, selected_cause_claim_status, selected_cause_classification,
                selected_cause_confidence, selected_fundamental_score, selected_is_primary_cause,
                shock_direction, abs_move_pct, z_score, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, shock_ts, bar_minutes) DO UPDATE SET
                root_topic_id = excluded.root_topic_id,
                root_link_type = excluded.root_link_type,
                root_primary_shock_ts = excluded.root_primary_shock_ts,
                root_episode_event_index = excluded.root_episode_event_index,
                selected_event_source = excluded.selected_event_source,
                selected_event_id = excluded.selected_event_id,
                selected_match_mode = excluded.selected_match_mode,
                selected_cause_event = excluded.selected_cause_event,
                selected_cause_route_key = excluded.selected_cause_route_key,
                selected_cause_claim_status = excluded.selected_cause_claim_status,
                selected_cause_classification = excluded.selected_cause_classification,
                selected_cause_confidence = excluded.selected_cause_confidence,
                selected_fundamental_score = excluded.selected_fundamental_score,
                selected_is_primary_cause = excluded.selected_is_primary_cause,
                shock_direction = excluded.shock_direction,
                abs_move_pct = excluded.abs_move_pct,
                z_score = excluded.z_score,
                updated_at_utc = excluded.updated_at_utc
            """,
            link_rows,
        )

        registry_rows: list[tuple[Any, ...]] = []
        grouped = work.sort_values("shock_dt").groupby(["root_topic_id", "symbol"], sort=False)
        for (root_topic_id, symbol), part in grouped:
            first_ts = str(part["shock_ts"].iloc[0])
            last_ts = str(part["shock_ts"].iloc[-1])
            shock_count = int(len(part))
            root_type = part.get("root_link_type", pd.Series("", index=part.index)).astype(str).str.lower()
            primary_count = int(root_type.eq("primary").sum())
            aftershock_count = int(root_type.eq("aftershock").sum())
            max_abs_z = float(pd.to_numeric(part.get("z_score"), errors="coerce").abs().max() or 0.0)
            avg_abs_move = float(pd.to_numeric(part.get("abs_move_pct"), errors="coerce").abs().mean() or 0.0)
            last_row = part.iloc[-1]
            registry_rows.append(
                (
                    str(root_topic_id),
                    str(symbol).upper(),
                    first_ts,
                    last_ts,
                    shock_count,
                    primary_count,
                    aftershock_count,
                    max_abs_z,
                    avg_abs_move,
                    _normalize_text(last_row.get("selected_cause_event")),
                    _normalize_text(last_row.get("selected_cause_route_key")),
                    now_utc,
                )
            )

        conn.executemany(
            f"""
            INSERT INTO {_REGISTRY_TABLE} (
                root_topic_id, symbol, first_shock_ts, last_shock_ts, shock_count, primary_count,
                aftershock_count, max_abs_z, avg_abs_move_pct, last_cause_event, last_cause_route_key, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(root_topic_id, symbol) DO UPDATE SET
                first_shock_ts = excluded.first_shock_ts,
                last_shock_ts = excluded.last_shock_ts,
                shock_count = excluded.shock_count,
                primary_count = excluded.primary_count,
                aftershock_count = excluded.aftershock_count,
                max_abs_z = excluded.max_abs_z,
                avg_abs_move_pct = excluded.avg_abs_move_pct,
                last_cause_event = excluded.last_cause_event,
                last_cause_route_key = excluded.last_cause_route_key,
                updated_at_utc = excluded.updated_at_utc
            """,
            registry_rows,
        )

        edge_rows = [
            (
                symbol,
                route_key,
                source_node,
                target_node,
                int(meta["weight"]),
                str(meta["last_shock_ts"]),
                now_utc,
            )
            for (symbol, route_key, source_node, target_node), meta in edge_accumulator.items()
        ]
        if edge_rows:
            conn.executemany(
                f"""
                INSERT INTO {_EDGE_TABLE} (
                    symbol, cause_route_key, source_node, target_node, edge_weight, last_shock_ts, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, cause_route_key, source_node, target_node) DO UPDATE SET
                    edge_weight = excluded.edge_weight,
                    last_shock_ts = excluded.last_shock_ts,
                    updated_at_utc = excluded.updated_at_utc
                """,
                edge_rows,
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "rows_scanned": int(len(shocks)),
        "links_upserted": int(len(link_rows)),
        "registry_upserted": int(len(registry_rows)),
        "edges_upserted": int(len(edge_accumulator)),
    }
