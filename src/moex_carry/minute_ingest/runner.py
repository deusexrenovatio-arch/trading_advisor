from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from typing import Iterable

import pandas as pd

from moex_carry.config import AppSettings
from moex_carry.data.moex_iss import MoexIssClient
from moex_carry.minute_ingest.cursor_state import PairCursorState, load_cursor_state, save_cursor_state
from moex_carry.minute_ingest.store import (
    MinuteWatermark,
    UpsertMinuteResult,
    compute_watermark,
    load_minute_series,
    upsert_minute_series,
)


@dataclass(frozen=True)
class IngestPair:
    stock: str
    future: str
    future_scale: float = 1.0

    @property
    def pair_id(self) -> str:
        return f"{self.stock}|{self.future}"


@dataclass
class PairIngestResult:
    pair_id: str
    before: MinuteWatermark
    after: MinuteWatermark
    changed: bool
    append_only: bool
    earliest_changed_exec_ts: datetime | None
    degraded: bool
    error: str | None
    rows_total: int
    rows_inserted: int
    rows_replaced: int
    ingest_lag_sec: float | None
    state_path: Path | None = None
    data_path: Path | None = None


@dataclass
class MinuteIngestCycle:
    started_at: datetime
    finished_at: datetime
    pair_results: dict[str, PairIngestResult]
    global_watermark_before: str
    global_watermark_after: str
    degraded: bool

    @property
    def changed_pairs(self) -> set[str]:
        return {
            pair_id
            for pair_id, item in self.pair_results.items()
            if item.changed
        }


def run_incremental_minute_ingest(
    *,
    settings: AppSettings,
    data_dir: Path,
    checkpoint_root: Path,
    pairs: Iterable[IngestPair],
    overlap_minutes: int = 180,
    now: datetime | None = None,
    client: MoexIssClient | None = None,
) -> MinuteIngestCycle:
    now_utc = now if now is not None else datetime.now(timezone.utc)
    if now_utc.tzinfo is not None:
        now_naive = now_utc.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        now_naive = now_utc
    client_obj = client or MoexIssClient(
        settings.moex.base_url,
        settings.moex.request_timeout_sec,
        max_retries=settings.moex.request_max_retries,
        retry_backoff_sec=settings.moex.request_retry_backoff_sec,
        retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
        fallback_ips=settings.moex.fallback_ips,
        force_fallback=settings.moex.force_fallback,
    )

    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    results: dict[str, PairIngestResult] = {}
    for pair in pairs:
        pair_id = pair.pair_id
        before_frame = load_minute_series(data_dir=data_dir, stock=pair.stock, future=pair.future)
        before = compute_watermark(before_frame, tail_minutes=180)
        state_path: Path | None = None
        data_path: Path | None = None
        try:
            from_ts = _resolve_from_ts(
                checkpoint_root=checkpoint_root,
                pair_id=pair_id,
                before=before,
                now_ts=now_naive,
                overlap_minutes=overlap_minutes,
            )
            incoming = _fetch_common_minutes(
                client_obj=client_obj,
                settings=settings,
                pair=pair,
                from_ts=from_ts,
                till_ts=now_naive,
            )
            upsert = upsert_minute_series(
                data_dir=data_dir,
                stock=pair.stock,
                future=pair.future,
                incoming=incoming,
                tail_minutes=180,
            )
            state = PairCursorState(
                pair_id=pair_id,
                max_exec_ts=upsert.after.max_exec_ts,
                tail_hash_180m=upsert.after.tail_hash_180m,
                watermark=upsert.after.signature,
                last_update_at=now_naive,
                degraded=False,
                error=None,
            )
            state_path = save_cursor_state(checkpoint_root=checkpoint_root, state=state)
            lag_sec = (
                max((now_naive - upsert.after.max_exec_ts).total_seconds(), 0.0)
                if upsert.after.max_exec_ts is not None
                else None
            )
            data_path = upsert.path
            results[pair_id] = PairIngestResult(
                pair_id=pair_id,
                before=upsert.before,
                after=upsert.after,
                changed=upsert.changed,
                append_only=upsert.append_only,
                earliest_changed_exec_ts=upsert.earliest_changed_exec_ts,
                degraded=False,
                error=None,
                rows_total=upsert.rows_total,
                rows_inserted=upsert.rows_inserted,
                rows_replaced=upsert.rows_replaced,
                ingest_lag_sec=lag_sec,
                state_path=state_path,
                data_path=data_path,
            )
        except Exception as exc:
            fallback_state = PairCursorState(
                pair_id=pair_id,
                max_exec_ts=before.max_exec_ts,
                tail_hash_180m=before.tail_hash_180m,
                watermark=before.signature,
                last_update_at=now_naive,
                degraded=True,
                error=str(exc),
            )
            state_path = save_cursor_state(checkpoint_root=checkpoint_root, state=fallback_state)
            results[pair_id] = PairIngestResult(
                pair_id=pair_id,
                before=before,
                after=before,
                changed=False,
                append_only=True,
                earliest_changed_exec_ts=None,
                degraded=True,
                error=str(exc),
                rows_total=int(len(before_frame)),
                rows_inserted=0,
                rows_replaced=0,
                ingest_lag_sec=(
                    max((now_naive - before.max_exec_ts).total_seconds(), 0.0)
                    if before.max_exec_ts is not None
                    else None
                ),
                state_path=state_path,
                data_path=data_path,
            )

    finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    global_before = _global_watermark({key: item.before.signature for key, item in results.items()})
    global_after = _global_watermark({key: item.after.signature for key, item in results.items()})
    degraded = any(item.degraded for item in results.values())
    return MinuteIngestCycle(
        started_at=started_at,
        finished_at=finished_at,
        pair_results=results,
        global_watermark_before=global_before,
        global_watermark_after=global_after,
        degraded=degraded,
    )


