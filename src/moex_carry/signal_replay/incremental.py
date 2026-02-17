from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from datetime import datetime, timedelta, timezone
import inspect
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from moex_carry.config import AppSettings
from moex_carry.domain.models import ContractSpec, DividendEvent, KeyRate
from moex_carry.domain.portfolio import PairSpec
from moex_carry.pipeline import (
    _apply_spread_carry_signals,
    _avg_recent_trade_return_annual,
    _avg_recent_trade_return_annual_operational,
    _execution_quality_stats,
)
from moex_carry.signal_replay.core import (
    ReplayMetrics,
    ReplayResult,
    _normalize_series_base,
    apply_day_cutoff,
)

INCREMENTAL_ENGINE_VERSION = "incremental-replay-v1"
CHECKPOINT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ReplayMutation:
    changed: bool
    append_only: bool
    earliest_changed_exec_ts: datetime | None
    watermark_before: str | None
    watermark_after: str | None


@dataclass
class ReplayRuntimeState:
    pending_entry: dict[str, Any] | None = None
    pending_exit: dict[str, Any] | None = None
    open_position: dict[str, Any] | None = None
    current_cycle: int = 0
    spread_history: list[float] = field(default_factory=list)
    last_processed_exec_ts: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "pending_entry": _serialize_mapping(self.pending_entry),
            "pending_exit": _serialize_mapping(self.pending_exit),
            "open_position": _serialize_mapping(self.open_position),
            "current_cycle": int(self.current_cycle),
            "spread_history": [float(item) for item in self.spread_history[-2048:]],
            "last_processed_exec_ts": _iso_or_none(self.last_processed_exec_ts),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "ReplayRuntimeState":
        source = payload if isinstance(payload, dict) else {}
        return cls(
            pending_entry=_restore_mapping(source.get("pending_entry")),
            pending_exit=_restore_mapping(source.get("pending_exit")),
            open_position=_restore_mapping(source.get("open_position")),
            current_cycle=_safe_int(source.get("current_cycle"), default=0),
            spread_history=_restore_spread_history(source.get("spread_history")),
            last_processed_exec_ts=_as_utc_naive_datetime(source.get("last_processed_exec_ts")),
        )

    @property
    def has_pending_signal(self) -> bool:
        return self.pending_entry is not None or self.pending_exit is not None


@dataclass
class ReplayAccumulators:
    rows_total: int = 0
    rows_reused: int = 0
    rows_recomputed: int = 0


@dataclass
class ReplayCheckpoint:
    schema_version: int
    engine_version: str
    engine_signature: str
    pair_id: str
    created_at: datetime
    last_processed_exec_ts: datetime | None
    runtime_state: ReplayRuntimeState
    source_watermark_before: str | None
    source_watermark_after: str | None
    output_path: str
    output_format: str
    last_periodic_checkpoint_ts: datetime | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "engine_version": self.engine_version,
            "engine_signature": self.engine_signature,
            "pair_id": self.pair_id,
            "created_at": _iso_or_none(self.created_at),
            "last_processed_exec_ts": _iso_or_none(self.last_processed_exec_ts),
            "runtime_state": self.runtime_state.to_payload(),
            "source_watermark_before": self.source_watermark_before,
            "source_watermark_after": self.source_watermark_after,
            "output_path": self.output_path,
            "output_format": self.output_format,
            "last_periodic_checkpoint_ts": _iso_or_none(self.last_periodic_checkpoint_ts),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ReplayCheckpoint":
        return cls(
            schema_version=_safe_int(payload.get("schema_version"), default=-1),
            engine_version=str(payload.get("engine_version") or ""),
            engine_signature=str(payload.get("engine_signature") or ""),
            pair_id=str(payload.get("pair_id") or ""),
            created_at=_as_utc_naive_datetime(payload.get("created_at")) or datetime.now(timezone.utc).replace(
                tzinfo=None
            ),
            last_processed_exec_ts=_as_utc_naive_datetime(payload.get("last_processed_exec_ts")),
            runtime_state=ReplayRuntimeState.from_payload(payload.get("runtime_state")),
            source_watermark_before=_as_optional_text(payload.get("source_watermark_before")),
            source_watermark_after=_as_optional_text(payload.get("source_watermark_after")),
            output_path=str(payload.get("output_path") or ""),
            output_format=str(payload.get("output_format") or "unknown"),
            last_periodic_checkpoint_ts=_as_utc_naive_datetime(payload.get("last_periodic_checkpoint_ts")),
        )


