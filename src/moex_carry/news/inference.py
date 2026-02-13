from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterable


def _safe_import(name: str):
    try:
        module = __import__(name, fromlist=["*"])
        return module
    except Exception:
        return None


def _normalize_probs(prob_up: float, prob_down: float, prob_neutral: float) -> tuple[float, float, float]:
    values = [max(float(prob_up), 0.0), max(float(prob_down), 0.0), max(float(prob_neutral), 0.0)]
    total = sum(values)
    if total <= 0.0:
        return 0.0, 0.0, 1.0
    return values[0] / total, values[1] / total, values[2] / total


def _heuristic_score(text: str) -> tuple[float, float, float]:
    lowered = text.lower()
    up_words = ["cut", "shortage", "stimulus", "demand rose", "supply drop", "sanction", "bullish"]
    down_words = ["oversupply", "demand fell", "recession", "output rise", "inventory build", "bearish"]
    up_hits = sum(1 for word in up_words if word in lowered)
    down_hits = sum(1 for word in down_words if word in lowered)
    if up_hits == down_hits:
        return 0.2, 0.2, 0.6
    if up_hits > down_hits:
        return min(0.2 + 0.15 * up_hits, 0.9), 0.1, 0.1
    return 0.1, min(0.2 + 0.15 * down_hits, 0.9), 0.1


def _predict_finbert(text: str, model_name: str) -> tuple[float, float, float]:
    transformers = _safe_import("transformers")
    if transformers is None:
        return _heuristic_score(text)
    try:
        pipeline = transformers.pipeline(
            "text-classification",
            model=model_name,
            tokenizer=model_name,
            top_k=None,
            truncation=True,
        )
        result = pipeline(text)
        if isinstance(result, list) and result and isinstance(result[0], list):
            result = result[0]
        scores = {str(item.get("label", "")).lower(): float(item.get("score", 0.0)) for item in result}
        prob_up = scores.get("positive", 0.0)
        prob_down = scores.get("negative", 0.0)
        prob_neutral = scores.get("neutral", 0.0)
        return _normalize_probs(prob_up, prob_down, prob_neutral)
    except Exception:
        return _heuristic_score(text)


def _predict_nli(text: str, model_name: str) -> tuple[float, float, float]:
    transformers = _safe_import("transformers")
    if transformers is None:
        return _heuristic_score(text)
    try:
        pipeline = transformers.pipeline("zero-shot-classification", model=model_name)
        labels = ["price up", "price down", "price neutral"]
        result = pipeline(text, candidate_labels=labels, multi_label=False)
        label_scores = {
            str(label).strip().lower(): float(score)
            for label, score in zip(result.get("labels", []), result.get("scores", []))
        }
        prob_up = label_scores.get("price up", 0.0)
        prob_down = label_scores.get("price down", 0.0)
        prob_neutral = label_scores.get("price neutral", 0.0)
        return _normalize_probs(prob_up, prob_down, prob_neutral)
    except Exception:
        return _heuristic_score(text)


def _direction_from_probs(prob_up: float, prob_down: float, prob_neutral: float) -> str:
    if prob_up >= prob_down and prob_up >= prob_neutral:
        return "up"
    if prob_down >= prob_up and prob_down >= prob_neutral:
        return "down"
    return "neutral"


def _impact_from_probs(prob_up: float, prob_down: float, prob_neutral: float) -> float:
    directional = max(prob_up, prob_down)
    return max(min(directional * (1.0 - prob_neutral * 0.5), 1.0), 0.0)


def run_dual_model_inference(
    *,
    news_id: str,
    text: str,
    enabled_models: Iterable[str],
    finbert_model_name: str,
    nli_model_name: str,
    model_version: str = "v1",
) -> list[dict[str, object]]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    normalized_models = [str(item).strip().lower() for item in enabled_models if str(item).strip()]
    rows: list[dict[str, object]] = []

    if "finbert" in normalized_models:
        prob_up, prob_down, prob_neutral = _predict_finbert(text, finbert_model_name)
        rows.append(
            _build_score_row(
                news_id=news_id,
                model_id="finbert",
                model_version=model_version,
                prob_up=prob_up,
                prob_down=prob_down,
                prob_neutral=prob_neutral,
                inference_ts=now,
            )
        )

    if "nli" in normalized_models:
        prob_up, prob_down, prob_neutral = _predict_nli(text, nli_model_name)
        rows.append(
            _build_score_row(
                news_id=news_id,
                model_id="nli",
                model_version=model_version,
                prob_up=prob_up,
                prob_down=prob_down,
                prob_neutral=prob_neutral,
                inference_ts=now,
            )
        )

    return rows


def _build_score_row(
    *,
    news_id: str,
    model_id: str,
    model_version: str,
    prob_up: float,
    prob_down: float,
    prob_neutral: float,
    inference_ts: datetime,
) -> dict[str, object]:
    prob_up, prob_down, prob_neutral = _normalize_probs(prob_up, prob_down, prob_neutral)
    direction = _direction_from_probs(prob_up, prob_down, prob_neutral)
    impact_score = _impact_from_probs(prob_up, prob_down, prob_neutral)
    return {
        "news_id": news_id,
        "model_id": model_id,
        "model_version": model_version,
        "direction": direction,
        "prob_up": prob_up,
        "prob_down": prob_down,
        "prob_neutral": prob_neutral,
        "impact_score": impact_score,
        "calibrated": False,
        "inference_ts": inference_ts,
        "score_hash": hashlib.sha1(
            f"{news_id}|{model_id}|{model_version}|{inference_ts.isoformat()}".encode("utf-8")
        ).hexdigest()[:16],
    }
