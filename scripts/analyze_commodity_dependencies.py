from __future__ import annotations

import argparse
import json
import math
import sqlite3
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Iterable

from moex_carry.config import load_settings, resolve_paths


DEFAULT_SYMBOLS = (
    "BRN",
    "NG_US",
    "GOLD",
    "SILVER",
    "PLATINUM",
    "PALLADIUM",
    "COPPER",
    "ALUMINUM",
    "NICKEL",
    "ZINC",
    "WHEAT",
    "SUGAR",
    "COFFEE",
    "COCOA",
    "ORANGE",
)
GEO_TERMS = (
    "iran",
    "israel",
    "strait of hormuz",
    "hormuz",
    "middle east conflict",
    "war escalation",
    "houthi",
    "red sea",
    "shipping disruption",
    "sanctions",
    "missile",
    "drone strike",
)


@dataclass(frozen=True)
class BarPoint:
    ts: datetime
    price: float


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace("+00:00", ""))


def _iso(value: datetime) -> str:
    return value.isoformat() + "Z"


def _pick_price(bid: float | None, ask: float | None, last: float | None) -> float | None:
    if bid is not None and ask is not None:
        try:
            bid_f = float(bid)
            ask_f = float(ask)
        except (TypeError, ValueError):
            bid_f = 0.0
            ask_f = 0.0
        if bid_f > 0.0 and ask_f > 0.0:
            return (bid_f + ask_f) / 2.0
    if last is None:
        return None
    try:
        last_f = float(last)
    except (TypeError, ValueError):
        return None
    return last_f if last_f > 0.0 else None


