from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from moex_carry.config import AppSettings
from moex_carry.news_live_runtime import NewsIngestConfig
from moex_carry.news_root_maintenance import RootMaintenanceConfig, refresh_root_maintenance
from moex_carry.news_shock_live_input import LiveShockInputConfig, build_live_shock_input
from moex_carry.news_shock_store import upsert_live_shock_rows
from moex_carry.news_storage import open_sqlite_connection, sqlite_path_from_url


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_utc(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    if isinstance(parsed, pd.Timestamp):
        return parsed.to_pydatetime()
    return None


def _ensure_news_state_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_state (
            state_key TEXT PRIMARY KEY,
            state_value TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _get_state(conn: Any, key: str) -> str | None:
    row = conn.execute("SELECT state_value FROM news_state WHERE state_key = ?", (key,)).fetchone()
    if row is None:
        return None
    return str(row[0])


def _set_state(conn: Any, key: str, value: str) -> None:
    now = _iso_utc(datetime.now(timezone.utc))
    conn.execute(
        """
        INSERT INTO news_state (state_key, state_value, updated_at_utc)
        VALUES (?, ?, ?)
        ON CONFLICT(state_key) DO UPDATE SET
            state_value = excluded.state_value,
            updated_at_utc = excluded.updated_at_utc
        """,
        (key, value, now),
    )
    conn.commit()


@dataclass(frozen=True)
class ShockRowsBackfillConfig:
    cursor_key: str = "shock_rows_backfill_cursor_utc"
    start_utc: datetime = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end_utc: datetime | None = None
    window_hours: int = 24
    windows_per_run: int = 5
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
    news_min_confidence: float = 0.6
    news_max_items_per_symbol: int = 3000
    front_contract_candidates: int = 4
    history_padding_days: int = 10
    root_reuse_lookback_minutes: float = 2880.0
    root_min_fundamental_score: float = 0.45
    root_min_cause_confidence: float = 0.45
    aftershock_max_gap_minutes: float = 2880.0
    enable_candidate_newsapi_enrichment: bool = False
    enrichment_window_minutes: int = 90
    enrichment_max_requests_per_symbol: int = 4
    run_root_maintenance: bool = True
    write_csv_snapshot: bool = False
    snapshot_dir: str = "data/output/shock_backfill_snapshots"


def run_shock_rows_backfill(
    *,
    settings: AppSettings,
    news_config: NewsIngestConfig,
    cfg: ShockRowsBackfillConfig,
) -> dict[str, Any]:
    db_path = sqlite_path_from_url(news_config.database_url, data_dir=news_config.data_dir)
    conn = open_sqlite_connection(db_path, timeout_sec=15.0, write=True)
    try:
        _ensure_news_state_table(conn)
        raw_cursor = _get_state(conn, cfg.cursor_key)
    finally:
        conn.close()

    effective_end = cfg.end_utc.astimezone(timezone.utc) if cfg.end_utc is not None else datetime.now(timezone.utc)
    cursor = _parse_iso_utc(raw_cursor) if raw_cursor else effective_end
    if cursor is None:
        cursor = effective_end

    start_utc = cfg.start_utc.astimezone(timezone.utc)
    if cursor <= start_utc:
        return {
            "database_path": str(db_path),
            "cursor_key": cfg.cursor_key,
            "start_utc": _iso_utc(start_utc),
            "cursor_before": _iso_utc(cursor),
            "cursor_after": _iso_utc(cursor),
            "windows_processed": 0,
            "rows_upserted_total": 0,
            "done": True,
            "reason": "cursor_at_or_before_start",
        }

    windows_processed = 0
    rows_upserted_total = 0
    rows_detected_total = 0
    root_links_total = 0
    root_registry_total = 0
    root_edges_total = 0
    snapshots: list[str] = []
    cursor_before = cursor
    window_hours = max(int(cfg.window_hours), 1)
    windows_per_run = max(int(cfg.windows_per_run), 1)

    while windows_processed < windows_per_run and cursor > start_utc:
        window_end = cursor
        window_start = max(start_utc, window_end - timedelta(hours=window_hours))
        live_cfg = LiveShockInputConfig(
            lookback_hours=window_hours,
            bar_minutes=cfg.bar_minutes,
            min_abs_z=cfg.min_abs_z,
            rolling_window_bars=cfg.rolling_window_bars,
            rolling_min_bars=cfg.rolling_min_bars,
            max_delay_minutes=cfg.max_delay_minutes,
            strict_pre_shock_minutes=cfg.strict_pre_shock_minutes,
            broad_context_lookback_minutes=cfg.broad_context_lookback_minutes,
            v2_min_relevance=cfg.v2_min_relevance,
            broad_min_relevance=cfg.broad_min_relevance,
            cross_commodity_min_relevance=cfg.cross_commodity_min_relevance,
            news_min_impact_score=cfg.news_min_impact_score,
            news_min_confidence=cfg.news_min_confidence,
            news_max_items_per_symbol=cfg.news_max_items_per_symbol,
            front_contract_candidates=cfg.front_contract_candidates,
            history_padding_days=cfg.history_padding_days,
            root_reuse_lookback_minutes=cfg.root_reuse_lookback_minutes,
            root_min_fundamental_score=cfg.root_min_fundamental_score,
            root_min_cause_confidence=cfg.root_min_cause_confidence,
            aftershock_max_gap_minutes=cfg.aftershock_max_gap_minutes,
            enable_candidate_newsapi_enrichment=cfg.enable_candidate_newsapi_enrichment,
            enrichment_window_minutes=cfg.enrichment_window_minutes,
            enrichment_max_requests_per_symbol=cfg.enrichment_max_requests_per_symbol,
        )
        frame = build_live_shock_input(
            settings=settings,
            news_config=news_config,
            cfg=live_cfg,
            end_utc=window_end,
        )
        if not frame.empty:
            ts = pd.to_datetime(frame["shock_ts"], utc=True, errors="coerce")
            frame = frame[(ts >= window_start) & (ts <= window_end)].copy()
        rows_detected = int(len(frame))
        rows_detected_total += rows_detected
        rows_upserted = int(
            upsert_live_shock_rows(
                frame=frame,
                database_url=news_config.database_url,
                data_dir=news_config.data_dir,
            )
        )
        rows_upserted_total += rows_upserted
        if cfg.run_root_maintenance and rows_upserted > 0:
            root_report = refresh_root_maintenance(
                database_url=news_config.database_url,
                data_dir=news_config.data_dir,
                cfg=RootMaintenanceConfig(
                    bar_minutes=cfg.bar_minutes,
                    start_ts=_iso_utc(window_start),
                    end_ts=_iso_utc(window_end),
                    max_rows=0,
                ),
            )
            root_links_total += int(root_report.get("links_upserted") or 0)
            root_registry_total += int(root_report.get("registry_upserted") or 0)
            root_edges_total += int(root_report.get("edges_upserted") or 0)

        if cfg.write_csv_snapshot:
            snap_dir = Path(cfg.snapshot_dir)
            if not snap_dir.is_absolute():
                snap_dir = (Path(settings.data.data_dir) / snap_dir).resolve()
            snap_dir.mkdir(parents=True, exist_ok=True)
            snap_name = f"shock_rows_{window_start.strftime('%Y%m%dT%H%M%SZ')}_{window_end.strftime('%Y%m%dT%H%M%SZ')}.csv"
            snap_path = snap_dir / snap_name
            frame.to_csv(snap_path, index=False)
            snapshots.append(str(snap_path))

        cursor = window_start
        windows_processed += 1
        if cursor <= start_utc:
            break

    conn = open_sqlite_connection(db_path, timeout_sec=15.0, write=True)
    try:
        _ensure_news_state_table(conn)
        _set_state(conn, cfg.cursor_key, _iso_utc(cursor))
    finally:
        conn.close()

    return {
        "database_path": str(db_path),
        "cursor_key": cfg.cursor_key,
        "start_utc": _iso_utc(start_utc),
        "cursor_before": _iso_utc(cursor_before),
        "cursor_after": _iso_utc(cursor),
        "windows_processed": int(windows_processed),
        "rows_detected_total": int(rows_detected_total),
        "rows_upserted_total": int(rows_upserted_total),
        "root_links_upserted_total": int(root_links_total),
        "root_registry_upserted_total": int(root_registry_total),
        "root_edges_upserted_total": int(root_edges_total),
        "done": bool(cursor <= start_utc),
        "snapshots": snapshots,
    }
