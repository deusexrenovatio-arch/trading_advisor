from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from moex_carry.domain.portfolio import SnapshotPerPair


@dataclass(frozen=True)
class AllocationInput:
    pair_id: str
    score: float
    sigma: float
    score_floor: float
    score_alpha: float


def _normalize(weights: dict[str, float], epsilon: float) -> dict[str, float]:
    total = sum(weights.values())
    if total <= epsilon:
        count = len(weights)
        if count == 0:
            return {}
        return {key: 1.0 / count for key in weights}
    return {key: value / total for key, value in weights.items()}


def _apply_max_weight(weights: dict[str, float], max_weight: float | None, epsilon: float) -> dict[str, float]:
    if max_weight is None:
        return weights
    if max_weight <= 0:
        return {key: 0.0 for key in weights}

    normalized = dict(weights)
    capped = True
    while capped:
        capped = False
        overflow = 0.0
        remaining: dict[str, float] = {}
        for key, value in normalized.items():
            if value > max_weight:
                overflow += value - max_weight
                normalized[key] = max_weight
                capped = True
            else:
                remaining[key] = value
        if capped and overflow > epsilon and remaining:
            remaining_total = sum(remaining.values())
            if remaining_total <= epsilon:
                break
            for key in remaining:
                normalized[key] += overflow * (remaining[key] / remaining_total)
    return normalized


def equal_weights(items: Iterable[AllocationInput], epsilon: float) -> dict[str, float]:
    ids = [item.pair_id for item in items]
    base = {pair_id: 1.0 for pair_id in ids}
    return _normalize(base, epsilon)


def score_weighted_weights(items: Iterable[AllocationInput], epsilon: float) -> dict[str, float]:
    base = {item.pair_id: max(item.score, 0.0) for item in items}
    if sum(base.values()) <= epsilon:
        return equal_weights(items, epsilon)
    return _normalize(base, epsilon)


def score_risk_parity_weights(items: Iterable[AllocationInput], epsilon: float) -> dict[str, float]:
    base: dict[str, float] = {}
    for item in items:
        score = max(item.score, 0.0)
        sigma = item.sigma if item.sigma > epsilon else 1.0
        base[item.pair_id] = score / sigma
    if sum(base.values()) <= epsilon:
        return equal_weights(items, epsilon)
    return _normalize(base, epsilon)


def floor_plus_alpha_overlay_weights(
    items: Iterable[AllocationInput],
    *,
    alpha_overlay_weight: float,
    epsilon: float,
) -> dict[str, float]:
    base = {
        item.pair_id: max(item.score_floor, 0.0) + alpha_overlay_weight * max(item.score_alpha, 0.0)
        for item in items
    }
    if sum(base.values()) <= epsilon:
        return equal_weights(items, epsilon)
    return _normalize(base, epsilon)


def build_allocation_inputs(snapshots: Iterable[SnapshotPerPair]) -> dict[str, AllocationInput]:
    inputs: dict[str, AllocationInput] = {}
    for snapshot in snapshots:
        pair_id = f"{snapshot.stock_secid}|{snapshot.future_secid}"
        score = float(snapshot.scores.total_score) if snapshot.scores.total_score is not None else 0.0
        sigma = float(snapshot.alpha.sigma_h) if snapshot.alpha.sigma_h is not None else 1.0
        score_floor = float(snapshot.scores.score_floor) if snapshot.scores.score_floor is not None else 0.0
        score_alpha = float(snapshot.scores.score_alpha) if snapshot.scores.score_alpha is not None else 0.0
        inputs[pair_id] = AllocationInput(
            pair_id=pair_id,
            score=score,
            sigma=sigma,
            score_floor=score_floor,
            score_alpha=score_alpha,
        )
    return inputs


def compute_allocation_weights(
    items: Iterable[AllocationInput],
    method: str,
    *,
    max_weight: float | None,
    alpha_overlay_weight: float,
    epsilon: float,
) -> dict[str, float]:
    method_key = method.upper()
    items_list = list(items)
    if method_key == "EQUAL":
        weights = equal_weights(items_list, epsilon)
    elif method_key == "SCORE_WEIGHTED":
        weights = score_weighted_weights(items_list, epsilon)
    elif method_key == "SCORE_RISK_PARITY":
        weights = score_risk_parity_weights(items_list, epsilon)
    elif method_key == "FLOOR_PLUS_ALPHA_OVERLAY":
        weights = floor_plus_alpha_overlay_weights(
            items_list,
            alpha_overlay_weight=alpha_overlay_weight,
            epsilon=epsilon,
        )
    else:
        weights = equal_weights(items_list, epsilon)

    weights = _normalize(weights, epsilon)
    weights = _apply_max_weight(weights, max_weight, epsilon)
    weights = _normalize(weights, epsilon)
    return weights
