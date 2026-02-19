from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import sys
from bisect import bisect_right
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from moex_carry.config import load_settings, resolve_paths  # noqa: E402


DEFAULT_SYMBOLS = ("NG_US", "BRN", "GOLD")
DEFAULT_THRESHOLDS = (2.0, 2.5, 3.0)


@dataclass(frozen=True)
class EventRef:
    event_id: str
    event_ts: datetime
    title: str | None
    url: str | None
    source: str


@dataclass(frozen=True)
class LabelSummary:
    has_any: bool
    has_gold: bool
    has_silver: bool
    gold_direction: str | None
    silver_direction: str | None
    gold_source_count: int
    silver_source_count: int


@dataclass
class RollingStats:
    maxlen: int

    def __post_init__(self) -> None:
        self.values: deque[float] = deque()
        self.total: float = 0.0
        self.total_sq: float = 0.0

    def add(self, value: float) -> None:
        self.values.append(value)
        self.total += value
        self.total_sq += value * value
        while len(self.values) > self.maxlen:
            dropped = self.values.popleft()
            self.total -= dropped
            self.total_sq -= dropped * dropped

    @property
    def count(self) -> int:
        return len(self.values)

    def sample_std(self) -> float:
        n = len(self.values)
        if n < 2:
            return 0.0
        numerator = self.total_sq - (self.total * self.total / n)
        variance = numerator / (n - 1) if numerator > 0.0 else 0.0
        return math.sqrt(variance)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace("+00:00", ""))


def _to_iso_utc(value: datetime) -> str:
    return value.isoformat() + "Z"


def _parse_list(raw: str | None, *, cast=float, default: Iterable | None = None) -> list:
    if raw is None:
        return list(default or [])
    values: list = []
    for token in str(raw).split(","):
        item = token.strip()
        if not item:
            continue
        values.append(cast(item))
    return values if values else list(default or [])


def _parse_symbols(raw: str | None) -> list[str]:
    values = _parse_list(raw, cast=str, default=DEFAULT_SYMBOLS)
    return [str(item).strip().upper() for item in values if str(item).strip()]


def _pick_price(bid: float | None, ask: float | None, last: float | None) -> float | None:
    if bid is not None and ask is not None and bid > 0.0 and ask > 0.0:
        return (float(bid) + float(ask)) / 2.0
    if last is not None and last > 0.0:
        return float(last)
    if bid is not None and bid > 0.0:
        return float(bid)
    if ask is not None and ask > 0.0:
        return float(ask)
    return None


