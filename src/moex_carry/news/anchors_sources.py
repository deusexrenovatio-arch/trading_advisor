from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable

import requests


@dataclass(frozen=True)
class EpisodicAnchorRecord:
    source: str
    anchor_id: str
    family: str
    ticker: str
    event_ts: datetime
    event_status: str
    summary: str
    mechanism: str
    facts_json: dict[str, object]


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _safe_text(value: object, *, limit: int = 240) -> str:
    text = str(value or "").strip()
    if limit > 0 and len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _stable_hash(*parts: object, length: int = 20) -> str:
    raw = "|".join(str(item or "").strip() for item in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[: max(int(length), 8)]

def _parse_datetime_flexible(value: object) -> datetime | None:
    parsed = _parse_datetime(value)
    if parsed is not None:
        return parsed
    text = str(value or "").strip()
    if not text:
        return None
    try:
        fallback = parsedate_to_datetime(text)
        if fallback.tzinfo is not None:
            return fallback.astimezone(timezone.utc).replace(tzinfo=None)
        return fallback
    except Exception:
        pass
    month_match = re.search(
        r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b",
        text,
        flags=re.IGNORECASE,
    )
    if month_match:
        day = int(month_match.group(1))
        mon_key = month_match.group(2).lower()[:3]
        year = int(month_match.group(3))
        month_idx = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }.get(mon_key)
        if month_idx:
            try:
                return datetime(year, month_idx, day)
            except ValueError:
                return None
    return None

