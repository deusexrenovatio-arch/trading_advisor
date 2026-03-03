from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


_SYMBOL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "NG_US": (
        "natural gas",
        "lng",
        "henry hub",
        "eia storage",
        "pipeline",
        "freeze",
        "hdd",
        "cdd",
        "weather",
    ),
    "BRN": (
        "brent",
        "oil",
        "opec",
        "crude",
        "inventory",
        "stocks",
        "red sea",
        "hormuz",
        "sanctions",
    ),
    "GOLD": (
        "gold",
        "bullion",
        "fed",
        "fomc",
        "yield",
        "dxy",
        "safe haven",
        "inflation",
        "treasury",
    ),
}

_GLOBAL_CONTEXT_KEYWORDS: tuple[str, ...] = (
    "iran",
    "israel",
    "ukraine",
    "russia",
    "china",
    "middle east",
    "attack",
    "strike",
    "conflict",
    "war",
    "sanction",
    "suez",
    "panama canal",
)

_NOISE_KEYWORDS: tuple[str, ...] = (
    "football",
    "soccer",
    "tennis",
    "celebrity",
    "movie",
    "murder",
    "lottery",
    "fashion",
    "gossip",
)


@dataclass(frozen=True)
class CompareConfig:
    max_delay_minutes: float = 60.0
    broad_min_relevance: float = 1.0
    v2_min_relevance: float = 0.4
    relevance_weight: float = 0.7
    timeliness_weight: float = 0.6
    broad_source_bonus: float = 0.25
    v2_source_bonus: float = 0.9


def _normalize_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip().lower()
    return " ".join(text.split())


def _topic_relevance(symbol: str, title: str) -> float:
    lowered = _normalize_text(title)
    if not lowered:
        return 0.0

    score = 0.0
    for token in _SYMBOL_KEYWORDS.get(symbol, ()):
        if token in lowered:
            score += 1.0
    for token in _GLOBAL_CONTEXT_KEYWORDS:
        if token in lowered:
            score += 0.4
    for token in _NOISE_KEYWORDS:
        if token in lowered:
            score -= 1.25
    return score


def _candidate_from_row(row: pd.Series, source: str) -> dict[str, Any] | None:
    if source == "broad":
        prefix = "broad"
    elif source == "v2_clean":
        prefix = "v2"
    else:
        return None

    event_id = _normalize_text(row.get(f"{prefix}_event_id"))
    if not event_id:
        return None
    raw_delay = pd.to_numeric(row.get(f"{prefix}_delay_min"), errors="coerce")
    delay = float(raw_delay) if pd.notna(raw_delay) else float("nan")
    return {
        "source": source,
        "event_id": event_id,
        "event_ts": row.get(f"{prefix}_event_ts"),
        "delay_min": delay,
        "title": row.get(f"{prefix}_title"),
        "url": row.get(f"{prefix}_url"),
    }


def select_current_candidate(row: pd.Series) -> dict[str, Any] | None:
    broad = _candidate_from_row(row, "broad")
    if broad is not None:
        return broad
    return _candidate_from_row(row, "v2_clean")


def select_proposed_candidate(row: pd.Series, config: CompareConfig) -> dict[str, Any] | None:
    symbol = str(row.get("symbol") or "")
    candidates: list[dict[str, Any]] = []
    for source in ("v2_clean", "broad"):
        candidate = _candidate_from_row(row, source)
        if candidate is None:
            continue
        delay = candidate.get("delay_min")
        if pd.isna(delay):
            continue
        if delay < 0 or delay > config.max_delay_minutes:
            continue
        relevance = _topic_relevance(symbol, candidate.get("title"))
        min_relevance = config.v2_min_relevance if source == "v2_clean" else config.broad_min_relevance
        if relevance < min_relevance:
            continue
        time_score = max(0.0, (config.max_delay_minutes - float(delay)) / config.max_delay_minutes)
        source_bonus = config.v2_source_bonus if source == "v2_clean" else config.broad_source_bonus
        candidate["relevance"] = relevance
        candidate["score"] = source_bonus + config.relevance_weight * relevance + config.timeliness_weight * time_score
        candidates.append(candidate)

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["score"], -item["delay_min"]), reverse=True)
    return candidates[0]


