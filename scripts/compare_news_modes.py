import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from moex_carry.news_mode_compare import CompareConfig, compare_modes, run_compare


def _parse_grid(raw: str) -> list[float]:
    values: list[float] = []
    for token in raw.split(","):
        stripped = token.strip()
        if not stripped:
            continue
        values.append(float(stripped))
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare current vs proposed shock->news matching modes.")
    parser.add_argument(
        "--input-csv",
        type=Path,
        required=True,
        help="Path to shock_news_1h_annual_all.csv-like file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for detail/summary/delta/report files.",
    )
    parser.add_argument("--max-delay-min", type=float, default=60.0)
    parser.add_argument("--broad-min-relevance", type=float, default=1.0)
    parser.add_argument("--v2-min-relevance", type=float, default=0.4)
    parser.add_argument("--run-sweep", action="store_true")
    parser.add_argument("--sweep-broad-grid", type=str, default="0.0,0.2,0.4,0.6,0.8,1.0")
    parser.add_argument("--sweep-v2-grid", type=str, default="0.0,0.1,0.2,0.3,0.4,0.5")
    parser.add_argument("--sweep-min-coverage", type=float, default=0.1)
    args = parser.parse_args()

    if not args.input_csv.exists():
        raise SystemExit(f"Input file not found: {args.input_csv}")

    if args.output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output_dir = Path("data/output") / f"news_mode_compare_{stamp}"

    config = CompareConfig(
        max_delay_minutes=args.max_delay_min,
        broad_min_relevance=args.broad_min_relevance,
        v2_min_relevance=args.v2_min_relevance,
    )
    paths = run_compare(args.input_csv, args.output_dir, config)
    report_text = paths["report"].read_text(encoding="utf-8")
    print(report_text)
    print("\nArtifacts:")
    for key, path in paths.items():
        print(f"- {key}: {path}")

    if args.run_sweep:
        broad_grid = _parse_grid(args.sweep_broad_grid)
        v2_grid = _parse_grid(args.sweep_v2_grid)
        df = pd.read_csv(args.input_csv)
        rows: list[dict[str, float]] = []
        for broad_min in broad_grid:
            for v2_min in v2_grid:
                config = CompareConfig(
                    max_delay_minutes=args.max_delay_min,
                    broad_min_relevance=broad_min,
                    v2_min_relevance=v2_min,
                )
                _, summary_df, _ = compare_modes(df, config)
                proposed = summary_df[(summary_df["mode"] == "proposed") & (summary_df["symbol"] == "ALL")]
                if proposed.empty:
                    continue
                metrics = proposed.iloc[0]
                rows.append(
                    {
                        "broad_min_relevance": broad_min,
                        "v2_min_relevance": v2_min,
                        "coverage": float(metrics["coverage"]),
                        "silver_acc": float(0.0 if pd.isna(metrics["silver_direction_acc"]) else metrics["silver_direction_acc"]),
                        "labeled_coverage": float(metrics["labeled_coverage"]),
                        "acc_x_cov": float(metrics["accuracy_x_coverage"]),
                        "avg_relevance": float(0.0 if pd.isna(metrics["avg_relevance"]) else metrics["avg_relevance"]),
                    }
                )
        if rows:
            sweep_df = pd.DataFrame(rows).sort_values(["acc_x_cov", "silver_acc", "coverage"], ascending=False)
            sweep_path = args.output_dir / "news_mode_compare_sweep.csv"
            sweep_df.to_csv(sweep_path, index=False)
            top = sweep_df.iloc[0].to_dict()
            print("\nSweep top profile:")
            print(
                f"broad_min={top['broad_min_relevance']}, v2_min={top['v2_min_relevance']}, "
                f"coverage={top['coverage']:.3f}, silver_acc={top['silver_acc']:.3f}, "
                f"labeled_coverage={top['labeled_coverage']:.3f}, acc_x_cov={top['acc_x_cov']:.3f}"
            )
            constrained = sweep_df[sweep_df["coverage"] >= args.sweep_min_coverage]
            if not constrained.empty:
                precision_top = constrained.sort_values(
                    ["silver_acc", "acc_x_cov", "coverage"], ascending=False
                ).iloc[0]
                print(
                    "Sweep precision-top "
                    f"(coverage>={args.sweep_min_coverage:.2f}): "
                    f"broad_min={precision_top['broad_min_relevance']}, "
                    f"v2_min={precision_top['v2_min_relevance']}, "
                    f"coverage={precision_top['coverage']:.3f}, "
                    f"silver_acc={precision_top['silver_acc']:.3f}, "
                    f"labeled_coverage={precision_top['labeled_coverage']:.3f}, "
                    f"acc_x_cov={precision_top['acc_x_cov']:.3f}"
                )
            print(f"- sweep: {sweep_path}")


if __name__ == "__main__":
    main()
