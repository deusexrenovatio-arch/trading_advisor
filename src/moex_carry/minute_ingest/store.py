from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_MINUTE_COLUMNS: tuple[str, ...] = (
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
)


@dataclass(frozen=True)
class MinuteWatermark:
    max_exec_ts: datetime | None
    tail_hash_180m: str
    signature: str


@dataclass
class UpsertMinuteResult:
    before: MinuteWatermark
    after: MinuteWatermark
    changed: bool
    append_only: bool
    earliest_changed_exec_ts: datetime | None
    rows_total: int
    rows_replaced: int
    rows_inserted: int
    path: Path


def minute_series_path(*, data_dir: Path, stock: str, future: str) -> Path:
    safe_stock = str(stock or "").strip().upper()
    safe_future = str(future or "").strip().upper()
    return (
        Path(data_dir)
        / "output"
        / "intraday_minute_series"
        / f"intraday_minute_series_{safe_stock}_{safe_future}.csv"
    )


def load_minute_series(*, data_dir: Path, stock: str, future: str) -> pd.DataFrame:
    path = minute_series_path(data_dir=data_dir, stock=stock, future=future)
    if not path.exists():
        return pd.DataFrame(columns=list(REQUIRED_MINUTE_COLUMNS))
    try:
        frame = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=list(REQUIRED_MINUTE_COLUMNS))
    return normalize_minute_frame(frame)


def normalize_minute_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=list(REQUIRED_MINUTE_COLUMNS))
    work = frame.copy()
    if "exec_ts" not in work.columns and "ts" in work.columns:
        work["exec_ts"] = work["ts"]
    if "date" not in work.columns:
        work["date"] = pd.to_datetime(work.get("exec_ts"), errors="coerce").dt.date
    work["exec_ts"] = pd.to_datetime(work.get("exec_ts"), errors="coerce")
    work["date"] = pd.to_datetime(work.get("date"), errors="coerce").dt.date
    for col in REQUIRED_MINUTE_COLUMNS:
        if col in {"date", "exec_ts"}:
            continue
        if col not in work.columns:
            work[col] = 0.0
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=["date", "exec_ts", "spot_mid", "future_mid"]).copy()
    work = work.sort_values("exec_ts").drop_duplicates(subset=["exec_ts"], keep="last").reset_index(drop=True)
    missing = [col for col in REQUIRED_MINUTE_COLUMNS if col not in work.columns]
    for col in missing:
        work[col] = 0.0 if col not in {"date", "exec_ts"} else None
    return work[list(REQUIRED_MINUTE_COLUMNS)]


def compute_watermark(frame: pd.DataFrame, *, tail_minutes: int = 180) -> MinuteWatermark:
    if frame.empty or "exec_ts" not in frame.columns:
        return MinuteWatermark(max_exec_ts=None, tail_hash_180m="", signature="none")
    work = normalize_minute_frame(frame)
    if work.empty:
        return MinuteWatermark(max_exec_ts=None, tail_hash_180m="", signature="none")
    max_exec_ts = pd.to_datetime(work["exec_ts"], errors="coerce").max()
    if pd.isna(max_exec_ts):
        return MinuteWatermark(max_exec_ts=None, tail_hash_180m="", signature="none")
    if isinstance(max_exec_ts, pd.Timestamp):
        if max_exec_ts.tzinfo is not None:
            max_exec_ts = max_exec_ts.tz_convert("UTC").tz_localize(None)
        max_exec = max_exec_ts.to_pydatetime().replace(tzinfo=None)
    elif isinstance(max_exec_ts, datetime):
        max_exec = max_exec_ts.astimezone(timezone.utc).replace(tzinfo=None) if max_exec_ts.tzinfo else max_exec_ts
    else:
        max_exec = None
    if max_exec is None:
        return MinuteWatermark(max_exec_ts=None, tail_hash_180m="", signature="none")

    lower_bound = max_exec - timedelta(minutes=max(int(tail_minutes), 1))
    tail = work[pd.to_datetime(work["exec_ts"], errors="coerce") >= lower_bound].copy()
    if tail.empty:
        tail_hash = ""
    else:
        payload = (
            tail.sort_values("exec_ts")[
                ["exec_ts", "spot_mid", "future_mid", "spot_volume", "future_volume"]
            ]
            .astype({"spot_mid": "float64", "future_mid": "float64", "spot_volume": "float64", "future_volume": "float64"})
            .to_json(orient="records", date_format="iso")
        )
        tail_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    signature = watermark_signature(max_exec_ts=max_exec, tail_hash_180m=tail_hash)
    return MinuteWatermark(max_exec_ts=max_exec, tail_hash_180m=tail_hash, signature=signature)


