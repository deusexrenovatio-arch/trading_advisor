from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ShockEpisodeConfig:
    primary_z_threshold: float = 2.5
    aftershock_z_threshold: float = 2.0
    episode_window_minutes: int = 360
    max_gap_minutes: int = 120
    same_direction_aftershock_required: bool = False
    reversal_primary_starts_new_episode: bool = True


def _to_datetime_utc(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, utc=True, errors="coerce")


def _episode_id(symbol: str, ts: pd.Timestamp, ordinal: int) -> str:
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    return f"{symbol}-ep-{stamp}-{ordinal:04d}"


def build_shock_episodes(
    rows: pd.DataFrame,
    config: ShockEpisodeConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {"symbol", "shock_ts", "z_score", "shock_direction", "abs_move_pct", "logret"}
    missing = required.difference(rows.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = rows.copy()
    df["shock_ts_dt"] = _to_datetime_utc(df["shock_ts"])
    df["z_score"] = pd.to_numeric(df["z_score"], errors="coerce")
    df["abs_move_pct"] = pd.to_numeric(df["abs_move_pct"], errors="coerce")
    df["logret"] = pd.to_numeric(df["logret"], errors="coerce")
    df = df.dropna(subset=["shock_ts_dt", "z_score"]).sort_values(["symbol", "shock_ts_dt"])

    event_rows: list[dict[str, Any]] = []
    episode_rows: list[dict[str, Any]] = []

    for symbol, group in df.groupby("symbol", sort=False):
        active: dict[str, Any] | None = None
        episode_count = 0

        for _, row in group.iterrows():
            ts = row["shock_ts_dt"]
            z = float(abs(row["z_score"]))
            direction = str(row.get("shock_direction") or "").strip().lower() or "unknown"

            if active is not None:
                age_min = (ts - active["primary_ts"]).total_seconds() / 60.0
                gap_min = (ts - active["last_event_ts"]).total_seconds() / 60.0
                if age_min > config.episode_window_minutes or gap_min > config.max_gap_minutes:
                    episode_rows.append(active.copy())
                    active = None

            if z < config.aftershock_z_threshold:
                continue

            start_new = False
            role = "aftershock"
            if active is None:
                start_new = z >= config.primary_z_threshold
                role = "primary"
            else:
                same_direction = direction == str(active["primary_direction"]).lower()
                if (
                    config.reversal_primary_starts_new_episode
                    and z >= config.primary_z_threshold
                    and direction != "unknown"
                    and str(active["primary_direction"]).lower() != "unknown"
                    and not same_direction
                ):
                    episode_rows.append(active.copy())
                    active = None
                    start_new = True
                    role = "primary"
                elif config.same_direction_aftershock_required and not same_direction:
                    if z >= config.primary_z_threshold:
                        episode_rows.append(active.copy())
                        active = None
                        start_new = True
                        role = "primary"
                    else:
                        continue

            if start_new:
                episode_count += 1
                active = {
                    "episode_id": _episode_id(symbol, ts, episode_count),
                    "symbol": symbol,
                    "primary_ts": ts,
                    "primary_direction": direction,
                    "primary_z_score": z,
                    "primary_abs_move_pct": float(row["abs_move_pct"]) if pd.notna(row["abs_move_pct"]) else None,
                    "primary_logret": float(row["logret"]) if pd.notna(row["logret"]) else None,
                    "event_count": 0,
                    "aftershock_count": 0,
                    "last_event_ts": ts,
                    "episode_duration_min": 0.0,
                    "cum_abs_move_pct": 0.0,
                    "cum_signed_logret": 0.0,
                    "max_abs_z_score": z,
                }
                role = "primary"

            if active is None:
                continue

            signed_logret = float(row["logret"]) if pd.notna(row["logret"]) else 0.0
            abs_move = abs(float(row["abs_move_pct"])) if pd.notna(row["abs_move_pct"]) else 0.0
            active["event_count"] += 1
            if role == "aftershock":
                active["aftershock_count"] += 1
            active["last_event_ts"] = ts
            active["episode_duration_min"] = (ts - active["primary_ts"]).total_seconds() / 60.0
            active["cum_abs_move_pct"] += abs_move
            active["cum_signed_logret"] += signed_logret
            active["max_abs_z_score"] = max(active["max_abs_z_score"], z)

            event_rows.append(
                {
                    "episode_id": active["episode_id"],
                    "symbol": symbol,
                    "shock_ts": ts.isoformat().replace("+00:00", "Z"),
                    "role": role,
                    "shock_direction": direction,
                    "z_score_abs": z,
                    "abs_move_pct": float(row["abs_move_pct"]) if pd.notna(row["abs_move_pct"]) else None,
                    "signed_logret": signed_logret,
                    "episode_age_min": active["episode_duration_min"],
                    "episode_event_index": active["event_count"],
                    "episode_cum_abs_move_pct": active["cum_abs_move_pct"],
                    "episode_cum_signed_logret": active["cum_signed_logret"],
                }
            )

        if active is not None:
            episode_rows.append(active.copy())

    events_df = pd.DataFrame(event_rows)
    episodes_df = pd.DataFrame(episode_rows)
    if not episodes_df.empty:
        for ts_col in ("primary_ts", "last_event_ts"):
            episodes_df[ts_col] = pd.to_datetime(episodes_df[ts_col], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return events_df, episodes_df


def summarize_mode_shock_capture(
    detail_df: pd.DataFrame,
    events_df: pd.DataFrame,
    mode: str,
    min_delay_minutes: float = 0.0,
    max_delay_minutes: float = 60.0,
) -> pd.DataFrame:
    matched_col = f"matched_{mode}"
    delay_col = f"delay_min_{mode}"
    if matched_col not in detail_df.columns or delay_col not in detail_df.columns:
        raise ValueError(f"Mode columns not found for '{mode}'")

    base = events_df.copy()
    if base.empty:
        return pd.DataFrame(
            columns=[
                "mode",
                "symbol",
                "role",
                "total_events",
                "caught_events",
                "recall",
                "episodes_total",
                "episodes_with_any_catch",
                "episode_hit_rate",
            ]
        )

    detail = detail_df.copy()
    detail["shock_ts"] = _to_datetime_utc(detail["shock_ts"]).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    detail = detail[["symbol", "shock_ts", matched_col, delay_col]].copy()
    detail["caught"] = (
        (pd.to_numeric(detail[matched_col], errors="coerce").fillna(0).astype(int) == 1)
        & pd.to_numeric(detail[delay_col], errors="coerce").notna()
        & (pd.to_numeric(detail[delay_col], errors="coerce") >= min_delay_minutes)
        & (pd.to_numeric(detail[delay_col], errors="coerce") <= max_delay_minutes)
    )
    merged = base.merge(detail[["symbol", "shock_ts", "caught"]], on=["symbol", "shock_ts"], how="left")
    merged["caught"] = merged["caught"].fillna(False).astype(bool)

    rows: list[dict[str, Any]] = []
    for symbol in sorted(merged["symbol"].dropna().unique().tolist()) + ["ALL"]:
        symbol_subset = merged if symbol == "ALL" else merged[merged["symbol"] == symbol]
        for role in ("primary", "aftershock", "all"):
            subset = symbol_subset if role == "all" else symbol_subset[symbol_subset["role"] == role]
            total_events = int(len(subset))
            caught_events = int(subset["caught"].sum())
            recall = caught_events / total_events if total_events else 0.0

            episode_subset = subset[["episode_id", "caught"]].drop_duplicates(["episode_id", "caught"])
            episodes_total = int(subset["episode_id"].nunique()) if total_events else 0
            episodes_with_any_catch = int(
                episode_subset.groupby("episode_id", as_index=False)["caught"].max()["caught"].sum()
            ) if total_events else 0
            episode_hit_rate = episodes_with_any_catch / episodes_total if episodes_total else 0.0

            rows.append(
                {
                    "mode": mode,
                    "symbol": symbol,
                    "role": role,
                    "total_events": total_events,
                    "caught_events": caught_events,
                    "recall": recall,
                    "episodes_total": episodes_total,
                    "episodes_with_any_catch": episodes_with_any_catch,
                    "episode_hit_rate": episode_hit_rate,
                }
            )
    return pd.DataFrame(rows)


def run_shock_episode_analysis(
    detail_df: pd.DataFrame,
    output_dir: Path,
    config: ShockEpisodeConfig,
    min_delay_minutes: float = 0.0,
    max_delay_minutes: float = 60.0,
) -> dict[str, Path]:
    raw_cols = ["symbol", "shock_ts", "z_score", "shock_direction", "abs_move_pct", "logret"]
    events_df, episodes_df = build_shock_episodes(detail_df[raw_cols], config)
    capture_current = summarize_mode_shock_capture(
        detail_df=detail_df,
        events_df=events_df,
        mode="current",
        min_delay_minutes=min_delay_minutes,
        max_delay_minutes=max_delay_minutes,
    )
    capture_proposed = summarize_mode_shock_capture(
        detail_df=detail_df,
        events_df=events_df,
        mode="proposed",
        min_delay_minutes=min_delay_minutes,
        max_delay_minutes=max_delay_minutes,
    )
    capture_df = pd.concat([capture_current, capture_proposed], ignore_index=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir / "shock_episode_events.csv"
    episodes_path = output_dir / "shock_episodes_summary.csv"
    capture_path = output_dir / "shock_mode_capture.csv"
    events_df.to_csv(events_path, index=False)
    episodes_df.to_csv(episodes_path, index=False)
    capture_df.to_csv(capture_path, index=False)

    return {
        "events": events_path,
        "episodes": episodes_path,
        "capture": capture_path,
    }
