import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from moex_carry.news_mode_compare import CompareConfig, compare_modes
from moex_carry.shock_episodes import ShockEpisodeConfig, run_shock_episode_analysis


def _parse_ts(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid timestamp: {value}")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze primary shocks and aftershocks with mode capture metrics.")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--start-ts", type=str, default=None)
    parser.add_argument("--end-ts", type=str, default=None)

    parser.add_argument("--max-delay-min", type=float, default=60.0)
    parser.add_argument("--broad-min-relevance", type=float, default=1.0)
    parser.add_argument("--v2-min-relevance", type=float, default=0.4)

    parser.add_argument("--primary-z", type=float, default=2.5)
    parser.add_argument("--aftershock-z", type=float, default=2.0)
    parser.add_argument("--episode-window-min", type=int, default=360)
    parser.add_argument("--max-gap-min", type=int, default=120)
    parser.add_argument("--same-direction-aftershock-only", action="store_true")
    args = parser.parse_args()

    if not args.input_csv.exists():
        raise SystemExit(f"Input file not found: {args.input_csv}")
    if args.output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output_dir = Path("data/output") / f"shock_episode_analysis_{stamp}"

    df = pd.read_csv(args.input_csv)
    df["shock_ts_dt"] = pd.to_datetime(df["shock_ts"], utc=True, errors="coerce")
    start_ts = _parse_ts(args.start_ts)
    end_ts = _parse_ts(args.end_ts)
    if start_ts is not None:
        df = df[df["shock_ts_dt"] >= start_ts]
    if end_ts is not None:
        df = df[df["shock_ts_dt"] <= end_ts]
    if df.empty:
        raise SystemExit("No rows after date filtering.")

    compare_cfg = CompareConfig(
        max_delay_minutes=args.max_delay_min,
        broad_min_relevance=args.broad_min_relevance,
        v2_min_relevance=args.v2_min_relevance,
    )
    detail_df, _, _ = compare_modes(df.drop(columns=["shock_ts_dt"]), compare_cfg)

    episode_cfg = ShockEpisodeConfig(
        primary_z_threshold=args.primary_z,
        aftershock_z_threshold=args.aftershock_z,
        episode_window_minutes=args.episode_window_min,
        max_gap_minutes=args.max_gap_min,
        same_direction_aftershock_required=args.same_direction_aftershock_only,
    )
    outputs = run_shock_episode_analysis(
        detail_df=detail_df,
        output_dir=args.output_dir,
        config=episode_cfg,
        min_delay_minutes=0.0,
        max_delay_minutes=args.max_delay_min,
    )

    capture = pd.read_csv(outputs["capture"])
    all_primary = capture[(capture["symbol"] == "ALL") & (capture["role"] == "primary")]
    all_after = capture[(capture["symbol"] == "ALL") & (capture["role"] == "aftershock")]

    print("Shock episode analysis")
    if start_ts is not None or end_ts is not None:
        print(f"window: {start_ts if start_ts is not None else '-inf'} -> {end_ts if end_ts is not None else '+inf'}")
    for mode in ("current", "proposed"):
        p = all_primary[all_primary["mode"] == mode]
        a = all_after[all_after["mode"] == mode]
        if p.empty or a.empty:
            continue
        p0 = p.iloc[0]
        a0 = a.iloc[0]
        print(
            f"{mode}: primary_caught={int(p0['caught_events'])}/{int(p0['total_events'])} "
            f"(recall={p0['recall']:.3f}); aftershock_caught={int(a0['caught_events'])}/{int(a0['total_events'])} "
            f"(recall={a0['recall']:.3f})"
        )

    print("\nArtifacts:")
    for key, path in outputs.items():
        print(f"- {key}: {path}")


if __name__ == "__main__":
    main()
