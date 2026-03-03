from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from moex_carry.news_mode_compare import CompareConfig, compare_modes
from moex_carry.news_shock_pipeline import ShockCurationConfig, curate_shock_dataset
from moex_carry.shock_episodes import ShockEpisodeConfig, run_shock_episode_analysis


@dataclass(frozen=True)
class ReadinessThresholds:
    detector_min_primary_recall: float = 0.70
    detector_min_aftershock_recall: float = 0.75
    direction_min_accuracy_v2: float = 0.58
    direction_min_labeled_v2: int = 120
    direction_min_coverage_v2: float = 0.07
    max_critical_drop_share: float = 0.05
    min_aftershock_1d_count: int = 10


@dataclass(frozen=True)
class ReadinessConfig:
    max_delay_minutes: float = 60.0
    primary_z_threshold: float = 2.5
    aftershock_z_threshold: float = 2.0
    episode_window_minutes: int = 10080
    max_gap_minutes: int = 2880
    compare_broad_min_relevance: float = 1.0
    compare_v2_min_relevance: float = 0.4
    thresholds: ReadinessThresholds = ReadinessThresholds()
    curation: ShockCurationConfig = ShockCurationConfig.defaults()


def _metric(row: dict[str, Any]) -> dict[str, Any]:
    return row


def _safe_float(value: object) -> float:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return 0.0
    return float(num)


def _check(name: str, value: float, threshold: float, op: str, critical: bool = True) -> dict[str, Any]:
    if op == ">=":
        passed = value >= threshold
    elif op == "<=":
        passed = value <= threshold
    else:
        raise ValueError(f"Unsupported op: {op}")
    return {
        "check_name": name,
        "value": value,
        "op": op,
        "threshold": threshold,
        "passed": int(passed),
        "critical": int(critical),
        "severity": "critical" if critical else "warning",
    }


