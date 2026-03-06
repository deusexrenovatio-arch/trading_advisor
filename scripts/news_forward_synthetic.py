from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from moex_carry.news_mode_compare import CompareConfig, compare_modes
from moex_carry.news_shock_pipeline import ShockCurationConfig, curate_shock_dataset
from moex_carry.shock_episodes import ShockEpisodeConfig, run_shock_episode_analysis


def _parse_grid(raw: str) -> list[float]:
    values: list[float] = []
    for token in str(raw).split(","):
        token = token.strip()
        if not token:
            continue
        values.append(float(token))
    if not values:
        raise ValueError("Grid is empty.")
    return values


def _to_ts(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid timestamp: {value}")
    return parsed


def _safe_float(value: object, default: float = 0.0) -> float:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return float(default)
    return float(num)


def _safe_int(value: object, default: int = 0) -> int:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return int(default)
    return int(num)


def _event_link_ceiling(df: pd.DataFrame, max_delay_min: float, primary_z: float) -> tuple[int, int, float]:
    if "v2_delay_min" in df.columns:
        v2_delay = pd.to_numeric(df["v2_delay_min"], errors="coerce")
    else:
        v2_delay = pd.Series(float("nan"), index=df.index)
    if "broad_delay_min" in df.columns:
        broad_delay = pd.to_numeric(df["broad_delay_min"], errors="coerce")
    else:
        broad_delay = pd.Series(float("nan"), index=df.index)
    has_v2 = df["v2_event_id"].notna() if "v2_event_id" in df.columns else pd.Series(False, index=df.index)
    has_broad = df["broad_event_id"].notna() if "broad_event_id" in df.columns else pd.Series(False, index=df.index)
    v2_valid = has_v2 & v2_delay.between(0.0, float(max_delay_min), inclusive="both")
    broad_valid = has_broad & broad_delay.between(0.0, float(max_delay_min), inclusive="both")
    linked = v2_valid | broad_valid
    truth_primary = pd.to_numeric(df.get("z_score"), errors="coerce").abs().fillna(0.0) >= float(primary_z)
    linked_rows = int(linked.sum())
    truth_rows = int(truth_primary.sum())
    ceiling = (linked_rows / truth_rows) if truth_rows else 0.0
    return linked_rows, truth_rows, float(ceiling)


def _binary_metrics(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0.0:
        return precision, recall, 0.0
    return precision, recall, 2.0 * precision * recall / (precision + recall)


def _pick_profile(
    calibration_df: pd.DataFrame,
    *,
    broad_grid: list[float],
    v2_grid: list[float],
    max_delay_min: float,
    min_coverage: float,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for broad_min in broad_grid:
        for v2_min in v2_grid:
            cfg = CompareConfig(
                max_delay_minutes=max_delay_min,
                broad_min_relevance=float(broad_min),
                v2_min_relevance=float(v2_min),
            )
            _, summary_df, _ = compare_modes(calibration_df, cfg)
            proposed_all = summary_df[
                (summary_df["mode"] == "proposed")
                & (summary_df["symbol"] == "ALL")
            ]
            if proposed_all.empty:
                continue
            row = proposed_all.iloc[0]
            coverage = _safe_float(row.get("coverage"))
            silver_acc = _safe_float(row.get("silver_direction_acc"))
            labeled_cov = _safe_float(row.get("labeled_coverage"))
            acc_x_cov = _safe_float(row.get("accuracy_x_coverage"))
            candidates.append(
                {
                    "broad_min_relevance": float(broad_min),
                    "v2_min_relevance": float(v2_min),
                    "coverage": coverage,
                    "silver_direction_acc": silver_acc,
                    "labeled_coverage": labeled_cov,
                    "acc_x_cov": acc_x_cov,
                }
            )
    if not candidates:
        return {
            "broad_min_relevance": 1.0,
            "v2_min_relevance": 0.4,
            "coverage": 0.0,
            "silver_direction_acc": 0.0,
            "labeled_coverage": 0.0,
            "acc_x_cov": 0.0,
            "profile_source": "fallback_default",
        }

    table = pd.DataFrame(candidates)
    constrained = table[table["coverage"] >= float(min_coverage)].copy()
    source = "grid_constrained"
    if constrained.empty:
        constrained = table.copy()
        source = "grid_unconstrained"

    chosen = constrained.sort_values(
        ["acc_x_cov", "silver_direction_acc", "coverage"],
        ascending=[False, False, False],
    ).iloc[0]
    out = {key: chosen[key] for key in chosen.index.tolist()}
    out["profile_source"] = source
    return out


def _episode_capture_metric(capture_df: pd.DataFrame, role: str) -> dict[str, Any]:
    row = capture_df[
        (capture_df["mode"] == "proposed")
        & (capture_df["symbol"] == "ALL")
        & (capture_df["role"] == role)
    ]
    if row.empty:
        return {
            "events_total": 0,
            "events_caught": 0,
            "recall": 0.0,
            "episode_hit_rate": 0.0,
        }
    rec = row.iloc[0]
    return {
        "events_total": _safe_int(rec.get("total_events")),
        "events_caught": _safe_int(rec.get("caught_events")),
        "recall": _safe_float(rec.get("recall")),
        "episode_hit_rate": _safe_float(rec.get("episode_hit_rate")),
    }


def _evaluate_window(
    *,
    test_df: pd.DataFrame,
    compare_cfg: CompareConfig,
    episode_cfg: ShockEpisodeConfig,
    max_delay_min: float,
    window_dir: Path,
) -> dict[str, Any]:
    detail_df, summary_df, _ = compare_modes(test_df, compare_cfg)
    window_dir.mkdir(parents=True, exist_ok=True)

    episode_paths = run_shock_episode_analysis(
        detail_df=detail_df,
        output_dir=window_dir / "shock_episodes",
        config=episode_cfg,
        min_delay_minutes=0.0,
        max_delay_minutes=max_delay_min,
    )
    capture_df = pd.read_csv(episode_paths["capture"])
    proposed_all = summary_df[
        (summary_df["mode"] == "proposed")
        & (summary_df["symbol"] == "ALL")
    ]
    summary_row = proposed_all.iloc[0] if not proposed_all.empty else pd.Series(dtype=object)

    z_abs = pd.to_numeric(detail_df["z_score"], errors="coerce").abs().fillna(0.0)
    delay = pd.to_numeric(detail_df["delay_min_proposed"], errors="coerce")
    predicted = (
        (pd.to_numeric(detail_df["matched_proposed"], errors="coerce").fillna(0).astype(int) == 1)
        & delay.notna()
        & (delay >= 0.0)
        & (delay <= float(max_delay_min))
    )
    truth_primary = z_abs >= float(episode_cfg.primary_z_threshold)
    tp = int((predicted & truth_primary).sum())
    fp = int((predicted & ~truth_primary).sum())
    fn = int((~predicted & truth_primary).sum())
    precision, recall, f1 = _binary_metrics(tp, fp, fn)

    primary = _episode_capture_metric(capture_df, "primary")
    aftershock = _episode_capture_metric(capture_df, "aftershock")
    delays = delay[predicted].dropna()

    return {
        "rows_test": int(len(test_df)),
        "coverage": _safe_float(summary_row.get("coverage")),
        "labeled_coverage": _safe_float(summary_row.get("labeled_coverage")),
        "silver_direction_acc": _safe_float(summary_row.get("silver_direction_acc")),
        "acc_x_cov": _safe_float(summary_row.get("accuracy_x_coverage")),
        "matched_shocks": _safe_int(summary_row.get("matched_shocks")),
        "primary_recall_episode": float(primary["recall"]),
        "aftershock_recall_episode": float(aftershock["recall"]),
        "primary_events_total": int(primary["events_total"]),
        "aftershock_events_total": int(aftershock["events_total"]),
        "episode_hit_rate_primary": float(primary["episode_hit_rate"]),
        "episode_hit_rate_aftershock": float(aftershock["episode_hit_rate"]),
        "news_to_shock_precision": float(precision),
        "news_to_shock_recall": float(recall),
        "news_to_shock_f1": float(f1),
        "predicted_alerts": int(predicted.sum()),
        "truth_shocks_primary": int(truth_primary.sum()),
        "median_delay_min": float(delays.median()) if not delays.empty else None,
        "p90_delay_min": float(delays.quantile(0.9)) if not delays.empty else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Walk-forward synthetic validation for news root/aftershock detector with no-lookahead profile freezing."
    )
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--start-ts", type=str, default=None)
    parser.add_argument("--end-ts", type=str, default=None)
    parser.add_argument("--warmup-days", type=int, default=120)
    parser.add_argument("--test-window-days", type=int, default=14)
    parser.add_argument("--step-days", type=int, default=14)
    parser.add_argument("--min-calibration-rows", type=int, default=500)
    parser.add_argument("--min-test-rows", type=int, default=50)
    parser.add_argument("--max-delay-min", type=float, default=60.0)
    parser.add_argument("--sweep-broad-grid", type=str, default="0.2,0.4,0.6,0.8,1.0")
    parser.add_argument("--sweep-v2-grid", type=str, default="0.0,0.1,0.2,0.3,0.4,0.5")
    parser.add_argument("--sweep-min-coverage", type=float, default=0.10)
    parser.add_argument("--primary-z", type=float, default=2.5)
    parser.add_argument("--aftershock-z", type=float, default=2.0)
    parser.add_argument("--episode-window-min", type=int, default=10080)
    parser.add_argument("--max-gap-min", type=int, default=2880)
    parser.add_argument("--gate-primary-recall", type=float, default=0.90)
    parser.add_argument("--gate-aftershock-recall", type=float, default=0.90)
    parser.add_argument("--gate-precision", type=float, default=0.25)
    args = parser.parse_args()

    if not args.input_csv.exists():
        raise SystemExit(f"Input file not found: {args.input_csv}")
    if args.output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output_dir = Path("data/output") / f"news_forward_synthetic_{stamp}"
    args.output_dir.mkdir(parents=True, exist_ok=True)

    raw_df = pd.read_csv(args.input_csv)
    raw_rows = int(len(raw_df))
    leakage_postmove_dropped = 0
    if "leakage_postmove" in raw_df.columns:
        leakage_mask = pd.to_numeric(raw_df["leakage_postmove"], errors="coerce").fillna(0).astype(int) == 1
        leakage_postmove_dropped = int(leakage_mask.sum())
        raw_df = raw_df[~leakage_mask].copy()

    curated_df, issues_df, curation_summary_df = curate_shock_dataset(
        raw_df,
        config=ShockCurationConfig.defaults(),
    )
    curated_df["shock_ts_dt"] = pd.to_datetime(curated_df["shock_ts"], utc=True, errors="coerce")
    curated_df = curated_df.dropna(subset=["shock_ts_dt"]).sort_values("shock_ts_dt").reset_index(drop=True)

    start_ts = _to_ts(args.start_ts)
    end_ts = _to_ts(args.end_ts)
    if start_ts is not None:
        curated_df = curated_df[curated_df["shock_ts_dt"] >= start_ts].copy()
    if end_ts is not None:
        curated_df = curated_df[curated_df["shock_ts_dt"] <= end_ts].copy()
    if curated_df.empty:
        raise SystemExit("No rows after curation/date filters.")

    broad_grid = _parse_grid(args.sweep_broad_grid)
    v2_grid = _parse_grid(args.sweep_v2_grid)
    episode_cfg = ShockEpisodeConfig(
        primary_z_threshold=float(args.primary_z),
        aftershock_z_threshold=float(args.aftershock_z),
        episode_window_minutes=int(args.episode_window_min),
        max_gap_minutes=int(args.max_gap_min),
    )
    linked_rows, truth_primary_rows, recall_ceiling = _event_link_ceiling(
        curated_df,
        max_delay_min=float(args.max_delay_min),
        primary_z=float(args.primary_z),
    )

    min_ts = curated_df["shock_ts_dt"].min()
    max_ts = curated_df["shock_ts_dt"].max()
    window_start = min_ts + pd.Timedelta(days=max(int(args.warmup_days), 1))
    test_window = pd.Timedelta(days=max(int(args.test_window_days), 1))
    step = pd.Timedelta(days=max(int(args.step_days), 1))

    window_rows: list[dict[str, Any]] = []
    idx = 0
    while window_start <= max_ts:
        window_end = window_start + test_window
        calibration_df = curated_df[curated_df["shock_ts_dt"] < window_start].copy()
        test_df = curated_df[
            (curated_df["shock_ts_dt"] >= window_start)
            & (curated_df["shock_ts_dt"] < window_end)
        ].copy()
        idx += 1
        if len(calibration_df) < int(args.min_calibration_rows) or len(test_df) < int(args.min_test_rows):
            window_start = window_start + step
            continue

        profile = _pick_profile(
            calibration_df,
            broad_grid=broad_grid,
            v2_grid=v2_grid,
            max_delay_min=float(args.max_delay_min),
            min_coverage=float(args.sweep_min_coverage),
        )
        compare_cfg = CompareConfig(
            max_delay_minutes=float(args.max_delay_min),
            broad_min_relevance=float(profile["broad_min_relevance"]),
            v2_min_relevance=float(profile["v2_min_relevance"]),
        )
        window_dir = args.output_dir / f"window_{idx:03d}"
        metrics = _evaluate_window(
            test_df=test_df.drop(columns=["shock_ts_dt"]),
            compare_cfg=compare_cfg,
            episode_cfg=episode_cfg,
            max_delay_min=float(args.max_delay_min),
            window_dir=window_dir,
        )
        pass_primary = metrics["primary_recall_episode"] >= float(args.gate_primary_recall)
        pass_after = metrics["aftershock_recall_episode"] >= float(args.gate_aftershock_recall)
        pass_precision = metrics["news_to_shock_precision"] >= float(args.gate_precision)
        row = {
            "window_id": idx,
            "window_start_utc": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_end_utc": window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "calibration_rows": int(len(calibration_df)),
            "profile_source": profile["profile_source"],
            "broad_min_relevance": float(profile["broad_min_relevance"]),
            "v2_min_relevance": float(profile["v2_min_relevance"]),
            "profile_coverage_calib": float(profile["coverage"]),
            "profile_acc_x_cov_calib": float(profile["acc_x_cov"]),
            **metrics,
            "pass_primary_recall": int(pass_primary),
            "pass_aftershock_recall": int(pass_after),
            "pass_precision": int(pass_precision),
            "window_pass": int(pass_primary and pass_after and pass_precision),
        }
        window_rows.append(row)
        window_start = window_start + step

    if not window_rows:
        raise SystemExit("No valid windows produced. Lower warmup/min-row requirements or widen input range.")

    windows_df = pd.DataFrame(window_rows)
    summary = {
        "input_csv": str(args.input_csv),
        "rows_raw": raw_rows,
        "rows_after_leakage_filter": int(len(raw_df)),
        "rows_curated": int(len(curated_df)),
        "leakage_postmove_dropped": leakage_postmove_dropped,
        "event_linked_rows_within_delay": linked_rows,
        "truth_primary_rows": truth_primary_rows,
        "row_level_recall_ceiling": recall_ceiling,
        "windows": int(len(windows_df)),
        "window_pass_rate": float(windows_df["window_pass"].mean()),
        "avg_primary_recall_episode": float(windows_df["primary_recall_episode"].mean()),
        "avg_aftershock_recall_episode": float(windows_df["aftershock_recall_episode"].mean()),
        "avg_news_to_shock_precision": float(windows_df["news_to_shock_precision"].mean()),
        "avg_news_to_shock_recall": float(windows_df["news_to_shock_recall"].mean()),
        "gate_primary_recall": float(args.gate_primary_recall),
        "gate_aftershock_recall": float(args.gate_aftershock_recall),
        "gate_precision": float(args.gate_precision),
    }

    windows_path = args.output_dir / "forward_synthetic_windows.csv"
    summary_path = args.output_dir / "forward_synthetic_summary.json"
    report_path = args.output_dir / "forward_synthetic_report.md"
    issues_path = args.output_dir / "forward_synthetic_curation_issues.csv"
    curation_summary_path = args.output_dir / "forward_synthetic_curation_summary.csv"

    windows_df.to_csv(windows_path, index=False)
    issues_df.to_csv(issues_path, index=False)
    curation_summary_df.to_csv(curation_summary_path, index=False)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report_lines = [
        "# Forward Synthetic Validation (No-Lookahead)",
        "",
        f"- Input: `{args.input_csv}`",
        f"- Raw rows: {summary['rows_raw']}",
        f"- Leakage post-move rows dropped: {summary['leakage_postmove_dropped']}",
        f"- Curated rows: {summary['rows_curated']}",
        f"- Event-linked rows within delay: {summary['event_linked_rows_within_delay']}",
        f"- Truth primary rows (|z| >= {float(args.primary_z):.3f}): {summary['truth_primary_rows']}",
        f"- Theoretical row-level recall ceiling: {summary['row_level_recall_ceiling']:.3f}",
        f"- Windows: {summary['windows']}",
        f"- Window pass rate: {summary['window_pass_rate']:.3f}",
        f"- Avg primary recall: {summary['avg_primary_recall_episode']:.3f}",
        f"- Avg aftershock recall: {summary['avg_aftershock_recall_episode']:.3f}",
        f"- Avg precision: {summary['avg_news_to_shock_precision']:.3f}",
        f"- Avg recall: {summary['avg_news_to_shock_recall']:.3f}",
        "",
        "## Gates",
        f"- primary_recall >= {float(args.gate_primary_recall):.3f}",
        f"- aftershock_recall >= {float(args.gate_aftershock_recall):.3f}",
        f"- precision >= {float(args.gate_precision):.3f}",
    ]
    if float(recall_ceiling) < float(args.gate_primary_recall):
        report_lines.extend(
            [
                "",
                "## Warning",
                "- Current input has insufficient event-linked rows to reach primary gate on row-level ceiling.",
                "- Expand upstream event linking coverage before expecting gate pass.",
            ]
        )
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print("Forward synthetic validation completed")
    print(f"- windows: {windows_path}")
    print(f"- summary: {summary_path}")
    print(f"- report: {report_path}")
    print(f"- curation_issues: {issues_path}")
    print(f"- curation_summary: {curation_summary_path}")


if __name__ == "__main__":
    main()
