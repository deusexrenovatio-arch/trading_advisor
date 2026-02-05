from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from moex_carry.domain.portfolio import Order, PairSpec, PortfolioState, PositionState, SnapshotPerPair
from moex_carry.portfolio.allocation import build_allocation_inputs, compute_allocation_weights
from moex_carry.portfolio.contracts import RebalanceConfig, RebalanceResult, TargetPosition
from moex_carry.portfolio.turnover import apply_turnover_cap

EXIT_KILL = "EXIT_KILL"
EXIT_EXPIRY = "EXIT_EXPIRY"
EXIT_SL = "EXIT_SL"
EXIT_LIQ = "EXIT_LIQ"
EXIT_FLOOR_FAIL = "EXIT_FLOOR_FAIL"
EXIT_TIME = "EXIT_TIME"
EXIT_TP = "EXIT_TP"
EXIT_TRAIL = "EXIT_TRAIL"

SOFT_EXIT_SCORE = "SOFT_EXIT_SCORE"
SOFT_EXIT_DROP_RANK = "SOFT_EXIT_DROP_RANK"
ROTATION_REPLACE = "ROTATION_REPLACE"
BAND_REBALANCE_SKIP = "BAND_REBALANCE_SKIP"
TURNOVER_SCALED = "TURNOVER_SCALED"


def pair_key(stock_secid: str, future_secid: str) -> str:
    return f"{stock_secid}|{future_secid}"


