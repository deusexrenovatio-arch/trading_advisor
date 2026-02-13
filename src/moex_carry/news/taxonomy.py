from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NewsTagDefinition:
    code: str
    name: str
    description: str


TAG_TAXONOMY: tuple[NewsTagDefinition, ...] = (
    NewsTagDefinition("SUP_INC", "Supply Increase", "Events increasing commodity supply."),
    NewsTagDefinition("SUP_DEC", "Supply Decrease", "Events decreasing commodity supply."),
    NewsTagDefinition("DEM_INC", "Demand Increase", "Events increasing demand for commodity."),
    NewsTagDefinition("DEM_DEC", "Demand Decrease", "Events decreasing demand for commodity."),
    NewsTagDefinition("GEO_POL", "Geopolitics", "Geopolitical events affecting markets."),
    NewsTagDefinition("ECON_POL", "Economic Policy", "Central-bank and macro policy events."),
    NewsTagDefinition("WEATHER", "Weather", "Weather and force-majeure events."),
    NewsTagDefinition("TECH_DEV", "Technology", "Technology or structural sector changes."),
    NewsTagDefinition("MARKET", "Market Finance", "Risk appetite and market positioning events."),
    NewsTagDefinition("PRICE_MOV", "Price Move", "Price movement and analyst forecast headlines."),
)


SEVERITY_ORDER: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


def impact_to_severity(impact_score: float) -> str:
    score = max(min(float(impact_score), 1.0), 0.0)
    if score >= 0.85:
        return "critical"
    if score >= 0.65:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def normalize_direction(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"up", "long", "positive", "+1", "bullish"}:
        return "up"
    if raw in {"down", "short", "negative", "-1", "bearish"}:
        return "down"
    return "neutral"
