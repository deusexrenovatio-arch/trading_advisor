from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

import pandas as pd

from moex_carry.domain.portfolio import (
    PairSpec,
    SnapshotPerPair,
    SnapshotPerPairAlpha,
    SnapshotPerPairEvents,
    SnapshotPerPairLq,
    SnapshotPerPairScores,
)

MinuteEventType = Literal[
    "entry_filled",
    "entry_unfilled",
    "exit_filled",
    "exit_forced",
    "exit_unfilled",
]


@dataclass(frozen=True)
class MinuteDayEvent:
    pair_id: str
    day: date
    ts: datetime
    event_type: MinuteEventType
    signal_action: str
    trade_cycle: int | None
    trade_pnl_cash: float | None
    trade_return_pct_net: float | None
    entry_wait_minutes: float | None
    exit_wait_minutes: float | None
    unfilled_reason: str | None


@dataclass(frozen=True)
class MinutePairTape:
    pair: PairSpec
    snapshots_by_day: dict[date, SnapshotPerPair]
    events_by_day: dict[date, list[MinuteDayEvent]]


def _pair_id(pair: PairSpec) -> str:
    return f"{pair.stock_secid}|{pair.future_secid}"


def _to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    if isinstance(ts, pd.Timestamp):
        return ts.to_pydatetime()
    return ts


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _to_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return default
    return float(num)


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "t"}:
        return True
    if text in {"0", "false", "no", "n", "f", ""}:
        return False
    return default


def _row_score_components(row: pd.Series) -> tuple[float, float, float]:
    score_floor_raw = _to_float(row.get("score_floor"))
    score_alpha_raw = _to_float(row.get("score_alpha"))
    total_score_raw = _to_float(row.get("total_score"))
    floor_rate = _to_float(row.get("floor_rate_annual"), 0.0) or 0.0
    zscore = _to_float(row.get("zscore"), 0.0) or 0.0
    tp_net = _to_float(row.get("tp_net"), 0.0) or 0.0
    sl_net = _to_float(row.get("sl_net"), 0.0) or 0.0

    score_floor = score_floor_raw if score_floor_raw is not None else floor_rate
    score_alpha = score_alpha_raw if score_alpha_raw is not None else (tp_net - sl_net - abs(zscore) * 0.001)
    total_score = total_score_raw if total_score_raw is not None else (0.5 * score_floor + 0.5 * score_alpha)
    return float(score_floor), float(score_alpha), float(total_score)


def _snapshot_from_row(*, pair: PairSpec, row: pd.Series, day: date) -> SnapshotPerPair:
    exec_ts = _to_datetime(row.get("exec_ts")) or datetime.combine(day, datetime.min.time())
    floor_pass = _to_bool(row.get("floor_pass"), default=False)
    liq_pass = _to_bool(row.get("liquidity_pass"), default=False)
    score_floor, score_alpha, total_score = _row_score_components(row)
    dte = None
    if pair.expiry is not None:
        dte = int((pair.expiry - day).days)

    spot_mid = _to_float(row.get("spot_mid"))
    future_mid = _to_float(row.get("future_mid"))
    spread_mid = _to_float(row.get("spread_mid"))
    spread_pct = _to_float(row.get("spread_pct"))
    if spread_mid is None and spot_mid is not None and future_mid is not None:
        spread_mid = float(spot_mid - future_mid)
    if spread_pct is None and spread_mid is not None and spot_mid and spot_mid != 0.0:
        spread_pct = float(spread_mid / spot_mid)

    return SnapshotPerPair(
        as_of=exec_ts,
        stock_secid=pair.stock_secid,
        future_secid=pair.future_secid,
        expiry=pair.expiry,
        spot_mid=spot_mid,
        future_mid=future_mid,
        spread_mid=spread_mid,
        spread_pct=spread_pct,
        spread_entry_exec_pct=_to_float(row.get("entry_spread_pct_exec")),
        spread_exit_exec_pct=_to_float(row.get("exit_spread_pct_exec")),
        rtc_pct=_to_float(row.get("rtc_pct")),
        floor_rate_annual=_to_float(row.get("floor_rate_annual")),
        floor_pass=floor_pass,
        decision=str(row.get("signal_action") or "hold"),
        dte=dte,
        lq=SnapshotPerPairLq(
            liquidity_pass=liq_pass,
            dollar_vol_stock=_to_float(row.get("spot_volume")) * (spot_mid or 0.0),
            dollar_vol_fut=_to_float(row.get("future_volume")) * (future_mid or 0.0),
        ),
        alpha=SnapshotPerPairAlpha(
            zscore=_to_float(row.get("zscore")),
            tp_net=_to_float(row.get("tp_net")),
            sl_net=_to_float(row.get("sl_net")),
        ),
        scores=SnapshotPerPairScores(
            score_floor=score_floor,
            score_alpha=score_alpha,
            total_score=total_score,
        ),
        events=SnapshotPerPairEvents(warnings=[]),
        metadata={
            "signal_action": str(row.get("signal_action") or "hold").lower(),
            "entry_fill_status": str(row.get("entry_fill_status") or ""),
            "exit_fill_status": str(row.get("exit_fill_status") or ""),
        },
    )


