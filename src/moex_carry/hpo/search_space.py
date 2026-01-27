from __future__ import annotations

import math
import random
from typing import Any, Iterable, Mapping

from moex_carry.hpo.types import SearchSpaceParam


def parse_search_space(search_space: Mapping[str, Any]) -> list[SearchSpaceParam]:
    if not isinstance(search_space, Mapping):
        raise TypeError("search_space must be a mapping of key -> spec")
    params: list[SearchSpaceParam] = []
    for key, raw in search_space.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"invalid search_space key: {key!r}")
        params.append(_parse_param(key, raw))
    return params


def _parse_param(key: str, raw: Any) -> SearchSpaceParam:
    if isinstance(raw, SearchSpaceParam):
        return raw
    if isinstance(raw, Mapping):
        value_type = _normalize_value_type(raw.get("type") or raw.get("value_type"))
        if "options" in raw or "choices" in raw:
            options = list(raw.get("options") or raw.get("choices") or [])
            if not options:
                raise ValueError(f"{key}: options empty")
            return SearchSpaceParam(key=key, kind="categorical", options=options)
        if "min" in raw or "max" in raw or "min_value" in raw or "max_value" in raw:
            min_value = raw.get("min", raw.get("min_value"))
            max_value = raw.get("max", raw.get("max_value"))
            if min_value is None or max_value is None:
                raise ValueError(f"{key}: both min and max are required for numeric ranges")
            kind = "int" if value_type == "int" else "float"
            step = raw.get("step")
            log = bool(raw.get("log", False))
            return SearchSpaceParam(
                key=key,
                kind=kind,
                min_value=float(min_value),
                max_value=float(max_value),
                step=float(step) if step is not None else None,
                log=log,
            )
        if "value" in raw:
            return SearchSpaceParam(key=key, kind="categorical", options=[raw["value"]])
        if value_type in {"bool", "boolean"}:
            return SearchSpaceParam(key=key, kind="bool", options=[True, False])
        raise ValueError(f"{key}: unsupported search space spec")
    if isinstance(raw, (list, tuple, set)):
        options = list(raw)
        if not options:
            raise ValueError(f"{key}: options empty")
        return SearchSpaceParam(key=key, kind="categorical", options=options)
    return SearchSpaceParam(key=key, kind="categorical", options=[raw])


def _normalize_value_type(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"int", "integer"}:
        return "int"
    if text in {"float", "double", "number"}:
        return "float"
    if text in {"bool", "boolean"}:
        return "bool"
    if text in {"categorical", "choice"}:
        return "categorical"
    return text


def sample_random(params: Iterable[SearchSpaceParam], rng: random.Random) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for param in params:
        if param.kind == "categorical" or param.kind == "bool":
            if not param.options:
                raise ValueError(f"{param.key}: options required for categorical sampling")
            result[param.key] = rng.choice(list(param.options))
            continue
        if param.min_value is None or param.max_value is None:
            raise ValueError(f"{param.key}: min/max required for numeric sampling")
        if param.kind == "int":
            value = _sample_int(param, rng)
        else:
            value = _sample_float(param, rng)
        result[param.key] = value
    return result


def sample_tpe(
    params: Iterable[SearchSpaceParam],
    trials: Iterable[Any],
    rng: random.Random,
    *,
    mode: str = "max",
    quantile: float = 0.25,
    startup_trials: int = 10,
) -> dict[str, Any]:
    params = list(params)
    trials = list(trials)
    if len(trials) < startup_trials:
        return sample_random(params, rng)
    scored = _finite_trials(trials)
    if not scored:
        return sample_random(params, rng)
    reverse = mode == "max"
    scored.sort(key=lambda trial: trial.objective, reverse=reverse)
    good_count = max(1, int(len(scored) * quantile))
    good = scored[:good_count]
    result: dict[str, Any] = {}
    for param in params:
        if param.kind in {"categorical", "bool"}:
            result[param.key] = _sample_categorical_tpe(param, good, rng)
        elif param.kind == "int":
            result[param.key] = _sample_numeric_tpe(param, good, rng, as_int=True)
        else:
            result[param.key] = _sample_numeric_tpe(param, good, rng, as_int=False)
    return result


def _finite_trials(trials: Iterable[Any]) -> list[Any]:
    keep: list[Any] = []
    for trial in trials:
        obj = getattr(trial, "objective", None)
        if obj is None:
            continue
        if isinstance(obj, (int, float)) and math.isfinite(obj):
            keep.append(trial)
    return keep


def _sample_int(param: SearchSpaceParam, rng: random.Random) -> int:
    min_value = int(round(param.min_value or 0))
    max_value = int(round(param.max_value or 0))
    if min_value > max_value:
        min_value, max_value = max_value, min_value
    if param.step and param.step > 0:
        step = float(param.step)
        span = max_value - min_value
        steps = int(math.floor(span / step)) if step > 0 else 0
        choice = rng.randint(0, max(steps, 0))
        return int(round(min_value + choice * step))
    return rng.randint(min_value, max_value)


def _sample_float(param: SearchSpaceParam, rng: random.Random) -> float:
    min_value = float(param.min_value or 0.0)
    max_value = float(param.max_value or 0.0)
    if min_value > max_value:
        min_value, max_value = max_value, min_value
    if param.log and min_value > 0 and max_value > 0:
        value = math.exp(rng.uniform(math.log(min_value), math.log(max_value)))
    else:
        value = rng.uniform(min_value, max_value)
    if param.step and param.step > 0:
        value = _quantize(value, param.step, min_value)
    value = max(min_value, min(max_value, value))
    return float(value)


def _quantize(value: float, step: float, base: float) -> float:
    if step <= 0:
        return value
    return base + round((value - base) / step) * step


def _sample_categorical_tpe(param: SearchSpaceParam, good: list[Any], rng: random.Random) -> Any:
    if not param.options:
        raise ValueError(f"{param.key}: options required for categorical sampling")
    weights = {option: 1.0 for option in param.options}
    for trial in good:
        value = trial.params.get(param.key)
        if value in weights:
            weights[value] += 1.0
    total = sum(weights.values())
    pick = rng.random() * total
    cumulative = 0.0
    for option, weight in weights.items():
        cumulative += weight
        if pick <= cumulative:
            return option
    return rng.choice(list(param.options))


def _sample_numeric_tpe(
    param: SearchSpaceParam,
    good: list[Any],
    rng: random.Random,
    *,
    as_int: bool,
) -> Any:
    min_value = float(param.min_value or 0.0)
    max_value = float(param.max_value or 0.0)
    if min_value > max_value:
        min_value, max_value = max_value, min_value
    values: list[float] = []
    for trial in good:
        raw_value = trial.params.get(param.key)
        if raw_value is None:
            continue
        try:
            values.append(float(raw_value))
        except (TypeError, ValueError):
            continue
    if not values:
        return _sample_int(param, rng) if as_int else _sample_float(param, rng)
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / max(len(values) - 1, 1)
    std = var**0.5
    std = std if std > 0 else (max_value - min_value) * 0.1
    candidate = rng.gauss(mean, std)
    candidate = max(min_value, min(max_value, candidate))
    if param.step and param.step > 0:
        candidate = _quantize(candidate, param.step, min_value)
    if as_int:
        candidate = int(round(candidate))
        return int(max(min_value, min(max_value, candidate)))
    return float(candidate)
