from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Iterable
from urllib.parse import urlparse

import pandas as pd
import requests

try:
    import feedparser as _feedparser
except ModuleNotFoundError:
    _feedparser = None


COMMODITIES = [
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
]

ANCHOR_PATTERN = {
    "BRN": r"\b(brent|crude|oil)\b",
    "NG_US": r"\b(natural gas|lng|henry hub|gas)\b",
    "GOLD": r"\b(gold|bullion)\b",
    "SILVER": r"\b(silver|xag)\b",
    "PLATINUM": r"\b(platinum|pgm)\b",
    "PALLADIUM": r"\b(palladium)\b",
    "COPPER": r"\b(copper|codelco|escondida)\b",
    "ALUMINUM": r"\b(aluminum|aluminium|alumina|bauxite)\b",
    "NICKEL": r"\b(nickel)\b",
    "ZINC": r"\b(zinc|nyrstar)\b",
    "WHEAT": r"\b(wheat|barley|grain)\b",
    "SUGAR": r"\b(sugar|ethanol|cane)\b",
    "COFFEE": r"\b(coffee|arabica|robusta|conilon)\b",
    "COCOA": r"\b(cocoa|cacao|cocobod|ivory coast cocoa|ghana cocoa)\b",
    "ORANGE": r"\b(orange|fcoj|citrus)\b",
}

TRIGGER_PATTERN = {
    "BRN": r"\b(hormuz|opec|output|shipment|pipeline|refinery|sanction|tanker|closure)\b",
    "NG_US": r"\b(storage|eia|freeze|storm|outage|terminal|shipment|export|supply)\b",
    "GOLD": r"\b(rate|yield|reserve|central bank|geopolitic|war|treasury|inflation)\b",
    "SILVER": r"\b(solar|industrial|mine|smelter|supply|deficit|scrap|tariff|sanction)\b",
    "PLATINUM": r"\b(mine|autocatalyst|supply|deficit|south africa|power)\b",
    "PALLADIUM": r"\b(mine|autocatalyst|tariff|sanction|supply|russian)\b",
    "COPPER": r"\b(mine|smelter|strike|inventory|supply|export|investment|shutdown)\b",
    "ALUMINUM": r"\b(smelter|shutdown|force majeure|gas shortage|export|supply|ban)\b",
    "NICKEL": r"\b(ore|ban|mine|supply|indonesia|smelter|npi|morowali)\b",
    "ZINC": r"\b(smelter|mine|inventory|supply|treatment charges|emissions|shutdown)\b",
    "WHEAT": r"\b(harvest|crop|drought|export|supply|corridor)\b",
    "SUGAR": r"\b(harvest|crop|export|supply|ethanol|refiner|production|stocks)\b",
    "COFFEE": r"\b(frost|drought|crop|harvest|export|supply|production|bags)\b",
    "COCOA": r"\b(crop|harvest|farmgate|disease|grindings|supply|production|stocks|weather)\b",
    "ORANGE": r"\b(greening|freeze|hurricane|crop|supply|disease|quarantine)\b",
}

ROOT_CAUSE_PATTERN = {
    "BRN": r"\b(strait of hormuz|hormuz|opec|production cut|production hike|pipeline|terminal|shipment|tanker|sanction|refinery outage|export halt)\b",
    "NG_US": r"\b(eia storage|storage withdrawal|storage injection|lng terminal|freeport|pipeline outage|freeze|cold blast|hurricane|storm|force majeure|export halt)\b",
    "GOLD": r"\b(real yield|treasury yield|central bank buying|reserve diversification|rate cut|rate hike|inflation shock|geopolitical escalation|sanction)\b",
    "SILVER": r"\b(solar demand|photovoltaic|mine output|mine closure|industrial demand|supply deficit|scrap supply|tariff|sanction)\b",
    "PLATINUM": r"\b(south africa|pgm mine|load shedding|mine closure|autocatalyst demand|supply deficit|smelter outage|strike)\b",
    "PALLADIUM": r"\b(russian palladium|tariff|sanction|autocatalyst demand|mine output|supply deficit|embargo)\b",
    "COPPER": r"\b(codelco|escondida|smelter|mine strike|mine closure|treatment charges|warehouse stocks|export disruption|power outage)\b",
    "ALUMINUM": r"\b(alumina|bauxite|smelter shutdown|power shortage|gas shortage|export ban|force majeure|supply disruption)\b",
    "NICKEL": r"\b(indonesia|ore ban|rkab|smelter|npi|morowali|hpal|mine closure|export quota)\b",
    "ZINC": r"\b(smelter|mine closure|treatment charges|tc\/rc|inventory|output cut|power costs|shutdown)\b",
    "WHEAT": r"\b(harvest|drought|crop|export ban|export quota|grain corridor|black sea|usda|frost)\b",
    "SUGAR": r"\b(cane crop|harvest|ethanol parity|monsoon|export quota|mills output|production|surplus|deficit|india sugar|brazil sugar)\b",
    "COFFEE": r"\b(arabica|robusta|conilon|frost|drought|rainfall|crop|harvest|flowering|exports|bags|conab|cecafe)\b",
    "COCOA": r"\b(ivory coast|ghana|cocobod|farmgate|arrivals|mid-crop|main crop|harmattan|black pod|swollen shoot|grindings|stockpile)\b",
    "ORANGE": r"\b(citrus greening|huanglongbing|hlb|freeze|hurricane|crop|disease|quarantine|usda citrus)\b",
}

