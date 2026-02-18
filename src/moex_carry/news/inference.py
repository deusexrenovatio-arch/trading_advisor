from __future__ import annotations

import hashlib
import importlib
import os
from datetime import datetime, timezone
from typing import Iterable


_PIPELINE_CACHE: dict[str, object] = {}
_RUNTIME_LIMITS_APPLIED = False
_RUNTIME_LIMITS_LAST_CAP: int | None = None


def _safe_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _resolve_thread_cap(value: int | None) -> int | None:
    if value is None:
        return None
    normalized = int(value)
    if normalized < 0:
        return None
    if normalized > 0:
        return normalized
    cpu_count = max(int(os.cpu_count() or 4), 1)
    return max(1, min(8, cpu_count // 2))


def apply_inference_runtime_limits(*, thread_cap: int | None = 0, force: bool = False) -> None:
    global _RUNTIME_LIMITS_APPLIED
    global _RUNTIME_LIMITS_LAST_CAP
    if _RUNTIME_LIMITS_APPLIED:
        if not force and _RUNTIME_LIMITS_LAST_CAP == _resolve_thread_cap(thread_cap):
            return
    cap = _resolve_thread_cap(thread_cap)
    if cap is None:
        _RUNTIME_LIMITS_APPLIED = True
        _RUNTIME_LIMITS_LAST_CAP = None
        return

    cap_text = str(cap)
    for env_name in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "TOKENIZERS_PARALLELISM",
    ):
        if env_name == "TOKENIZERS_PARALLELISM":
            if force:
                os.environ[env_name] = "false"
            else:
                os.environ.setdefault(env_name, "false")
        else:
            if force:
                os.environ[env_name] = cap_text
            else:
                os.environ.setdefault(env_name, cap_text)
    if force:
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    else:
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

    torch_mod = _safe_import("torch")
    if torch_mod is not None:
        try:
            torch_mod.set_num_threads(cap)
        except Exception:
            pass
        try:
            interop_threads = max(1, min(cap, 4))
            torch_mod.set_num_interop_threads(interop_threads)
        except Exception:
            pass
    _RUNTIME_LIMITS_APPLIED = True
    _RUNTIME_LIMITS_LAST_CAP = cap


def _get_cached_pipeline(task: str, model_name: str, **kwargs):
    transformers = _safe_import("transformers")
    if transformers is None:
        return None
    cache_key = f"{task}|{model_name}|{hash(tuple(sorted(kwargs.items())))}"
    cached = _PIPELINE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        pipeline = transformers.pipeline(task, model=model_name, tokenizer=model_name, **kwargs)
    except Exception:
        return None
    _PIPELINE_CACHE[cache_key] = pipeline
    return pipeline


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
    pipeline = _get_cached_pipeline(
        "text-classification",
        model_name,
        top_k=None,
        truncation=True,
    )
    if pipeline is None:
        return _heuristic_score(text)
    try:
        result = pipeline(text)
    except Exception:
        return _heuristic_score(text)
    if isinstance(result, list) and result and isinstance(result[0], list):
        result = result[0]
    scores = {str(item.get("label", "")).lower(): float(item.get("score", 0.0)) for item in result}
    prob_up = scores.get("positive", 0.0)
    prob_down = scores.get("negative", 0.0)
    prob_neutral = scores.get("neutral", 0.0)
    return _normalize_probs(prob_up, prob_down, prob_neutral)


def _predict_nli(text: str, model_name: str) -> tuple[float, float, float]:
    pipeline = _get_cached_pipeline("zero-shot-classification", model_name)
    if pipeline is None:
        return _heuristic_score(text)
    try:
        labels = ["price up", "price down", "price neutral"]
        result = pipeline(text, candidate_labels=labels, multi_label=False)
    except Exception:
        return _heuristic_score(text)
    label_scores = {
        str(label).strip().lower(): float(score)
        for label, score in zip(result.get("labels", []), result.get("scores", []))
    }
    prob_up = label_scores.get("price up", 0.0)
    prob_down = label_scores.get("price down", 0.0)
    prob_neutral = label_scores.get("price neutral", 0.0)
    return _normalize_probs(prob_up, prob_down, prob_neutral)


def _normalize_text(text: str, *, max_chars: int) -> str:
    normalized = str(text or "").strip()
    if max_chars > 0 and len(normalized) > max_chars:
        return normalized[:max_chars]
    return normalized


def _predict_finbert_batch(
    *,
    texts: list[str],
    model_name: str,
    batch_size: int,
) -> list[tuple[float, float, float]]:
    if not texts:
        return []
    pipeline = _get_cached_pipeline(
        "text-classification",
        model_name,
        top_k=None,
        truncation=True,
    )
    if pipeline is None:
        return [_heuristic_score(text) for text in texts]
    try:
        result = pipeline(texts, batch_size=max(int(batch_size), 1))
    except Exception:
        return [_heuristic_score(text) for text in texts]

    if isinstance(result, dict):
        result_items = [result]
    else:
        result_items = list(result)

    scores_list: list[tuple[float, float, float]] = []
    for idx, item in enumerate(result_items):
        parsed = item[0] if isinstance(item, list) and item and isinstance(item[0], list) else item
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            scores_list.append(_heuristic_score(texts[idx]))
            continue
        scores = {str(entry.get("label", "")).lower(): float(entry.get("score", 0.0)) for entry in parsed}
        scores_list.append(
            _normalize_probs(
                scores.get("positive", 0.0),
                scores.get("negative", 0.0),
                scores.get("neutral", 0.0),
            )
        )
    while len(scores_list) < len(texts):
        scores_list.append(_heuristic_score(texts[len(scores_list)]))
    return scores_list


def _predict_nli_batch(
    *,
    texts: list[str],
    model_name: str,
    batch_size: int,
) -> list[tuple[float, float, float]]:
    if not texts:
        return []
    pipeline = _get_cached_pipeline("zero-shot-classification", model_name)
    if pipeline is None:
        return [_heuristic_score(text) for text in texts]

    labels = ["price up", "price down", "price neutral"]
    try:
        result = pipeline(
            texts,
            candidate_labels=labels,
            multi_label=False,
            batch_size=max(int(batch_size), 1),
        )
    except Exception:
        return [_heuristic_score(text) for text in texts]

    if isinstance(result, dict):
        result_items = [result]
    else:
        result_items = list(result)

    scores_list: list[tuple[float, float, float]] = []
    for idx, item in enumerate(result_items):
        if not isinstance(item, dict):
            scores_list.append(_heuristic_score(texts[idx]))
            continue
        label_scores = {
            str(label).strip().lower(): float(score)
            for label, score in zip(item.get("labels", []), item.get("scores", []))
        }
        scores_list.append(
            _normalize_probs(
                label_scores.get("price up", 0.0),
                label_scores.get("price down", 0.0),
                label_scores.get("price neutral", 0.0),
            )
        )
    while len(scores_list) < len(texts):
        scores_list.append(_heuristic_score(texts[len(scores_list)]))
    return scores_list


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
    return run_dual_model_inference_batch(
        news_items=[{"news_id": news_id, "text": text}],
        enabled_models=enabled_models,
        finbert_model_name=finbert_model_name,
        nli_model_name=nli_model_name,
        model_version=model_version,
    )


def run_dual_model_inference_batch(
    *,
    news_items: Iterable[dict[str, str]],
    enabled_models: Iterable[str],
    finbert_model_name: str,
    nli_model_name: str,
    model_version: str = "v1",
    batch_size: int = 16,
    text_max_chars: int = 2000,
    thread_cap: int | None = 0,
) -> list[dict[str, object]]:
    apply_inference_runtime_limits(thread_cap=thread_cap)
    normalized_models = [str(item).strip().lower() for item in enabled_models if str(item).strip()]
    filtered_items: list[dict[str, str]] = []
    for item in news_items:
        news_id = str(item.get("news_id") or "").strip()
        text = _normalize_text(str(item.get("text") or ""), max_chars=max(int(text_max_chars), 0))
        if not news_id or not text:
            continue
        filtered_items.append({"news_id": news_id, "text": text})
    if not filtered_items:
        return []

    rows: list[dict[str, object]] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    texts = [item["text"] for item in filtered_items]
    item_ids = [item["news_id"] for item in filtered_items]
    normalized_batch_size = max(int(batch_size), 1)

    if "finbert" in normalized_models:
        finbert_scores = _predict_finbert_batch(
            texts=texts,
            model_name=finbert_model_name,
            batch_size=normalized_batch_size,
        )
        for news_id, (prob_up, prob_down, prob_neutral) in zip(item_ids, finbert_scores):
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
        nli_scores = _predict_nli_batch(
            texts=texts,
            model_name=nli_model_name,
            batch_size=normalized_batch_size,
        )
        for news_id, (prob_up, prob_down, prob_neutral) in zip(item_ids, nli_scores):
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
