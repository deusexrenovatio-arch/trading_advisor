from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from moex_carry.news_causal import analyze_causal_news


def _norm_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return " ".join(str(value).strip().split())


def _norm_bool(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y"}


def _to_ts(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid timestamp: {value}")
    return parsed


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


def _binary_metrics(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0.0:
        return precision, recall, 0.0
    return precision, recall, 2.0 * precision * recall / (precision + recall)


def _known_event_key(commodity: str, ts: pd.Timestamp, cause_event: str, title: str) -> str:
    day = ts.strftime("%Y-%m-%d")
    ce = _norm_text(cause_event).lower()
    if ce:
        return f"{commodity}|{day}|{ce}"
    title_norm = re.sub(r"[^a-z0-9\s]", " ", _norm_text(title).lower())
    title_norm = re.sub(r"\s+", " ", title_norm).strip()
    digest = hashlib.sha1(f"{commodity}|{day}|{title_norm}".encode("utf-8")).hexdigest()[:12]
    return f"{commodity}|{day}|{digest}"


def _run_causal_detector(df: pd.DataFrame, *, causal_profile: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        payload = analyze_causal_news(
            commodity=_norm_text(row.get("commodity")).upper(),
            title=_norm_text(row.get("title")),
            description=_norm_text(row.get("description")),
            content=_norm_text(row.get("content")),
            direction="hold",
            profile=causal_profile,
        )
        rows.append(
            {
                "pred_classification": _norm_text(payload.get("cause_classification")).lower(),
                "pred_event": _norm_text(payload.get("cause_event")).lower(),
                "pred_route_key": _norm_text(payload.get("cause_route_key")),
                "pred_claim_status": _norm_text(payload.get("cause_claim_status")).lower(),
                "pred_is_primary": bool(payload.get("is_primary_cause")),
                "pred_fundamental_score": float(payload.get("fundamental_score") or 0.0),
                "pred_cause_confidence": float(payload.get("cause_confidence") or 0.0),
                "pred_is_causal": _norm_text(payload.get("cause_classification")).lower() in {"cause", "mixed"},
            }
        )
    return pd.DataFrame(rows, index=df.index)


def _prediction_mask(
    df: pd.DataFrame,
    *,
    min_fundamental: float,
    min_confidence: float,
    require_primary_flag: bool,
    allow_rumor: bool,
) -> pd.Series:
    mask = df["pred_is_causal"].astype(bool)
    mask = mask & (pd.to_numeric(df["pred_fundamental_score"], errors="coerce").fillna(0.0) >= float(min_fundamental))
    mask = mask & (pd.to_numeric(df["pred_cause_confidence"], errors="coerce").fillna(0.0) >= float(min_confidence))
    if require_primary_flag:
        mask = mask & df["pred_is_primary"].astype(bool)
    if not allow_rumor:
        mask = mask & (df["pred_claim_status"].astype(str).str.lower() != "rumor")
    return mask


def _pick_thresholds(
    calib_df: pd.DataFrame,
    *,
    fund_grid: list[float],
    conf_grid: list[float],
    min_precision: float,
    require_primary_flag: bool,
    allow_rumor: bool,
) -> dict[str, Any]:
    truth = calib_df["truth_root"].astype(bool)
    candidates: list[dict[str, Any]] = []
    for min_fund in fund_grid:
        for min_conf in conf_grid:
            pred = _prediction_mask(
                calib_df,
                min_fundamental=float(min_fund),
                min_confidence=float(min_conf),
                require_primary_flag=require_primary_flag,
                allow_rumor=allow_rumor,
            )
            tp = int((pred & truth).sum())
            fp = int((pred & ~truth).sum())
            fn = int((~pred & truth).sum())
            precision, recall, f1 = _binary_metrics(tp, fp, fn)
            candidates.append(
                {
                    "min_fundamental": float(min_fund),
                    "min_confidence": float(min_conf),
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                    "precision": float(precision),
                    "recall": float(recall),
                    "f1": float(f1),
                    "predicted": int(pred.sum()),
                }
            )

    if not candidates:
        return {
            "min_fundamental": 0.5,
            "min_confidence": 0.5,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "profile_source": "fallback",
        }

    table = pd.DataFrame(candidates)
    constrained = table[table["precision"] >= float(min_precision)].copy()
    source = "grid_precision_constrained"
    if constrained.empty:
        constrained = table.copy()
        source = "grid_precision_unconstrained"

    selected = constrained.sort_values(
        ["recall", "precision", "f1", "predicted"],
        ascending=[False, False, False, False],
    ).iloc[0]
    out = {key: selected[key] for key in selected.index.tolist()}
    out["profile_source"] = source
    return out


def _evaluate_window(
    test_df: pd.DataFrame,
    *,
    min_fundamental: float,
    min_confidence: float,
    require_primary_flag: bool,
    allow_rumor: bool,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    pred = _prediction_mask(
        test_df,
        min_fundamental=min_fundamental,
        min_confidence=min_confidence,
        require_primary_flag=require_primary_flag,
        allow_rumor=allow_rumor,
    )
    truth = test_df["truth_root"].astype(bool)
    tp = int((pred & truth).sum())
    fp = int((pred & ~truth).sum())
    fn = int((~pred & truth).sum())
    precision, recall, f1 = _binary_metrics(tp, fp, fn)

    known_rows = test_df[truth].copy()
    known_total = int(len(known_rows))
    known_caught_rows = int((pred & truth).sum())
    known_row_recall = known_caught_rows / known_total if known_total else 0.0

    all_known_keys = set(known_rows["known_event_key"].astype(str).tolist())
    hit_known_keys = set(test_df[pred & truth]["known_event_key"].astype(str).tolist())
    known_event_coverage = len(hit_known_keys) / len(all_known_keys) if all_known_keys else 0.0

    has_expected = truth & test_df["expected_event"].astype(str).str.strip().ne("")
    expected_total = int(has_expected.sum())
    exact_hits = has_expected & pred & (
        test_df["pred_event"].astype(str).str.strip().str.lower()
        == test_df["expected_event"].astype(str).str.strip().str.lower()
    )
    exact_total = int(exact_hits.sum())
    exact_event_recall = exact_total / expected_total if expected_total else 0.0

    found_df = test_df[pred].copy()
    found_df["predicted_positive"] = 1
    found_df["truth_root_int"] = truth[pred].astype(int)
    found_df["exact_event_match"] = (
        found_df["expected_event"].astype(str).str.strip().str.lower()
        == found_df["pred_event"].astype(str).str.strip().str.lower()
    ).astype(int)

    missed_df = test_df[truth & ~pred].copy()
    missed_df["predicted_positive"] = 0

    metrics = {
        "rows_test": int(len(test_df)),
        "truth_known_rows": known_total,
        "predicted_rows": int(pred.sum()),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "known_row_recall": float(known_row_recall),
        "known_event_coverage": float(known_event_coverage),
        "known_event_keys_total": int(len(all_known_keys)),
        "known_event_keys_caught": int(len(hit_known_keys)),
        "exact_event_labeled_total": expected_total,
        "exact_event_hits": exact_total,
        "exact_event_recall": float(exact_event_recall),
    }
    return metrics, found_df, missed_df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Walk-forward no-lookahead validation for known root-event coverage."
    )
    parser.add_argument("--known-events-csv", type=Path, default=Path("docs/research/news_golden_events_gold.csv"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--start-ts", type=str, default=None)
    parser.add_argument("--end-ts", type=str, default=None)
    parser.add_argument("--warmup-days", type=int, default=120)
    parser.add_argument("--test-window-days", type=int, default=14)
    parser.add_argument("--step-days", type=int, default=14)
    parser.add_argument("--min-calibration-rows", type=int, default=60)
    parser.add_argument("--min-test-known-rows", type=int, default=6)
    parser.add_argument("--grid-min-fundamental", type=str, default="0.3,0.4,0.5,0.6")
    parser.add_argument("--grid-min-confidence", type=str, default="0.3,0.4,0.5,0.6")
    parser.add_argument("--min-calibration-precision", type=float, default=0.40)
    parser.add_argument("--causal-profile", type=str, choices=("discovery", "publish"), default="discovery")
    parser.add_argument("--require-primary-flag", action="store_true")
    parser.add_argument("--allow-rumor", dest="allow_rumor", action="store_true")
    parser.add_argument("--block-rumor", dest="allow_rumor", action="store_false")
    parser.set_defaults(allow_rumor=None)
    parser.add_argument("--gate-known-row-recall", type=float, default=0.90)
    parser.add_argument("--gate-known-event-coverage", type=float, default=0.90)
    parser.add_argument("--gate-precision", type=float, default=0.40)
    args = parser.parse_args()
    allow_rumor = bool(args.allow_rumor) if args.allow_rumor is not None else (str(args.causal_profile) == "discovery")

    if not args.known_events_csv.exists():
        raise SystemExit(f"Known-events file not found: {args.known_events_csv}")
    if args.output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output_dir = Path("data/output") / f"news_known_events_walkforward_{stamp}"
    args.output_dir.mkdir(parents=True, exist_ok=True)

    raw_df = pd.read_csv(args.known_events_csv)
    if "published_at_utc" not in raw_df.columns:
        raise SystemExit("Known-events CSV must contain `published_at_utc`.")
    if "root_hit" not in raw_df.columns:
        raise SystemExit("Known-events CSV must contain `root_hit`.")
    if "commodity" not in raw_df.columns:
        raise SystemExit("Known-events CSV must contain `commodity`.")
    if "title" not in raw_df.columns:
        raise SystemExit("Known-events CSV must contain `title`.")

    df = raw_df.copy()
    df["published_ts"] = pd.to_datetime(df["published_at_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["published_ts"]).copy()
    df["truth_root"] = df["root_hit"].map(_norm_bool)
    df["commodity"] = df["commodity"].map(lambda value: _norm_text(value).upper())
    df["expected_event"] = df.get("cause_event", "").map(lambda value: _norm_text(value).lower())
    df["title"] = df["title"].map(_norm_text)
    if "description" not in df.columns:
        df["description"] = ""
    if "content" not in df.columns:
        df["content"] = ""
    df["known_event_key"] = df.apply(
        lambda row: _known_event_key(
            commodity=str(row.get("commodity") or "UNK"),
            ts=row["published_ts"],
            cause_event=str(row.get("expected_event") or ""),
            title=str(row.get("title") or ""),
        ),
        axis=1,
    )

    start_ts = _to_ts(args.start_ts)
    end_ts = _to_ts(args.end_ts)
    if start_ts is not None:
        df = df[df["published_ts"] >= start_ts].copy()
    if end_ts is not None:
        df = df[df["published_ts"] <= end_ts].copy()
    if df.empty:
        raise SystemExit("No rows after date filter.")

    predictions = _run_causal_detector(df, causal_profile=args.causal_profile)
    df = pd.concat([df.reset_index(drop=True), predictions.reset_index(drop=True)], axis=1)
    df = df.sort_values("published_ts").reset_index(drop=True)

    fund_grid = _parse_grid(args.grid_min_fundamental)
    conf_grid = _parse_grid(args.grid_min_confidence)

    min_ts = df["published_ts"].min()
    max_ts = df["published_ts"].max()
    window_start = min_ts + pd.Timedelta(days=max(int(args.warmup_days), 1))
    test_window = pd.Timedelta(days=max(int(args.test_window_days), 1))
    step = pd.Timedelta(days=max(int(args.step_days), 1))

    window_rows: list[dict[str, Any]] = []
    found_parts: list[pd.DataFrame] = []
    missed_parts: list[pd.DataFrame] = []

    idx = 0
    while window_start <= max_ts:
        window_end = window_start + test_window
        calibration_df = df[df["published_ts"] < window_start].copy()
        test_df = df[(df["published_ts"] >= window_start) & (df["published_ts"] < window_end)].copy()
        idx += 1
        test_known_rows = int(test_df["truth_root"].astype(bool).sum())
        if len(calibration_df) < int(args.min_calibration_rows) or test_known_rows < int(args.min_test_known_rows):
            window_start = window_start + step
            continue

        profile = _pick_thresholds(
            calibration_df,
            fund_grid=fund_grid,
            conf_grid=conf_grid,
            min_precision=float(args.min_calibration_precision),
            require_primary_flag=bool(args.require_primary_flag),
            allow_rumor=allow_rumor,
        )
        metrics, found_df, missed_df = _evaluate_window(
            test_df,
            min_fundamental=float(profile["min_fundamental"]),
            min_confidence=float(profile["min_confidence"]),
            require_primary_flag=bool(args.require_primary_flag),
            allow_rumor=allow_rumor,
        )
        pass_known_rows = metrics["known_row_recall"] >= float(args.gate_known_row_recall)
        pass_known_events = metrics["known_event_coverage"] >= float(args.gate_known_event_coverage)
        pass_precision = metrics["precision"] >= float(args.gate_precision)

        found_df["window_id"] = idx
        found_df["window_start_utc"] = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        found_df["window_end_utc"] = window_end.strftime("%Y-%m-%dT%H:%M:%SZ")
        missed_df["window_id"] = idx
        missed_df["window_start_utc"] = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        missed_df["window_end_utc"] = window_end.strftime("%Y-%m-%dT%H:%M:%SZ")
        found_parts.append(found_df)
        missed_parts.append(missed_df)

        row = {
            "window_id": idx,
            "window_start_utc": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_end_utc": window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "calibration_rows": int(len(calibration_df)),
            "test_known_rows": int(test_known_rows),
            "profile_source": profile["profile_source"],
            "min_fundamental": float(profile["min_fundamental"]),
            "min_confidence": float(profile["min_confidence"]),
            "calib_precision": float(profile.get("precision", 0.0)),
            "calib_recall": float(profile.get("recall", 0.0)),
            **metrics,
            "pass_known_row_recall": int(pass_known_rows),
            "pass_known_event_coverage": int(pass_known_events),
            "pass_precision": int(pass_precision),
            "window_pass": int(pass_known_rows and pass_known_events and pass_precision),
        }
        window_rows.append(row)
        window_start = window_start + step

    if not window_rows:
        raise SystemExit("No valid windows produced. Lower warmup/min-row settings or widen period.")

    windows_df = pd.DataFrame(window_rows)
    found_df = pd.concat(found_parts, ignore_index=True) if found_parts else pd.DataFrame()
    missed_df = pd.concat(missed_parts, ignore_index=True) if missed_parts else pd.DataFrame()

    summary = {
        "known_events_csv": str(args.known_events_csv),
        "rows_total": int(len(df)),
        "rows_truth_root": int(df["truth_root"].astype(bool).sum()),
        "windows": int(len(windows_df)),
        "window_pass_rate": float(windows_df["window_pass"].mean()),
        "avg_known_row_recall": float(windows_df["known_row_recall"].mean()),
        "avg_known_event_coverage": float(windows_df["known_event_coverage"].mean()),
        "avg_precision": float(windows_df["precision"].mean()),
        "avg_exact_event_recall": float(windows_df["exact_event_recall"].mean()),
        "gate_known_row_recall": float(args.gate_known_row_recall),
        "gate_known_event_coverage": float(args.gate_known_event_coverage),
        "gate_precision": float(args.gate_precision),
        "causal_profile": str(args.causal_profile),
        "require_primary_flag": bool(args.require_primary_flag),
        "allow_rumor": allow_rumor,
    }

    windows_path = args.output_dir / "known_events_walkforward_windows.csv"
    found_path = args.output_dir / "known_events_walkforward_found.csv"
    missed_path = args.output_dir / "known_events_walkforward_missed.csv"
    summary_path = args.output_dir / "known_events_walkforward_summary.json"
    report_path = args.output_dir / "known_events_walkforward_report.md"

    windows_df.to_csv(windows_path, index=False)
    found_df.to_csv(found_path, index=False)
    missed_df.to_csv(missed_path, index=False)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report_lines = [
        "# Known Events Walk-Forward (No-Lookahead)",
        "",
        f"- Input: `{args.known_events_csv}`",
        f"- Rows total: {summary['rows_total']}",
        f"- Truth root rows: {summary['rows_truth_root']}",
        f"- Windows: {summary['windows']}",
        f"- Window pass rate: {summary['window_pass_rate']:.3f}",
        f"- Avg known row recall: {summary['avg_known_row_recall']:.3f}",
        f"- Avg known event coverage: {summary['avg_known_event_coverage']:.3f}",
        f"- Avg precision: {summary['avg_precision']:.3f}",
        f"- Avg exact event recall: {summary['avg_exact_event_recall']:.3f}",
        "",
        "## Gates",
        f"- known_row_recall >= {float(args.gate_known_row_recall):.3f}",
        f"- known_event_coverage >= {float(args.gate_known_event_coverage):.3f}",
        f"- precision >= {float(args.gate_precision):.3f}",
    ]
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print("Known-events walk-forward completed")
    print(f"- windows: {windows_path}")
    print(f"- summary: {summary_path}")
    print(f"- report: {report_path}")
    print(f"- found: {found_path}")
    print(f"- missed: {missed_path}")


if __name__ == "__main__":
    main()