def upsert_minute_series(
    *,
    data_dir: Path,
    stock: str,
    future: str,
    incoming: pd.DataFrame,
    tail_minutes: int = 180,
) -> UpsertMinuteResult:
    path = minute_series_path(data_dir=data_dir, stock=stock, future=future)
    existing = load_minute_series(data_dir=data_dir, stock=stock, future=future)
    incoming_norm = normalize_minute_frame(incoming)
    before = compute_watermark(existing, tail_minutes=tail_minutes)
    if incoming_norm.empty:
        return UpsertMinuteResult(
            before=before,
            after=before,
            changed=False,
            append_only=True,
            earliest_changed_exec_ts=None,
            rows_total=int(len(existing)),
            rows_replaced=0,
            rows_inserted=0,
            path=path,
        )

    changed = False
    append_only = True
    earliest_changed_exec_ts: datetime | None = None
    rows_replaced = 0
    rows_inserted = 0

    existing_idx = existing.set_index("exec_ts") if not existing.empty else pd.DataFrame()
    before_max_ts = before.max_exec_ts

    for row in incoming_norm.to_dict("records"):
        exec_ts = pd.to_datetime(row.get("exec_ts"), errors="coerce")
        if pd.isna(exec_ts):
            continue
        exec_ts_key = pd.Timestamp(exec_ts)
        if not existing_idx.empty and exec_ts_key in existing_idx.index:
            prev_row = existing_idx.loc[exec_ts_key]
            if isinstance(prev_row, pd.DataFrame):
                prev_row = prev_row.iloc[-1]
            same = _row_payload(prev_row) == _row_payload(row)
            if not same:
                changed = True
                rows_replaced += 1
                if before_max_ts is not None and exec_ts_key.to_pydatetime().replace(tzinfo=None) <= before_max_ts:
                    append_only = False
                    earliest_changed_exec_ts = _min_exec_ts(
                        earliest_changed_exec_ts,
                        exec_ts_key.to_pydatetime().replace(tzinfo=None),
                    )
        else:
            changed = True
            rows_inserted += 1
            if before_max_ts is not None and exec_ts_key.to_pydatetime().replace(tzinfo=None) <= before_max_ts:
                append_only = False
                earliest_changed_exec_ts = _min_exec_ts(
                    earliest_changed_exec_ts,
                    exec_ts_key.to_pydatetime().replace(tzinfo=None),
                )

    if changed:
        merged = pd.concat([existing, incoming_norm], ignore_index=True)
        merged = normalize_minute_frame(merged)
        _write_csv_atomic(path, merged)
    else:
        merged = existing

    after = compute_watermark(merged, tail_minutes=tail_minutes)
    return UpsertMinuteResult(
        before=before,
        after=after,
        changed=changed,
        append_only=append_only,
        earliest_changed_exec_ts=earliest_changed_exec_ts,
        rows_total=int(len(merged)),
        rows_replaced=rows_replaced,
        rows_inserted=rows_inserted,
        path=path,
    )


def watermark_signature(*, max_exec_ts: datetime | None, tail_hash_180m: str) -> str:
    max_text = max_exec_ts.isoformat(timespec="seconds") if max_exec_ts is not None else "none"
    payload = f"{max_text}|{tail_hash_180m}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row_payload(row: Any) -> tuple[float | None, float | None, float | None, float | None]:
    if isinstance(row, dict):
        getter = row.get
    else:
        getter = row.get  # type: ignore[assignment]
    return (
        _as_opt_float(getter("spot_mid")),
        _as_opt_float(getter("future_mid")),
        _as_opt_float(getter("spot_volume")),
        _as_opt_float(getter("future_volume")),
    )


def _as_opt_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return numeric


def _min_exec_ts(current: datetime | None, candidate: datetime) -> datetime:
    if current is None:
        return candidate
    return candidate if candidate < current else current


def _write_csv_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["exec_ts"] = pd.to_datetime(out["exec_ts"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
    out.to_csv(tmp_path, index=False)
    os.replace(tmp_path, path)