def _event_from_row(*, pair_id: str, day: date, row: pd.Series) -> list[MinuteDayEvent]:
    events: list[MinuteDayEvent] = []
    action = str(row.get("signal_action") or "hold").strip().lower()
    trade_cycle = _to_float(row.get("trade_cycle"))
    cycle_value = int(trade_cycle) if trade_cycle is not None else None

    def _build(
        *,
        event_type: MinuteEventType,
        ts: datetime | None,
        trade_pnl_cash: float | None = None,
        trade_return_pct_net: float | None = None,
        entry_wait_minutes: float | None = None,
        exit_wait_minutes: float | None = None,
        reason: str | None = None,
    ) -> MinuteDayEvent:
        pnl_value = trade_pnl_cash if trade_pnl_cash is not None else _to_float(row.get("trade_pnl_cash"))
        ret_value = (
            trade_return_pct_net if trade_return_pct_net is not None else _to_float(row.get("trade_return_pct_net"))
        )
        entry_wait_value = (
            entry_wait_minutes if entry_wait_minutes is not None else _to_float(row.get("entry_wait_minutes"))
        )
        exit_wait_value = exit_wait_minutes if exit_wait_minutes is not None else _to_float(row.get("exit_wait_minutes"))
        return MinuteDayEvent(
            pair_id=pair_id,
            day=day,
            ts=ts or datetime.combine(day, datetime.min.time()),
            event_type=event_type,
            signal_action=action,
            trade_cycle=cycle_value,
            trade_pnl_cash=pnl_value,
            trade_return_pct_net=ret_value,
            entry_wait_minutes=entry_wait_value,
            exit_wait_minutes=exit_wait_value,
            unfilled_reason=reason,
        )

    entry_status = str(row.get("entry_fill_status") or "").strip().lower()
    exit_status = str(row.get("exit_fill_status") or "").strip().lower()
    exit_forced = _to_bool(row.get("exit_forced"), default=False)
    unfilled_reason = str(row.get("unfilled_reason") or "").strip() or None

    # Entry/exit fill statuses are causal execution facts and may arrive on hold rows
    # when signal submission happened earlier (lag + wait window). Event extraction
    # therefore must rely on status columns, not only on signal_action.
    if entry_status == "filled":
        ts = _to_datetime(row.get("entry_fill_ts")) or _to_datetime(row.get("exec_ts"))
        events.append(_build(event_type="entry_filled", ts=ts))
    elif entry_status.startswith("entry_unfilled"):
        ts = _to_datetime(row.get("entry_submit_ts")) or _to_datetime(row.get("exec_ts"))
        events.append(_build(event_type="entry_unfilled", ts=ts, reason=unfilled_reason))

    if exit_status in {"filled", "forced"}:
        ts = _to_datetime(row.get("exit_fill_ts")) or _to_datetime(row.get("exec_ts"))
        event_type: MinuteEventType = "exit_forced" if exit_status == "forced" or exit_forced else "exit_filled"
        events.append(_build(event_type=event_type, ts=ts))
    elif exit_status.startswith("exit_unfilled"):
        ts = _to_datetime(row.get("exit_submit_ts")) or _to_datetime(row.get("exec_ts"))
        events.append(_build(event_type="exit_unfilled", ts=ts, reason=unfilled_reason))
    return events