FINANCIAL_NOISE = re.compile(
    r"\b(stock|shares|etf|portfolio|forecast|technical analysis|trading strategy|book profit|"
    r"how to trade|top \d+|recipe|decor|table|interior|festival|movie|album|tottenham|"
    r"coffee shop|guide|vitamin c|orange county|burn ban|ivf|coupon|flyer deals)\b",
    re.IGNORECASE,
)

COMMODITY_NEGATIVE_PATTERN = {
    "GOLD": r"\b(22k|24k|18k|jeweller|jewelry|jewellery|tola|sgb|sovereign gold bond|aaj sone|loan product)\b",
    "SILVER": r"\b(jewellery|jewelry|mcx|comex|forecast|book profit|to buy|technical)\b",
    "PLATINUM": r"\b(price of platinum|price forecast|jewellery|jewelry)\b",
    "PALLADIUM": r"\b(price forecast|price today|trading limits?|gold and silver prices|precious metals witness|will palladium prices continue)\b",
    "COPPER": r"\b(conference|resource estimate|exploration|stock pick|how to trade)\b",
    "ALUMINUM": r"\b(apple watch|iphone|ipo|listing)\b",
    "NICKEL": r"\b(invitation|booth|conference|stock pick)\b",
    "ZINC": r"\b(sakhi stall|swadeshi|takeover battle|record profit)\b",
    "WHEAT": r"\b(gluten[- ]?free|daily grain highlights|trading lower|pushing higher)\b",
    "SUGAR": r"\b(flyer deals|coupon|hershey|dog|sugar stocks rise|market sell[- ]off|stock)\b",
    "COFFEE": r"\b(coffee shop|cafe|barista|coffee table|machine|creamer|tottenham|hoddle|archdaily)\b",
    "COCOA": r"\b(chocolate recipe|beauty|festival)\b",
    "ORANGE": r"\b(orange county|orange mobile|orange tv|vitamin c|burn ban|ivf|happiness|orange warning|appels frauduleux|clean monday)\b",
}

TRUSTED_SOURCE_PATTERN = re.compile(
    r"(reuters|bloomberg|cnbc|nikkei|aljazeera|businessline|economictimes|"
    r"thehindubusinessline|financialpost|hellenicshippingnews|rigzone|oilprice|"
    r"marketscreener|fastmarkets|mining\.com|miningmx|spglobal|argus|fao|usda|"
    r"freshplaza|graincentral|capitalpress|zawya|africanews|ghanaweb|allafrica|"
    r"devdiscourse|anadolu|cocobod|reuters connect)",
    re.IGNORECASE,
)

STRICT_TITLE_ANCHOR = {"SILVER", "PLATINUM", "COFFEE", "COCOA", "SUGAR", "COPPER", "ZINC"}

