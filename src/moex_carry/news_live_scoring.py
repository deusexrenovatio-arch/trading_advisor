from __future__ import annotations

from dataclasses import dataclass


MODEL_NAME_KEYWORD = "keyword_v1"
SEVERITY_ORDER = ("low", "medium", "high", "critical")


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _keyword_sets() -> dict[str, dict[str, set[str]]]:
    return {
        "BRN": {
            "up": {
                "attack",
                "drone",
                "missile",
                "explosion",
                "pipeline outage",
                "disruption",
                "opec cut",
                "output cut",
                "sanctions",
                "hormuz",
                "red sea",
                "suez",
            },
            "down": {
                "inventory build",
                "stocks build",
                "output increase",
                "opec increase",
                "demand slowdown",
                "recession",
                "oversupply",
                "ceasefire",
            },
        },
        "GOLD": {
            "up": {
                "safe haven",
                "geopolitical",
                "risk-off",
                "rate cut",
                "dovish",
                "real yields fall",
                "dollar weak",
                "uncertainty",
            },
            "down": {
                "hawkish",
                "yields rise",
                "real yields rise",
                "dollar stronger",
                "risk-on",
                "rate hike",
                "profit-taking",
            },
        },
        "NG_US": {
            "up": {
                "cold",
                "colder",
                "freeze",
                "freeze-off",
                "storm",
                "withdrawal",
                "draw",
                "hdd",
                "pipeline outage",
                "supply disruption",
            },
            "down": {
                "warm",
                "warmer",
                "injection",
                "build",
                "production increase",
                "output rise",
                "lng outage",
                "maintenance restart",
            },
        },
    }


def _match_keywords(text: str, terms: set[str]) -> list[str]:
    matched: list[str] = []
    lowered = text.lower()
    for term in sorted(terms):
        if term in lowered:
            matched.append(term)
    return matched


def score_article(*, commodity: str, title: str, description: str, content: str) -> dict[str, object]:
    table = _keyword_sets().get(commodity.upper(), {"up": set(), "down": set()})
    full_text = " ".join(
        part for part in (_normalize_text(title), _normalize_text(description), _normalize_text(content)) if part
    )
    title_text = _normalize_text(title)

    up_hits = set(_match_keywords(full_text, table["up"]))
    down_hits = set(_match_keywords(full_text, table["down"]))
    title_up_hits = set(_match_keywords(title_text, table["up"]))
    title_down_hits = set(_match_keywords(title_text, table["down"]))

    up_weight = float(len(up_hits) + len(title_up_hits))
    down_weight = float(len(down_hits) + len(title_down_hits))
    direction_score = up_weight - down_weight

    if direction_score > 0.5:
        direction = "up"
    elif direction_score < -0.5:
        direction = "down"
    else:
        direction = "hold"

    raw_impact = 0.1 + 0.12 * (up_weight + down_weight)
    lowered = full_text.lower()
    if "attack" in lowered or "missile" in lowered or "explosion" in lowered:
        raw_impact += 0.25
    if "opec" in lowered or "eia" in lowered or "fomc" in lowered:
        raw_impact += 0.12
    impact_score = max(0.0, min(raw_impact, 1.0))

    confidence = 0.35 + 0.18 * abs(direction_score) + 0.08 * (len(up_hits) + len(down_hits))
    confidence = max(0.0, min(confidence, 1.0))

    if impact_score >= 0.8:
        severity = "critical"
    elif impact_score >= 0.6:
        severity = "high"
    elif impact_score >= 0.35:
        severity = "medium"
    else:
        severity = "low"

    if direction == "hold" and impact_score < 0.45:
        confidence = min(confidence, 0.6)

    return {
        "direction": direction,
        "impact_score": round(float(impact_score), 6),
        "confidence": round(float(confidence), 6),
        "severity": severity,
        "reason_terms_up": sorted(up_hits),
        "reason_terms_down": sorted(down_hits),
    }


@dataclass
class ScoringModelConfig:
    mode: str
    nli_model_name: str
    finbert_model_name: str
    model_device: str


