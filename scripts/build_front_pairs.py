from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

import intraday_minute_sweep as base
from moex_carry.config import load_settings, resolve_paths


def _pick_universe_csv(user_path: str | None) -> Path:
    if user_path:
        return Path(user_path)
    candidates = [
        Path("data/output/spread_series_summary.csv"),
        Path("data/output/top_pairs.csv"),
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("Universe CSV not found. Pass --universe-csv explicitly.")


def _read_pairs(path: Path) -> list[base.Pair]:
    frame = pd.read_csv(path)
    need = {"stock", "future"}
    if not need.issubset(set(frame.columns)):
        raise ValueError(f"{path} must include columns: {sorted(need)}")
    pairs: list[base.Pair] = []
    seen: set[tuple[str, str]] = set()
    for row in frame.itertuples(index=False):
        stock = str(getattr(row, "stock", "")).strip().upper()
        future = str(getattr(row, "future", "")).strip().upper()
        if not stock or not future:
            continue
        key = (stock, future)
        if key in seen:
            continue
        seen.add(key)
        pairs.append(base.Pair(stock=stock, future=future))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build front-only pair list from universe CSV.")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--universe-csv", default=None, help="CSV with stock,future columns.")
    parser.add_argument("--asof-date", default=None, help="YYYY-MM-DD; default=today.")
    parser.add_argument("--roll-days", type=int, default=7)
    parser.add_argument("--liquidity-csv", default=None)
    parser.add_argument("--liquidity-column", default="liquidity_pass")
    parser.add_argument("--out-pairs-list", default="data/output/front_pairs_list.txt")
    parser.add_argument("--out-pairs-csv", default="data/output/front_pairs.csv")
    args = parser.parse_args()

    settings = load_settings(args.config).model_copy(deep=True)
    universe_csv = _pick_universe_csv(args.universe_csv)
    raw_pairs = _read_pairs(universe_csv)
    if not raw_pairs:
        raise SystemExit(f"No valid pairs in {universe_csv}")

    asof = base._parse_date(args.asof_date) if args.asof_date else date.today()
    selected, warnings = base.select_front_pairs(
        settings=settings,
        pairs=raw_pairs,
        asof_date=asof,
        roll_days=max(int(args.roll_days), 0),
        liquidity_csv=Path(args.liquidity_csv) if args.liquidity_csv else None,
        liquidity_column=args.liquidity_column,
    )
    if not selected:
        raise SystemExit("Front selection returned zero pairs")

    paths = resolve_paths(settings)
    spec_map = base._load_future_specs(paths.data_dir)
    rows: list[dict[str, object]] = []
    for pair in selected:
        spec = spec_map.get(pair.future)
        expiry = spec.expiry.isoformat() if spec is not None else None
        dte = (spec.expiry - asof).days if spec is not None else None
        rows.append(
            {
                "stock": pair.stock,
                "future": pair.future,
                "asof_date": asof.isoformat(),
                "expiry": expiry,
                "dte": dte,
            }
        )
    out_csv = Path(args.out_pairs_csv)
    out_list = Path(args.out_pairs_list)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values(["stock", "future"]).to_csv(out_csv, index=False)
    out_list.write_text(",".join(f"{p.stock}:{p.future}" for p in selected), encoding="utf-8")

    print(
        f"[front-pairs] universe={universe_csv} total_pairs={len(raw_pairs)} "
        f"selected_front={len(selected)} asof={asof.isoformat()} roll_days={max(int(args.roll_days), 0)}",
        flush=True,
    )
    print(f"[front-pairs] out_csv={out_csv}", flush=True)
    print(f"[front-pairs] out_list={out_list}", flush=True)
    if warnings:
        print(f"[front-pairs] warnings={warnings}", flush=True)


if __name__ == "__main__":
    main()