def _fetch_nhc_episodic_records(
    *,
    url: str,
    timeout_sec: int,
    now: datetime,
    user_agent: str,
) -> list[EpisodicAnchorRecord]:
    try:
        response = requests.get(
            url,
            timeout=max(int(timeout_sec), 5),
            headers={"User-Agent": str(user_agent or "moex-carry/0.1")},
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"nhc_request_error:{exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"nhc_http_{response.status_code}")
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError("nhc_invalid_json") from exc

    storms: list[dict[str, object]] = []
    if isinstance(payload, dict):
        for key in ("activeStorms", "storms", "data", "currentStorms"):
            value = payload.get(key)
            if isinstance(value, list):
                storms = [item for item in value if isinstance(item, dict)]
                if storms:
                    break
    elif isinstance(payload, list):
        storms = [item for item in payload if isinstance(item, dict)]

    records: list[EpisodicAnchorRecord] = []
    for item in storms:
        anchor_id = _safe_text(
            item.get("id")
            or item.get("stormId")
            or item.get("stormID")
            or item.get("storm_id")
            or item.get("number")
            or "",
            limit=64,
        )
        name = _safe_text(item.get("name") or item.get("stormName") or "", limit=80)
        if not anchor_id and not name:
            continue
        event_ts = _parse_datetime_flexible(
            item.get("lastUpdate")
            or item.get("updated")
            or item.get("timestamp")
            or item.get("advisoryDate")
        ) or now
        status_raw = _safe_text(item.get("status") or item.get("stormStatus") or "active", limit=32).lower()
        status = "resolved" if any(token in status_raw for token in ("dissip", "inactive", "post")) else "active"
        basin = _safe_text(item.get("basin") or item.get("region") or "", limit=24)
        title = f"NHC storm update {name or anchor_id}".strip()
        if basin:
            title = f"{title} ({basin})"
        facts = {
            "name": name,
            "basin": basin,
            "status_raw": status_raw,
        }
        for ticker in ("NG_US", "BRN"):
            records.append(
                EpisodicAnchorRecord(
                    source="NHC",
                    anchor_id=anchor_id or _stable_hash(name, event_ts.isoformat(), length=16),
                    family="HURRICANE_GOM_SHUTINS",
                    ticker=ticker,
                    event_ts=event_ts,
                    event_status=status,
                    summary=title,
                    mechanism=f"episodic_anchor|anchor_source=NHC|event_family=HURRICANE_GOM_SHUTINS|ticker={ticker}|anchor_id={anchor_id or name}",
                    facts_json=facts,
                )
            )
    return records


def _fetch_nws_alert_episodic_records(
    *,
    url: str,
    timeout_sec: int,
    now: datetime,
    user_agent: str,
) -> list[EpisodicAnchorRecord]:
    try:
        response = requests.get(
            url,
            timeout=max(int(timeout_sec), 5),
            headers={"User-Agent": str(user_agent or "moex-carry/0.1")},
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"nws_request_error:{exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"nws_http_{response.status_code}")
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError("nws_invalid_json") from exc

    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        return []
    records: list[EpisodicAnchorRecord] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        if not isinstance(props, dict):
            continue
        anchor_id = _safe_text(props.get("id") or props.get("@id") or "", limit=80)
        if not anchor_id:
            anchor_id = _stable_hash(props.get("event"), props.get("headline"), props.get("sent"), length=20)
        event_name = _safe_text(props.get("event") or props.get("headline") or "NWS alert", limit=120)
        sent_ts = _parse_datetime_flexible(props.get("sent") or props.get("effective") or props.get("onset")) or now
        status_raw = _safe_text(props.get("status") or "actual", limit=24).lower()
        event_status = "resolved" if status_raw in {"cancel", "expired"} else "active"
        area_desc = _safe_text(props.get("areaDesc") or "", limit=200)
        summary = event_name if not area_desc else f"{event_name} | {area_desc}"
        records.append(
            EpisodicAnchorRecord(
                source="NWS",
                anchor_id=anchor_id,
                family="WEATHER_COLD_HEAT_DD",
                ticker="NG_US",
                event_ts=sent_ts,
                event_status=event_status,
                summary=summary,
                mechanism=f"episodic_anchor|anchor_source=NWS|event_family=WEATHER_COLD_HEAT_DD|ticker=NG_US|anchor_id={anchor_id}",
                facts_json={
                    "event": event_name,
                    "severity": _safe_text(props.get("severity") or "", limit=24),
                    "urgency": _safe_text(props.get("urgency") or "", limit=24),
                    "certainty": _safe_text(props.get("certainty") or "", limit=24),
                },
            )
        )
    return records


def _fetch_ukmto_episodic_records(
    *,
    url: str,
    timeout_sec: int,
    now: datetime,
    user_agent: str,
) -> list[EpisodicAnchorRecord]:
    try:
        response = requests.get(
            url,
            timeout=max(int(timeout_sec), 5),
            headers={"User-Agent": str(user_agent or "moex-carry/0.1")},
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"ukmto_request_error:{exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"ukmto_http_{response.status_code}")
    html = str(response.text or "")
    if not html.strip():
        raise RuntimeError("ukmto_empty_html")

    try:
        from bs4 import BeautifulSoup
    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    keywords = ("incident", "attack", "board", "security", "missile", "hijack")
    for node in soup.find_all(["a", "li", "article", "tr", "div"]):
        text = _safe_text(node.get_text(" ", strip=True), limit=240)
        if len(text) < 18:
            continue
        lowered = text.lower()
        if not any(word in lowered for word in keywords):
            continue
        href = ""
        if getattr(node, "name", "") == "a":
            href = _safe_text(node.get("href") or "", limit=300)
        if href and href.startswith("/"):
            href = "https://www.ukmto.org" + href
        event_ts = _parse_datetime_flexible(text) or now
        dedupe_key = _stable_hash(text, href, event_ts.isoformat(), length=24)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidates.append((text, href, event_ts))
        if len(candidates) >= 25:
            break

    records: list[EpisodicAnchorRecord] = []
    for text, href, event_ts in candidates:
        anchor_id = _stable_hash(text, href or "ukmto", length=18)
        facts = {"source_url": href, "headline": text}
        for ticker in ("BRN", "GOLD"):
            records.append(
                EpisodicAnchorRecord(
                    source="UKMTO",
                    anchor_id=anchor_id,
                    family="MARITIME_SECURITY_UKMTO",
                    ticker=ticker,
                    event_ts=event_ts,
                    event_status="active",
                    summary=_safe_text(text, limit=180),
                    mechanism=f"episodic_anchor|anchor_source=UKMTO|event_family=MARITIME_SECURITY_UKMTO|ticker={ticker}|anchor_id={anchor_id}",
                    facts_json=facts,
                )
            )
    return records


def _fetch_bsee_episodic_records(
    *,
    url: str,
    timeout_sec: int,
    now: datetime,
    user_agent: str,
) -> list[EpisodicAnchorRecord]:
    try:
        response = requests.get(
            url,
            timeout=max(int(timeout_sec), 5),
            headers={"User-Agent": str(user_agent or "moex-carry/0.1")},
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"bsee_request_error:{exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"bsee_http_{response.status_code}")
    html = str(response.text or "")
    if not html.strip():
        return []

    try:
        from bs4 import BeautifulSoup
    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")
    keywords = ("shut", "evac", "hurricane", "storm", "gulf", "offshore", "production")
    candidates: list[tuple[str, str, datetime]] = []
    seen: set[str] = set()
    for node in soup.find_all(["a", "li", "article", "tr", "div", "p"]):
        text = _safe_text(node.get_text(" ", strip=True), limit=260)
        if len(text) < 20:
            continue
        lowered = text.lower()
        if not any(token in lowered for token in keywords):
            continue
        href = ""
        if getattr(node, "name", "") == "a":
            href = _safe_text(node.get("href") or "", limit=320)
        if href.startswith("/"):
            href = "https://www.bsee.gov" + href
        event_ts = _parse_datetime_flexible(text) or now
        key = _stable_hash(text, href, event_ts.isoformat(), length=24)
        if key in seen:
            continue
        seen.add(key)
        candidates.append((text, href, event_ts))
        if len(candidates) >= 30:
            break

    rows: list[EpisodicAnchorRecord] = []
    for text, href, event_ts in candidates:
        anchor_id = _stable_hash(text, href or "bsee", length=18)
        facts = {"source_url": href, "headline": text}
        for ticker in ("NG_US", "BRN"):
            rows.append(
                EpisodicAnchorRecord(
                    source="BSEE",
                    anchor_id=anchor_id,
                    family="HURRICANE_GOM_SHUTINS",
                    ticker=ticker,
                    event_ts=event_ts,
                    event_status="active",
                    summary=_safe_text(text, limit=180),
                    mechanism=f"episodic_anchor|anchor_source=BSEE|event_family=HURRICANE_GOM_SHUTINS|ticker={ticker}|anchor_id={anchor_id}",
                    facts_json=facts,
                )
            )
    return rows


def _fetch_panama_episodic_records(
    *,
    url: str,
    timeout_sec: int,
    now: datetime,
    user_agent: str,
) -> list[EpisodicAnchorRecord]:
    try:
        response = requests.get(
            url,
            timeout=max(int(timeout_sec), 5),
            headers={"User-Agent": str(user_agent or "moex-carry/0.1")},
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"panama_request_error:{exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"panama_http_{response.status_code}")
    html = str(response.text or "")
    if not html.strip():
        return []

    try:
        from bs4 import BeautifulSoup
    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")
    keywords = ("advisory", "shipping", "draft", "slot", "restriction", "transit")
    records: list[EpisodicAnchorRecord] = []
    seen: set[str] = set()
    for node in soup.find_all(["a", "li", "article", "tr", "div"]):
        text = _safe_text(node.get_text(" ", strip=True), limit=240)
        if len(text) < 18:
            continue
        lowered = text.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue
        href = ""
        if getattr(node, "name", "") == "a":
            href = _safe_text(node.get("href") or "", limit=320)
        if href.startswith("/"):
            href = "https://pancanal.com" + href
        event_ts = _parse_datetime_flexible(text) or now
        anchor_id = _stable_hash(text, href or "panama", length=18)
        if anchor_id in seen:
            continue
        seen.add(anchor_id)
        records.append(
            EpisodicAnchorRecord(
                source="PANAMA",
                anchor_id=anchor_id,
                family="SHIPPING_CHOKEPOINT_PANAMA",
                ticker="NG_US",
                event_ts=event_ts,
                event_status="active",
                summary=_safe_text(text, limit=180),
                mechanism=f"episodic_anchor|anchor_source=PANAMA|event_family=SHIPPING_CHOKEPOINT_PANAMA|ticker=NG_US|anchor_id={anchor_id}",
                facts_json={"source_url": href, "headline": text},
            )
        )
        if len(records) >= 30:
            break
    return records


def _fetch_suez_episodic_records(
    *,
    url: str,
    timeout_sec: int,
    now: datetime,
    user_agent: str,
) -> list[EpisodicAnchorRecord]:
    try:
        response = requests.get(
            url,
            timeout=max(int(timeout_sec), 5),
            headers={"User-Agent": str(user_agent or "moex-carry/0.1")},
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"suez_request_error:{exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"suez_http_{response.status_code}")
    html = str(response.text or "")
    if not html.strip():
        return []

    try:
        from bs4 import BeautifulSoup
    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")
    keywords = ("circular", "navigation", "transit", "route", "restriction", "discount")
    records: list[EpisodicAnchorRecord] = []
    seen: set[str] = set()
    for node in soup.find_all(["a", "li", "article", "tr", "div"]):
        text = _safe_text(node.get_text(" ", strip=True), limit=240)
        if len(text) < 18:
            continue
        lowered = text.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue
        href = ""
        if getattr(node, "name", "") == "a":
            href = _safe_text(node.get("href") or "", limit=320)
        if href.startswith("/"):
            href = "https://www.suezcanal.gov.eg" + href
        event_ts = _parse_datetime_flexible(text) or now
        anchor_id = _stable_hash(text, href or "suez", length=18)
        if anchor_id in seen:
            continue
        seen.add(anchor_id)
        records.append(
            EpisodicAnchorRecord(
                source="SUEZ",
                anchor_id=anchor_id,
                family="SHIPPING_CHOKEPOINT_SUEZ_REDIR",
                ticker="BRN",
                event_ts=event_ts,
                event_status="active",
                summary=_safe_text(text, limit=180),
                mechanism=f"episodic_anchor|anchor_source=SUEZ|event_family=SHIPPING_CHOKEPOINT_SUEZ_REDIR|ticker=BRN|anchor_id={anchor_id}",
                facts_json={"source_url": href, "headline": text},
            )
        )
        if len(records) >= 30:
            break
    return records


def _fetch_fred_release_records(
    *,
    url: str,
    timeout_sec: int,
    now: datetime,
    user_agent: str,
    release_ids: Iterable[int],
    api_key_env: str,
) -> list[EpisodicAnchorRecord]:
    api_key = os.getenv(str(api_key_env or "").strip(), "").strip()
    if not api_key:
        return []
    rows: list[EpisodicAnchorRecord] = []
    for release_id in release_ids:
        try:
            rid = int(release_id)
        except (TypeError, ValueError):
            continue
        try:
            response = requests.get(
                url,
                params={
                    "release_id": rid,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 5,
                },
                timeout=max(int(timeout_sec), 5),
                headers={"User-Agent": str(user_agent or "moex-carry/0.1")},
            )
        except requests.RequestException:
            continue
        if response.status_code != 200:
            continue
        try:
            payload = response.json()
        except Exception:
            continue
        release_rows = payload.get("release_dates") if isinstance(payload, dict) else None
        if not isinstance(release_rows, list):
            continue
        for item in release_rows[:3]:
            if not isinstance(item, dict):
                continue
            date_raw = _safe_text(item.get("date") or "", limit=32)
            if not date_raw:
                continue
            event_ts = _parse_datetime_flexible(date_raw) or now
            anchor_id = _stable_hash("fred", rid, date_raw, length=20)
            summary = f"FRED release {rid} {date_raw}"
            for ticker in ("GOLD", "BRN", "NG_US"):
                rows.append(
                    EpisodicAnchorRecord(
                        source="FRED",
                        anchor_id=anchor_id,
                        family="FOMC_DECISION_MINUTES_SPEECH",
                        ticker=ticker,
                        event_ts=event_ts,
                        event_status="resolved" if event_ts < now else "active",
                        summary=summary,
                        mechanism=f"scheduled_anchor|anchor_source=FRED|event_family=FOMC_DECISION_MINUTES_SPEECH|ticker={ticker}|anchor_id={anchor_id}",
                        facts_json={"release_id": rid, "date": date_raw},
                    )
                )
    return rows