@dataclass
class IncrementalReplayOutcome:
    replay_result: ReplayResult
    mode: str
    recomputed: bool
    fallback_reason: str | None
    skip_reason: str | None
    output_path: Path
    latest_checkpoint_path: Path
    periodic_checkpoint_path: Path | None
    runtime_state: ReplayRuntimeState
    accumulators: ReplayAccumulators


def run_true_incremental_replay(
    *,
    pair_id: str,
    pair: PairSpec,
    series_base: pd.DataFrame,
    settings: AppSettings,
    dividends: list[DividendEvent],
    key_rates: list[KeyRate],
    mutation: ReplayMutation,
    checkpoint_root: Path,
    output_root: Path,
    overlap_minutes: int,
    checkpoint_interval_minutes: int,
    force_full: bool = False,
) -> IncrementalReplayOutcome:
    cutoff_minutes = max(int(getattr(settings.spread_carry_alpha, "signal_cutoff_before_day_end_minutes", 0) or 0), 0)
    normalized = _normalize_series_base(series_base)
    series = apply_day_cutoff(normalized, cutoff_minutes)
    if not series.empty:
        series = series.copy()
        series["exec_ts"] = pd.to_datetime(series["exec_ts"], errors="coerce")
        series["date"] = pd.to_datetime(series["date"], errors="coerce").dt.date
        series = series.dropna(subset=["exec_ts", "date"]).sort_values(["date", "exec_ts"]).reset_index(drop=True)

    safe_pair_id = _safe_pair_id(pair_id)
    pair_state_dir = checkpoint_root / safe_pair_id
    latest_path = pair_state_dir / "latest.json"
    checkpoints_dir = pair_state_dir / "checkpoints"
    output_path = output_root / f"{safe_pair_id}.parquet"
    pair_state_dir.mkdir(parents=True, exist_ok=True)
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    future_spec = _future_spec_from_pair(pair, series)
    engine_signature = _engine_signature(settings=settings, future_spec=future_spec)
    existing_output = _load_replay_output(output_path)
    latest = _load_checkpoint(latest_path)

    if not mutation.changed and latest is not None and mutation.watermark_after == latest.source_watermark_after:
        reused = existing_output if existing_output is not None else pd.DataFrame()
        result = _build_result_from_frame(reused, cutoff_minutes=cutoff_minutes)
        return IncrementalReplayOutcome(
            replay_result=result,
            mode="reuse",
            recomputed=False,
            fallback_reason=None,
            skip_reason="no_data_change",
            output_path=output_path,
            latest_checkpoint_path=latest_path,
            periodic_checkpoint_path=None,
            runtime_state=latest.runtime_state if latest is not None else ReplayRuntimeState(),
            accumulators=ReplayAccumulators(
                rows_total=int(len(reused)),
                rows_reused=int(len(reused)),
                rows_recomputed=0,
            ),
        )

    fallback_reason: str | None = None
    run_mode = "full"
    initial_state = ReplayRuntimeState()
    base_prefix = pd.DataFrame()
    periodic_checkpoint: Path | None = None

    if not force_full and latest is not None:
        if latest.schema_version != CHECKPOINT_SCHEMA_VERSION:
            fallback_reason = "checkpoint_schema_mismatch"
        elif latest.engine_signature != engine_signature:
            fallback_reason = "engine_signature_mismatch"
        else:
            if mutation.append_only and latest.last_processed_exec_ts is not None and not latest.runtime_state.has_pending_signal:
                run_mode = "append_only"
                initial_state = latest.runtime_state
                if existing_output is not None and not existing_output.empty:
                    cutoff_ts = latest.last_processed_exec_ts
                    base_prefix = existing_output[
                        pd.to_datetime(existing_output["exec_ts"], errors="coerce") <= cutoff_ts
                    ].copy()
            else:
                if latest.last_processed_exec_ts is None:
                    fallback_reason = "missing_last_processed_exec_ts"
                else:
                    replay_start_ts = latest.last_processed_exec_ts - timedelta(minutes=max(int(overlap_minutes), 1))
                    if (
                        mutation.earliest_changed_exec_ts is not None
                        and mutation.earliest_changed_exec_ts < replay_start_ts
                    ):
                        fallback_reason = "retro_outside_overlap"
                    else:
                        checkpoint = _load_nearest_checkpoint(checkpoints_dir, replay_start_ts)
                        if checkpoint is None:
                            fallback_reason = "missing_overlap_checkpoint"
                        else:
                            run_mode = "overlap_replay"
                            initial_state = checkpoint.runtime_state
                            if existing_output is not None and not existing_output.empty and checkpoint.last_processed_exec_ts is not None:
                                cutoff_ts = checkpoint.last_processed_exec_ts
                                base_prefix = existing_output[
                                    pd.to_datetime(existing_output["exec_ts"], errors="coerce") <= cutoff_ts
                                ].copy()

    if force_full:
        run_mode = "full"
        fallback_reason = None
        initial_state = ReplayRuntimeState()
        base_prefix = pd.DataFrame()
    elif fallback_reason is not None:
        run_mode = "full"
        initial_state = ReplayRuntimeState()
        base_prefix = pd.DataFrame()

    if not force_full and not _supports_stateful_replay() and run_mode != "full":
        run_mode = "full"
        fallback_reason = "stateful_replay_unavailable"
        initial_state = ReplayRuntimeState()
        base_prefix = pd.DataFrame()

    tail_start_ts = initial_state.last_processed_exec_ts
    if tail_start_ts is None or run_mode == "full":
        tail = series.copy()
    else:
        tail = series[pd.to_datetime(series["exec_ts"], errors="coerce") > tail_start_ts].copy()

    if tail.empty and not base_prefix.empty:
        merged_frame = base_prefix.reset_index(drop=True)
        output_format = _write_replay_output_atomic(merged_frame, output_path)
        latest_checkpoint = ReplayCheckpoint(
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            engine_version=INCREMENTAL_ENGINE_VERSION,
            engine_signature=engine_signature,
            pair_id=pair_id,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            last_processed_exec_ts=initial_state.last_processed_exec_ts,
            runtime_state=initial_state,
            source_watermark_before=mutation.watermark_before,
            source_watermark_after=mutation.watermark_after,
            output_path=str(output_path).replace("\\", "/"),
            output_format=output_format,
            last_periodic_checkpoint_ts=latest.last_periodic_checkpoint_ts if latest is not None else None,
        )
        _write_checkpoint_atomic(latest_path, latest_checkpoint)
        result = _build_result_from_frame(merged_frame, cutoff_minutes=cutoff_minutes)
        return IncrementalReplayOutcome(
            replay_result=result,
            mode=run_mode,
            recomputed=False,
            fallback_reason=fallback_reason,
            skip_reason="tail_empty",
            output_path=output_path,
            latest_checkpoint_path=latest_path,
            periodic_checkpoint_path=None,
            runtime_state=initial_state,
            accumulators=ReplayAccumulators(
                rows_total=int(len(merged_frame)),
                rows_reused=int(len(merged_frame)),
                rows_recomputed=0,
            ),
        )

    if _supports_stateful_replay():
        initial_payload = initial_state.to_payload()
        replay_tail_result = _apply_spread_carry_signals(
            tail,
            merged=None,
            dividends=dividends,
            key_rates=key_rates,
            settings=settings,
            future_spec=future_spec,
            alpha_cfg=settings.spread_carry_alpha,
            initial_state=initial_payload,
            return_state=True,
        )
        if not isinstance(replay_tail_result, tuple):
            raise RuntimeError("incremental_replay_state_unavailable")
        replay_tail, final_state_payload = replay_tail_result
        final_state = ReplayRuntimeState.from_payload(final_state_payload)
    else:
        replay_tail = _apply_spread_carry_signals(
            tail,
            merged=None,
            dividends=dividends,
            key_rates=key_rates,
            settings=settings,
            future_spec=future_spec,
            alpha_cfg=settings.spread_carry_alpha,
        )
        final_state = _runtime_state_from_replay_tail(replay_tail)

    if base_prefix.empty:
        merged_frame = replay_tail.reset_index(drop=True)
    else:
        merged_frame = pd.concat([base_prefix, replay_tail], ignore_index=True)
        merged_frame = merged_frame.sort_values(["date", "exec_ts"]).reset_index(drop=True)
        if "exec_ts" in merged_frame.columns:
            merged_frame = merged_frame.drop_duplicates(subset=["exec_ts"], keep="last")

    output_format = _write_replay_output_atomic(merged_frame, output_path)
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    latest_checkpoint = ReplayCheckpoint(
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        engine_version=INCREMENTAL_ENGINE_VERSION,
        engine_signature=engine_signature,
        pair_id=pair_id,
        created_at=now_naive,
        last_processed_exec_ts=final_state.last_processed_exec_ts,
        runtime_state=final_state,
        source_watermark_before=mutation.watermark_before,
        source_watermark_after=mutation.watermark_after,
        output_path=str(output_path).replace("\\", "/"),
        output_format=output_format,
        last_periodic_checkpoint_ts=latest.last_periodic_checkpoint_ts if latest is not None else None,
    )

    if _should_emit_periodic_checkpoint(
        latest_checkpoint=latest_checkpoint,
        interval_minutes=max(int(checkpoint_interval_minutes), 1),
    ):
        periodic_checkpoint = _checkpoint_file_path(
            checkpoints_dir,
            latest_checkpoint.last_processed_exec_ts or now_naive,
        )
        _write_checkpoint_atomic(periodic_checkpoint, latest_checkpoint)
        latest_checkpoint.last_periodic_checkpoint_ts = latest_checkpoint.last_processed_exec_ts or now_naive
    _write_checkpoint_atomic(latest_path, latest_checkpoint)

    result = _build_result_from_frame(merged_frame, cutoff_minutes=cutoff_minutes)
    return IncrementalReplayOutcome(
        replay_result=result,
        mode=run_mode,
        recomputed=True,
        fallback_reason=fallback_reason,
        skip_reason=None,
        output_path=output_path,
        latest_checkpoint_path=latest_path,
        periodic_checkpoint_path=periodic_checkpoint,
        runtime_state=final_state,
        accumulators=ReplayAccumulators(
            rows_total=int(len(merged_frame)),
            rows_reused=max(int(len(base_prefix)), 0),
            rows_recomputed=int(len(replay_tail)),
        ),
    )