GOOGLE_RSS_QUERIES = {
    "SILVER": [
        "silver mine supply disruption 2026 Reuters",
        "silver solar demand deficit 2026 Reuters",
        "industrial silver demand photovoltaic 2026",
    ],
    "PLATINUM": [
        "platinum mine South Africa outage 2026 Reuters",
        "PGM producer output South Africa 2026",
        "platinum autocatalyst demand supply deficit 2026",
    ],
    "PALLADIUM": [
        "palladium tariff Russia 2026 Reuters",
        "palladium mine supply disruption 2026",
        "autocatalyst palladium demand sanctions 2026",
        "US duties on palladium imports Russia 2026 Reuters",
        "South Africa palladium mine output 2025 Reuters",
    ],
    "COPPER": [
        "copper smelter outage 2026 Reuters",
        "codelco copper production disruption 2026 Reuters",
        "copper mine strike treatment charges 2026",
    ],
    "ALUMINUM": [
        "aluminum smelter shutdown gas shortage 2026 Reuters",
        "alumina supply disruption 2026 Reuters",
        "bauxite export ban 2026 Reuters",
    ],
    "NICKEL": [
        "Indonesia nickel ore policy export quota 2026 Reuters",
        "nickel mine disruption Indonesia 2026",
        "nickel smelter output Morowali 2026",
    ],
    "ZINC": [
        "zinc smelter shutdown 2026 Reuters",
        "zinc treatment charges 2026 Fastmarkets",
        "zinc mine closure supply 2026 Reuters",
    ],
    "WHEAT": [
        "wheat harvest drought export 2026 Reuters",
        "black sea grain corridor wheat export 2026 Reuters",
        "USDA wheat crop outlook export 2026",
    ],
    "SUGAR": [
        "brazil sugar ethanol parity 2026 Reuters",
        "india sugar export quota 2026 Reuters",
        "sugar harvest production mills 2026 Reuters",
        "india sugar output lower exports 2026 Reuters",
        "brazil sugar cane crush weather 2026 Reuters",
        "thailand sugar production drought 2025 Reuters",
    ],
    "COFFEE": [
        "brazil coffee frost drought 2026 Reuters",
        "vietnam robusta coffee exports 2026 Reuters",
        "brazil conab coffee crop estimate 2026",
        "arabica harvest weather brazil 2026 Reuters",
    ],
    "COCOA": [
        "ivory coast cocoa arrivals 2026 Reuters",
        "ghana cocoa production cocobod 2026 Reuters",
        "ivory coast cocoa farmgate price 2026 Reuters",
        "cocoa mid crop weather ivory coast 2026 Reuters",
    ],
    "ORANGE": [
        "citrus greening orange crop 2026 Reuters",
        "Florida orange freeze citrus harvest 2026 Reuters",
        "FCOJ supply citrus disease 2026",
        "Florida citrus production USDA forecast 2026 Reuters",
        "Brazil orange crop citrus greening 2026 Reuters",
    ],
    "GOLD": [
        "gold real yields central bank buying 2026 Reuters",
        "gold treasury yields inflation expectations 2026 Reuters",
        "gold reserve diversification central banks 2026",
    ],
    "NG_US": [
        "natural gas storage EIA withdrawal 2026 Reuters",
        "LNG export terminal outage force majeure 2026 Reuters",
        "Henry Hub freeze storm supply shock 2026",
    ],
    "BRN": [
        "brent oil hormuz shipping disruption 2026 Reuters",
        "OPEC output policy cut hike 2026 Reuters",
        "crude tanker route disruption sanctions 2026 Reuters",
    ],
}

NEGATIVE_PATTERN_COMPILED = {
    key: re.compile(pattern, re.IGNORECASE)
    for key, pattern in COMMODITY_NEGATIVE_PATTERN.items()
}


@dataclass(frozen=True)
class BuildConfig:
    db_path: Path
    output_csv: Path
    output_md: Path
    output_top20_md: Path
    lookback_days: int
    top_n: int
    gdelt_maxrecords: int
    gdelt_min_interval_sec: float


def _norm_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _norm_url(value: object) -> str:
    text = _norm_text(value)
    if not text:
        return ""
    lowered = text.lower()
    for marker in ("?utm_", "&utm_", "?fbclid=", "&fbclid="):
        idx = lowered.find(marker)
        if idx >= 0:
            return text[:idx]
    return text


def _strip_html(value: object) -> str:
    raw = str(value or "")
    text = re.sub(r"<[^>]+>", " ", raw)
    return _norm_text(html.unescape(text))


def _to_dt(value: object) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed


def _host(value: object) -> str:
    url = _norm_url(value)
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _canonical_title(title: object, source_name: object = "") -> str:
    text = _norm_text(title).lower()
    source = _norm_text(source_name).lower()
    if source and text.endswith(f" - {source}"):
        text = text[: -(len(source) + 3)].strip()
    if " - " in text:
        tail = text.rsplit(" - ", 1)[-1].strip()
        if len(tail) <= 40 and any(char.isalpha() for char in tail):
            text = text.rsplit(" - ", 1)[0].strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _source_key(name: object, source_url: object, article_url: object) -> str:
    parts = [
        _norm_text(name).lower(),
        _host(source_url),
        _host(article_url),
        _norm_text(source_url).lower(),
    ]
    return " ".join(part for part in parts if part)


def _is_trusted_source(source_key: str) -> bool:
    return bool(TRUSTED_SOURCE_PATTERN.search(_norm_text(source_key)))


