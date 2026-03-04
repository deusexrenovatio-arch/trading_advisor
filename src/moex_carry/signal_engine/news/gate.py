from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sqlite3
from typing import Any


SEVERITY_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_FUT_MONTH_CODE_RE = re.compile(r"^([A-Za-z0-9]+?)[FGHJKMNQUVXZ]\d{1,2}$")
_DEFAULT_COMMODITY_MAP: dict[str, str] = {
    "BR": "BRN",
    "BRN": "BRN",
    "NG": "NG_US",
    "NGUS": "NG_US",
    "NG_US": "NG_US",
    "GD": "GOLD",
    "GL": "GOLD",
    "GOLD": "GOLD",
}


@dataclass(frozen=True)
class NewsGateItem:
    article_id: str
    published_at_utc: datetime
    source: str
    title: str
    severity: str
    impact_score: float
    confidence: float
    commodity: str


@dataclass(frozen=True)
class NewsGateDecision:
    action: str
    highest_severity: str
    commodity: str | None
    matched_items: tuple[NewsGateItem, ...]
    reasons: tuple[str, ...]


def _severity_value(severity: str) -> int:
    return int(SEVERITY_ORDER.get(str(severity or "").strip().lower(), -1))


def _instrument_group(instrument_id: str) -> str:
    secid = str(instrument_id or "").strip()
    matched = _FUT_MONTH_CODE_RE.match(secid)
    if matched:
        return str(matched.group(1)).upper()
    return secid.upper()


def _sqlite_path_from_url(database_url: str) -> Path:
    normalized = str(database_url or "").strip()
    if normalized.startswith("sqlite:///"):
        return Path(normalized[len("sqlite:///") :])
    if normalized.startswith("sqlite://"):
        return Path(normalized[len("sqlite://") :])
    raise ValueError(f"unsupported_news_db_url:{database_url}")