def _resolve_from_ts(
    *,
    checkpoint_root: Path,
    pair_id: str,
    before: MinuteWatermark,
    now_ts: datetime,
    overlap_minutes: int,
) -> datetime:
    cursor = load_cursor_state(checkpoint_root=checkpoint_root, pair_id=pair_id)
    anchor = before.max_exec_ts
    if cursor is not None and cursor.max_exec_ts is not None:
        anchor = cursor.max_exec_ts
    if anchor is None:
        return now_ts - timedelta(days=2)
    return anchor - timedelta(minutes=max(int(overlap_minutes), 1))


def _fetch_common_minutes(
    *,
    client_obj: MoexIssClient,
    settings: AppSettings,
    pair: IngestPair,
    from_ts: datetime,
    till_ts: datetime,
) -> pd.DataFrame:
    from_day = from_ts.date()
    till_day = till_ts.date()
    stock_raw = client_obj.get_candles(
        settings.moex.engine_shares,
        settings.moex.market_shares,
        pair.stock,
        settings.moex.shares_board,
        from_day,
        till_day,
        interval=1,
    )
    future_raw = client_obj.get_candles(
        settings.moex.engine_futures,
        settings.moex.market_futures,
        pair.future,
        settings.moex.futures_board,
        from_day,
        till_day,
        interval=1,
    )
    stock_df = _minute_close_frame(stock_raw, price_scale=1.0)
    future_df = _minute_close_frame(future_raw, price_scale=max(float(pair.future_scale or 1.0), 1e-9))
    if stock_df.empty or future_df.empty:
        return pd.DataFrame(columns=["date", "spot_mid", "future_mid", "pv_div", "div_sum", "spread_mid", "spread_pct", "exec_ts", "spot_volume", "future_volume"])
    joined = stock_df.merge(future_df, on="ts", how="inner", suffixes=("_stock", "_future"))
    if joined.empty:
        return pd.DataFrame(columns=["date", "spot_mid", "future_mid", "pv_div", "div_sum", "spread_mid", "spread_pct", "exec_ts", "spot_volume", "future_volume"])
    joined = joined.sort_values("ts").drop_duplicates(subset=["ts"], keep="last")
    joined["spot_mid"] = pd.to_numeric(joined["price_stock"], errors="coerce")
    joined["future_mid"] = pd.to_numeric(joined["price_future"], errors="coerce")
    joined["spread_mid"] = joined["spot_mid"] - joined["future_mid"]
    joined["spread_pct"] = joined["spread_mid"] / joined["spot_mid"].where(joined["spot_mid"] != 0)
    joined["spot_volume"] = pd.to_numeric(joined["volume_stock"], errors="coerce").fillna(0.0)
    joined["future_volume"] = pd.to_numeric(joined["volume_future"], errors="coerce").fillna(0.0)
    joined["date"] = pd.to_datetime(joined["ts"], errors="coerce").dt.date
    joined["exec_ts"] = pd.to_datetime(joined["ts"], errors="coerce")
    joined["pv_div"] = 0.0
    joined["div_sum"] = 0.0
    joined = joined.dropna(subset=["date", "exec_ts", "spot_mid", "future_mid"])
    return joined[
        [
            "date",
            "spot_mid",
            "future_mid",
            "pv_div",
            "div_sum",
            "spread_mid",
            "spread_pct",
            "exec_ts",
            "spot_volume",
            "future_volume",
        ]
    ].reset_index(drop=True)


def _minute_close_frame(raw: list[dict[str, object]], *, price_scale: float = 1.0) -> pd.DataFrame:
    frame = pd.DataFrame(raw)
    if frame.empty:
        return pd.DataFrame(columns=["ts", "price", "volume"])
    frame["ts"] = pd.to_datetime(frame.get("begin"), errors="coerce").dt.floor("min")
    frame["price"] = pd.to_numeric(frame.get("close"), errors="coerce")
    scale = float(price_scale) if float(price_scale) > 0 else 1.0
    frame["price"] = frame["price"] / scale
    frame["volume"] = pd.to_numeric(frame.get("volume"), errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["ts", "price"])
    if frame.empty:
        return pd.DataFrame(columns=["ts", "price", "volume"])
    return frame.sort_values("ts").drop_duplicates(subset=["ts"], keep="last")[["ts", "price", "volume"]]


def _global_watermark(signatures: dict[str, str]) -> str:
    if not signatures:
        return "none"
    payload = "|".join(f"{key}:{signatures[key]}" for key in sorted(signatures))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