def _build_internal_candidates(conn: sqlite3.Connection) -> pd.DataFrame:
    articles = pd.read_sql_query(
        """
        SELECT
            a.article_id,
            a.commodity,
            a.published_at_utc,
            a.title,
            a.description,
            a.content,
            a.url,
            a.source_name,
            a.provider,
            s.cause_event,
            s.cause_route_key,
            s.cause_claim_status,
            s.cause_classification,
            s.is_primary_cause,
            s.fundamental_score,
            s.impact_score,
            s.confidence
        FROM news_articles a
        JOIN news_scores s ON s.article_id = a.article_id
        """,
        conn,
    )
    if articles.empty:
        return pd.DataFrame()
    articles["published_dt"] = pd.to_datetime(articles["published_at_utc"], utc=True, errors="coerce")
    articles = articles.dropna(subset=["published_dt"]).copy()
    articles["source_type"] = "internal"
    articles["source_url"] = ""
    return articles


def _require_feedparser() -> ModuleType:
    if _feedparser is None:
        raise SystemExit(
            "Missing optional dependency 'feedparser'. Install with "
            "`pip install -e .[news]` (or `pip install feedparser`) and rerun."
        )
    return _feedparser


def _google_rss_fetch_query(*, query: str, max_records: int) -> list[dict[str, object]]:
    rss_url = (
        "https://news.google.com/rss/search?"
        f"q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    feed = _require_feedparser().parse(rss_url)
    entries = getattr(feed, "entries", []) or []
    out: list[dict[str, object]] = []
    for entry in entries[: max(int(max_records), 1)]:
        title = _norm_text(getattr(entry, "title", ""))
        if not title:
            continue
        link = _norm_url(getattr(entry, "link", ""))
        published = _to_dt(getattr(entry, "published", ""))
        if published is None:
            continue
        source_payload = getattr(entry, "source", {}) or {}
        source_name = ""
        source_url = ""
        if isinstance(source_payload, dict):
            source_name = _norm_text(source_payload.get("title", ""))
            source_url = _norm_url(source_payload.get("href", ""))
        if not source_name and " - " in title:
            source_name = _norm_text(title.rsplit(" - ", 1)[-1])
        title_clean = _canonical_title(title, source_name)
        summary = _strip_html(getattr(entry, "summary", ""))
        hash_key = "|".join(
            [
                title_clean or title.lower(),
                source_name.lower(),
                source_url.lower(),
                str(published),
                query.lower(),
            ]
        )
        article_id = "external:rss:" + hashlib.sha1(hash_key.encode("utf-8")).hexdigest()[:20]
        out.append(
            {
                "article_id": article_id,
                "commodity": "",
                "published_at_utc": published.isoformat().replace("+00:00", "Z"),
                "published_dt": published,
                "title": title_clean or title,
                "description": summary,
                "content": summary,
                "url": link,
                "source_name": source_name or "google_rss",
                "source_url": source_url,
                "provider": "google_rss",
                "cause_event": "",
                "cause_route_key": "",
                "cause_claim_status": "unknown",
                "cause_classification": "unknown",
                "is_primary_cause": 0,
                "fundamental_score": 0.45,
                "impact_score": 0.45,
                "confidence": 0.55,
                "source_type": "external",
                "external_query": query,
            }
        )
    return out


def _build_external_candidates(*, cfg: BuildConfig, needed_symbols: Iterable[str]) -> pd.DataFrame:
    symbols = [item for item in needed_symbols if item in GOOGLE_RSS_QUERIES]
    if not symbols:
        return pd.DataFrame()
    all_rows: list[dict[str, object]] = []
    for s_idx, symbol in enumerate(symbols):
        queries = GOOGLE_RSS_QUERIES[symbol]
        for q_idx, query in enumerate(queries):
            rows = _google_rss_fetch_query(query=query, max_records=cfg.gdelt_maxrecords)
            all_rows.extend(rows)
            if q_idx < len(queries) - 1:
                time.sleep(max(cfg.gdelt_min_interval_sec, 0.0))
        if s_idx < len(symbols) - 1:
            time.sleep(max(cfg.gdelt_min_interval_sec, 0.0))
    if not all_rows:
        return pd.DataFrame()
    return pd.DataFrame(all_rows)


def _attach_verification(frame: pd.DataFrame, shocks: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    shocks = shocks.copy()
    shocks["shock_dt"] = pd.to_datetime(shocks["shock_ts"], utc=True, errors="coerce")
    shocks = shocks.dropna(subset=["shock_dt"])
    shocks["abs_z"] = pd.to_numeric(shocks["z_score"], errors="coerce").abs().fillna(0.0)
    grouped: dict[str, pd.DataFrame] = {
        str(symbol): part.sort_values("shock_dt").reset_index(drop=True)
        for symbol, part in shocks.groupby("symbol", sort=False)
    }
    v1h: list[bool] = []
    v1d: list[bool] = []
    z1h: list[float] = []
    z1d: list[float] = []
    for symbol, pub in zip(frame["target_symbol"], frame["published_dt"], strict=False):
        part = grouped.get(str(symbol))
        if part is None or pd.isna(pub):
            v1h.append(False)
            v1d.append(False)
            z1h.append(0.0)
            z1d.append(0.0)
            continue
        after = part[part["shock_dt"] >= pub]
        within_1h = after[after["shock_dt"] <= pub + timedelta(hours=1)]
        within_1d = after[after["shock_dt"] <= pub + timedelta(days=1)]
        ok1h = not within_1h.empty
        ok1d = not within_1d.empty
        v1h.append(ok1h)
        v1d.append(ok1d)
        z1h.append(float(within_1h["abs_z"].max()) if ok1h else 0.0)
        z1d.append(float(within_1d["abs_z"].max()) if ok1d else 0.0)
    frame["verified_move_1h"] = v1h
    frame["verified_move_1d"] = v1d
    frame["max_abs_z_1h"] = z1h
    frame["max_abs_z_1d"] = z1d
    return frame


def _score_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    out["fundamental_score"] = pd.to_numeric(out["fundamental_score"], errors="coerce").fillna(0.0)
    out["impact_score"] = pd.to_numeric(out["impact_score"], errors="coerce").fillna(0.0)
    out["confidence"] = pd.to_numeric(out["confidence"], errors="coerce").fillna(0.0)
    out["is_primary_cause"] = out["is_primary_cause"].fillna(0).astype(int)
    out["source_url"] = out.get("source_url", "").fillna("")

    text = (
        out["title"].fillna("")
        + " "
        + out["description"].fillna("")
        + " "
        + out["content"].fillna("")
    ).str.lower()
    title_text = out["title"].fillna("").astype(str).str.lower()

    anchor_flags: list[bool] = []
    trigger_flags: list[bool] = []
    title_anchor_flags: list[bool] = []
    root_flags: list[bool] = []
    root_title_flags: list[bool] = []
    negative_flags: list[bool] = []
    trusted_flags: list[bool] = []
    source_keys: list[str] = []

    for symbol, payload, title_payload, source_name, source_url, article_url in zip(
        out["target_symbol"],
        text,
        title_text,
        out["source_name"].fillna(""),
        out["source_url"].fillna(""),
        out["url"].fillna(""),
        strict=False,
    ):
        sym = str(symbol)
        anchor_expr = ANCHOR_PATTERN.get(sym, r"$^")
        trigger_expr = TRIGGER_PATTERN.get(sym, r"$^")
        root_expr = ROOT_CAUSE_PATTERN.get(sym, r"$^")
        negative_re = NEGATIVE_PATTERN_COMPILED.get(sym)

        anchor_hit = bool(re.search(anchor_expr, payload, flags=re.IGNORECASE))
        trigger_hit = bool(re.search(trigger_expr, payload, flags=re.IGNORECASE))
        root_hit = bool(re.search(root_expr, payload, flags=re.IGNORECASE))
        title_anchor_hit = bool(re.search(anchor_expr, title_payload, flags=re.IGNORECASE))
        title_root_hit = bool(re.search(root_expr, title_payload, flags=re.IGNORECASE))
        negative_hit = bool(negative_re.search(payload)) if negative_re else False

        src_key = _source_key(source_name, source_url, article_url)
        trusted_hit = _is_trusted_source(src_key)

        anchor_flags.append(anchor_hit)
        trigger_flags.append(trigger_hit)
        title_anchor_flags.append(title_anchor_hit)
        root_flags.append(root_hit)
        root_title_flags.append(title_root_hit)
        negative_flags.append(negative_hit)
        trusted_flags.append(trusted_hit)
        source_keys.append(src_key)

    out["anchor_hit"] = anchor_flags
    out["trigger_hit"] = trigger_flags
    out["anchor_title_hit"] = title_anchor_flags
    out["root_hit"] = root_flags
    out["root_title_hit"] = root_title_flags
    out["negative_hit"] = negative_flags
    out["trusted_source"] = trusted_flags
    out["source_key"] = source_keys
    out["financial_noise"] = text.apply(lambda item: bool(FINANCIAL_NOISE.search(item)))

    strict_mask = out["target_symbol"].isin(STRICT_TITLE_ANCHOR)
    out.loc[strict_mask, "anchor_hit"] = out.loc[strict_mask, "anchor_title_hit"]
    out.loc[strict_mask, "root_hit"] = out.loc[strict_mask, "root_title_hit"] | out.loc[strict_mask, "root_hit"]

    cause_class = out["cause_classification"].fillna("").astype(str).str.lower()
    cause_bonus = cause_class.map({"cause": 0.25, "mixed": 0.12, "effect": -0.06}).fillna(0.0)
    verify_score = out["verified_move_1h"].astype(int) * 0.45 + out["verified_move_1d"].astype(int) * 0.55
    z_component = out["max_abs_z_1d"].clip(lower=0.0, upper=8.0) / 8.0
    out["verification_score"] = (verify_score + z_component * 0.2).clip(0.0, 1.2)

    now = pd.Timestamp.now(tz="UTC")
    out["age_days"] = ((now - out["published_dt"]).dt.total_seconds() / 86400.0).fillna(9999.0)
    stale_penalty = ((out["age_days"] - 365.0).clip(lower=0.0) / 365.0).clip(upper=2.0) * 0.25

    out["quality_score"] = (
        out["fundamental_score"] * 1.7
        + out["impact_score"] * 1.25
        + out["confidence"] * 0.85
        + verify_score * 1.2
        + z_component
        + out["trigger_hit"].astype(int) * 0.65
        + out["anchor_hit"].astype(int) * 0.35
        + out["root_hit"].astype(int) * 0.85
        + out["root_title_hit"].astype(int) * 0.55
        + out["trusted_source"].astype(int) * 0.35
        + out["is_primary_cause"].astype(int) * 0.25
        + cause_bonus
        - out["financial_noise"].astype(int) * 0.8
        - out["negative_hit"].astype(int) * 1.2
        - stale_penalty
    )
    return out


def _select_top(frame: pd.DataFrame, *, top_n: int) -> pd.DataFrame:
    if frame.empty:
        return frame
    parts: list[pd.DataFrame] = []
    for symbol in COMMODITIES:
        subset = frame[frame["target_symbol"] == symbol].copy()
        if subset.empty:
            continue
        subset["canonical_title"] = subset.apply(
            lambda row: _canonical_title(row.get("title", ""), row.get("source_name", "")),
            axis=1,
        )
        subset["publisher_key"] = subset.apply(
            lambda row: _source_key(row.get("source_name", ""), row.get("source_url", ""), row.get("url", "")),
            axis=1,
        )
        subset["dedupe_key"] = subset["canonical_title"].where(
            subset["canonical_title"].str.len() >= 18,
            subset["canonical_title"] + "|" + subset["publisher_key"],
        )
        subset = subset[subset["dedupe_key"].str.len() > 0].copy()

        verify_mask = subset["verified_move_1d"]
        if symbol in {"ORANGE", "PALLADIUM", "SUGAR"}:
            verify_mask = subset["verified_move_1d"] | subset["verified_move_1h"]
        base = subset[
            verify_mask
            & ~subset["financial_noise"]
            & ~subset["negative_hit"]
        ].copy()
        if base.empty:
            continue

        tier1 = base[base["root_title_hit"] & base["trigger_hit"] & base["trusted_source"]]
        tier2 = base[base["root_hit"] & base["trigger_hit"] & base["trusted_source"]]
        tier3 = base[base["root_hit"] & base["trusted_source"]]
        tier4 = base[base["root_hit"]]
        tier5 = base[base["anchor_hit"] & base["trigger_hit"] & base["trusted_source"]]
        tier6 = base[base["anchor_hit"] & base["trusted_source"]]
        tier7 = base[base["anchor_hit"]]

        buckets = [tier1, tier2, tier3, tier4]
        if symbol not in STRICT_TITLE_ANCHOR:
            buckets.extend([tier5, tier6, tier7])
        else:
            buckets.extend([tier6, tier7])

        chosen: list[pd.Series] = []
        used: set[str] = set()
        for bucket in buckets:
            if bucket.empty:
                continue
            bucket = bucket.sort_values(
                ["quality_score", "verified_move_1h", "published_dt"],
                ascending=[False, False, False],
            )
            for _, row in bucket.iterrows():
                key = str(row.get("dedupe_key") or "")
                if not key or key in used:
                    continue
                used.add(key)
                chosen.append(row)
                if len(chosen) >= top_n:
                    break
            if len(chosen) >= top_n:
                break
        if len(chosen) < top_n and symbol in {"ORANGE", "PALLADIUM", "SUGAR"}:
            sparse_extra = subset[
                (subset["root_hit"] | subset["trigger_hit"])
                & subset["trusted_source"]
                & ~subset["financial_noise"]
                & ~subset["negative_hit"]
            ].sort_values(["quality_score", "published_dt"], ascending=[False, False])
            for _, row in sparse_extra.iterrows():
                key = str(row.get("dedupe_key") or "")
                if not key or key in used:
                    continue
                used.add(key)
                chosen.append(row)
                if len(chosen) >= top_n:
                    break
        if len(chosen) < top_n and symbol in {"ORANGE", "PALLADIUM", "SUGAR"}:
            sparse_extra_2 = subset[
                (subset["root_hit"] | subset["trigger_hit"])
                & ~subset["financial_noise"]
                & ~subset["negative_hit"]
            ].sort_values(["quality_score", "published_dt"], ascending=[False, False])
            for _, row in sparse_extra_2.iterrows():
                key = str(row.get("dedupe_key") or "")
                if not key or key in used:
                    continue
                used.add(key)
                chosen.append(row)
                if len(chosen) >= top_n:
                    break
        if not chosen:
            continue
        part = pd.DataFrame(chosen).head(top_n).copy()
        parts.append(part)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def _prepare_output(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    out["is_primary_cause"] = out["is_primary_cause"].astype(bool)
    out["manual_note"] = out.apply(
        lambda row: (
            f"source={row.get('source_type', 'internal')};"
            f"trusted={int(bool(row.get('trusted_source')))};"
            f"anchor={int(bool(row.get('anchor_hit')))};"
            f"trigger={int(bool(row.get('trigger_hit')))};"
            f"root={int(bool(row.get('root_hit')))};"
            f"negative={int(bool(row.get('negative_hit')))};"
            f"noise={int(bool(row.get('financial_noise')))};"
            f"verified(1h={int(bool(row.get('verified_move_1h')))},1d={int(bool(row.get('verified_move_1d')))});"
            f"query={_norm_text(row.get('external_query')) if _norm_text(row.get('external_query')) else 'n/a'}"
        ),
        axis=1,
    )
    keep = [
        "target_symbol",
        "published_at_utc",
        "title",
        "url",
        "source_name",
        "provider",
        "cause_event",
        "cause_route_key",
        "cause_claim_status",
        "cause_classification",
        "is_primary_cause",
        "fundamental_score",
        "impact_score",
        "confidence",
        "max_abs_z_1h",
        "max_abs_z_1d",
        "verified_move_1h",
        "verified_move_1d",
        "verification_score",
        "quality_score",
        "root_hit",
        "trusted_source",
        "negative_hit",
        "manual_note",
        "source_type",
    ]
    out = out[keep].copy()
    out = out.rename(columns={"target_symbol": "commodity"})
    return out


def _write_md(frame: pd.DataFrame, *, path: Path, top_n: int) -> None:
    lines: list[str] = []
    lines.append("# News GOLD Top-20 (Manual + Verified)")
    lines.append("")
    lines.append(f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
    lines.append(f"Rows: {len(frame)}")
    lines.append(f"Commodities: {', '.join(sorted(frame['commodity'].astype(str).unique().tolist()))}")
    lines.append("")
    for symbol in COMMODITIES:
        part = frame[frame["commodity"] == symbol].copy()
        lines.append(f"## {symbol}")
        if part.empty:
            lines.append("- No rows selected.")
            lines.append("")
            continue
        lines.append(f"- Selected: {len(part)}")
        lines.append(f"- Verified 1D: {int(part['verified_move_1d'].sum())}, Verified 1H: {int(part['verified_move_1h'].sum())}")
        for _, row in part.sort_values("quality_score", ascending=False).head(top_n).iterrows():
            lines.append(
                f"- {row['published_at_utc']} | q={float(row['quality_score']):.3f} | z1d={float(row['max_abs_z_1d']):.2f} | "
                f"root={int(bool(row['root_hit']))} | trusted={int(bool(row['trusted_source']))} | [{row['title']}]({row['url']})"
            )
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_top20_report(frame: pd.DataFrame, *, path: Path) -> None:
    lines: list[str] = []
    lines.append("# GOLD Top-20 By Commodity")
    lines.append("")
    for symbol in COMMODITIES:
        lines.append(f"## {symbol}")
        part = frame[frame["commodity"] == symbol].copy()
        if part.empty:
            lines.append("- No rows selected.")
            lines.append("")
            continue
        part = part.sort_values(["quality_score", "published_at_utc"], ascending=[False, False]).head(20)
        idx = 1
        for _, row in part.iterrows():
            lines.append(
                f"{idx}. {row['published_at_utc']} | quality={float(row['quality_score']):.3f} | "
                f"z1d={float(row['max_abs_z_1d']):.2f} | src={row['source_type']} | "
                f"root={int(bool(row['root_hit']))} | trusted={int(bool(row['trusted_source']))} | [{row['title']}]({row['url']})"
            )
            idx += 1
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build(cfg: BuildConfig) -> pd.DataFrame:
    conn = sqlite3.connect(cfg.db_path)
    try:
        internal = _build_internal_candidates(conn)
        shocks = pd.read_sql_query(
            "SELECT symbol, shock_ts, z_score FROM news_shock_rows WHERE symbol IN ({})".format(
                ",".join("?" for _ in COMMODITIES)
            ),
            conn,
            params=COMMODITIES,
        )
    finally:
        conn.close()

    if internal.empty:
        return pd.DataFrame()

    now = pd.Timestamp.now(tz="UTC")
    cutoff = now - pd.Timedelta(days=max(int(cfg.lookback_days), 1))
    internal = internal[internal["published_dt"] >= cutoff].copy()
    if internal.empty:
        return pd.DataFrame()

    # Expand internal candidates by symbol anchors.
    internal_text = (
        internal["title"].fillna("")
        + " "
        + internal["description"].fillna("")
        + " "
        + internal["content"].fillna("")
    ).str.lower()

    expanded_rows: list[dict[str, object]] = []
    for symbol in COMMODITIES:
        anchor_re = re.compile(ANCHOR_PATTERN[symbol], re.IGNORECASE)
        mask = internal_text.apply(lambda payload: bool(anchor_re.search(payload)))
        part = internal[mask].copy()
        if part.empty:
            continue
        part["target_symbol"] = symbol
        expanded_rows.extend(part.to_dict("records"))
    if not expanded_rows:
        return pd.DataFrame()

    base = pd.DataFrame(expanded_rows)
    base = _attach_verification(base, shocks)
    base_scored = _score_candidates(base)

    strict_pool = base_scored[
        base_scored["verified_move_1d"]
        & base_scored["root_hit"]
        & base_scored["trigger_hit"]
        & ~base_scored["financial_noise"]
        & ~base_scored["negative_hit"]
    ]
    verified_counts = strict_pool.groupby("target_symbol", sort=False)["article_id"].nunique().to_dict()
    need_external = [sym for sym in COMMODITIES if int(verified_counts.get(sym, 0)) < cfg.top_n]

    external = _build_external_candidates(cfg=cfg, needed_symbols=need_external)
    if not external.empty:
        external = external[external["published_dt"] <= now + pd.Timedelta(days=1)].copy()
        ext_text = (
            external["title"].fillna("")
            + " "
            + external["description"].fillna("")
            + " "
            + external["content"].fillna("")
        ).str.lower()
        ext_rows: list[dict[str, object]] = []
        for symbol in need_external:
            anchor_re = re.compile(ANCHOR_PATTERN.get(symbol, r"$^"), re.IGNORECASE)
            mask = ext_text.apply(lambda payload: bool(anchor_re.search(payload)))
            part = external[mask].copy()
            if part.empty:
                continue
            part["target_symbol"] = symbol
            ext_rows.extend(part.to_dict("records"))
        external_expanded = pd.DataFrame(ext_rows)
    else:
        external_expanded = pd.DataFrame()

    if not external_expanded.empty:
        combined = pd.concat([base, external_expanded], ignore_index=True)
    else:
        combined = base.copy()

    combined = _attach_verification(combined, shocks)
    combined = _score_candidates(combined)
    selected = _select_top(combined, top_n=cfg.top_n)
    return _prepare_output(selected)


def parse_args() -> BuildConfig:
    parser = argparse.ArgumentParser(description="Build final GOLD top-20 commodity news events.")
    parser.add_argument("--db-path", type=Path, default=Path("data/news_livecheck_ng.db"))
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path("docs/research/news_golden_events_gold.csv"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/research/news_golden_events_gold.md"),
    )
    parser.add_argument(
        "--output-top20-md",
        type=Path,
        default=Path("docs/research/news_top20_by_commodity_gold.md"),
    )
    parser.add_argument("--lookback-days", type=int, default=1200)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--gdelt-maxrecords", type=int, default=120)
    parser.add_argument("--gdelt-min-interval-sec", type=float, default=2.6)
    args = parser.parse_args()
    return BuildConfig(
        db_path=args.db_path,
        output_csv=args.output_csv,
        output_md=args.output_md,
        output_top20_md=args.output_top20_md,
        lookback_days=args.lookback_days,
        top_n=args.top_n,
        gdelt_maxrecords=args.gdelt_maxrecords,
        gdelt_min_interval_sec=args.gdelt_min_interval_sec,
    )


def main() -> None:
    cfg = parse_args()
    frame = build(cfg)
    if frame.empty:
        raise SystemExit("No GOLD events produced.")
    cfg.output_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(cfg.output_csv, index=False, quoting=csv.QUOTE_MINIMAL)
    _write_md(frame, path=cfg.output_md, top_n=10)
    _write_top20_report(frame, path=cfg.output_top20_md)
    coverage = frame.groupby("commodity", sort=True).size().to_dict()
    payload = {
        "output_csv": str(cfg.output_csv),
        "output_md": str(cfg.output_md),
        "output_top20_md": str(cfg.output_top20_md),
        "rows": int(len(frame)),
        "coverage": coverage,
    }
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