def _parse_utc(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class CommodityNewsGate:
    def __init__(self, cfg: dict[str, Any] | None = None):
        raw = dict(cfg or {})
        self.enabled = bool(raw.get("enabled", False))
        self.db_url = str(raw.get("db_url", "sqlite:///./data/news_livecheck_ng.db"))
        self.lookback_minutes = max(int(raw.get("lookback_minutes", 180)), 1)
        self.block_severity_threshold = str(raw.get("block_severity_threshold", "high")).strip().lower()
        self.reduce_severity_threshold = str(raw.get("reduce_severity_threshold", "medium")).strip().lower()
        self.min_impact_score = float(raw.get("min_impact_score", 0.35))
        self.min_confidence = float(raw.get("min_confidence", 0.9))
        self.max_items = max(int(raw.get("max_items", 200)), 1)
        self.reduce_max_setups = max(int(raw.get("reduce_max_setups", 1)), 1)
        sources = raw.get("sources") or []
        self.sources = {str(item).strip().lower() for item in sources if str(item).strip()}

        commodity_map = dict(_DEFAULT_COMMODITY_MAP)
        for key, value in dict(raw.get("commodity_map") or {}).items():
            normalized_key = str(key or "").strip().upper()
            normalized_value = str(value or "").strip().upper()
            if normalized_key and normalized_value:
                commodity_map[normalized_key] = normalized_value
        self.commodity_map = commodity_map

    def evaluate(self, *, as_of_ts: datetime, instrument_id: str) -> NewsGateDecision:
        if not self.enabled:
            return NewsGateDecision(
                action="allow",
                highest_severity="low",
                commodity=None,
                matched_items=(),
                reasons=("news_gate_disabled",),
            )
        try:
            commodity = self._resolve_commodity(instrument_id)
        except ValueError as exc:
            return NewsGateDecision(
                action="allow",
                highest_severity="low",
                commodity=None,
                matched_items=(),
                reasons=(str(exc),),
            )
        if not commodity:
            return NewsGateDecision(
                action="allow",
                highest_severity="low",
                commodity=None,
                matched_items=(),
                reasons=("commodity_unmapped",),
            )
        block_value = _severity_value(self.block_severity_threshold)
        reduce_value = _severity_value(self.reduce_severity_threshold)
        if block_value < 0 or reduce_value < 0 or block_value <= reduce_value:
            return NewsGateDecision(
                action="block",
                highest_severity="critical",
                commodity=commodity,
                matched_items=(),
                reasons=("invalid_severity_thresholds",),
            )

        try:
            db_path = _sqlite_path_from_url(self.db_url)
        except ValueError as exc:
            return NewsGateDecision(
                action="allow",
                highest_severity="low",
                commodity=commodity,
                matched_items=(),
                reasons=(str(exc),),
            )
        if not db_path.exists():
            return NewsGateDecision(
                action="allow",
                highest_severity="low",
                commodity=commodity,
                matched_items=(),
                reasons=("news_db_missing",),
            )

        items, errors = self._load_items(
            db_path=db_path,
            commodity=commodity,
            as_of_ts=as_of_ts,
        )
        if errors:
            return NewsGateDecision(
                action="allow",
                highest_severity="low",
                commodity=commodity,
                matched_items=(),
                reasons=tuple(errors),
            )
        if not items:
            return NewsGateDecision(
                action="allow",
                highest_severity="low",
                commodity=commodity,
                matched_items=(),
                reasons=(),
            )

        highest_item = max(items, key=lambda item: _severity_value(item.severity))
        highest_severity = str(highest_item.severity)
        has_block = any(_severity_value(item.severity) >= block_value for item in items)
        if has_block:
            return NewsGateDecision(
                action="block",
                highest_severity=highest_severity,
                commodity=commodity,
                matched_items=tuple(items),
                reasons=(),
            )
        has_reduce = any(_severity_value(item.severity) >= reduce_value for item in items)
        if has_reduce:
            return NewsGateDecision(
                action="reduce",
                highest_severity=highest_severity,
                commodity=commodity,
                matched_items=tuple(items),
                reasons=(),
            )
        return NewsGateDecision(
            action="allow",
            highest_severity=highest_severity,
            commodity=commodity,
            matched_items=tuple(items),
            reasons=(),
        )

    def _resolve_commodity(self, instrument_id: str) -> str | None:
        root = _instrument_group(instrument_id)
        if not root:
            return None
        if root in self.commodity_map:
            return str(self.commodity_map[root]).upper()
        for key, value in self.commodity_map.items():
            if root.startswith(str(key).upper()):
                return str(value).upper()
        return None

    def _load_items(
        self,
        *,
        db_path: Path,
        commodity: str,
        as_of_ts: datetime,
    ) -> tuple[list[NewsGateItem], list[str]]:
        as_of_utc = as_of_ts.astimezone(timezone.utc) if as_of_ts.tzinfo else as_of_ts.replace(tzinfo=timezone.utc)
        cutoff_utc = as_of_utc - timedelta(minutes=int(self.lookback_minutes))
        as_of_iso = as_of_utc.isoformat().replace("+00:00", "Z")
        cutoff_iso = cutoff_utc.isoformat().replace("+00:00", "Z")
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                """
                SELECT
                    a.article_id,
                    a.published_at_utc,
                    a.source_name,
                    a.title,
                    s.severity,
                    s.impact_score,
                    s.confidence,
                    a.provider,
                    a.commodity
                FROM news_articles a
                JOIN news_scores s ON a.article_id = s.article_id
                WHERE a.commodity = ?
                  AND a.published_at_utc >= ?
                  AND a.published_at_utc <= ?
                  AND s.impact_score >= ?
                  AND s.confidence >= ?
                ORDER BY a.published_at_utc DESC
                LIMIT ?
                """,
                (
                    str(commodity),
                    cutoff_iso,
                    as_of_iso,
                    float(self.min_impact_score),
                    float(self.min_confidence),
                    int(self.max_items),
                ),
            ).fetchall()
        except sqlite3.Error as exc:
            return [], [f"news_db_query_error:{exc.__class__.__name__}"]
        finally:
            conn.close()

        items: list[NewsGateItem] = []
        errors: list[str] = []
        for row in rows:
            (
                article_id,
                published_at_utc,
                source_name,
                title,
                severity,
                impact_score,
                confidence,
                provider,
                commodity_value,
            ) = row
            source = str(source_name or provider or "news").strip()
            if self.sources and source.lower() not in self.sources:
                continue
            published = _parse_utc(published_at_utc)
            if published is None:
                errors.append(f"invalid_timestamp:{article_id}")
                continue
            sev = str(severity or "").strip().lower()
            if _severity_value(sev) < 0:
                errors.append(f"invalid_severity:{article_id}")
                continue
            items.append(
                NewsGateItem(
                    article_id=str(article_id),
                    published_at_utc=published,
                    source=source,
                    title=str(title or "").strip(),
                    severity=sev,
                    impact_score=float(impact_score or 0.0),
                    confidence=float(confidence or 0.0),
                    commodity=str(commodity_value or commodity).strip().upper(),
                )
            )
        return items, errors
