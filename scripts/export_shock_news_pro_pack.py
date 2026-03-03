from __future__ import annotations

import argparse
import csv
import json
import math
import re
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
_ROOT_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "after",
    "amid",
    "update",
    "updated",
    "follow",
    "follows",
    "followup",
    "revision",
    "revised",
    "report",
    "reports",
    "reporting",
    "says",
    "say",
    "said",
    "news",
    "live",
    "analysis",
}
_BRN_TEXT_CUES = (
    "brent",
    "crude oil",
    "oil prices",
    "opec",
    "barrel",
    "wti",
)
_GOLD_TEXT_CUES = (
    "gold",
    "bullion",
    "xau",
    "spot gold",
)
_GAS_GENERAL_CUES = (
    "natural gas",
    "natgas",
    "lng",
    "henry hub",
    "nymex gas",
)
_GAS_US_CUES = (
    "henry hub",
    "nymex",
    "u.s.",
    "us natural gas",
    "u.s. natural gas",
    "u.s. gas",
    "usa",
    "united states",
    "american gas",
    "eia",
    "freeport",
    "sabine",
    "louisiana",
    "texas",
    "permian",
    "marcellus",
    "haynesville",
)
_GAS_EU_CUES = (
    "ttf",
    "title transfer facility",
    "nbp",
    "dutch gas",
    "european gas",
    "europe",
    "european union",
    "eu ",
    "eu gas",
    "uk gas",
    "greece",
    "german",
    "france",
    "italy",
    "netherlands",
    "ice endex",
)
_CROSS_ASSET_GEO_CUES = (
    "iran",
    "tehran",
    "hormuz",
    "strait of hormuz",
    "israel",
    "u.s. strikes",
    "us strikes",
    "air strike",
    "missile",
    "drone strike",
    "military strike",
    "war",
    "conflict",
    "irgc",
    "sanctions",
    "shipping route",
    "gulf markets",
)


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


@dataclass(frozen=True)
class RootEventRef:
    root_event_id: str
    root_event_ts: datetime
    root_title: str | None
    aftershock_rank: int


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


def _contains_phrase(text: str, phrase: str) -> bool:
    body = str(text or "").lower()
    needle = str(phrase or "").strip().lower()
    if not body or not needle:
        return False
    if " " in needle or "-" in needle or "/" in needle:
        return needle in body
    pattern = rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
    return re.search(pattern, body) is not None


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    for phrase in phrases:
        if _contains_phrase(text, str(phrase)):
            return True
    return False


def _supports_ng_us(text: str) -> bool:
    lowered = str(text or "").lower()
    if not _contains_any(lowered, _GAS_GENERAL_CUES):
        return False
    has_us = _contains_any(lowered, _GAS_US_CUES)
    has_eu = _contains_any(lowered, _GAS_EU_CUES)
    if has_eu and not has_us:
        return False
    return bool(has_us)


def _normalized_entity_tokens(raw: object) -> list[str]:
    if raw is None:
        return []
    values: list[str] = []
    for item in str(raw).split(","):
        token = str(item or "").strip().upper().replace("-", "_").replace(" ", "_")
        if token:
            values.append(token)
    return values


def _normalize_event_symbols(*, entity_tokens: Iterable[str], text: str) -> set[str]:
    symbols: set[str] = set()
    lowered = str(text or "").lower()
    brn_text = _contains_any(lowered, _BRN_TEXT_CUES)
    gold_text = _contains_any(lowered, _GOLD_TEXT_CUES)
    ng_us_text = _supports_ng_us(lowered)
    gas_has_us = _contains_any(lowered, _GAS_US_CUES)
    gas_has_eu = _contains_any(lowered, _GAS_EU_CUES)
    token_set = {str(item or "").strip().upper() for item in entity_tokens if str(item or "").strip()}
    if "BRN" in token_set and brn_text:
        symbols.add("BRN")
    if ("GOLD" in token_set or "XAU" in token_set) and gold_text:
        symbols.add("GOLD")
    if "NG_US" in token_set and ng_us_text and not (gas_has_eu and not gas_has_us):
        symbols.add("NG_US")

    if {"OIL", "WTI", "CRUDE", "BRENT"} & token_set and brn_text:
        symbols.add("BRN")
    if {"GLD", "BULLION"} & token_set and gold_text:
        symbols.add("GOLD")
    if {"GAS", "NATGAS", "NATURAL_GAS", "NG", "LNG"} & token_set and ng_us_text:
        symbols.add("NG_US")

    if brn_text:
        symbols.add("BRN")
    if gold_text:
        symbols.add("GOLD")
    if ng_us_text:
        symbols.add("NG_US")
    # Geopolitical shock can propagate across oil/gold/gas even without explicit ticker mention.
    if _contains_any(lowered, _CROSS_ASSET_GEO_CUES):
        symbols.update({"BRN", "GOLD", "NG_US"})
    return symbols


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