class ModelScorer:
    def __init__(self, config: ScoringModelConfig) -> None:
        mode = str(config.mode or "keyword").strip().lower()
        self.mode = mode if mode in {"keyword", "nli", "finbert", "auto"} else "keyword"
        self.nli_model_name = config.nli_model_name
        self.finbert_model_name = config.finbert_model_name
        self.model_device = self._resolve_device(config.model_device)
        self._nli_pipeline = None
        self._finbert_pipeline = None
        self._pipeline_error: str | None = None

    @staticmethod
    def _resolve_device(raw: str) -> int:
        normalized = str(raw or "auto").strip().lower()
        if normalized in {"cpu", "-1"}:
            return -1
        if normalized in {"gpu", "cuda", "auto", "0"}:
            try:
                import torch

                if torch.cuda.is_available():
                    return 0
            except Exception:  # pragma: no cover - optional dependency
                return -1
            return -1
        try:
            parsed = int(normalized)
            return parsed
        except Exception:
            return -1

    def _try_load_nli(self):
        if self._nli_pipeline is not None or self._pipeline_error is not None:
            return self._nli_pipeline
        try:
            from transformers import pipeline

            self._nli_pipeline = pipeline(
                "zero-shot-classification",
                model=self.nli_model_name,
                device=self.model_device,
            )
            return self._nli_pipeline
        except Exception as exc:  # pragma: no cover - runtime fallback
            self._pipeline_error = f"nli:{exc}"
            return None

    def _try_load_finbert(self):
        if self._finbert_pipeline is not None or self._pipeline_error is not None:
            return self._finbert_pipeline
        try:
            from transformers import pipeline

            self._finbert_pipeline = pipeline(
                "text-classification",
                model=self.finbert_model_name,
                return_all_scores=True,
                device=self.model_device,
            )
            return self._finbert_pipeline
        except Exception as exc:  # pragma: no cover - runtime fallback
            self._pipeline_error = f"finbert:{exc}"
            return None

    def _score_nli(self, text: str) -> dict[str, object] | None:
        pipeline_obj = self._try_load_nli()
        if pipeline_obj is None:
            return None
        labels = ["bullish pressure", "bearish pressure", "no directional pressure"]
        result = pipeline_obj(
            text,
            candidate_labels=labels,
            hypothesis_template="This news implies {} for nearby commodity futures.",
        )
        scores = {label: float(score) for label, score in zip(result["labels"], result["scores"])}
        bull = scores.get("bullish pressure", 0.0)
        bear = scores.get("bearish pressure", 0.0)
        neutral = scores.get("no directional pressure", 0.0)
        if bull >= bear and bull >= neutral:
            direction = "up"
            conf = bull
        elif bear >= bull and bear >= neutral:
            direction = "down"
            conf = bear
        else:
            direction = "hold"
            conf = neutral
        impact = min(1.0, max(0.0, 0.2 + abs(bull - bear) + 0.3 * (1.0 - neutral)))
        severity = "critical" if impact >= 0.8 else "high" if impact >= 0.6 else "medium" if impact >= 0.35 else "low"
        return {
            "direction": direction,
            "impact_score": round(float(impact), 6),
            "confidence": round(float(conf), 6),
            "severity": severity,
            "reason_terms_up": [],
            "reason_terms_down": [],
            "model_name": "nli",
        }

    def _score_finbert(self, text: str) -> dict[str, object] | None:
        pipeline_obj = self._try_load_finbert()
        if pipeline_obj is None:
            return None
        result = pipeline_obj(text)
        if not result or not isinstance(result, list) or not isinstance(result[0], list):
            return None
        scores = {str(item.get("label", "")).lower(): float(item.get("score", 0.0)) for item in result[0]}
        pos = scores.get("positive", 0.0)
        neg = scores.get("negative", 0.0)
        neu = scores.get("neutral", 0.0)
        if pos >= neg and pos >= neu:
            direction = "up"
            conf = pos
        elif neg >= pos and neg >= neu:
            direction = "down"
            conf = neg
        else:
            direction = "hold"
            conf = neu
        impact = min(1.0, max(0.0, 0.15 + abs(pos - neg) + 0.25 * (1.0 - neu)))
        severity = "critical" if impact >= 0.8 else "high" if impact >= 0.6 else "medium" if impact >= 0.35 else "low"
        return {
            "direction": direction,
            "impact_score": round(float(impact), 6),
            "confidence": round(float(conf), 6),
            "severity": severity,
            "reason_terms_up": [],
            "reason_terms_down": [],
            "model_name": "finbert",
        }

    def score(self, *, commodity: str, title: str, description: str, content: str) -> dict[str, object]:
        text = " ".join(part for part in (title, description, content) if part).strip()
        if not text:
            base = score_article(commodity=commodity, title=title, description=description, content=content)
            base["model_name"] = "keyword"
            return base
        ordered_modes = (
            ["nli", "finbert", "keyword"]
            if self.mode == "auto"
            else [self.mode, "keyword"] if self.mode in {"nli", "finbert"} else ["keyword"]
        )
        for mode in ordered_modes:
            if mode == "nli":
                scored = self._score_nli(text)
                if scored is not None:
                    return scored
            elif mode == "finbert":
                scored = self._score_finbert(text)
                if scored is not None:
                    return scored
            else:
                base = score_article(commodity=commodity, title=title, description=description, content=content)
                base["model_name"] = "keyword"
                return base
        base = score_article(commodity=commodity, title=title, description=description, content=content)
        base["model_name"] = "keyword"
        return base

