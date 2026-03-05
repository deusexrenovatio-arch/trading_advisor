from __future__ import annotations

import hashlib
import re
from datetime import datetime

import pandas as pd

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "will",
    "into",
    "over",
    "after",
    "amid",
    "news",
    "report",
    "reports",
    "update",
    "market",
    "markets",
    "prices",
    "price",
    "oil",
    "gold",
    "gas",
}

_THEME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "mideast_geopolitics",
        (
            "iran",
            "israel",
            "hormuz",
            "red sea",
            "gulf",
            "missile",
            "drone",
            "attack",
            "strike",
            "sanction",
        ),
    ),
    (
        "opec_policy",
        (
            "opec",
            "opec+",
            "quota",
            "production cut",
            "output cut",
            "output increase",
        ),
    ),
    (
        "weather_demand",
        (
            "cold",
            "colder",
            "storm",
            "freeze",
            "freeze-off",
            "hdd",
            "cdd",
            "heat wave",
            "weather forecast",
        ),
    ),
    (
        "eia_storage",
        (
            "eia",
            "storage",
            "withdrawal",
            "injection",
            "draw",
            "build",
        ),
    ),
    (
        "rates_usd",
        (
            "fed",
            "fomc",
            "real yields",
            "treasury yields",
            "dxy",
            "dollar",
        ),
    ),
)

_IMPACT_TIER_ORDER = ("minor", "medium", "strong", "major")
_IMPACT_TIER_RANK = {name: idx for idx, name in enumerate(_IMPACT_TIER_ORDER)}


def normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _topic_tokens(text: str, *, limit: int = 6) -> list[str]:
    tokens = re.findall(r"[a-z0-9]{3,}", text.lower())
    cleaned = [item for item in tokens if item not in _STOPWORDS]
    return cleaned[:limit]


def _parse_any_utc(value: object) -> datetime | None:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    if isinstance(parsed, pd.Timestamp):
        return parsed.to_pydatetime()
    return None


def build_story_fingerprint(
    *,
    title: object,
    url: object,
    published_at_utc: object,
    provider: object = "",
) -> str:
    ts = _parse_any_utc(published_at_utc)
    ts_bucket = ts.strftime("%Y-%m-%dT%H:%M") if ts is not None else normalize_text(published_at_utc)
    payload = "|".join(
        [
            normalize_text(provider).lower(),
            normalize_text(url).lower(),
            normalize_text(title).lower(),
            ts_bucket,
        ]
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"story:{digest}"


def classify_shock_impact_tier(
    *,
    z_score_abs: float | None,
    abs_move_pct: float | None,
) -> str:
    z = float(abs(z_score_abs or 0.0))
    move = float(abs(abs_move_pct or 0.0))
    if z >= 4.0 or move >= 2.5:
        return "major"
    if z >= 3.0 or move >= 1.5:
        return "strong"
    if z >= 2.5 or move >= 1.0:
        return "medium"
    return "minor"


def impact_tier_rank(value: object) -> int:
    key = normalize_text(value).lower()
    return _IMPACT_TIER_RANK.get(key, 0)


def derive_root_topic_key(
    *,
    symbol: object,
    headline: object,
    url: object = "",
    selected_event_id: object = "",
    selected_source: object = "",
    explicit_root_topic_id: object = "",
) -> str:
    explicit = normalize_text(explicit_root_topic_id).lower()
    if explicit:
        return explicit

    sym = normalize_text(symbol).upper() or "UNK"
    headline_text = normalize_text(headline).lower()
    url_text = normalize_text(url).lower()
    theme_text = " ".join(part for part in (headline_text, url_text) if part)
    for theme_name, keywords in _THEME_RULES:
        if any(keyword in theme_text for keyword in keywords):
            return f"root:{sym}:{theme_name}"

    source = normalize_text(selected_source).lower()
    event_id = normalize_text(selected_event_id).lower()
    if event_id and source == "v2_clean":
        return f"root:{sym}:evt:{event_id}"

    tokens = _topic_tokens(headline_text if headline_text else url_text)
    if tokens:
        token_slug = "-".join(tokens)
        return f"root:{sym}:topic:{token_slug}"

    if event_id:
        return f"root:{sym}:evt:{event_id}"
    return f"root:{sym}:generic"