def _build_result_from_frame(frame: pd.DataFrame, *, cutoff_minutes: int) -> ReplayResult:
    replay = frame.reset_index(drop=True) if frame is not None else pd.DataFrame()
    metrics = _collect_metrics(replay)
    return ReplayResult(replay=replay, metrics=metrics, cutoff_minutes=cutoff_minutes)


def _collect_metrics(replay: pd.DataFrame) -> ReplayMetrics:
    action = (
        replay["signal_action"].astype(str).str.lower()
        if "signal_action" in replay.columns
        else pd.Series([], dtype="string")
    )
    entry_signals = int((action == "enter").sum())
    exit_signals = int((action == "exit").sum())
    exit_mask = (
        replay["exit_flag"].fillna(False).astype(bool)
        if "exit_flag" in replay.columns
        else pd.Series(False, index=replay.index)
    )
    closed_mask = exit_mask & replay["trade_return_annual_operational"].notna()
    trades_closed = int(closed_mask.sum())
    stats = _execution_quality_stats(replay)
    avg_fill = _avg_recent_trade_return_annual(replay)
    avg_oper = _avg_recent_trade_return_annual_operational(replay)
    entry_wait = (
        replay.loc[closed_mask, "entry_wait_minutes"].dropna()
        if "entry_wait_minutes" in replay.columns
        else pd.Series(dtype=float)
    )
    exit_wait = (
        replay.loc[closed_mask, "exit_wait_minutes"].dropna()
        if "exit_wait_minutes" in replay.columns
        else pd.Series(dtype=float)
    )
    return ReplayMetrics(
        rows=int(len(replay)),
        days=int(pd.Series(replay["date"]).nunique()) if "date" in replay.columns else 0,
        entry_signals=entry_signals,
        exit_signals=exit_signals,
        trades_closed=trades_closed,
        avg_trade_return_annual_fill_to_fill_last5=avg_fill,
        avg_trade_return_annual_operational_last5=avg_oper,
        share_target_pass=stats.get("share_target_pass"),
        unfilled_entry_rate=stats.get("unfilled_entry_rate"),
        unfilled_exit_rate=stats.get("unfilled_exit_rate"),
        forced_exit_rate=stats.get("forced_exit_rate"),
        avg_entry_wait_min_closed=float(entry_wait.mean()) if not entry_wait.empty else None,
        avg_exit_wait_min_closed=float(exit_wait.mean()) if not exit_wait.empty else None,
        error=None,
    )


