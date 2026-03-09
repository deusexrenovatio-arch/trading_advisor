from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import run_execution_profiles_historical_review as hist

REPO_ROOT = Path(__file__).resolve().parents[1]
FUTURES_CSV = REPO_ROOT / "data" / "raw" / "futures.csv"

ASSET_DISPLAY = {
    "ALUM": "Aluminum",
    "BR": "Brent",
    "BRM": "Brent mini",
    "COCOA": "Cocoa",
    "COFFEE": "Coffee",
    "COPPER": "Copper",
    "DAX": "DAX",
    "DJ30": "Dow Jones",
    "GOLD": "Gold",
    "GOLDM": "Gold mini",
    "HANG": "Hang Seng",
    "NASD": "Nasdaq 100",
    "NG": "Natural Gas",
    "NGM": "Natural Gas mini",
    "NICKEL": "Nickel",
    "NIKK": "Nikkei 225",
    "PLD": "Palladium",
    "PLT": "Platinum",
    "RTS": "RTS Index",
    "RTSM": "RTS mini",
    "SILV": "Silver",
    "SILVM": "Silver mini",
    "SPYF": "S&P 500",
    "STOX": "Euro Stoxx 50",
    "SUGAR": "Sugar",
    "SUGR": "Sugar",
    "TTF": "TTF Gas",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_root_metadata() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    root_meta: dict[str, dict[str, str]] = {}
    asset_to_root: dict[str, str] = {}
    with FUTURES_CSV.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            root = str(row.get("SECTYPE") or "").strip().upper()
            asset = str(row.get("ASSETCODE") or "").strip().upper()
            if not root or not asset:
                continue
            root_meta.setdefault(
                root,
                {
                    "assetcode": asset,
                    "display_name": ASSET_DISPLAY.get(asset, asset),
                },
            )
            asset_to_root.setdefault(asset, root)

    mini_pairs: dict[str, dict[str, str]] = {}
    for root, meta in root_meta.items():
        asset = meta["assetcode"]
        if not asset.endswith("M"):
            continue
        base_asset = asset[:-1]
        full_root = asset_to_root.get(base_asset)
        if not full_root:
            continue
        mini_pairs[root] = {
            "mini_root": root,
            "mini_label": format_root_label(root, root_meta),
            "mini_assetcode": asset,
            "full_root": full_root,
            "full_label": format_root_label(full_root, root_meta),
            "full_assetcode": base_asset,
        }
    return root_meta, mini_pairs


def format_root_label(root: str, root_meta: dict[str, dict[str, str]]) -> str:
    meta = root_meta.get(root, {})
    display_name = str(meta.get("display_name") or meta.get("assetcode") or root)
    return f"{root} ({display_name})"


def filled_rows_detailed(report: dict[str, Any], root_meta: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in report.get("planned_signals") or []:
        if not bool(item.get("simulated_filled")):
            continue
        trade_date = str(item.get("trade_date") or "")
        root = str(item.get("instrument_id") or "")
        if not trade_date or not root:
            continue
        rows.append(
            {
                "trade_date": trade_date,
                "trade_month": trade_date[:7],
                "trade_year": trade_date[:4],
                "root": root,
                "root_label": format_root_label(root, root_meta),
                "setup_id": str(item.get("setup_id") or ""),
                "setup_kind": str(item.get("setup_kind") or ""),
                "side": str(item.get("side") or ""),
                "outcome": str(item.get("simulated_outcome") or ""),
                "net_ticks": float(item.get("simulated_net_ticks", 0.0) or 0.0),
                "gross_ticks": float(item.get("simulated_gross_ticks", 0.0) or 0.0),
                "simulated_entry_ts": item.get("simulated_entry_ts"),
                "simulated_exit_ts": item.get("simulated_exit_ts"),
            }
        )
    return rows


def month_sequence(start_date: date, end_date: date) -> list[str]:
    year = start_date.year
    month = start_date.month
    result: list[str] = []
    while (year, month) <= (end_date.year, end_date.month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month = 1
            year += 1
    return result


def full_calendar_summary(rows: list[dict[str, Any]], start_date: date, end_date: date) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["trade_month"]].append(row)
    months: list[dict[str, Any]] = []
    for month in month_sequence(start_date, end_date):
        month_rows = grouped.get(month, [])
        net_ticks = float(sum(float(item["net_ticks"]) for item in month_rows))
        gross_ticks = float(sum(float(item["gross_ticks"]) for item in month_rows))
        win_rate = hist.positive_share([float(item["net_ticks"]) for item in month_rows])
        months.append(
            {
                "month": month,
                "filled_trades": len(month_rows),
                "net_ticks_sum": net_ticks,
                "gross_ticks_sum": gross_ticks,
                "win_rate_net": win_rate,
            }
        )
    profitable = sum(1 for item in months if float(item["net_ticks_sum"]) > 0.0)
    losing = sum(1 for item in months if float(item["net_ticks_sum"]) < 0.0)
    flat = len(months) - profitable - losing
    return {
        "months": months,
        "summary": {
            "months_total": len(months),
            "profitable_months": profitable,
            "losing_months": losing,
            "flat_months": flat,
            "flat_month_list": [item["month"] for item in months if float(item["net_ticks_sum"]) == 0.0],
        },
    }


def negative_month_details(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["trade_month"]].append(row)
    details: list[dict[str, Any]] = []
    for month, month_rows in sorted(grouped.items()):
        month_net = float(sum(float(item["net_ticks"]) for item in month_rows))
        if month_net >= 0.0:
            continue
        root_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in month_rows:
            root_groups[row["root_label"]].append(row)
        by_root = []
        for root_label, root_rows in root_groups.items():
            by_root.append(
                {
                    "root_label": root_label,
                    "filled_trades": len(root_rows),
                    "net_ticks_sum": float(sum(float(item["net_ticks"]) for item in root_rows)),
                    "gross_ticks_sum": float(sum(float(item["gross_ticks"]) for item in root_rows)),
                }
            )
        by_root.sort(key=lambda item: float(item["net_ticks_sum"]))
        worst_trades = sorted(month_rows, key=lambda item: float(item["net_ticks"]))[:10]
        details.append(
            {
                "month": month,
                "filled_trades": len(month_rows),
                "net_ticks_sum": month_net,
                "gross_ticks_sum": float(sum(float(item["gross_ticks"]) for item in month_rows)),
                "by_root": by_root,
                "worst_trades": worst_trades,
            }
        )
    return details


def thin_sample_roots(
    rows: list[dict[str, Any]],
    root_meta: dict[str, dict[str, str]],
    min_trades: int,
    min_months: int,
) -> list[dict[str, Any]]:
    by_root = hist.by_root_summary(rows)
    result: list[dict[str, Any]] = []
    for item in by_root:
        if int(item["filled_trades"]) >= min_trades and int(item["active_months"]) >= min_months:
            continue
        root = str(item["root"])
        result.append(
            {
                "root": root,
                "root_label": format_root_label(root, root_meta),
                "filled_trades": int(item["filled_trades"]),
                "active_months": int(item["active_months"]),
                "net_ticks_sum": float(item["net_ticks_sum"]),
                "expectancy_net_ticks": float(item["expectancy_net_ticks"]),
                "win_rate_net": float(item["win_rate_net"]),
                "first_month": item["first_month"],
                "last_month": item["last_month"],
            }
        )
    result.sort(key=lambda item: (int(item["filled_trades"]), int(item["active_months"]), float(item["net_ticks_sum"])))
    return result


def subset_payload_with_calendar(rows: list[dict[str, Any]], start_date: date, end_date: date) -> dict[str, Any]:
    filtered = hist.rows_in_window(rows, start_date, end_date)
    return {
        "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "summary": hist.summary_from_rows(filtered),
        "by_root": hist.by_root_summary(filtered),
        "monthly": hist.monthly_calendar(filtered),
        "full_calendar": full_calendar_summary(filtered, start_date, end_date),
        "yearly": hist.yearly_calendar(filtered),
        "negative_months": negative_month_details(filtered),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze historical execution-profile review artifacts.")
    parser.add_argument(
        "--review-artifact",
        default="artifacts/research/wf_goal_v6_execution_profiles_historical_review_2020_2026_20260306.json",
    )
    parser.add_argument(
        "--out-json",
        default="artifacts/research/wf_goal_v6_execution_profiles_historical_review_no_minis_2020_2026_20260306.json",
    )
    parser.add_argument("--exclude-mini", action="store_true")
    parser.add_argument("--thin-min-trades", type=int, default=20)
    parser.add_argument("--thin-min-months", type=int, default=6)
    args = parser.parse_args()

    review_path = Path(args.review_artifact)
    review = load_json(review_path)
    root_meta, mini_pairs = load_root_metadata()
    excluded_roots = sorted(mini_pairs) if args.exclude_mini else []
    excluded_set = set(excluded_roots)

    run_start = date.fromisoformat(str(review["run_period"]["start_date"]))
    run_end = date.fromisoformat(str(review["run_period"]["end_date"]))
    subset_start = date.fromisoformat(str(review["subset_period"]["start_date"]))
    subset_end = date.fromisoformat(str(review["subset_period"]["end_date"]))

    profile_rows: dict[str, list[dict[str, Any]]] = {}
    profile_payloads: dict[str, dict[str, Any]] = {}
    for profile_id in review["profiles"]:
        artifact_rel = str(review["profile_results"][profile_id]["artifact_path"])
        report = load_json(REPO_ROOT / artifact_rel)
        rows = filled_rows_detailed(report, root_meta)
        if excluded_set:
            rows = [row for row in rows if row["root"] not in excluded_set]
        profile_rows[profile_id] = rows
        profile_payloads[profile_id] = {
            "label": str(review["profile_results"][profile_id]["label"]),
            "overrides": dict(review["profile_results"][profile_id]["overrides"]),
            "artifact_path": artifact_rel,
            "full_2020_2026": subset_payload_with_calendar(rows, run_start, run_end),
            "subset_2020_2024": subset_payload_with_calendar(rows, subset_start, subset_end),
        }

    baseline_full = profile_payloads["O1"]["full_2020_2026"]["summary"]
    baseline_subset = profile_payloads["O1"]["subset_2020_2024"]["summary"]
    comparison_full: dict[str, Any] = {}
    comparison_subset: dict[str, Any] = {}
    for profile_id in review["profiles"]:
        if profile_id == "O1":
            continue
        comparison_full[profile_id] = hist.delta_summary(profile_payloads[profile_id]["full_2020_2026"]["summary"], baseline_full)
        comparison_subset[profile_id] = hist.delta_summary(profile_payloads[profile_id]["subset_2020_2024"]["summary"], baseline_subset)

    thin_roots = thin_sample_roots(profile_rows["O1"], root_meta, args.thin_min_trades, args.thin_min_months)
    negative_roots = [item for item in thin_roots if float(item["net_ticks_sum"]) < 0.0]
    positive_thin_roots = [item for item in thin_roots if float(item["net_ticks_sum"]) >= 0.0]

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "review_artifact": hist.o1prog.relpath(review_path),
        "exclude_mini": bool(args.exclude_mini),
        "excluded_roots": [mini_pairs[root] for root in excluded_roots],
        "profiles": list(review["profiles"]),
        "run_period": dict(review["run_period"]),
        "subset_period": dict(review["subset_period"]),
        "profile_results": profile_payloads,
        "comparison_vs_O1": {
            "full_2020_2026": comparison_full,
            "subset_2020_2024": comparison_subset,
        },
        "per_root_compare_vs_O1": {
            "full_2020_2026": hist.root_compare(profile_payloads, "full_2020_2026"),
            "subset_2020_2024": hist.root_compare(profile_payloads, "subset_2020_2024"),
        },
        "thin_sample": {
            "thresholds": {"min_trades": args.thin_min_trades, "min_months": args.thin_min_months},
            "positive_or_neutral_roots": positive_thin_roots,
            "negative_roots": negative_roots,
        },
        "negative_months_by_profile": {
            profile_id: profile_payloads[profile_id]["full_2020_2026"]["negative_months"] for profile_id in review["profiles"]
        },
    }
    write_json(Path(args.out_json), payload)


if __name__ == "__main__":
    main()