def _mode_rows(df: pd.DataFrame, mode: str, config: CompareConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        candidate = select_current_candidate(row) if mode == "current" else select_proposed_candidate(row, config)
        symbol = str(row.get("symbol") or "")
        entry: dict[str, Any] = {
            "symbol": symbol,
            "shock_ts": row.get("shock_ts"),
            "shock_direction": row.get("shock_direction"),
            "z_score": pd.to_numeric(row.get("z_score"), errors="coerce"),
            "label_has_silver": int(pd.to_numeric(row.get("label_has_silver"), errors="coerce") == 1),
            "silver_direction_match": int(pd.to_numeric(row.get("silver_direction_match"), errors="coerce") == 1),
            "mode": mode,
            "matched": int(candidate is not None),
            "source": None,
            "event_id": None,
            "delay_min": None,
            "title": None,
            "relevance": None,
            "score": None,
        }
        if candidate is not None:
            entry["source"] = candidate.get("source")
            entry["event_id"] = candidate.get("event_id")
            entry["delay_min"] = candidate.get("delay_min")
            entry["title"] = candidate.get("title")
            if mode == "current":
                entry["relevance"] = _topic_relevance(symbol, candidate.get("title"))
                entry["score"] = None
            else:
                entry["relevance"] = candidate.get("relevance")
                entry["score"] = candidate.get("score")
        rows.append(entry)
    return pd.DataFrame(rows)


def _summarize_mode(mode_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol in sorted(mode_df["symbol"].dropna().unique().tolist()) + ["ALL"]:
        subset = mode_df if symbol == "ALL" else mode_df[mode_df["symbol"] == symbol]
        total = int(len(subset))
        matched = subset[subset["matched"] == 1]
        matched_count = int(len(matched))
        delays = pd.to_numeric(matched["delay_min"], errors="coerce").dropna()
        relevance = pd.to_numeric(matched["relevance"], errors="coerce").dropna()
        labeled = subset[subset["label_has_silver"] == 1]
        labeled_total = int(len(labeled))
        labeled_covered = labeled[labeled["matched"] == 1]
        labeled_covered_count = int(len(labeled_covered))
        row = {
            "mode": str(subset["mode"].iloc[0]) if total else "",
            "symbol": symbol,
            "total_shocks": total,
            "matched_shocks": matched_count,
            "coverage": matched_count / total if total else 0.0,
            "median_delay_min": float(delays.median()) if not delays.empty else None,
            "p90_delay_min": float(delays.quantile(0.9)) if not delays.empty else None,
            "avg_relevance": float(relevance.mean()) if not relevance.empty else None,
            "high_relevance_share": float((relevance >= 1.5).mean()) if not relevance.empty else None,
            "unique_events": int(matched["event_id"].nunique()) if matched_count else 0,
            "shocks_per_event": float(matched_count / max(int(matched["event_id"].nunique()), 1)) if matched_count else None,
            "labeled_total": labeled_total,
            "labeled_covered": labeled_covered_count,
            "labeled_coverage": labeled_covered_count / labeled_total if labeled_total else 0.0,
            "silver_direction_acc": float(labeled_covered["silver_direction_match"].mean()) if labeled_covered_count else None,
            "accuracy_x_coverage": float(labeled_covered["silver_direction_match"].mean() * (labeled_covered_count / labeled_total))
            if labeled_total and labeled_covered_count
            else 0.0,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _binary_metrics(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0:
        return precision, recall, 0.0
    return precision, recall, 2 * precision * recall / (precision + recall)


def evaluate_news_to_shock_metrics(
    mode_frames: list[pd.DataFrame],
    z_thresholds: tuple[float, ...] = (2.0, 2.5, 3.0),
    min_delay_minutes: float = 0.0,
    max_delay_minutes: float = 60.0,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for mode_df in mode_frames:
        if mode_df.empty:
            continue
        mode_name = str(mode_df["mode"].iloc[0])
        for z_threshold in z_thresholds:
            z = pd.to_numeric(mode_df["z_score"], errors="coerce").abs().fillna(0.0)
            delay = pd.to_numeric(mode_df["delay_min"], errors="coerce")
            predicted = (
                (mode_df["matched"] == 1)
                & delay.notna()
                & (delay >= min_delay_minutes)
                & (delay <= max_delay_minutes)
            )
            truth = z >= float(z_threshold)
            for symbol in sorted(mode_df["symbol"].dropna().unique().tolist()) + ["ALL"]:
                subset_mask = mode_df["symbol"] == symbol if symbol != "ALL" else pd.Series(True, index=mode_df.index)
                sub_truth = truth[subset_mask]
                sub_pred = predicted[subset_mask]
                total = int(len(sub_truth))
                tp = int((sub_pred & sub_truth).sum())
                fp = int((sub_pred & ~sub_truth).sum())
                fn = int((~sub_pred & sub_truth).sum())
                tn = int((~sub_pred & ~sub_truth).sum())
                precision, recall, f1 = _binary_metrics(tp, fp, fn)
                base_rate = float(sub_truth.mean()) if total else 0.0
                alert_rate = float(sub_pred.mean()) if total else 0.0
                rows.append(
                    {
                        "mode": mode_name,
                        "symbol": symbol,
                        "z_threshold": float(z_threshold),
                        "rows": total,
                        "truth_shocks": int(sub_truth.sum()),
                        "predicted_alerts": int(sub_pred.sum()),
                        "tp": tp,
                        "fp": fp,
                        "fn": fn,
                        "tn": tn,
                        "precision": precision,
                        "recall": recall,
                        "f1": f1,
                        "base_shock_rate": base_rate,
                        "alert_rate": alert_rate,
                        "precision_lift_vs_base": (precision / base_rate) if base_rate > 0 else None,
                    }
                )
    return pd.DataFrame(rows)


def compare_modes(df: pd.DataFrame, config: CompareConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    current_df = _mode_rows(df, "current", config)
    proposed_df = _mode_rows(df, "proposed", config)
    detail_df = current_df.merge(
        proposed_df,
        on=["symbol", "shock_ts", "shock_direction", "z_score", "label_has_silver", "silver_direction_match"],
        suffixes=("_current", "_proposed"),
    )
    detail_df["mode_switched"] = (
        detail_df["event_id_current"].fillna("") != detail_df["event_id_proposed"].fillna("")
    ).astype(int)
    if {"symbol", "shock_ts"}.issubset(df.columns):
        base_cols = ["symbol", "shock_ts"]
        for extra in ("abs_move_pct", "logret"):
            if extra in df.columns:
                base_cols.append(extra)
        base = df[base_cols].drop_duplicates(subset=["symbol", "shock_ts"]).copy()
        detail_df = detail_df.merge(base, on=["symbol", "shock_ts"], how="left")

    summary_df = pd.concat([_summarize_mode(current_df), _summarize_mode(proposed_df)], ignore_index=True)
    current_summary = summary_df[summary_df["mode"] == "current"].copy()
    proposed_summary = summary_df[summary_df["mode"] == "proposed"].copy()
    delta_df = current_summary.merge(proposed_summary, on="symbol", suffixes=("_current", "_proposed"))
    for metric in (
        "coverage",
        "silver_direction_acc",
        "labeled_coverage",
        "accuracy_x_coverage",
        "avg_relevance",
    ):
        delta_df[f"delta_{metric}"] = (
            pd.to_numeric(delta_df[f"{metric}_proposed"], errors="coerce")
            - pd.to_numeric(delta_df[f"{metric}_current"], errors="coerce")
        )
    return detail_df, summary_df, delta_df


def render_report(
    summary_df: pd.DataFrame,
    delta_df: pd.DataFrame,
    news_to_shock_df: pd.DataFrame | None = None,
) -> str:
    all_current = summary_df[(summary_df["symbol"] == "ALL") & (summary_df["mode"] == "current")]
    all_proposed = summary_df[(summary_df["symbol"] == "ALL") & (summary_df["mode"] == "proposed")]
    if all_current.empty or all_proposed.empty:
        return "No comparable rows found."
    c = all_current.iloc[0]
    p = all_proposed.iloc[0]
    lines = [
        "News Matching A/B Comparison",
        f"Current coverage: {c['coverage']:.3f} ({int(c['matched_shocks'])}/{int(c['total_shocks'])})",
        f"Proposed coverage: {p['coverage']:.3f} ({int(p['matched_shocks'])}/{int(p['total_shocks'])})",
        f"Current labeled coverage: {c['labeled_coverage']:.3f}",
        f"Proposed labeled coverage: {p['labeled_coverage']:.3f}",
        f"Current silver accuracy: {0.0 if pd.isna(c['silver_direction_acc']) else c['silver_direction_acc']:.3f}",
        f"Proposed silver accuracy: {0.0 if pd.isna(p['silver_direction_acc']) else p['silver_direction_acc']:.3f}",
        f"Current avg relevance: {0.0 if pd.isna(c['avg_relevance']) else c['avg_relevance']:.3f}",
        f"Proposed avg relevance: {0.0 if pd.isna(p['avg_relevance']) else p['avg_relevance']:.3f}",
        "",
        "Per-symbol deltas (proposed - current):",
    ]
    for _, row in delta_df.sort_values("symbol").iterrows():
        lines.append(
            (
                f"- {row['symbol']}: "
                f"d_coverage={row.get('delta_coverage', 0.0):+.3f}, "
                f"d_acc={0.0 if pd.isna(row.get('delta_silver_direction_acc')) else row.get('delta_silver_direction_acc'):+.3f}, "
                f"d_labeled_cov={row.get('delta_labeled_coverage', 0.0):+.3f}, "
                f"d_avg_rel={0.0 if pd.isna(row.get('delta_avg_relevance')) else row.get('delta_avg_relevance'):+.3f}"
            )
        )
    if news_to_shock_df is not None and not news_to_shock_df.empty:
        lines.append("")
        lines.append("News -> Shock metrics (ALL symbols):")
        display = news_to_shock_df[news_to_shock_df["symbol"] == "ALL"].sort_values(["z_threshold", "mode"])
        for _, row in display.iterrows():
            lines.append(
                (
                    f"- z>={row['z_threshold']:.1f} {row['mode']}: "
                    f"precision={row['precision']:.3f}, recall={row['recall']:.3f}, "
                    f"f1={row['f1']:.3f}, alerts={int(row['predicted_alerts'])}, shocks={int(row['truth_shocks'])}"
                )
            )
    return "\n".join(lines)


def run_compare(
    input_csv: Path,
    output_dir: Path,
    config: CompareConfig,
) -> dict[str, Path]:
    df = pd.read_csv(input_csv)
    detail_df, summary_df, delta_df = compare_modes(df, config)
    current_df = _mode_rows(df, "current", config)
    proposed_df = _mode_rows(df, "proposed", config)
    news_to_shock_df = evaluate_news_to_shock_metrics([current_df, proposed_df])
    output_dir.mkdir(parents=True, exist_ok=True)

    detail_path = output_dir / "news_mode_compare_detail.csv"
    summary_path = output_dir / "news_mode_compare_summary.csv"
    delta_path = output_dir / "news_mode_compare_delta.csv"
    news_to_shock_path = output_dir / "news_mode_compare_news_to_shock.csv"
    report_path = output_dir / "news_mode_compare_report.txt"

    detail_df.to_csv(detail_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    delta_df.to_csv(delta_path, index=False)
    news_to_shock_df.to_csv(news_to_shock_path, index=False)
    report_path.write_text(render_report(summary_df, delta_df, news_to_shock_df), encoding="utf-8")

    return {
        "detail": detail_path,
        "summary": summary_path,
        "delta": delta_path,
        "news_to_shock": news_to_shock_path,
        "report": report_path,
    }