def run_readiness_assessment(
    input_csv: Path,
    output_dir: Path,
    *,
    config: ReadinessConfig | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> dict[str, Path]:
    cfg = config or ReadinessConfig()
    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")

    raw = pd.read_csv(input_csv)
    if "shock_ts" not in raw.columns:
        raise ValueError("Input must contain shock_ts column")
    raw["shock_ts_dt"] = pd.to_datetime(raw["shock_ts"], utc=True, errors="coerce")
    if start_ts:
        start = pd.to_datetime(start_ts, utc=True, errors="coerce")
        if pd.isna(start):
            raise ValueError(f"Invalid start_ts: {start_ts}")
        raw = raw[raw["shock_ts_dt"] >= start]
    if end_ts:
        end = pd.to_datetime(end_ts, utc=True, errors="coerce")
        if pd.isna(end):
            raise ValueError(f"Invalid end_ts: {end_ts}")
        raw = raw[raw["shock_ts_dt"] <= end]
    raw = raw.drop(columns=["shock_ts_dt"])
    if raw.empty:
        raise ValueError("No rows after date filtering")

    curated_df, issues_df, curation_summary_df = curate_shock_dataset(raw, cfg.curation)
    compare_cfg = CompareConfig(
        max_delay_minutes=cfg.max_delay_minutes,
        broad_min_relevance=cfg.compare_broad_min_relevance,
        v2_min_relevance=cfg.compare_v2_min_relevance,
    )
    detail_df, summary_df, delta_df = compare_modes(curated_df, compare_cfg)

    episode_cfg = ShockEpisodeConfig(
        primary_z_threshold=cfg.primary_z_threshold,
        aftershock_z_threshold=cfg.aftershock_z_threshold,
        episode_window_minutes=cfg.episode_window_minutes,
        max_gap_minutes=cfg.max_gap_minutes,
    )
    episode_paths = run_shock_episode_analysis(
        detail_df=detail_df,
        output_dir=output_dir,
        config=episode_cfg,
        min_delay_minutes=0.0,
        max_delay_minutes=cfg.max_delay_minutes,
    )
    capture_df = pd.read_csv(episode_paths["capture"])
    events_df = pd.read_csv(episode_paths["events"])

    current_primary = capture_df[
        (capture_df["mode"] == "current") & (capture_df["symbol"] == "ALL") & (capture_df["role"] == "primary")
    ]
    current_after = capture_df[
        (capture_df["mode"] == "current") & (capture_df["symbol"] == "ALL") & (capture_df["role"] == "aftershock")
    ]

    labeled = curated_df[
        (pd.to_numeric(curated_df.get("label_has_silver"), errors="coerce") == 1)
        & pd.to_numeric(curated_df.get("silver_direction_match"), errors="coerce").notna()
    ].copy()
    labeled["selected_source"] = (
        labeled.get("selected_event_source", pd.Series([""] * len(labeled), index=labeled.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )
    labeled_v2 = labeled[labeled["selected_source"] == "v2_clean"]
    v2_direction_accuracy = float(
        pd.to_numeric(labeled_v2.get("silver_direction_match"), errors="coerce").mean()
    ) if not labeled_v2.empty else 0.0
    v2_labeled_count = int(len(labeled_v2))

    v2_cov = (
        (
            curated_df.get("v2_event_id", pd.Series([""] * len(curated_df), index=curated_df.index))
            .fillna("")
            .astype(str)
            .str.strip()
            != ""
        )
        & pd.to_numeric(curated_df.get("v2_delay_min"), errors="coerce").between(
            0.0, cfg.max_delay_minutes, inclusive="both"
        )
    ).mean()
    v2_coverage = float(v2_cov) if len(curated_df) else 0.0

    aftershock_1d_count = int(
        ((events_df.get("role") == "aftershock") & (pd.to_numeric(events_df.get("episode_age_min"), errors="coerce") >= 1440.0)).sum()
    )
    all_cur = curation_summary_df[curation_summary_df["symbol"] == "ALL"]
    critical_drop_share = float(all_cur["critical_drop_share"].iloc[0]) if not all_cur.empty else 1.0
    primary_recall = _safe_float(current_primary["recall"].iloc[0]) if not current_primary.empty else 0.0
    aftershock_recall = _safe_float(current_after["recall"].iloc[0]) if not current_after.empty else 0.0

    checks = [
        _check(
            "detector_primary_recall",
            primary_recall,
            cfg.thresholds.detector_min_primary_recall,
            ">=",
            True,
        ),
        _check(
            "detector_aftershock_recall",
            aftershock_recall,
            cfg.thresholds.detector_min_aftershock_recall,
            ">=",
            True,
        ),
        _check(
            "direction_v2_accuracy",
            v2_direction_accuracy,
            cfg.thresholds.direction_min_accuracy_v2,
            ">=",
            True,
        ),
        _check(
            "direction_v2_labeled_count",
            float(v2_labeled_count),
            float(cfg.thresholds.direction_min_labeled_v2),
            ">=",
            True,
        ),
        _check(
            "direction_v2_coverage",
            v2_coverage,
            cfg.thresholds.direction_min_coverage_v2,
            ">=",
            True,
        ),
        _check(
            "curation_critical_drop_share",
            critical_drop_share,
            cfg.thresholds.max_critical_drop_share,
            "<=",
            True,
        ),
        _check(
            "aftershock_1d_count",
            float(aftershock_1d_count),
            float(cfg.thresholds.min_aftershock_1d_count),
            ">=",
            True,
        ),
    ]
    checks_df = pd.DataFrame(checks)
    critical_failed = checks_df[(checks_df["critical"] == 1) & (checks_df["passed"] == 0)]
    overall_ready = critical_failed.empty

    metrics_df = pd.DataFrame(
        [
            _metric({"metric": "rows_raw", "value": int(len(raw))}),
            _metric({"metric": "rows_curated", "value": int(len(curated_df))}),
            _metric({"metric": "primary_recall_current", "value": primary_recall}),
            _metric({"metric": "aftershock_recall_current", "value": aftershock_recall}),
            _metric({"metric": "v2_direction_accuracy", "value": v2_direction_accuracy}),
            _metric({"metric": "v2_labeled_count", "value": v2_labeled_count}),
            _metric({"metric": "v2_coverage", "value": v2_coverage}),
            _metric({"metric": "critical_drop_share", "value": critical_drop_share}),
            _metric({"metric": "aftershock_1d_count", "value": aftershock_1d_count}),
            _metric({"metric": "overall_ready", "value": int(overall_ready)}),
        ]
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    curated_path = output_dir / "readiness_curated_shocks.csv"
    issues_path = output_dir / "readiness_curation_issues.csv"
    curation_summary_path = output_dir / "readiness_curation_summary.csv"
    summary_path = output_dir / "readiness_mode_summary.csv"
    delta_path = output_dir / "readiness_mode_delta.csv"
    checks_path = output_dir / "readiness_checks.csv"
    metrics_path = output_dir / "readiness_metrics.csv"
    report_md_path = output_dir / "readiness_report.md"
    report_json_path = output_dir / "readiness_report.json"

    curated_df.to_csv(curated_path, index=False)
    issues_df.to_csv(issues_path, index=False)
    curation_summary_df.to_csv(curation_summary_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    delta_df.to_csv(delta_path, index=False)
    checks_df.to_csv(checks_path, index=False)
    metrics_df.to_csv(metrics_path, index=False)

    critical_lines = []
    for _, row in checks_df.iterrows():
        status = "PASS" if int(row["passed"]) == 1 else "FAIL"
        critical_lines.append(
            f"- {status} `{row['check_name']}`: value={float(row['value']):.6g} {row['op']} {float(row['threshold']):.6g}"
        )
    report_md = "\n".join(
        [
            "# News Shock Readiness Report",
            f"- Overall ready: **{'YES' if overall_ready else 'NO'}**",
            f"- Raw rows: {int(len(raw))}",
            f"- Curated rows: {int(len(curated_df))}",
            "",
            "## Critical Checks",
            *critical_lines,
            "",
            "## Key Metrics",
            *[f"- {row['metric']}: {row['value']}" for _, row in metrics_df.iterrows()],
            "",
            "## Critical Blockers",
            *(
                [f"- {row['check_name']}" for _, row in critical_failed.iterrows()]
                if not critical_failed.empty
                else ["- none"]
            ),
        ]
    )
    report_md_path.write_text(report_md, encoding="utf-8")

    report_payload = {
        "overall_ready": bool(overall_ready),
        "critical_failed_checks": [str(x) for x in critical_failed["check_name"].tolist()],
        "metrics": {str(row["metric"]): row["value"] for _, row in metrics_df.iterrows()},
        "artifacts": {
            "curated": str(curated_path),
            "issues": str(issues_path),
            "checks": str(checks_path),
            "metrics": str(metrics_path),
            "episode_events": str(episode_paths["events"]),
            "episode_capture": str(episode_paths["capture"]),
        },
    }
    report_json_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "curated": curated_path,
        "issues": issues_path,
        "curation_summary": curation_summary_path,
        "mode_summary": summary_path,
        "mode_delta": delta_path,
        "checks": checks_path,
        "metrics": metrics_path,
        "report_md": report_md_path,
        "report_json": report_json_path,
        "episode_events": Path(episode_paths["events"]),
        "episode_summary": Path(episode_paths["episodes"]),
        "episode_capture": Path(episode_paths["capture"]),
    }