def _corr(values_x: list[float], values_y: list[float]) -> float | None:
    n = len(values_x)
    if n < 3 or n != len(values_y):
        return None
    mx = mean(values_x)
    my = mean(values_y)
    num = 0.0
    den_x = 0.0
    den_y = 0.0
    for idx in range(n):
        dx = values_x[idx] - mx
        dy = values_y[idx] - my
        num += dx * dy
        den_x += dx * dx
        den_y += dy * dy
    if den_x <= 0.0 or den_y <= 0.0:
        return None
    return num / math.sqrt(den_x * den_y)


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0.0:
        return min(values)
    if q >= 1.0:
        return max(values)
    sorted_values = sorted(values)
    pos = (len(sorted_values) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _safe_pct(value: float) -> float:
    return value * 100.0


def _load_hourly_bars(
    *,
    conn: sqlite3.Connection,
    symbols: Iterable[str],
    from_ts: datetime,
) -> dict[str, list[BarPoint]]:
    symbol_list = [str(item).strip().upper() for item in symbols if str(item).strip()]
    placeholders = ",".join("?" for _ in symbol_list)
    query = f"""
        select secid, timestamp, bid, ask, last
        from quotes
        where secid in ({placeholders})
          and timestamp >= ?
        order by secid asc, timestamp asc
    """
    rows = conn.execute(query, [*symbol_list, from_ts.isoformat(sep=" ")]).fetchall()
    by_symbol_bucket: dict[str, dict[datetime, tuple[datetime, float]]] = defaultdict(dict)
    for secid, ts_raw, bid, ask, last in rows:
        price = _pick_price(bid, ask, last)
        if price is None:
            continue
        ts = _parse_dt(str(ts_raw))
        bucket = ts.replace(minute=0, second=0, microsecond=0)
        current = by_symbol_bucket[str(secid)].get(bucket)
        if current is None or ts > current[0]:
            by_symbol_bucket[str(secid)][bucket] = (ts, float(price))
    result: dict[str, list[BarPoint]] = {}
    for symbol, bucket_map in by_symbol_bucket.items():
        points = [BarPoint(ts=bucket, price=value[1]) for bucket, value in bucket_map.items()]
        points.sort(key=lambda item: item.ts)
        result[symbol] = points
    return result


def _build_returns(
    *,
    bars: list[BarPoint],
    max_gap_hours: float | None,
) -> tuple[dict[datetime, float], dict[str, float]]:
    returns: dict[datetime, float] = {}
    gaps_hours: list[float] = []
    skipped_by_gap = 0
    for idx in range(1, len(bars)):
        prev = bars[idx - 1]
        cur = bars[idx]
        if prev.price <= 0.0 or cur.price <= 0.0 or cur.ts <= prev.ts:
            continue
        gap_h = (cur.ts - prev.ts).total_seconds() / 3600.0
        gaps_hours.append(gap_h)
        if max_gap_hours is not None and gap_h > max_gap_hours:
            skipped_by_gap += 1
            continue
        returns[cur.ts] = math.log(cur.price / prev.price)
    summary = {
        "bars": float(len(bars)),
        "returns": float(len(returns)),
        "max_gap_hours": float(max(gaps_hours)) if gaps_hours else 0.0,
        "median_gap_hours": float(median(gaps_hours)) if gaps_hours else 0.0,
        "gaps_over_3h": float(sum(1 for item in gaps_hours if item > 3.0)),
        "skipped_by_gap": float(skipped_by_gap),
    }
    return returns, summary


def _pairwise_same_time_corr(
    returns_map: dict[str, dict[datetime, float]],
    symbols: list[str],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in range(len(symbols)):
        for jdx in range(idx + 1, len(symbols)):
            left = symbols[idx]
            right = symbols[jdx]
            l_map = returns_map.get(left, {})
            r_map = returns_map.get(right, {})
            common = sorted(set(l_map).intersection(r_map))
            l_values = [l_map[item] for item in common]
            r_values = [r_map[item] for item in common]
            corr = _corr(l_values, r_values)
            rows.append(
                {
                    "left": left,
                    "right": right,
                    "points": len(common),
                    "corr": corr,
                }
            )
    return rows


def _lead_lag_corr(
    returns_map: dict[str, dict[datetime, float]],
    symbols: list[str],
    max_lag_hours: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in range(len(symbols)):
        for jdx in range(idx + 1, len(symbols)):
            left = symbols[idx]
            right = symbols[jdx]
            l_map = returns_map.get(left, {})
            r_map = returns_map.get(right, {})
            best: dict[str, object] = {"lag_hours": 0, "corr": None, "points": 0}
            by_lag: list[dict[str, object]] = []
            for lag in range(-max_lag_hours, max_lag_hours + 1):
                l_values: list[float] = []
                r_values: list[float] = []
                delta = timedelta(hours=lag)
                for ts, l_ret in l_map.items():
                    r_ret = r_map.get(ts + delta)
                    if r_ret is None:
                        continue
                    l_values.append(l_ret)
                    r_values.append(r_ret)
                corr = _corr(l_values, r_values)
                by_lag.append({"lag_hours": lag, "corr": corr, "points": len(l_values)})
                if corr is None:
                    continue
                if best["corr"] is None or abs(float(corr)) > abs(float(best["corr"])):
                    best = {"lag_hours": lag, "corr": corr, "points": len(l_values)}
            rows.append(
                {
                    "left": left,
                    "right": right,
                    "best": best,
                    "by_lag": by_lag,
                }
            )
    return rows


def _co_shock_stats(
    returns_map: dict[str, dict[datetime, float]],
    symbols: list[str],
    shock_quantile: float,
) -> list[dict[str, object]]:
    shock_sets: dict[str, set[datetime]] = {}
    shock_thresholds: dict[str, float] = {}
    for symbol in symbols:
        values = [abs(item) for item in returns_map.get(symbol, {}).values()]
        threshold = _quantile(values, shock_quantile)
        shock_thresholds[symbol] = threshold
        shock_sets[symbol] = {
            ts
            for ts, ret in returns_map.get(symbol, {}).items()
            if abs(ret) >= threshold and threshold > 0.0
        }
    rows: list[dict[str, object]] = []
    for idx in range(len(symbols)):
        for jdx in range(len(symbols)):
            if idx == jdx:
                continue
            src = symbols[idx]
            dst = symbols[jdx]
            src_set = shock_sets.get(src, set())
            dst_set = shock_sets.get(dst, set())
            if not src_set:
                continue
            same_hour = sum(1 for ts in src_set if ts in dst_set)
            plus_1h = sum(
                1
                for ts in src_set
                if (ts in dst_set) or ((ts + timedelta(hours=1)) in dst_set)
            )
            rows.append(
                {
                    "src": src,
                    "dst": dst,
                    "src_shocks": len(src_set),
                    "dst_shocks": len(dst_set),
                    "src_q_absret": shock_thresholds.get(src, 0.0),
                    "dst_q_absret": shock_thresholds.get(dst, 0.0),
                    "p_dst_same_hour": same_hour / len(src_set),
                    "p_dst_within_1h": plus_1h / len(src_set),
                }
            )
    return rows


def _load_geo_events(
    *,
    conn: sqlite3.Connection,
    from_ts: datetime,
    symbols: list[str],
) -> list[dict[str, object]]:
    symbol_placeholders = ",".join("?" for _ in symbols)
    like_clause = " or ".join(
        ["lower(coalesce(n.title,'')) like ? or lower(coalesce(n.content,'')) like ?" for _ in GEO_TERMS]
    )
    params: list[object] = [*symbols, from_ts.isoformat(sep=" ")]
    for term in GEO_TERMS:
        params.append(f"%{term}%")
        params.append(f"%{term}%")
    query = f"""
        select
            n.news_id,
            n.published_at,
            n.title,
            n.url,
            group_concat(distinct upper(coalesce(l.ticker,''))) as tickers
        from news_items n
        join news_entity_links l
          on l.news_id = n.news_id
        where upper(coalesce(l.ticker,'')) in ({symbol_placeholders})
          and n.published_at >= ?
          and ({like_clause})
        group by n.news_id, n.published_at, n.title, n.url
        order by n.published_at asc
    """
    rows = conn.execute(query, params).fetchall()
    result: list[dict[str, object]] = []
    for news_id, published_at, title, url, tickers in rows:
        try:
            published_ts = _parse_dt(str(published_at))
        except ValueError:
            continue
        result.append(
            {
                "news_id": str(news_id),
                "published_at": _iso(published_ts),
                "title": str(title or ""),
                "url": str(url or ""),
                "tickers": str(tickers or ""),
            }
        )
    return result


def _find_first_bar_at_or_after(ts_list: list[datetime], target: datetime) -> int:
    return bisect_left(ts_list, target)


def _geo_reaction_stats(
    *,
    geo_events: list[dict[str, object]],
    bars_by_symbol: dict[str, list[BarPoint]],
    symbols: list[str],
) -> dict[str, object]:
    by_symbol: dict[str, dict[str, object]] = {
        item: {
            "events": 0,
            "r1h": [],
            "r4h": [],
            "abs_r1h": [],
            "abs_r4h": [],
        }
        for item in symbols
    }
    for event in geo_events:
        event_ts = _parse_dt(str(event["published_at"]))
        for symbol in symbols:
            bars = bars_by_symbol.get(symbol, [])
            if not bars:
                continue
            ts_list = [item.ts for item in bars]
            idx0 = _find_first_bar_at_or_after(ts_list, event_ts)
            if idx0 >= len(bars):
                continue
            t0 = bars[idx0].ts
            p0 = bars[idx0].price
            idx1 = _find_first_bar_at_or_after(ts_list, t0 + timedelta(hours=1))
            idx4 = _find_first_bar_at_or_after(ts_list, t0 + timedelta(hours=4))
            bucket = by_symbol[symbol]
            bucket["events"] = int(bucket["events"]) + 1
            if idx1 < len(bars) and p0 > 0.0 and bars[idx1].price > 0.0:
                r1 = math.log(bars[idx1].price / p0)
                bucket["r1h"].append(r1)
                bucket["abs_r1h"].append(abs(r1))
            if idx4 < len(bars) and p0 > 0.0 and bars[idx4].price > 0.0:
                r4 = math.log(bars[idx4].price / p0)
                bucket["r4h"].append(r4)
                bucket["abs_r4h"].append(abs(r4))
    summary: dict[str, object] = {}
    for symbol, stats in by_symbol.items():
        r1 = list(stats["r1h"])
        r4 = list(stats["r4h"])
        a1 = list(stats["abs_r1h"])
        a4 = list(stats["abs_r4h"])
        summary[symbol] = {
            "events": int(stats["events"]),
            "r1h_count": len(r1),
            "r4h_count": len(r4),
            "r1h_mean_pct": _safe_pct(mean(r1)) if r1 else None,
            "r1h_median_pct": _safe_pct(median(r1)) if r1 else None,
            "r4h_mean_pct": _safe_pct(mean(r4)) if r4 else None,
            "r4h_median_pct": _safe_pct(median(r4)) if r4 else None,
            "abs_r1h_mean_pct": _safe_pct(mean(a1)) if a1 else None,
            "abs_r4h_mean_pct": _safe_pct(mean(a4)) if a4 else None,
            "up_share_1h": (sum(1 for item in r1 if item > 0.0) / len(r1)) if r1 else None,
            "up_share_4h": (sum(1 for item in r4 if item > 0.0) / len(r4)) if r4 else None,
        }
    return summary


def _build_text_summary(report: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("Commodity Dependency Report")
    lines.append(f"Period: {report['period_from']} .. {report['period_to']}")
    lines.append(f"Symbols: {', '.join(report['symbols'])}")
    lines.append("")
    lines.append("Same-time 1h return correlations:")
    for row in report["same_time_corr"]:
        corr = row["corr"]
        corr_text = "n/a" if corr is None else f"{float(corr):.3f}"
        lines.append(f"- {row['left']} vs {row['right']}: corr={corr_text} (n={row['points']})")
    lines.append("")
    lines.append("Lead-lag strongest links (corr abs max):")
    for row in report["lead_lag"]:
        best = row["best"]
        corr = best["corr"]
        corr_text = "n/a" if corr is None else f"{float(corr):.3f}"
        lag = best["lag_hours"]
        points = best["points"]
        direction = "left leads right" if int(lag) > 0 else ("right leads left" if int(lag) < 0 else "synchronous")
        lines.append(f"- {row['left']} vs {row['right']}: best_lag={lag}h ({direction}), corr={corr_text}, n={points}")
    lines.append("")
    lines.append("Shock propagation (same-hour / +1h):")
    for row in report["co_shock"]:
        lines.append(
            "- {src}->{dst}: same_hour={same:.2%}, within_1h={w1:.2%}, src_shocks={src_n}".format(
                src=row["src"],
                dst=row["dst"],
                same=float(row["p_dst_same_hour"]),
                w1=float(row["p_dst_within_1h"]),
                src_n=int(row["src_shocks"]),
            )
        )
    lines.append("")
    lines.append(f"Geo-linked events: {report['geo_events_count']}")
    lines.append("Geo event reaction (news->next bar, then 1h/4h):")
    for symbol in report["symbols"]:
        stats = report["geo_reaction"][symbol]
        lines.append(
            f"- {symbol}: events={stats['events']}, r1h_mean={stats['r1h_mean_pct']}, "
            f"r4h_mean={stats['r4h_mean_pct']}, abs_r1h_mean={stats['abs_r1h_mean_pct']}"
        )
    return "\n".join(lines)


def run_report(
    *,
    db_path: Path,
    symbols: list[str],
    period_days: int,
    max_gap_hours: float,
    max_lag_hours: int,
    shock_quantile: float,
    out_dir: Path,
) -> dict[str, object]:
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    from_ts = now - timedelta(days=max(period_days, 1))
    conn = sqlite3.connect(str(db_path))
    try:
        bars = _load_hourly_bars(conn=conn, symbols=symbols, from_ts=from_ts)
        returns_map: dict[str, dict[datetime, float]] = {}
        bar_quality: dict[str, dict[str, float]] = {}
        for symbol in symbols:
            symbol_bars = bars.get(symbol, [])
            symbol_returns, quality = _build_returns(
                bars=symbol_bars,
                max_gap_hours=max_gap_hours if max_gap_hours > 0 else None,
            )
            returns_map[symbol] = symbol_returns
            bar_quality[symbol] = quality
        same_time = _pairwise_same_time_corr(returns_map, symbols)
        lead_lag = _lead_lag_corr(returns_map, symbols, max_lag_hours=max_lag_hours)
        co_shock = _co_shock_stats(returns_map, symbols, shock_quantile=shock_quantile)
        geo_events = _load_geo_events(conn=conn, from_ts=from_ts, symbols=symbols)
        geo_reaction = _geo_reaction_stats(geo_events=geo_events, bars_by_symbol=bars, symbols=symbols)
    finally:
        conn.close()

    report: dict[str, object] = {
        "generated_at": _iso(now),
        "period_from": _iso(from_ts),
        "period_to": _iso(now),
        "symbols": symbols,
        "params": {
            "period_days": period_days,
            "max_gap_hours": max_gap_hours,
            "max_lag_hours": max_lag_hours,
            "shock_quantile": shock_quantile,
        },
        "bar_quality": bar_quality,
        "same_time_corr": same_time,
        "lead_lag": lead_lag,
        "co_shock": co_shock,
        "geo_events_count": len(geo_events),
        "geo_events_sample": geo_events[:20],
        "geo_reaction": geo_reaction,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "commodity_dependency_report.json"
    txt_path = out_dir / "commodity_dependency_report.txt"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(_build_text_summary(report), encoding="utf-8")
    report["json_path"] = str(json_path)
    report["txt_path"] = str(txt_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="analyze_commodity_dependencies",
        description="Analyze cross-commodity dependencies for BRN/GOLD/NG_US from hourly quotes and geo-linked news.",
    )
    parser.add_argument("--config", type=str, default=None, help="Optional config path.")
    parser.add_argument("--db-path", type=str, default=None, help="Optional explicit sqlite db path.")
    parser.add_argument(
        "--symbols",
        type=str,
        default="BRN,NG_US,GOLD,SILVER,PLATINUM,PALLADIUM,COPPER,ALUMINUM,NICKEL,ZINC,WHEAT,SUGAR,COFFEE,COCOA,ORANGE",
    )
    parser.add_argument("--period-days", type=int, default=365)
    parser.add_argument("--max-gap-hours", type=float, default=3.0)
    parser.add_argument("--max-lag-hours", type=int, default=6)
    parser.add_argument("--shock-quantile", type=float, default=0.95)
    parser.add_argument("--out-dir", type=str, default=None, help="Output directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    db_path = Path(args.db_path) if args.db_path else (resolve_paths(settings).data_dir / "moex_carry.db")
    symbols = [item.strip().upper() for item in str(args.symbols).split(",") if item.strip()]
    if not symbols:
        symbols = list(DEFAULT_SYMBOLS)
    out_dir = (
        Path(args.out_dir)
        if args.out_dir
        else (resolve_paths(settings).data_dir / "output" / "commodity_dependency")
    )
    report = run_report(
        db_path=db_path,
        symbols=symbols,
        period_days=max(int(args.period_days), 1),
        max_gap_hours=max(float(args.max_gap_hours), 0.0),
        max_lag_hours=max(int(args.max_lag_hours), 0),
        shock_quantile=min(max(float(args.shock_quantile), 0.50), 0.999),
        out_dir=out_dir,
    )
    print(json.dumps(report, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