def _safe_pair_id(pair_id: str) -> str:
    text = str(pair_id or "").strip()
    if not text:
        return "unknown_pair"
    out = text.replace("\\", "_").replace("/", "_").replace("|", "__").replace(":", "_")
    return out


def _future_spec_from_pair(pair: PairSpec, series: pd.DataFrame) -> ContractSpec:
    expiry = pair.expiry
    if expiry is None and not series.empty:
        expiry = max(pd.to_datetime(series["date"], errors="coerce").dt.date.dropna())
    if expiry is None:
        expiry = datetime.now(timezone.utc).date()
    return ContractSpec(
        secid=pair.future_secid,
        asset_code=pair.stock_secid,
        expiry=expiry,
        lot_size=float(pair.lot_size or 1.0),
        price_step=float(pair.tick_size or 0.01),
        multiplier=float(pair.multiplier or 1.0),
    )


def _engine_signature(*, settings: AppSettings, future_spec: ContractSpec) -> str:
    payload = {
        "engine_version": INCREMENTAL_ENGINE_VERSION,
        "alpha": settings.spread_carry_alpha.model_dump(mode="python"),
        "costs": settings.costs.model_dump(mode="python"),
        "future_spec": {
            "secid": future_spec.secid,
            "asset_code": future_spec.asset_code,
            "expiry": future_spec.expiry.isoformat(),
            "lot_size": float(future_spec.lot_size),
            "price_step": float(future_spec.price_step),
            "multiplier": float(future_spec.multiplier),
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        normalized = value.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        normalized = value
    return normalized.isoformat(timespec="seconds")


def _as_utc_naive_datetime(value: object) -> datetime | None:
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


def _serialize_mapping(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    payload: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, datetime):
            payload[key] = _iso_or_none(item)
        elif isinstance(item, date):
            payload[key] = item.isoformat()
        else:
            payload[key] = item
    return payload


def _restore_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    restored: dict[str, Any] = {}
    for key, item in value.items():
        if key.endswith("_ts"):
            parsed = _as_utc_naive_datetime(item)
            restored[key] = parsed if parsed is not None else item
        elif key.endswith("_day"):
            day = pd.to_datetime(item, errors="coerce")
            restored[key] = day.date() if not pd.isna(day) else item
        else:
            restored[key] = item
    return restored


def _restore_spread_history(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    out: list[float] = []
    for item in value[-2048:]:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _as_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _supports_stateful_replay() -> bool:
    try:
        params = inspect.signature(_apply_spread_carry_signals).parameters
    except (TypeError, ValueError):
        return False
    return "initial_state" in params and "return_state" in params


def _runtime_state_from_replay_tail(replay_tail: pd.DataFrame) -> ReplayRuntimeState:
    if replay_tail is None or replay_tail.empty:
        return ReplayRuntimeState()
    last_processed_exec_ts = _as_utc_naive_datetime(replay_tail["exec_ts"].iloc[-1]) if "exec_ts" in replay_tail.columns else None
    current_cycle = 0
    if "cycle_id" in replay_tail.columns:
        cycle = pd.to_numeric(replay_tail["cycle_id"], errors="coerce")
        if cycle.notna().any():
            current_cycle = int(cycle.max())
    return ReplayRuntimeState(
        pending_entry=None,
        pending_exit=None,
        open_position=None,
        current_cycle=current_cycle,
        spread_history=[],
        last_processed_exec_ts=last_processed_exec_ts,
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def _write_checkpoint_atomic(path: Path, checkpoint: ReplayCheckpoint) -> None:
    _atomic_write_text(path, json.dumps(checkpoint.to_payload(), ensure_ascii=False, sort_keys=True, indent=2))


def _load_checkpoint(path: Path) -> ReplayCheckpoint | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return ReplayCheckpoint.from_payload(payload)
    except Exception:
        return None


def _checkpoint_file_path(checkpoints_dir: Path, ts: datetime) -> Path:
    stamp = ts.strftime("%Y%m%dT%H%M%S")
    return checkpoints_dir / f"{stamp}.json"


def _load_nearest_checkpoint(checkpoints_dir: Path, replay_start_ts: datetime) -> ReplayCheckpoint | None:
    if not checkpoints_dir.exists():
        return None
    candidates: list[tuple[datetime, Path]] = []
    for path in checkpoints_dir.glob("*.json"):
        stem = path.stem
        parsed = pd.to_datetime(stem, format="%Y%m%dT%H%M%S", errors="coerce")
        if pd.isna(parsed):
            continue
        ts = parsed.to_pydatetime().replace(tzinfo=None)
        if ts <= replay_start_ts:
            candidates.append((ts, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    for _, path in candidates:
        checkpoint = _load_checkpoint(path)
        if checkpoint is not None:
            return checkpoint
    return None


def _should_emit_periodic_checkpoint(*, latest_checkpoint: ReplayCheckpoint, interval_minutes: int) -> bool:
    if latest_checkpoint.runtime_state.has_pending_signal:
        return False
    current_ts = latest_checkpoint.last_processed_exec_ts
    if current_ts is None:
        return False
    previous_ts = latest_checkpoint.last_periodic_checkpoint_ts
    if previous_ts is None:
        return True
    delta_minutes = (current_ts - previous_ts).total_seconds() / 60.0
    return delta_minutes >= float(max(interval_minutes, 1))


def _load_replay_output(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        frame = pd.read_parquet(path)
    except Exception:
        try:
            frame = pd.read_pickle(path)
        except Exception:
            return None
    if not isinstance(frame, pd.DataFrame):
        return None
    return frame


def _write_replay_output_atomic(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        frame.to_parquet(tmp_path, index=False)
        output_format = "parquet"
    except Exception:
        frame.to_pickle(tmp_path)
        output_format = "pickle"
    os.replace(tmp_path, path)
    return output_format