def _ensure_runtime_indexes(*, conn: sqlite3.Connection) -> None:
    # Speed up hot queries on primary-event joins for large windows.
    conn.execute(
        """
        create index if not exists ix_news_event_items_role_event_added_news
        on news_event_items(link_role, event_id, added_at, news_id)
        """
    )
    conn.execute(
        """
        create index if not exists ix_news_events_pub_event
        on news_events(event_first_published_at_utc, event_id)
        """
    )
    conn.commit()


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


def _fetch_primary_news_map(
    *,
    conn: sqlite3.Connection,
    event_ids: list[str] | None = None,
) -> dict[str, tuple[str | None, str | None]]:
    # Load canonical primary headline/url only for relevant events in the current run.
    normalized_ids = sorted({str(item).strip() for item in (event_ids or []) if str(item).strip()})
    if not normalized_ids:
        return {}

    mapping: dict[str, tuple[str | None, str | None]] = {}
    chunk_size = 800
    for offset in range(0, len(normalized_ids), chunk_size):
        chunk = normalized_ids[offset : offset + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            with first_added as (
                select event_id, min(coalesce(added_at, '9999-12-31 23:59:59.999999')) as min_added
                from news_event_items
                where link_role = 'primary'
                  and event_id in ({placeholders})
                group by event_id
            )
            select ei.event_id, ei.news_id, i.title, i.url
            from news_event_items ei
            join first_added fa
              on fa.event_id = ei.event_id
             and fa.min_added = coalesce(ei.added_at, '9999-12-31 23:59:59.999999')
            left join news_items i
              on i.news_id = ei.news_id
            where ei.link_role = 'primary'
              and ei.event_id in ({placeholders})
            order by ei.event_id asc, ei.news_id asc
            """,
            [*chunk, *chunk],
        ).fetchall()
        for event_id, _news_id, title, url in rows:
            key = str(event_id)
            if key in mapping:
                continue
            mapping[key] = (
                str(title) if title is not None else None,
                str(url) if url is not None else None,
            )
    return mapping


def _enrich_event_refs(
    refs: list[EventRef],
    primary_news: dict[str, tuple[str | None, str | None]],
) -> list[EventRef]:
    if not refs or not primary_news:
        return refs
    enriched: list[EventRef] = []
    for ref in refs:
        title, url = primary_news.get(ref.event_id, (ref.title, ref.url))
        if title == ref.title and url == ref.url:
            enriched.append(ref)
            continue
        enriched.append(
            EventRef(
                event_id=ref.event_id,
                event_ts=ref.event_ts,
                title=title,
                url=url,
                source=ref.source,
            )
        )
    return enriched


def _fetch_broad_events_by_symbol(
    *,
    conn: sqlite3.Connection,
    symbols: list[str],
    period_from: datetime,
    period_to: datetime,
    primary_news: dict[str, tuple[str | None, str | None]],
) -> dict[str, tuple[list[datetime], list[EventRef]]]:
    by_symbol: dict[str, list[EventRef]] = {symbol: [] for symbol in symbols}
    query = """
        select
            e.event_id,
            e.event_first_published_at_utc,
            e.canonical_summary,
            e.canonical_mechanism,
            group_concat(distinct upper(coalesce(l.ticker, l.entity_id))) as entity_tokens
        from news_events e
        left join news_event_items ei
          on ei.event_id = e.event_id
        left join news_entity_links l
          on l.news_id = ei.news_id
        where e.event_first_published_at_utc is not null
          and e.event_first_published_at_utc >= ?
          and e.event_first_published_at_utc <= ?
        group by
            e.event_id,
            e.event_first_published_at_utc,
            e.canonical_summary,
            e.canonical_mechanism
        order by e.event_first_published_at_utc asc, e.event_id asc
    """
    rows = conn.execute(
        query,
        (
            (period_from - timedelta(days=1)).isoformat(sep=" "),
            (period_to + timedelta(days=1)).isoformat(sep=" "),
        ),
    ).fetchall()
    for event_id, ts_raw, canonical_summary, canonical_mechanism, entity_tokens in rows:
        title, url = primary_news.get(str(event_id), (None, None))
        ts = _parse_datetime(ts_raw)
        summary_text = str(canonical_summary or "").strip()
        mechanism_text = str(canonical_mechanism or "").strip()
        title_text = str(title or "").strip()
        normalization_text = " ".join(part for part in (title_text, summary_text, mechanism_text) if part).strip()
        normalized_symbols = _normalize_event_symbols(
            entity_tokens=_normalized_entity_tokens(entity_tokens),
            text=normalization_text,
        )
        for symbol in symbols:
            if symbol not in normalized_symbols:
                continue
            by_symbol.setdefault(symbol, []).append(
                EventRef(
                    event_id=str(event_id),
                    event_ts=ts,
                    title=title_text or summary_text or None,
                    url=str(url) if url is not None else None,
                    source="broad",
                )
            )
    prepared: dict[str, tuple[list[datetime], list[EventRef]]] = {}
    for symbol in symbols:
        refs = sorted(
            by_symbol.get(symbol, []),
            key=lambda item: (item.event_ts, item.event_id),
        )
        prepared[symbol] = ([item.event_ts for item in refs], refs)
    return prepared


def _root_tokens(text: str, *, max_tokens: int = 14) -> set[str]:
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]{3,}", str(text or "").lower()):
        if token in _ROOT_STOPWORDS:
            continue
        if token.isdigit():
            continue
        tokens.append(token)
        if len(tokens) >= max_tokens:
            break
    return set(tokens)


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return float(len(left & right)) / float(len(union))


def _build_root_event_map(
    refs: list[EventRef],
    *,
    root_window_minutes: int,
    min_similarity: float,
) -> dict[str, RootEventRef]:
    deduped: dict[str, EventRef] = {}
    for ref in sorted(refs, key=lambda item: (item.event_ts, item.event_id)):
        deduped.setdefault(ref.event_id, ref)
    ordered = list(deduped.values())
    roots: list[dict[str, object]] = []
    mapping: dict[str, RootEventRef] = {}

    window_delta = timedelta(minutes=max(int(root_window_minutes), 1))
    similarity_threshold = max(float(min_similarity), 0.0)

    for ref in ordered:
        title_tokens = _root_tokens(ref.title or "")
        matched_index: int | None = None
        matched_score = 0.0

        for idx, root in enumerate(roots):
            root_last_ts = root.get("last_ts")
            root_tokens = root.get("tokens")
            if not isinstance(root_last_ts, datetime) or not isinstance(root_tokens, set):
                continue
            if (ref.event_ts - root_last_ts) > window_delta:
                continue
            score = _jaccard_similarity(title_tokens, root_tokens)
            if score < similarity_threshold:
                continue
            if score > matched_score:
                matched_score = score
                matched_index = idx

        if matched_index is None:
            roots.append(
                {
                    "root_event_id": ref.event_id,
                    "root_event_ts": ref.event_ts,
                    "root_title": ref.title,
                    "tokens": set(title_tokens),
                    "last_ts": ref.event_ts,
                    "count": 1,
                }
            )
            mapping[ref.event_id] = RootEventRef(
                root_event_id=ref.event_id,
                root_event_ts=ref.event_ts,
                root_title=ref.title,
                aftershock_rank=0,
            )
            continue

        root = roots[matched_index]
        rank = int(root.get("count") or 0)
        root["count"] = rank + 1
        root["last_ts"] = ref.event_ts
        root["tokens"] = set(root.get("tokens") or set()) | title_tokens
        mapping[ref.event_id] = RootEventRef(
            root_event_id=str(root.get("root_event_id") or ref.event_id),
            root_event_ts=root.get("root_event_ts") if isinstance(root.get("root_event_ts"), datetime) else ref.event_ts,
            root_title=str(root.get("root_title") or "") or ref.title,
            aftershock_rank=rank,
        )
    return mapping


def _fetch_v2_clean_events_by_symbol(
    *,
    conn: sqlite3.Connection,
    symbols: list[str],
    period_from: datetime,
    period_to: datetime,
    primary_news: dict[str, tuple[str | None, str | None]],
) -> dict[str, tuple[list[datetime], list[EventRef]]]:
    result: dict[str, tuple[list[datetime], list[EventRef]]] = {}
    query = """
        select
            t.event_id,
            coalesce(e.event_first_published_at_utc, t.t0) as event_ts
        from event_target_v2 t
        left join news_events e
          on e.event_id = t.event_id
        where t.symbol = ?
          and t.horizon = '1h'
          and coalesce(e.event_first_published_at_utc, t.t0) is not null
          and coalesce(e.event_first_published_at_utc, t.t0) >= ?
          and coalesce(e.event_first_published_at_utc, t.t0) <= ?
          and coalesce(t.is_repost, 0) = 0
          and coalesce(t.is_overlapped, 0) = 0
          and coalesce(t.leakage_postmove, 0) = 0
        order by coalesce(e.event_first_published_at_utc, t.t0) asc, t.event_id asc
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
        for event_id, ts_raw in rows:
            title, url = primary_news.get(str(event_id), (None, None))
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
        _ensure_runtime_indexes(conn=conn)
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
        broad_map = _fetch_broad_events_by_symbol(
            conn=conn,
            symbols=symbols,
            period_from=period_from,
            period_to=period_to,
            primary_news={},
        )
        v2_map = _fetch_v2_clean_events_by_symbol(
            conn=conn,
            symbols=symbols,
            period_from=period_from,
            period_to=period_to,
            primary_news={},
        )
        candidate_event_ids: set[str] = set()
        for _symbol, (_ts_values, refs) in broad_map.items():
            for ref in refs:
                if ref.event_id:
                    candidate_event_ids.add(ref.event_id)
        for _symbol, (_ts_values, refs) in v2_map.items():
            for ref in refs:
                if ref.event_id:
                    candidate_event_ids.add(ref.event_id)
        primary_news = _fetch_primary_news_map(conn=conn, event_ids=sorted(candidate_event_ids))
        broad_map = _fetch_broad_events_by_symbol(
            conn=conn,
            symbols=symbols,
            period_from=period_from,
            period_to=period_to,
            primary_news=primary_news,
        )
        v2_map = {
            key: (ts_values, _enrich_event_refs(refs, primary_news))
            for key, (ts_values, refs) in v2_map.items()
        }
        root_map_by_symbol: dict[str, dict[str, RootEventRef]] = {}
        for symbol in symbols:
            merged_refs: dict[str, EventRef] = {}
            for ref in broad_map.get(symbol, ([], []))[1]:
                merged_refs.setdefault(ref.event_id, ref)
            for ref in v2_map.get(symbol, ([], []))[1]:
                merged_refs.setdefault(ref.event_id, ref)
            root_map_by_symbol[symbol] = _build_root_event_map(
                list(merged_refs.values()),
                root_window_minutes=max(int(args.root_window_minutes), 1),
                min_similarity=float(args.root_similarity),
            )
        labels_by_event = _load_label_summary_by_event(conn=conn)
    finally:
        conn.close()

    all_rows: list[dict[str, object]] = []
    for symbol in symbols:
        quote_points = quote_points_by_symbol.get(symbol, [])
        bar_points = _build_bar_closes(quote_points, bar_minutes=max(int(args.bar_minutes), 1))
        rolling = RollingStats(maxlen=max(int(args.lookback_bars), 2))
        broad_ts, broad_refs = broad_map.get(symbol, ([], []))
        v2_ts, v2_refs = v2_map.get(symbol, ([], []))
        roots = root_map_by_symbol.get(symbol, {})

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
                    root_meta = roots.get(selected.event_id) if selected is not None else None

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
                            "selected_root_event_id": root_meta.root_event_id if root_meta is not None else "",
                            "selected_root_event_ts": (
                                _to_iso_utc(root_meta.root_event_ts) if root_meta is not None else ""
                            ),
                            "selected_root_title": root_meta.root_title if root_meta is not None else "",
                            "selected_is_root_event": (
                                int(bool(selected is not None and root_meta is not None and selected.event_id == root_meta.root_event_id))
                            ),
                            "selected_aftershock_rank": int(root_meta.aftershock_rank) if root_meta is not None else "",
                            "selected_root_delay_min": (
                                round((cur_ts - root_meta.root_event_ts).total_seconds() / 60.0, 1)
                                if root_meta is not None
                                else ""
                            ),
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
                        "selected_root_unique_count": 0,
                        "selected_root_primary_count": 0,
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
            selected_root_unique = {
                str(row.get("selected_root_event_id") or "").strip()
                for row in subset
                if str(row.get("selected_root_event_id") or "").strip()
            }
            selected_root_primary_count = sum(1 for row in subset if int(row.get("selected_is_root_event") or 0) == 1)
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
                    "selected_root_unique_count": len(selected_root_unique),
                    "selected_root_primary_count": selected_root_primary_count,
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
    if bool(args.pack_root_only):
        best_by_root: dict[tuple[str, str], dict[str, object]] = {}
        for row in pack_rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            root_event_id = str(row.get("selected_root_event_id") or "").strip()
            event_key = root_event_id or str(row.get("selected_event_id") or "").strip()
            if not symbol or not event_key:
                continue
            key = (symbol, event_key)
            prev = best_by_root.get(key)
            if prev is None:
                best_by_root[key] = row
                continue
            prev_rank = int(prev.get("selected_aftershock_rank") or 9999)
            new_rank = int(row.get("selected_aftershock_rank") or 9999)
            if new_rank < prev_rank:
                best_by_root[key] = row
                continue
            if new_rank == prev_rank and float(row.get("z_score") or 0.0) > float(prev.get("z_score") or 0.0):
                best_by_root[key] = row
        pack_rows = list(best_by_root.values())
        pack_rows.sort(
            key=lambda row: (
                str(row.get("symbol") or ""),
                str(row.get("selected_root_event_ts") or row.get("selected_event_ts") or ""),
                -float(row.get("z_score") or 0.0),
            )
        )
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
                    "root_event_id": row.get("selected_root_event_id") or row["selected_event_id"],
                    "root_event_ts_utc": row.get("selected_root_event_ts") or row["selected_event_ts"],
                    "is_root_event": bool(int(row.get("selected_is_root_event") or 0)),
                    "aftershock_rank": row.get("selected_aftershock_rank"),
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
        f"Root-only pack: {'yes' if bool(args.pack_root_only) else 'no'}",
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
    parser.add_argument("--root-window-minutes", type=int, default=720)
    parser.add_argument("--root-similarity", type=float, default=0.40)
    parser.add_argument("--z-thresholds", type=str, default="2.0,2.5,3.0")
    parser.add_argument("--pack-threshold", type=float, default=2.5)
    parser.add_argument("--pack-root-only", action="store_true", default=True)
    parser.add_argument("--no-pack-root-only", dest="pack_root_only", action="store_false")
    parser.add_argument("--max-pack-items", type=int, default=0, help="0 means all")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_export(args)


if __name__ == "__main__":
    raise SystemExit(main())