def _closed_trade_payloads(
    work: pd.DataFrame,
) -> tuple[dict[int, dict[str, float | None]], dict[datetime, dict[str, float | None]]]:
    closed_by_cycle: dict[int, dict[str, float | None]] = {}
    closed_by_fill_ts: dict[datetime, dict[str, float | None]] = {}
    if "trade_cycle" not in work.columns:
        return closed_by_cycle, closed_by_fill_ts
    if "exit_flag" not in work.columns:
        return closed_by_cycle, closed_by_fill_ts
    exit_mask = work["exit_flag"].fillna(False).astype(bool)
    if not exit_mask.any():
        return closed_by_cycle, closed_by_fill_ts
    closed_rows = work.loc[exit_mask]
    for _, row in closed_rows.iterrows():
        payload = {
            "trade_pnl_cash": _to_float(row.get("trade_pnl_cash")),
            "trade_return_pct_net": _to_float(row.get("trade_return_pct_net")),
            "entry_wait_minutes": _to_float(row.get("entry_wait_minutes")),
            "exit_wait_minutes": _to_float(row.get("exit_wait_minutes")),
        }
        cycle = _to_float(row.get("trade_cycle"))
        if cycle is not None:
            closed_by_cycle[int(cycle)] = payload
        fill_ts = _to_datetime(row.get("exec_ts")) or _to_datetime(row.get("exit_fill_ts"))
        if fill_ts is not None:
            closed_by_fill_ts[fill_ts] = payload
    return closed_by_cycle, closed_by_fill_ts


def build_minute_pair_tape(*, replay: pd.DataFrame, pair: PairSpec) -> MinutePairTape:
    if replay.empty:
        return MinutePairTape(pair=pair, snapshots_by_day={}, events_by_day={})

    work = replay.copy()
    if "date" not in work.columns and "exec_ts" in work.columns:
        work["date"] = pd.to_datetime(work["exec_ts"], errors="coerce").dt.date
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.date
    work["exec_ts"] = pd.to_datetime(work.get("exec_ts"), errors="coerce")
    work = work.dropna(subset=["date", "exec_ts"]).sort_values(["date", "exec_ts"]).reset_index(drop=True)
    if work.empty:
        return MinutePairTape(pair=pair, snapshots_by_day={}, events_by_day={})

    pair_id = _pair_id(pair)
    closed_by_cycle, closed_by_fill_ts = _closed_trade_payloads(work)
    snapshots_by_day: dict[date, SnapshotPerPair] = {}
    events_by_day: dict[date, list[MinuteDayEvent]] = {}
    for day, day_frame in work.groupby("date", sort=True):
        last_row = day_frame.iloc[-1]
        snapshots_by_day[day] = _snapshot_from_row(pair=pair, row=last_row, day=day)

        day_events: list[MinuteDayEvent] = []
        seen_event_keys: set[tuple[str, datetime, int | None, str | None]] = set()
        for _, row in day_frame.iterrows():
            events = _event_from_row(pair_id=pair_id, day=day, row=row)
            if events:
                for idx, event in enumerate(events):
                    if event.event_type not in {"exit_filled", "exit_forced"}:
                        continue
                    payload = None
                    if event.trade_cycle is not None:
                        payload = closed_by_cycle.get(int(event.trade_cycle))
                    if payload is None:
                        payload = closed_by_fill_ts.get(event.ts)
                    if payload is None:
                        continue
                    if event.trade_pnl_cash is None and payload.get("trade_pnl_cash") is None:
                        continue
                    events[idx] = MinuteDayEvent(
                        pair_id=event.pair_id,
                        day=event.day,
                        ts=event.ts,
                        event_type=event.event_type,
                        signal_action=event.signal_action,
                        trade_cycle=event.trade_cycle,
                        trade_pnl_cash=(
                            event.trade_pnl_cash
                            if event.trade_pnl_cash is not None
                            else payload.get("trade_pnl_cash")
                        ),
                        trade_return_pct_net=(
                            event.trade_return_pct_net
                            if event.trade_return_pct_net is not None
                            else payload.get("trade_return_pct_net")
                        ),
                        entry_wait_minutes=(
                            event.entry_wait_minutes
                            if event.entry_wait_minutes is not None
                            else payload.get("entry_wait_minutes")
                        ),
                        exit_wait_minutes=(
                            event.exit_wait_minutes
                            if event.exit_wait_minutes is not None
                            else payload.get("exit_wait_minutes")
                        ),
                        unfilled_reason=event.unfilled_reason,
                    )
            for event in events:
                key = (event.event_type, event.ts, event.trade_cycle, event.unfilled_reason)
                if key in seen_event_keys:
                    continue
                seen_event_keys.add(key)
                day_events.append(event)
        day_events.sort(key=lambda item: item.ts)
        if day_events:
            events_by_day[day] = day_events

    return MinutePairTape(pair=pair, snapshots_by_day=snapshots_by_day, events_by_day=events_by_day)