def _bucket_start(ts: datetime, bar_minutes: int) -> datetime:
    # Floor to N-minute bucket from the start of day.
    interval = max(int(bar_minutes), 1)
    minute_of_day = ts.hour * 60 + ts.minute
    floored = (minute_of_day // interval) * interval
    bucket_hour = floored // 60
    bucket_minute = floored % 60
    return ts.replace(hour=bucket_hour, minute=bucket_minute, second=0, microsecond=0)


def _build_bar_closes(points: list[tuple[datetime, float]], *, bar_minutes: int) -> list[tuple[datetime, float]]:
    last_price_by_bucket: dict[datetime, float] = {}
    for ts, price in points:
        bucket = _bucket_start(ts, bar_minutes=max(int(bar_minutes), 1))
        last_price_by_bucket[bucket] = price
    return sorted(last_price_by_bucket.items(), key=lambda item: item[0])


def _latest_preceding_within(
    *,
    shock_ts: datetime,
    event_ts: list[datetime],
    event_meta: list[EventRef],
    max_delay_minutes: int,
) -> tuple[EventRef | None, float | None]:
    if not event_ts:
        return None, None
    idx = bisect_right(event_ts, shock_ts) - 1
    if idx < 0:
        return None, None
    event = event_meta[idx]
    delay_min = (shock_ts - event.event_ts).total_seconds() / 60.0
    if delay_min < 0.0 or delay_min > float(max_delay_minutes):
        return None, None
    return event, delay_min


def _majority_direction(rows: list[tuple[str, str]]) -> str | None:
    if not rows:
        return None
    counts = Counter(direction for _, direction in rows if direction in {"up", "down", "neutral"})
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _resolve_db_path(config_path: str | None, db_path_arg: str | None) -> Path:
    if db_path_arg:
        return Path(db_path_arg)
    settings = load_settings(config_path)
    return resolve_paths(settings).data_dir / "moex_carry.db"


def _fetch_quote_points(
    *,
    conn: sqlite3.Connection,
    symbols: list[str],
    period_from: datetime,
    period_to: datetime,
) -> dict[str, list[tuple[datetime, float]]]:
    placeholders = ",".join("?" for _ in symbols)
    query = f"""
        select secid, timestamp, bid, ask, last
        from quotes
        where secid in ({placeholders})
          and timestamp >= ?
          and timestamp <= ?
        order by secid asc, timestamp asc
    """
    params = [*symbols, period_from.isoformat(sep=" "), period_to.isoformat(sep=" ")]
    rows = conn.execute(query, params).fetchall()
    by_symbol: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for secid, ts_raw, bid, ask, last in rows:
        price = _pick_price(bid, ask, last)
        if price is None:
            continue
        by_symbol[str(secid)].append((_parse_datetime(ts_raw), float(price)))
    return by_symbol


def _fetch_broad_events(
    *,
    conn: sqlite3.Connection,
    period_from: datetime,
    period_to: datetime,
) -> tuple[list[datetime], list[EventRef]]:
    query = """
        select e.event_id, e.event_first_published_at_utc, i.title, i.url
        from news_events e
        left join news_event_items ei
          on ei.event_id = e.event_id and ei.link_role = 'primary'
        left join news_items i
          on i.news_id = ei.news_id
        where e.event_first_published_at_utc is not null
          and e.event_first_published_at_utc >= ?
          and e.event_first_published_at_utc <= ?
        order by e.event_first_published_at_utc asc
    """
    rows = conn.execute(
        query,
        (
            (period_from - timedelta(days=1)).isoformat(sep=" "),
            (period_to + timedelta(days=1)).isoformat(sep=" "),
        ),
    ).fetchall()
    ts_list: list[datetime] = []
    refs: list[EventRef] = []
    for event_id, ts_raw, title, url in rows:
        ts = _parse_datetime(ts_raw)
        ts_list.append(ts)
        refs.append(
            EventRef(
                event_id=str(event_id),
                event_ts=ts,
                title=str(title) if title is not None else None,
                url=str(url) if url is not None else None,
                source="broad",
            )
        )
    return ts_list, refs


def _fetch_v2_clean_events_by_symbol(
    *,
    conn: sqlite3.Connection,
    symbols: list[str],
    period_from: datetime,
    period_to: datetime,
) -> dict[str, tuple[list[datetime], list[EventRef]]]:
    result: dict[str, tuple[list[datetime], list[EventRef]]] = {}
    query = """
        select distinct t.event_id, t.t0, i.title, i.url
        from event_target_v2 t
        left join news_event_items ei
          on ei.event_id = t.event_id and ei.link_role = 'primary'
        left join news_items i
          on i.news_id = ei.news_id
        where t.symbol = ?
          and t.horizon = '1h'
          and t.t0 is not null
          and t.t0 >= ?
          and t.t0 <= ?
          and coalesce(t.is_repost, 0) = 0
          and coalesce(t.is_overlapped, 0) = 0
          and coalesce(t.leakage_postmove, 0) = 0
        order by t.t0 asc
    """
    for symbol in symbols:
        rows = conn.execute(
            query,
            (
                symbol,
                (period_from - timedelta(days=1)).isoformat(sep=" "),
                (period_to + timedelta(days=1)).isoformat(sep=" "),
            ),
        ).fetchall()
        ts_list: list[datetime] = []
        refs: list[EventRef] = []
        for event_id, ts_raw, title, url in rows:
            ts = _parse_datetime(ts_raw)
            ts_list.append(ts)
            refs.append(
                EventRef(
                    event_id=str(event_id),
                    event_ts=ts,
                    title=str(title) if title is not None else None,
                    url=str(url) if url is not None else None,
                    source="v2_clean",
                )
            )
        result[symbol] = (ts_list, refs)
    return result


def _load_label_summary_by_event(*, conn: sqlite3.Connection) -> dict[str, LabelSummary]:
    rows = conn.execute(
        """
        select target_id, quality, direction_label, source
        from news_gold_labels
        where target_type = 'event'
        """
    ).fetchall()
    by_event_quality: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for event_id, quality, direction, source in rows:
        event_key = str(event_id)
        quality_key = str(quality or "").lower()
        direction_value = str(direction or "").lower()
        source_value = str(source or "")
        by_event_quality[event_key][quality_key].append((source_value, direction_value))

    summary: dict[str, LabelSummary] = {}
    for event_id, qualities in by_event_quality.items():
        gold_rows = qualities.get("gold", [])
        silver_rows = qualities.get("silver", [])
        summary[event_id] = LabelSummary(
            has_any=bool(gold_rows or silver_rows),
            has_gold=bool(gold_rows),
            has_silver=bool(silver_rows),
            gold_direction=_majority_direction(gold_rows),
            silver_direction=_majority_direction(silver_rows),
            gold_source_count=len({source for source, _ in gold_rows}),
            silver_source_count=len({source for source, _ in silver_rows}),
        )
    return summary


def _shock_direction(logret: float) -> str:
    if logret > 0.0:
        return "up"
    if logret < 0.0:
        return "down"
    return "neutral"


def _label_direction_match(label_direction: str | None, shock_direction: str) -> int | None:
    if label_direction not in {"up", "down"}:
        return None
    if shock_direction not in {"up", "down"}:
        return None
    return int(label_direction == shock_direction)


def run_export(args: argparse.Namespace) -> int:
    symbols = _parse_symbols(args.symbols)
    thresholds = _parse_list(args.z_thresholds, cast=float, default=DEFAULT_THRESHOLDS)
    db_path = _resolve_db_path(args.config, args.db_path)
    out_dir = Path(args.out_dir) if args.out_dir else (Path("data") / "output")
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        placeholders = ",".join("?" for _ in symbols)
        max_ts_row = conn.execute(
            f"select max(timestamp) from quotes where secid in ({placeholders})",
            symbols,
        ).fetchone()
        if max_ts_row is None or max_ts_row[0] is None:
            raise RuntimeError("No quotes found for selected symbols")
        period_to = _parse_datetime(max_ts_row[0])
        period_from = period_to - timedelta(days=max(int(args.period_days), 1))

        quote_points_by_symbol = _fetch_quote_points(
            conn=conn,
            symbols=symbols,
            period_from=period_from,
            period_to=period_to,
        )
        broad_ts, broad_refs = _fetch_broad_events(conn=conn, period_from=period_from, period_to=period_to)
        v2_map = _fetch_v2_clean_events_by_symbol(
            conn=conn,
            symbols=symbols,
            period_from=period_from,
            period_to=period_to,
        )
        labels_by_event = _load_label_summary_by_event(conn=conn)
    finally:
        conn.close()

    all_rows: list[dict[str, object]] = []
    for symbol in symbols:
        quote_points = quote_points_by_symbol.get(symbol, [])
        bar_points = _build_bar_closes(quote_points, bar_minutes=max(int(args.bar_minutes), 1))
        rolling = RollingStats(maxlen=max(int(args.lookback_bars), 2))
        v2_ts, v2_refs = v2_map.get(symbol, ([], []))

        for idx in range(1, len(bar_points)):
            prev_ts, prev_px = bar_points[idx - 1]
            cur_ts, cur_px = bar_points[idx]
            if prev_px <= 0.0 or cur_px <= 0.0:
                continue
            gap_hours = (cur_ts - prev_ts).total_seconds() / 3600.0
            if gap_hours > float(args.max_gap_hours):
                continue
            logret = math.log(cur_px / prev_px)
            abs_move_pct = abs(math.exp(logret) - 1.0) * 100.0

            if rolling.count >= max(int(args.min_std_bars), 2):
                sigma = rolling.sample_std()
                if sigma > 0.0:
                    z_score = abs(logret) / sigma
                    shock_dir = _shock_direction(logret)

                    broad_event, broad_delay = _latest_preceding_within(
                        shock_ts=cur_ts,
                        event_ts=broad_ts,
                        event_meta=broad_refs,
                        max_delay_minutes=max(int(args.causal_window_minutes), 1),
                    )
                    v2_event, v2_delay = _latest_preceding_within(
                        shock_ts=cur_ts,
                        event_ts=v2_ts,
                        event_meta=v2_refs,
                        max_delay_minutes=max(int(args.causal_window_minutes), 1),
                    )

                    selected = v2_event if v2_event is not None else broad_event
                    selected_delay = v2_delay if v2_event is not None else broad_delay

                    label = labels_by_event.get(selected.event_id) if selected is not None else None
                    label_has_any = bool(label.has_any) if label else False
                    label_has_gold = bool(label.has_gold) if label else False
                    label_has_silver = bool(label.has_silver) if label else False
                    gold_match = _label_direction_match(label.gold_direction, shock_dir) if label else None
                    silver_match = _label_direction_match(label.silver_direction, shock_dir) if label else None

                    all_rows.append(
                        {
                            "symbol": symbol,
                            "shock_ts": _to_iso_utc(cur_ts),
                            "prev_ts": _to_iso_utc(prev_ts),
                            "bar_minutes": int(args.bar_minutes),
                            "prev_price": prev_px,
                            "price": cur_px,
                            "logret": logret,
                            "abs_move_pct": abs_move_pct,
                            "shock_direction": shock_dir,
                            "rolling_sigma": sigma,
                            "z_score": z_score,
                            "broad_event_id": broad_event.event_id if broad_event else "",
                            "broad_event_ts": _to_iso_utc(broad_event.event_ts) if broad_event else "",
                            "broad_delay_min": round(float(broad_delay), 1) if broad_delay is not None else "",
                            "broad_title": broad_event.title or "" if broad_event else "",
                            "broad_url": broad_event.url or "" if broad_event else "",
                            "v2_event_id": v2_event.event_id if v2_event else "",
                            "v2_event_ts": _to_iso_utc(v2_event.event_ts) if v2_event else "",
                            "v2_delay_min": round(float(v2_delay), 1) if v2_delay is not None else "",
                            "v2_title": v2_event.title or "" if v2_event else "",
                            "v2_url": v2_event.url or "" if v2_event else "",
                            "selected_event_source": selected.source if selected else "",
                            "selected_event_id": selected.event_id if selected else "",
                            "selected_event_ts": _to_iso_utc(selected.event_ts) if selected else "",
                            "selected_delay_min": round(float(selected_delay), 1) if selected_delay is not None else "",
                            "selected_title": selected.title or "" if selected else "",
                            "selected_url": selected.url or "" if selected else "",
                            "label_has_any": int(label_has_any),
                            "label_has_gold": int(label_has_gold),
                            "label_has_silver": int(label_has_silver),
                            "label_gold_direction": label.gold_direction if label else "",
                            "label_silver_direction": label.silver_direction if label else "",
                            "gold_direction_match": "" if gold_match is None else int(gold_match),
                            "silver_direction_match": "" if silver_match is None else int(silver_match),
                        }
                    )

            rolling.add(logret)

    all_rows.sort(key=lambda row: (str(row["symbol"]), str(row["shock_ts"])))

    summary_rows: list[dict[str, object]] = []
    for threshold in sorted(set(float(x) for x in thresholds)):
        for symbol in symbols:
            subset = [
                row
                for row in all_rows
                if str(row["symbol"]) == symbol and float(row["z_score"]) >= threshold
            ]
            shock_count = len(subset)
            if shock_count <= 0:
                summary_rows.append(
                    {
                        "threshold_z": threshold,
                        "symbol": symbol,
                        "shock_count": 0,
                        "avg_abs_move_pct": 0.0,
                        "median_abs_move_pct": 0.0,
                        "broad_causal_count": 0,
                        "v2_causal_count": 0,
                        "selected_causal_count": 0,
                        "label_any_count": 0,
                        "label_gold_count": 0,
                        "label_silver_count": 0,
                        "gold_dir_match_cov": 0,
                        "gold_dir_match_acc": "",
                        "silver_dir_match_cov": 0,
                        "silver_dir_match_acc": "",
                    }
                )
                continue
            broad_causal_count = sum(1 for row in subset if str(row["broad_event_id"]))
            v2_causal_count = sum(1 for row in subset if str(row["v2_event_id"]))
            selected_count = sum(1 for row in subset if str(row["selected_event_id"]))
            label_any_count = sum(int(row["label_has_any"]) for row in subset)
            label_gold_count = sum(int(row["label_has_gold"]) for row in subset)
            label_silver_count = sum(int(row["label_has_silver"]) for row in subset)

            gold_matches = [row["gold_direction_match"] for row in subset if row["gold_direction_match"] != ""]
            silver_matches = [row["silver_direction_match"] for row in subset if row["silver_direction_match"] != ""]

            summary_rows.append(
                {
                    "threshold_z": threshold,
                    "symbol": symbol,
                    "shock_count": shock_count,
                    "avg_abs_move_pct": round(mean(float(row["abs_move_pct"]) for row in subset), 6),
                    "median_abs_move_pct": round(median(float(row["abs_move_pct"]) for row in subset), 6),
                    "broad_causal_count": broad_causal_count,
                    "v2_causal_count": v2_causal_count,
                    "selected_causal_count": selected_count,
                    "label_any_count": label_any_count,
                    "label_gold_count": label_gold_count,
                    "label_silver_count": label_silver_count,
                    "gold_dir_match_cov": len(gold_matches),
                    "gold_dir_match_acc": (
                        round(sum(int(x) for x in gold_matches) / len(gold_matches), 6) if gold_matches else ""
                    ),
                    "silver_dir_match_cov": len(silver_matches),
                    "silver_dir_match_acc": (
                        round(sum(int(x) for x in silver_matches) / len(silver_matches), 6)
                        if silver_matches
                        else ""
                    ),
                }
            )

    detail_path = out_dir / "shock_news_1h_annual_all.csv"
    with detail_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(all_rows[0].keys()) if all_rows else []
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(all_rows)

    summary_path = out_dir / "shock_news_1h_annual_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(summary_rows[0].keys()) if summary_rows else []
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(summary_rows)

    pack_threshold = float(args.pack_threshold)
    pack_rows = [
        row for row in all_rows if float(row["z_score"]) >= pack_threshold and str(row["selected_event_id"])
    ]
    pack_rows.sort(key=lambda row: float(row["z_score"]), reverse=True)
    if int(args.max_pack_items) > 0:
        pack_rows = pack_rows[: int(args.max_pack_items)]

    pack_path = out_dir / f"shock_news_pro_tasks_zge{str(pack_threshold).replace('.', 'p')}.jsonl"
    with pack_path.open("w", encoding="utf-8") as handle:
        for idx, row in enumerate(pack_rows, start=1):
            task = {
                "task_id": f"shock-{idx:04d}-{row['symbol']}-{row['shock_ts']}",
                "shock": {
                    "symbol": row["symbol"],
                    "shock_ts_utc": row["shock_ts"],
                    "shock_direction": row["shock_direction"],
                    "abs_move_pct": round(float(row["abs_move_pct"]), 4),
                    "z_score": round(float(row["z_score"]), 4),
                },
                "candidate": {
                    "event_id": row["selected_event_id"],
                    "source": row["selected_event_source"],
                    "event_ts_utc": row["selected_event_ts"],
                    "delay_min": row["selected_delay_min"],
                    "title": row["selected_title"],
                    "url": row["selected_url"],
                },
                "secondary_candidates": [
                    {
                        "source": "v2_clean",
                        "event_id": row["v2_event_id"],
                        "event_ts_utc": row["v2_event_ts"],
                        "delay_min": row["v2_delay_min"],
                        "title": row["v2_title"],
                        "url": row["v2_url"],
                    },
                    {
                        "source": "broad",
                        "event_id": row["broad_event_id"],
                        "event_ts_utc": row["broad_event_ts"],
                        "delay_min": row["broad_delay_min"],
                        "title": row["broad_title"],
                        "url": row["broad_url"],
                    },
                ],
                "existing_label_snapshot": {
                    "has_any": bool(int(row["label_has_any"])),
                    "has_gold": bool(int(row["label_has_gold"])),
                    "has_silver": bool(int(row["label_has_silver"])),
                    "gold_direction": row["label_gold_direction"] or None,
                    "silver_direction": row["label_silver_direction"] or None,
                },
                "expected_answer_schema": {
                    "event_id": "string",
                    "is_causal": "yes|no|uncertain",
                    "direction_label": "up|down|neutral",
                    "confidence": "float_0_1",
                    "notes": "string_short",
                },
            }
            handle.write(json.dumps(task, ensure_ascii=False) + "\n")

    readme_lines = [
        "# Shock -> News (ChatGPT PRO) Label Pack",
        "",
        f"Period: {period_from.isoformat()} -> {period_to.isoformat()}",
        f"Symbols: {', '.join(symbols)}",
        f"Bar: {int(args.bar_minutes)}m",
        f"Causal window: {int(args.causal_window_minutes)}m (news must be before shock)",
        "",
        "## Files",
        f"- Summary: `{summary_path.as_posix()}`",
        f"- Detail: `{detail_path.as_posix()}`",
        f"- PRO tasks: `{pack_path.as_posix()}`",
        "",
        "## Prompt for ChatGPT PRO",
        "Return ONLY JSONL.",
        "One line per task with fields:",
        '- `event_id` (string, from candidate.event_id)',
        '- `is_causal` (`yes|no|uncertain`)',
        '- `direction_label` (`up|down|neutral`)',
        '- `confidence` (0..1 float)',
        "- `notes` (short string)",
        "",
        "No markdown. No explanations. JSONL only.",
    ]
    readme_path = out_dir / "README_SHOCK_NEWS_PRO_LABELING.md"
    readme_path.write_text("\n".join(readme_lines), encoding="utf-8")

    print(
        json.dumps(
            {
                "period_from": period_from.isoformat() + "Z",
                "period_to": period_to.isoformat() + "Z",
                "symbols": symbols,
                "thresholds": sorted(set(float(x) for x in thresholds)),
                "shock_rows_total": len(all_rows),
                "summary_rows_total": len(summary_rows),
                "pack_threshold": pack_threshold,
                "pack_rows_total": len(pack_rows),
                "summary_path": summary_path.as_posix(),
                "detail_path": detail_path.as_posix(),
                "pack_path": pack_path.as_posix(),
                "readme_path": readme_path.as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export_shock_news_pro_pack",
        description="Build annual shock-first analytics and ChatGPT PRO labeling pack from local DB.",
    )
    parser.add_argument("--config", type=str, default=None, help="Optional YAML config path")
    parser.add_argument("--db-path", type=str, default=None, help="Optional explicit sqlite DB path")
    parser.add_argument("--out-dir", type=str, default=None, help="Output directory (default: data/output)")
    parser.add_argument("--symbols", type=str, default="NG_US,BRN,GOLD")
    parser.add_argument("--period-days", type=int, default=365)
    parser.add_argument("--bar-minutes", type=int, default=60)
    parser.add_argument("--lookback-bars", type=int, default=480)
    parser.add_argument("--min-std-bars", type=int, default=120)
    parser.add_argument("--max-gap-hours", type=float, default=2.5)
    parser.add_argument("--causal-window-minutes", type=int, default=60)
    parser.add_argument("--z-thresholds", type=str, default="2.0,2.5,3.0")
    parser.add_argument("--pack-threshold", type=float, default=2.5)
    parser.add_argument("--max-pack-items", type=int, default=0, help="0 means all")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_export(args)


if __name__ == "__main__":
    raise SystemExit(main())
