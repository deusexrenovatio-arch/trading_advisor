from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class PairCursorState:
    pair_id: str
    max_exec_ts: datetime | None
    tail_hash_180m: str
    watermark: str
    last_update_at: datetime
    degraded: bool = False
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "max_exec_ts": _iso_or_none(self.max_exec_ts),
            "tail_hash_180m": self.tail_hash_180m,
            "watermark": self.watermark,
            "last_update_at": _iso_or_none(self.last_update_at),
            "degraded": bool(self.degraded),
            "error": self.error,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PairCursorState":
        return cls(
            pair_id=str(payload.get("pair_id") or ""),
            max_exec_ts=_as_naive_datetime(payload.get("max_exec_ts")),
            tail_hash_180m=str(payload.get("tail_hash_180m") or ""),
            watermark=str(payload.get("watermark") or ""),
            last_update_at=_as_naive_datetime(payload.get("last_update_at"))
            or datetime.now(timezone.utc).replace(tzinfo=None),
            degraded=bool(payload.get("degraded") or False),
            error=str(payload.get("error") or "") or None,
        )


def cursor_state_path(*, checkpoint_root: Path, pair_id: str) -> Path:
    safe = _safe_pair_id(pair_id)
    return checkpoint_root / safe / "cursor.json"


def load_cursor_state(*, checkpoint_root: Path, pair_id: str) -> PairCursorState | None:
    path = cursor_state_path(checkpoint_root=checkpoint_root, pair_id=pair_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return PairCursorState.from_payload(payload)
    except Exception:
        return None


def save_cursor_state(*, checkpoint_root: Path, state: PairCursorState) -> Path:
    path = cursor_state_path(checkpoint_root=checkpoint_root, pair_id=state.pair_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(
        json.dumps(state.to_payload(), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_path, path)
    return path


def _safe_pair_id(pair_id: str) -> str:
    return (
        str(pair_id or "")
        .strip()
        .replace("\\", "_")
        .replace("/", "_")
        .replace("|", "__")
        .replace(":", "_")
        or "unknown_pair"
    )


def _as_naive_datetime(value: object) -> datetime | None:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        return ts.to_pydatetime().replace(tzinfo=None)
    if isinstance(ts, datetime):
        if ts.tzinfo is not None:
            return ts.astimezone(timezone.utc).replace(tzinfo=None)
        return ts
    return None


def _iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="seconds")