def _as_date(value: date | datetime | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.today()


def _resolve_as_of_date(
    portfolio: PortfolioState | None,
    snapshots: Iterable[SnapshotPerPair],
) -> date:
    if portfolio is not None:
        return _as_date(portfolio.as_of)
    for snapshot in snapshots:
        return _as_date(snapshot.as_of)
    return date.today()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    if percentile <= 0:
        return min(values)
    if percentile >= 1:
        return max(values)
    values_sorted = sorted(values)
    k = (len(values_sorted) - 1) * percentile
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values_sorted[int(k)]
    lower = values_sorted[f]
    upper = values_sorted[c]
    return lower + (upper - lower) * (k - f)


@dataclass
class _PositionView:
    position: PositionState
    snapshot: SnapshotPerPair | None
    score: float | None
    rank: int | None


class PortfolioRebalanceController:
    def __init__(self, *, order_id_prefix: str = "RB") -> None:
        self._order_id_prefix = order_id_prefix
        self._order_counter = 0

    def rebalance(
        self,
        snapshots: list[SnapshotPerPair],
        portfolio: PortfolioState,
        config: RebalanceConfig,
    ) -> RebalanceResult:
        as_of_date = _resolve_as_of_date(portfolio, snapshots)
        reasons: dict[str, list[str]] = {}
        warnings: list[str] = []

        snapshot_map = {pair_key(s.stock_secid, s.future_secid): s for s in snapshots}
        positions_map = {
            pair_key(pos.pair.stock_secid, pos.pair.future_secid): pos for pos in portfolio.positions
        }

        soft_rebalance_day = self._is_soft_rebalance_day(as_of_date, config)
        hard_checks_run = self._should_run_hard_checks(soft_rebalance_day, config)

        hard_exit_pairs: dict[str, str] = {}
        if hard_checks_run:
            for pair_id, pos in positions_map.items():
                snapshot = snapshot_map.get(pair_id)
                reason = self._evaluate_hard_exit(pos, snapshot, as_of_date, config, warnings)
                if reason:
                    hard_exit_pairs[pair_id] = reason
                    reasons.setdefault(pair_id, []).append(reason)

        # Step 2: eligible candidates
        eligible_candidates: list[SnapshotPerPair] = []
        eligible_scores: dict[str, float] = {}
        for snapshot in snapshots:
            pair_id = pair_key(snapshot.stock_secid, snapshot.future_secid)
            if self._is_in_cooldown(pair_id, portfolio, config, as_of_date):
                continue
            if not self._passes_entry_gates(snapshot, config):
                continue
            eligible_candidates.append(snapshot)
            score = snapshot.scores.total_score
            if score is not None:
                eligible_scores[pair_id] = float(score)

        # Step 3: score thresholds
        all_scores = [float(s.scores.total_score) for s in snapshots if s.scores.total_score is not None]
        enter_threshold_value: float | None = None
        keep_threshold_value: float | None = None
        if config.score_threshold_mode.upper() == "PERCENTILE":
            enter_threshold_value = _percentile(all_scores, config.enter_threshold)
            keep_threshold_value = _percentile(all_scores, config.keep_threshold)
        else:
            enter_threshold_value = config.enter_total_score_min
            keep_threshold_value = config.keep_total_score_min

        # Step 4: soft-exit candidates
        position_views = self._build_position_views(positions_map, snapshot_map)
        soft_exit_pairs: set[str] = set()
        if soft_rebalance_day:
            for pair_id, view in position_views.items():
                if pair_id in hard_exit_pairs:
                    continue
                score_value = view.score
                if keep_threshold_value is not None and score_value is not None:
                    if score_value < keep_threshold_value:
                        soft_exit_pairs.add(pair_id)
                        reasons.setdefault(pair_id, []).append(SOFT_EXIT_SCORE)
                        continue
                if self._drop_rank_exit(pair_id, view, config):
                    soft_exit_pairs.add(pair_id)
                    reasons.setdefault(pair_id, []).append(SOFT_EXIT_DROP_RANK)

        # Step 5: target_set
        kept_pairs = {
            pair_id
            for pair_id in positions_map
            if pair_id not in hard_exit_pairs and pair_id not in soft_exit_pairs
        }
        target_pairs = set(kept_pairs)
        if soft_rebalance_day:
            candidates = self._filter_enter_candidates(
                eligible_candidates,
                enter_threshold_value,
            )
            max_pairs = max(config.max_pairs_held, 0)
            slots = max(max_pairs - len(target_pairs), 0)
            for snapshot in sorted(
                candidates,
                key=lambda s: eligible_scores.get(pair_key(s.stock_secid, s.future_secid), -1e9),
                reverse=True,
            ):
                if slots <= 0:
                    break
                pair_id = pair_key(snapshot.stock_secid, snapshot.future_secid)
                if pair_id in target_pairs:
                    continue
                target_pairs.add(pair_id)
                slots -= 1

        # Step 6: rotation
        if soft_rebalance_day:
            target_pairs = self._apply_rotation(
                target_pairs,
                kept_pairs,
                eligible_candidates,
                position_views,
                eligible_scores,
                config,
                reasons,
            )

        # Step 7 + 8 + 9: allocation and contracts
        target_contracts: dict[str, int] = {}
        target_positions: dict[str, TargetPosition] = {}
        current_contracts = self._current_contracts(positions_map)

        if soft_rebalance_day:
            target_contracts, target_positions = self._build_targets(
                target_pairs,
                positions_map,
                snapshot_map,
                config,
                portfolio,
                warnings,
            )
            target_contracts = self._apply_band_rebalance(
                target_contracts,
                current_contracts,
                config,
                reasons,
            )
            # refresh target_positions quantities after band rebalance
            target_positions = self._refresh_target_positions(
                target_positions,
                target_contracts,
                positions_map,
                snapshot_map,
                config,
            )
            for pair_id in positions_map:
                if pair_id not in target_contracts:
                    target_contracts[pair_id] = 0
            target_positions = self._refresh_target_positions(
                target_positions,
                target_contracts,
                positions_map,
                snapshot_map,
                config,
            )
        else:
            target_contracts = {pair_id: current_contracts.get(pair_id, 0) for pair_id in positions_map}
            for pair_id, pos in positions_map.items():
                target_positions[pair_id] = self._target_from_position(pair_id, pos, snapshot_map, weight=0.0)

        for pair_id in hard_exit_pairs:
            target_contracts[pair_id] = 0
        if hard_exit_pairs:
            target_positions = self._refresh_target_positions(
                target_positions,
                target_contracts,
                positions_map,
                snapshot_map,
                config,
            )

        # Step 10: turnover cap
        turnover_estimate = self._estimate_turnover(
            positions_map,
            target_positions,
            snapshot_map,
        )
        limit_notional = self._resolve_turnover_limit(portfolio, config)
        if limit_notional is not None:
            per_contract_notional = self._per_contract_notional(target_positions, snapshot_map, positions_map)
            turnover_result = apply_turnover_cap(
                current_contracts=current_contracts,
                target_contracts=target_contracts,
                per_contract_notional=per_contract_notional,
                limit_notional=limit_notional,
                preserve_pairs=set(hard_exit_pairs.keys()),
            )
            if turnover_result.warnings:
                warnings.extend(turnover_result.warnings)
            if turnover_result.scale_factor < 1.0:
                for pair_id, target in turnover_result.scaled_targets.items():
                    if target < target_contracts.get(pair_id, 0):
                        reasons.setdefault(pair_id, []).append(TURNOVER_SCALED)
            target_contracts = turnover_result.scaled_targets
            target_positions = self._refresh_target_positions(
                target_positions,
                target_contracts,
                positions_map,
                snapshot_map,
                config,
            )
            turnover_estimate = turnover_result.turnover_notional

        # Step 11: orders
        orders = self._build_orders(
            as_of_date,
            positions_map,
            target_positions,
            hard_exit_pairs,
        )

        sorted_targets = [target_positions[pair_id] for pair_id in sorted(target_positions.keys())]

        return RebalanceResult(
            date=as_of_date,
            orders=orders,
            target_positions=sorted_targets,
            reasons=reasons,
            turnover_estimate_notional=float(turnover_estimate),
            warnings=warnings,
        )

    def _is_soft_rebalance_day(self, as_of_date: date, config: RebalanceConfig) -> bool:
        freq = config.soft_rebalance_frequency.upper()
        if freq == "NONE":
            return False
        if freq == "DAILY":
            return True
        if freq == "WEEKLY":
            return as_of_date.weekday() == config.soft_rebalance_day_of_week
        return False

    def _should_run_hard_checks(self, soft_rebalance_day: bool, config: RebalanceConfig) -> bool:
        freq = config.hard_checks_frequency.upper()
        if freq == "DAILY":
            return True
        if freq in {"SOFT", "REBALANCE"}:
            return soft_rebalance_day
        return False

    def _evaluate_hard_exit(
        self,
        pos: PositionState,
        snapshot: SnapshotPerPair | None,
        as_of_date: date,
        config: RebalanceConfig,
        warnings: list[str],
    ) -> str | None:
        if config.kill_switch:
            return EXIT_KILL
        if snapshot is None:
            warnings.append(f"missing_snapshot:{pos.pair.stock_secid}:{pos.pair.future_secid}")
            return None

        if snapshot.dte is not None and snapshot.dte <= config.close_buffer_days:
            return EXIT_EXPIRY

        entry_spread = pos.entry_spread_exec_pct
        if entry_spread is None:
            entry_spread = pos.metadata.get("entry_spread_exec_pct") if pos.metadata else None
        exit_spread = snapshot.spread_exit_exec_pct
        if entry_spread is None or exit_spread is None:
            warnings.append(f"missing_spread_exec_pct:{snapshot.stock_secid}:{snapshot.future_secid}")
        delta = None
        if entry_spread is not None and exit_spread is not None:
            delta = float(exit_spread) - float(entry_spread)

        tp_net = float(config.TP_pct)
        if config.tp_net_mode.upper() == "INCLUDE_RTC" and snapshot.rtc_pct is not None:
            tp_net += float(snapshot.rtc_pct)
        sl_net = float(config.SL_pct)

        if delta is not None:
            if delta <= -sl_net:
                return EXIT_SL

        liq_pass = snapshot.lq.liquidity_pass if snapshot.lq is not None else None
        liq_streak = pos.liq_fail_streak if hasattr(pos, "liq_fail_streak") else 0
        if pos.metadata and "liq_fail_streak" in pos.metadata:
            liq_streak = int(pos.metadata.get("liq_fail_streak", liq_streak))
        if liq_pass is False:
            liq_streak += 1
        else:
            liq_streak = 0
        if config.liquidity_exit_streak > 0 and liq_streak >= config.liquidity_exit_streak:
            return EXIT_LIQ

        if config.exit_on_floor_fail and snapshot.floor_pass is False:
            return EXIT_FLOOR_FAIL

        if pos.entry_date is not None and config.h_max_days > 0:
            hold_days = (as_of_date - pos.entry_date).days
            if hold_days >= config.h_max_days:
                return EXIT_TIME

        if delta is not None and delta >= tp_net:
            return EXIT_TP

        if delta is not None and config.trailing_stop_pct is not None:
            peak = pos.trail_peak_spread_pct if hasattr(pos, "trail_peak_spread_pct") else None
            if pos.metadata and pos.metadata.get("trail_peak_spread_pct") is not None:
                peak = float(pos.metadata.get("trail_peak_spread_pct"))
            if peak is None:
                peak = delta
            trigger = peak - delta
            min_gain = config.trailing_start_pct if config.trailing_start_pct is not None else 0.0
            if peak >= min_gain and trigger >= config.trailing_stop_pct:
                return EXIT_TRAIL
        return None

    def _is_in_cooldown(
        self,
        pair_id: str,
        portfolio: PortfolioState,
        config: RebalanceConfig,
        as_of_date: date,
    ) -> bool:
        if config.cooldown_days <= 0:
            return False
        meta = portfolio.metadata or {}
        cooldowns = meta.get("cooldowns") or meta.get("cooldown") or {}
        last_exit = cooldowns.get(pair_id)
        if last_exit is None:
            return False
        if isinstance(last_exit, datetime):
            last_exit_date = last_exit.date()
        elif isinstance(last_exit, date):
            last_exit_date = last_exit
        elif isinstance(last_exit, int):
            return last_exit > 0
        else:
            return False
        return (as_of_date - last_exit_date).days < config.cooldown_days

    def _passes_entry_gates(self, snapshot: SnapshotPerPair, config: RebalanceConfig) -> bool:
        if snapshot.floor_pass is False:
            return False
        if snapshot.lq.liquidity_pass is False:
            return False
        if snapshot.dte is None or snapshot.dte < config.enter_min_DTE:
            return False
        if config.z_entry_threshold is not None:
            zscore = snapshot.alpha.zscore
            if zscore is None:
                return False
            if float(zscore) > float(config.z_entry_threshold):
                return False
        if config.min_floor_score is not None:
            score_floor = snapshot.scores.score_floor
            if score_floor is None or float(score_floor) < float(config.min_floor_score):
                return False
        if config.min_alpha_score is not None:
            score_alpha = snapshot.scores.score_alpha
            if score_alpha is None or float(score_alpha) < float(config.min_alpha_score):
                return False
        severity = snapshot.events.news_severity if snapshot.events is not None else None
        if severity and severity.lower() in {s.lower() for s in config.block_news_severities}:
            return False
        if snapshot.events.warnings:
            lowered = {warning.lower() for warning in snapshot.events.warnings}
            if "event_blocked" in lowered or "news_blocked" in lowered:
                return False
        return True

    def _build_position_views(
        self,
        positions_map: dict[str, PositionState],
        snapshot_map: dict[str, SnapshotPerPair],
    ) -> dict[str, _PositionView]:
        views: dict[str, _PositionView] = {}
        scores: dict[str, float] = {}
        for pair_id, snapshot in snapshot_map.items():
            if snapshot.scores.total_score is not None:
                scores[pair_id] = float(snapshot.scores.total_score)
        ranked_pairs = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ranks = {pair_id: idx + 1 for idx, (pair_id, _) in enumerate(ranked_pairs)}

        for pair_id, pos in positions_map.items():
            snapshot = snapshot_map.get(pair_id)
            score = scores.get(pair_id)
            rank = ranks.get(pair_id)
            views[pair_id] = _PositionView(position=pos, snapshot=snapshot, score=score, rank=rank)
        return views

    def _drop_rank_exit(self, pair_id: str, view: _PositionView, config: RebalanceConfig) -> bool:
        if config.drop_rank_threshold is None or view.rank is None:
            return False
        current_streak = view.position.drop_rank_streak if hasattr(view.position, "drop_rank_streak") else 0
        if view.position.metadata and "drop_rank_streak" in view.position.metadata:
            current_streak = int(view.position.metadata.get("drop_rank_streak", current_streak))
        if view.rank > config.drop_rank_threshold:
            current_streak += 1
        else:
            current_streak = 0
        return current_streak >= max(config.drop_rank_grace_days, 0)

    def _filter_enter_candidates(
        self,
        candidates: list[SnapshotPerPair],
        enter_threshold: float | None,
    ) -> list[SnapshotPerPair]:
        if enter_threshold is None:
            return candidates
        filtered: list[SnapshotPerPair] = []
        for snapshot in candidates:
            score = snapshot.scores.total_score
            if score is None:
                continue
            if float(score) >= enter_threshold:
                filtered.append(snapshot)
        return filtered

    def _apply_rotation(
        self,
        target_pairs: set[str],
        kept_pairs: set[str],
        eligible_candidates: list[SnapshotPerPair],
        position_views: dict[str, _PositionView],
        eligible_scores: dict[str, float],
        config: RebalanceConfig,
        reasons: dict[str, list[str]],
    ) -> set[str]:
        if config.replacement_threshold_score_gap_pct <= 0:
            return target_pairs
        old_list = [pair_id for pair_id in kept_pairs if pair_id in target_pairs]
        old_list.sort(key=lambda pid: (position_views.get(pid).score if position_views.get(pid) else -1e9))
        new_list = [
            pair_key(s.stock_secid, s.future_secid)
            for s in eligible_candidates
            if pair_key(s.stock_secid, s.future_secid) not in target_pairs
        ]
        new_list.sort(key=lambda pid: eligible_scores.get(pid, -1e9), reverse=True)

        updated = set(target_pairs)
        for new_id in new_list:
            if not old_list:
                break
            old_id = old_list[0]
            old_score = position_views.get(old_id).score if position_views.get(old_id) else None
            new_score = eligible_scores.get(new_id)
            if old_score is None or new_score is None:
                continue
            gap = (new_score - old_score) / max(abs(old_score), config.epsilon)
            if gap >= config.replacement_threshold_score_gap_pct:
                updated.discard(old_id)
                updated.add(new_id)
                old_list.pop(0)
                reasons.setdefault(old_id, []).append(ROTATION_REPLACE)
                reasons.setdefault(new_id, []).append(ROTATION_REPLACE)
        return updated

    def _build_targets(
        self,
        target_pairs: set[str],
        positions_map: dict[str, PositionState],
        snapshot_map: dict[str, SnapshotPerPair],
        config: RebalanceConfig,
        portfolio: PortfolioState,
        warnings: list[str],
    ) -> tuple[dict[str, int], dict[str, TargetPosition]]:
        targets: dict[str, int] = {}
        target_positions: dict[str, TargetPosition] = {}

        snapshots = [snapshot_map[pair_id] for pair_id in target_pairs if pair_id in snapshot_map]
        allocation_inputs = build_allocation_inputs(snapshots)
        weights = compute_allocation_weights(
            allocation_inputs.values(),
            config.allocation_method,
            max_weight=config.max_weight_per_pair,
            alpha_overlay_weight=config.alpha_overlay_weight,
            epsilon=config.epsilon,
        )

        equity = portfolio.equity if portfolio.equity is not None else portfolio.cash
        cap_book = float(equity or 0.0) * config.target_utilization

        for pair_id in sorted(target_pairs):
            snapshot = snapshot_map.get(pair_id)
            if snapshot is None:
                continue
            weight = weights.get(pair_id, 0.0)
            cap_i = cap_book * weight
            contracts = self._contracts_for_pair(snapshot, positions_map.get(pair_id), cap_i, config, warnings)
            targets[pair_id] = contracts
            target_positions[pair_id] = self._target_from_snapshot(
                pair_id, snapshot, positions_map.get(pair_id), contracts, weight, config
            )

        return targets, target_positions

    def _contracts_for_pair(
        self,
        snapshot: SnapshotPerPair,
        position: PositionState | None,
        cap_i: float,
        config: RebalanceConfig,
        warnings: list[str],
    ) -> int:
        spot_mid = snapshot.spot_mid
        if spot_mid is None:
            warnings.append(f"missing_spot_mid:{snapshot.stock_secid}:{snapshot.future_secid}")
            return 0
        multiplier = self._resolve_multiplier(snapshot, position)
        if multiplier <= 0:
            warnings.append(f"missing_multiplier:{snapshot.stock_secid}:{snapshot.future_secid}")
            return 0
        if config.capital_base_mode.upper() == "MARGIN_AWARE":
            buffer = config.var_margin_buffer_pct
            capital_per_contract = spot_mid * multiplier * (
                config.margin_stock_pct + config.margin_fut_pct + buffer
            )
        else:
            capital_per_contract = spot_mid * multiplier
        if capital_per_contract <= 0:
            return 0
        contracts = int(math.floor(cap_i / capital_per_contract))
        if contracts > 0 and config.min_contracts_per_pair > 0:
            contracts = max(contracts, config.min_contracts_per_pair)
        if config.max_contracts_per_pair is not None:
            contracts = min(contracts, config.max_contracts_per_pair)
        return max(contracts, 0)

    def _apply_band_rebalance(
        self,
        target_contracts: dict[str, int],
        current_contracts: dict[str, int],
        config: RebalanceConfig,
        reasons: dict[str, list[str]],
    ) -> dict[str, int]:
        adjusted = dict(target_contracts)
        for pair_id, target in target_contracts.items():
            current = current_contracts.get(pair_id, 0)
            if current == 0:
                continue
            diff = abs(current - target) / max(1, abs(current))
            if diff < config.rebalance_band:
                adjusted[pair_id] = current
                reasons.setdefault(pair_id, []).append(BAND_REBALANCE_SKIP)
        return adjusted

    def _current_contracts(self, positions_map: dict[str, PositionState]) -> dict[str, int]:
        contracts: dict[str, int] = {}
        for pair_id, pos in positions_map.items():
            contracts[pair_id] = int(round(abs(pos.quantity_fut)))
        return contracts

    def _resolve_turnover_limit(self, portfolio: PortfolioState, config: RebalanceConfig) -> float | None:
        if config.turnover_limit_notional is not None:
            return float(config.turnover_limit_notional)
        if config.turnover_limit_pct is None:
            return None
        equity = portfolio.equity if portfolio.equity is not None else portfolio.cash
        return float(equity or 0.0) * config.turnover_limit_pct

    def _estimate_turnover(
        self,
        positions_map: dict[str, PositionState],
        target_positions: dict[str, TargetPosition],
        snapshot_map: dict[str, SnapshotPerPair],
    ) -> float:
        total = 0.0
        for pair_id, target in target_positions.items():
            current = positions_map.get(pair_id)
            if current is None:
                current_stock = 0.0
                current_fut = 0.0
            else:
                current_stock = current.quantity_stock
                current_fut = current.quantity_fut
            snapshot = snapshot_map.get(pair_id)
            if snapshot is None:
                continue
            spot_mid = snapshot.spot_mid or 0.0
            fut_mid = snapshot.future_mid or 0.0
            multiplier = self._resolve_multiplier(snapshot, current)
            delta_stock = target.quantity_stock - current_stock
            delta_fut = target.quantity_fut - current_fut
            total += abs(delta_stock) * spot_mid
            total += abs(delta_fut) * fut_mid * multiplier
        return total

    def _per_contract_notional(
        self,
        target_positions: dict[str, TargetPosition],
        snapshot_map: dict[str, SnapshotPerPair],
        positions_map: dict[str, PositionState],
    ) -> dict[str, float]:
        result: dict[str, float] = {}
        for pair_id, target in target_positions.items():
            snapshot = snapshot_map.get(pair_id)
            if snapshot is None:
                continue
            spot_mid = snapshot.spot_mid or 0.0
            fut_mid = snapshot.future_mid or 0.0
            multiplier = self._resolve_multiplier(snapshot, positions_map.get(pair_id))
            per_contract = (spot_mid * multiplier) + (fut_mid * multiplier)
            result[pair_id] = per_contract
        return result

    def _resolve_multiplier(self, snapshot: SnapshotPerPair, position: PositionState | None) -> float:
        if position is not None and position.pair.multiplier is not None:
            return float(position.pair.multiplier)
        meta = snapshot.metadata or {}
        if meta.get("multiplier") is not None:
            return float(meta.get("multiplier"))
        return 1.0

    def _target_from_snapshot(
        self,
        pair_id: str,
        snapshot: SnapshotPerPair,
        position: PositionState | None,
        contracts: int,
        weight: float,
        config: RebalanceConfig,
    ) -> TargetPosition:
        pair_spec = position.pair if position is not None else PairSpec(
            stock_secid=snapshot.stock_secid,
            future_secid=snapshot.future_secid,
            expiry=snapshot.expiry,
            multiplier=self._resolve_multiplier(snapshot, position),
            metadata=snapshot.metadata or {},
        )
        direction = position.direction if position is not None else config.default_direction
        qty_stock, qty_fut = self._quantities_from_contracts(contracts, direction, pair_spec)
        score = snapshot.scores.total_score if snapshot.scores.total_score is not None else None
        return TargetPosition(
            pair=pair_spec,
            direction=direction,
            contracts=contracts,
            quantity_stock=qty_stock,
            quantity_fut=qty_fut,
            weight=weight,
            score=float(score) if score is not None else None,
        )

    def _target_from_position(
        self,
        pair_id: str,
        position: PositionState,
        snapshot_map: dict[str, SnapshotPerPair],
        weight: float,
    ) -> TargetPosition:
        snapshot = snapshot_map.get(pair_id)
        score = snapshot.scores.total_score if snapshot and snapshot.scores.total_score is not None else None
        return TargetPosition(
            pair=position.pair,
            direction=position.direction,
            contracts=int(round(abs(position.quantity_fut))),
            quantity_stock=position.quantity_stock,
            quantity_fut=position.quantity_fut,
            weight=weight,
            score=float(score) if score is not None else None,
        )

    def _refresh_target_positions(
        self,
        existing: dict[str, TargetPosition],
        target_contracts: dict[str, int],
        positions_map: dict[str, PositionState],
        snapshot_map: dict[str, SnapshotPerPair],
        config: RebalanceConfig,
    ) -> dict[str, TargetPosition]:
        refreshed: dict[str, TargetPosition] = {}
        for pair_id, contracts in target_contracts.items():
            snapshot = snapshot_map.get(pair_id)
            position = positions_map.get(pair_id)
            weight = existing.get(pair_id).weight if pair_id in existing else 0.0
            if snapshot is None:
                if position is None:
                    continue
                refreshed[pair_id] = TargetPosition(
                    pair=position.pair,
                    direction=position.direction,
                    contracts=contracts,
                    quantity_stock=0.0,
                    quantity_fut=0.0,
                    weight=weight,
                    score=None,
                )
            else:
                refreshed[pair_id] = self._target_from_snapshot(
                    pair_id,
                    snapshot,
                    position,
                    contracts,
                    weight,
                    config,
                )
        return refreshed

    def _quantities_from_contracts(
        self,
        contracts: int,
        direction: str,
        pair: PairSpec,
    ) -> tuple[float, float]:
        multiplier = float(pair.multiplier) if pair.multiplier else 1.0
        qty_stock = contracts * multiplier
        qty_fut = contracts
        if direction.lower() == "reverse":
            qty_stock = -qty_stock
            qty_fut = -qty_fut
        else:
            qty_fut = -qty_fut
        return qty_stock, qty_fut

    def _build_orders(
        self,
        as_of_date: date,
        positions_map: dict[str, PositionState],
        target_positions: dict[str, TargetPosition],
        hard_exit_pairs: dict[str, str],
    ) -> list[Order]:
        exit_orders: list[Order] = []
        size_down_orders: list[Order] = []
        size_up_orders: list[Order] = []
        enter_orders: list[Order] = []

        for pair_id, target in target_positions.items():
            current = positions_map.get(pair_id)
            current_stock = current.quantity_stock if current else 0.0
            current_fut = current.quantity_fut if current else 0.0
            delta_stock = target.quantity_stock - current_stock
            delta_fut = target.quantity_fut - current_fut
            if delta_stock == 0 and delta_fut == 0:
                continue

            current_contracts = int(round(abs(current.quantity_fut))) if current else 0
            target_contracts = target.contracts
            if current_contracts > 0 and target_contracts == 0:
                category = "exit"
            elif current_contracts > target_contracts:
                category = "size_down"
            elif current_contracts == 0 and target_contracts > 0:
                category = "enter"
            else:
                category = "size_up"

            orders = self._orders_for_delta(pair_id, target.pair, delta_stock, delta_fut)
            if category == "exit":
                exit_orders.extend(orders)
            elif category == "size_down":
                size_down_orders.extend(orders)
            elif category == "size_up":
                size_up_orders.extend(orders)
            else:
                enter_orders.extend(orders)

        ordered = (
            self._sort_orders(exit_orders)
            + self._sort_orders(size_down_orders)
            + self._sort_orders(size_up_orders)
            + self._sort_orders(enter_orders)
        )

        # ensure deterministic order ids
        for order in ordered:
            if not order.order_id:
                order.order_id = self._next_order_id(as_of_date, order.instrument)
        return ordered

    def _orders_for_delta(
        self,
        pair_id: str,
        pair: PairSpec,
        delta_stock: float,
        delta_fut: float,
    ) -> list[Order]:
        orders: list[Order] = []
        if delta_stock != 0:
            side = "buy" if delta_stock > 0 else "sell"
            orders.append(
                Order(
                    order_id="",
                    instrument=pair.stock_secid,
                    side=side,
                    order_type="market",
                    quantity=abs(delta_stock),
                    metadata={"pair_id": pair_id},
                )
            )
        if delta_fut != 0:
            side = "buy" if delta_fut > 0 else "sell"
            orders.append(
                Order(
                    order_id="",
                    instrument=pair.future_secid,
                    side=side,
                    order_type="market",
                    quantity=abs(delta_fut),
                    metadata={"pair_id": pair_id},
                )
            )
        return orders

    def _sort_orders(self, orders: list[Order]) -> list[Order]:
        return sorted(orders, key=lambda order: (order.instrument, order.side, order.quantity))

    def _next_order_id(self, as_of_date: date, instrument: str) -> str:
        self._order_counter += 1
        return f"{self._order_id_prefix}-{as_of_date.strftime('%Y%m%d')}-{instrument}-{self._order_counter:04d}"
