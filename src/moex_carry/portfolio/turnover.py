from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from moex_carry.domain.portfolio import PairSpec, SnapshotPerPair


@dataclass(frozen=True)
class TurnoverEntry:
    pair_id: str
    delta_stock: float
    delta_fut: float
    spot_mid: float | None
    fut_mid: float | None
    multiplier: float

    @property
    def notional(self) -> float:
        stock_part = abs(self.delta_stock) * (self.spot_mid or 0.0)
        fut_part = abs(self.delta_fut) * (self.fut_mid or 0.0) * self.multiplier
        return stock_part + fut_part


@dataclass
class TurnoverCapResult:
    scaled_targets: dict[str, int]
    turnover_notional: float
    scale_factor: float
    warnings: list[str]


def build_turnover_entries(
    deltas: Mapping[str, tuple[float, float]],
    snapshots: Mapping[str, SnapshotPerPair],
    pairs: Mapping[str, PairSpec],
) -> list[TurnoverEntry]:
    entries: list[TurnoverEntry] = []
    for pair_id, (delta_stock, delta_fut) in deltas.items():
        snapshot = snapshots.get(pair_id)
        pair = pairs.get(pair_id)
        if snapshot is None or pair is None:
            continue
        multiplier = float(pair.multiplier) if pair.multiplier else 1.0
        entries.append(
            TurnoverEntry(
                pair_id=pair_id,
                delta_stock=delta_stock,
                delta_fut=delta_fut,
                spot_mid=snapshot.spot_mid,
                fut_mid=snapshot.future_mid,
                multiplier=multiplier,
            )
        )
    return entries


def estimate_turnover_notional(entries: list[TurnoverEntry]) -> float:
    return sum(entry.notional for entry in entries)


def apply_turnover_cap(
    *,
    current_contracts: Mapping[str, int],
    target_contracts: Mapping[str, int],
    per_contract_notional: Mapping[str, float],
    limit_notional: float,
    preserve_pairs: set[str],
) -> TurnoverCapResult:
    warnings: list[str] = []
    if limit_notional <= 0:
        scaled: dict[str, int] = {}
        for pair_id, target in target_contracts.items():
            current = current_contracts.get(pair_id, 0)
            if target <= current or pair_id in preserve_pairs:
                scaled[pair_id] = target
            else:
                scaled[pair_id] = current
        return TurnoverCapResult(
            scaled_targets=scaled,
            turnover_notional=0.0,
            scale_factor=0.0,
            warnings=["turnover_limit_zero"],
        )

    reduction_turnover = 0.0
    increase_turnover = 0.0
    increase_pairs: list[str] = []
    for pair_id, target in target_contracts.items():
        current = current_contracts.get(pair_id, 0)
        notional_per_contract = per_contract_notional.get(pair_id, 0.0)
        delta = target - current
        if delta <= 0:
            reduction_turnover += abs(delta) * notional_per_contract
        else:
            increase_turnover += delta * notional_per_contract
            increase_pairs.append(pair_id)

    remaining = limit_notional - reduction_turnover
    if remaining < 0:
        warnings.append("turnover_reductions_exceed_limit")
        remaining = 0.0

    if increase_turnover <= 0:
        return TurnoverCapResult(
            scaled_targets=dict(target_contracts),
            turnover_notional=reduction_turnover,
            scale_factor=1.0,
            warnings=warnings,
        )

    if increase_turnover <= remaining:
        return TurnoverCapResult(
            scaled_targets=dict(target_contracts),
            turnover_notional=reduction_turnover + increase_turnover,
            scale_factor=1.0,
            warnings=warnings,
        )

    scale_factor = remaining / increase_turnover if increase_turnover > 0 else 0.0
    scaled_targets = dict(target_contracts)
    for pair_id in increase_pairs:
        if pair_id in preserve_pairs:
            continue
        current = current_contracts.get(pair_id, 0)
        target = target_contracts.get(pair_id, 0)
        delta = max(target - current, 0)
        scaled_delta = int(delta * scale_factor)
        scaled_targets[pair_id] = current + scaled_delta
    warnings.append("turnover_scaled")

    scaled_turnover = reduction_turnover
    for pair_id, target in scaled_targets.items():
        current = current_contracts.get(pair_id, 0)
        delta = abs(target - current)
        scaled_turnover += delta * per_contract_notional.get(pair_id, 0.0)

    return TurnoverCapResult(
        scaled_targets=scaled_targets,
        turnover_notional=scaled_turnover,
        scale_factor=scale_factor,
        warnings=warnings,
    )
