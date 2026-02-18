from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass(frozen=True)
class FactorDefinition:
    code: str
    description: str


@dataclass(frozen=True)
class EventFamilyDefinition:
    code: str
    category: str
    commodities: tuple[str, ...]
    anchor_sources: tuple[str, ...]
    default_factors: dict[str, str]


@dataclass(frozen=True)
class NewsTaxonomyCatalog:
    schema_version: str
    factors: tuple[FactorDefinition, ...]
    event_families: tuple[EventFamilyDefinition, ...]

    def factor_codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.factors)

    def event_family_codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.event_families)


def _default_taxonomy_path() -> Path:
    return Path(__file__).resolve().parents[3] / "configs" / "news-taxonomy.yaml"


def _normalize_str(value: object) -> str:
    text = str(value or "").strip()
    return text


def _to_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value:
        text = _normalize_str(item)
        if text:
            out.append(text)
    return tuple(out)


def _to_str_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for key, raw_value in value.items():
        key_text = _normalize_str(key)
        value_text = _normalize_str(raw_value)
        if key_text:
            out[key_text] = value_text
    return out


def _parse_catalog(payload: dict[str, object]) -> NewsTaxonomyCatalog:
    raw_factors = payload.get("factors")
    factors: list[FactorDefinition] = []
    if isinstance(raw_factors, list):
        for item in raw_factors:
            if not isinstance(item, dict):
                continue
            code = _normalize_str(item.get("code"))
            if not code:
                continue
            factors.append(
                FactorDefinition(
                    code=code,
                    description=_normalize_str(item.get("description")),
                )
            )

    raw_families = payload.get("event_families")
    event_families: list[EventFamilyDefinition] = []
    if isinstance(raw_families, list):
        for item in raw_families:
            if not isinstance(item, dict):
                continue
            code = _normalize_str(item.get("code"))
            if not code:
                continue
            event_families.append(
                EventFamilyDefinition(
                    code=code,
                    category=_normalize_str(item.get("category")) or "episodic",
                    commodities=_to_str_tuple(item.get("commodities")),
                    anchor_sources=_to_str_tuple(item.get("anchor_sources")),
                    default_factors=_to_str_dict(item.get("default_factors")),
                )
            )

    return NewsTaxonomyCatalog(
        schema_version=_normalize_str(payload.get("schema_version")) or "v0",
        factors=tuple(factors),
        event_families=tuple(event_families),
    )


@lru_cache(maxsize=4)
def load_news_taxonomy_catalog(path: str | None = None) -> NewsTaxonomyCatalog:
    target = Path(path) if path else _default_taxonomy_path()
    if not target.exists():
        return NewsTaxonomyCatalog(schema_version="v0", factors=(), event_families=())
    with target.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        return NewsTaxonomyCatalog(schema_version="v0", factors=(), event_families=())
    return _parse_catalog(payload)

