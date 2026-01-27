from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping

import numpy as np

from moex_carry.analytics.alpha import alpha_matrices_fast
from moex_carry.backtest_v2.engine import BacktestPrecomputed, SPREAD_HISTORY_DAYS_DEFAULT
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.domain.models import KeyRate
from moex_carry.domain.portfolio import PairSpec, SnapshotPerPair
from moex_carry.portfolio.rebalance_controller import pair_key


@dataclass
class FeatureMatrices:
    days: list[date]
    pair_ids: list[str]
    r_cb: np.ndarray
    floor_rate: np.ndarray
    floor_pass: np.ndarray
    rtc_pct: np.ndarray
    spread_bps_stock: np.ndarray
    spread_bps_fut: np.ndarray
    liquidity_pass: np.ndarray
    event_blocked: np.ndarray
    dte: np.ndarray
    spread_pct: np.ndarray


@dataclass
class AlphaMatrices:
    p_hit_tp: np.ndarray
    p_hit_sl: np.ndarray
    sigma_h: np.ndarray
    half_life: np.ndarray


@dataclass(frozen=True)
class ScoreParams:
    w_floor: float = 0.5
    w_alpha: float = 0.5
    w_liq: float = 1.0
    w_event: float = 1.0
    k_event: float = 0.0
    tp_pct: float = 0.0
    sl_pct: float = 0.0
    max_spread_bps_stock: float | None = None
    max_spread_bps_fut: float | None = None


def build_feature_matrices(precomputed: BacktestPrecomputed, universe: list[PairSpec]) -> FeatureMatrices:
    days = list(precomputed.trading_days)
    pair_ids = [pair_key(p.stock_secid, p.future_secid) for p in universe]
    pair_index = {pair_id: idx for idx, pair_id in enumerate(pair_ids)}
    d_count = len(days)
    p_count = len(pair_ids)

    floor_rate = np.full((d_count, p_count), np.nan, dtype=float)
    floor_pass = np.ones((d_count, p_count), dtype=bool)
    rtc_pct = np.full((d_count, p_count), np.nan, dtype=float)
    spread_bps_stock = np.full((d_count, p_count), np.nan, dtype=float)
    spread_bps_fut = np.full((d_count, p_count), np.nan, dtype=float)
    liquidity_pass = np.ones((d_count, p_count), dtype=bool)
    event_blocked = np.zeros((d_count, p_count), dtype=bool)
    dte = np.full((d_count, p_count), np.nan, dtype=float)
    spread_pct = np.full((d_count, p_count), np.nan, dtype=float)

    for day_idx, day in enumerate(days):
        snapshots = precomputed.snapshots_by_day.get(day, [])
        _fill_day_features(
            snapshots=snapshots,
            pair_index=pair_index,
            day_idx=day_idx,
            floor_rate=floor_rate,
            floor_pass=floor_pass,
            rtc_pct=rtc_pct,
            spread_bps_stock=spread_bps_stock,
            spread_bps_fut=spread_bps_fut,
            liquidity_pass=liquidity_pass,
            event_blocked=event_blocked,
            dte=dte,
            spread_pct=spread_pct,
        )

    r_cb = _resolve_r_cb_vector(days, precomputed.resolved_config, precomputed.key_rates)

    return FeatureMatrices(
        days=days,
        pair_ids=pair_ids,
        r_cb=r_cb,
        floor_rate=floor_rate,
        floor_pass=floor_pass,
        rtc_pct=rtc_pct,
        spread_bps_stock=spread_bps_stock,
        spread_bps_fut=spread_bps_fut,
        liquidity_pass=liquidity_pass,
        event_blocked=event_blocked,
        dte=dte,
        spread_pct=spread_pct,
    )


def build_alpha_matrices(
    features: FeatureMatrices,
    *,
    horizon: int,
    tp_pct: float,
    sl_pct: float,
    history_days: int | None = None,
) -> AlphaMatrices:
    window = history_days or SPREAD_HISTORY_DAYS_DEFAULT
    p_hit_tp, p_hit_sl, sigma_h, half_life = alpha_matrices_fast(
        features.spread_pct,
        horizon=horizon,
        tp=tp_pct,
        sl=sl_pct,
        history_days=window,
    )
    return AlphaMatrices(
        p_hit_tp=p_hit_tp,
        p_hit_sl=p_hit_sl,
        sigma_h=sigma_h,
        half_life=half_life,
    )


def batch_score(
    features: FeatureMatrices,
    params_list: Iterable[ScoreParams | Mapping[str, Any]],
    *,
    alpha: AlphaMatrices | None = None,
) -> list[np.ndarray]:
    score_floor = np.nan_to_num(features.floor_rate, nan=0.0) - features.r_cb[:, None]
    rtc_pct = np.nan_to_num(features.rtc_pct, nan=0.0)

    if alpha is None:
        p_hit_tp = np.zeros_like(score_floor)
        p_hit_sl = np.zeros_like(score_floor)
    else:
        p_hit_tp = alpha.p_hit_tp
        p_hit_sl = alpha.p_hit_sl

    results: list[np.ndarray] = []
    for raw_params in params_list:
        params = _coerce_params(raw_params)
        penalty_liq = _compute_liq_penalty(
            features,
            max_spread_bps_stock=params.max_spread_bps_stock,
            max_spread_bps_fut=params.max_spread_bps_fut,
        )
        penalty_event = np.where(features.event_blocked, float(params.k_event), 0.0)
        tp_net = float(params.tp_pct) + rtc_pct
        score_alpha = p_hit_tp * tp_net - p_hit_sl * float(params.sl_pct) - rtc_pct
        total_score = (
            float(params.w_floor) * score_floor
            + float(params.w_alpha) * score_alpha
            - float(params.w_liq) * penalty_liq
            - float(params.w_event) * penalty_event
        )
        results.append(total_score)
    return results


def batch_score_day(
    features: FeatureMatrices,
    day_index: int,
    params_list: Iterable[ScoreParams | Mapping[str, Any]],
    *,
    alpha: AlphaMatrices | None = None,
) -> list[np.ndarray]:
    score_floor = np.nan_to_num(features.floor_rate[day_index], nan=0.0) - features.r_cb[day_index]
    rtc_pct = np.nan_to_num(features.rtc_pct[day_index], nan=0.0)
    if alpha is None:
        p_hit_tp = np.zeros_like(score_floor)
        p_hit_sl = np.zeros_like(score_floor)
    else:
        p_hit_tp = alpha.p_hit_tp[day_index]
        p_hit_sl = alpha.p_hit_sl[day_index]

    results: list[np.ndarray] = []
    for raw_params in params_list:
        params = _coerce_params(raw_params)
        penalty_liq = _compute_liq_penalty_day(
            features,
            day_index=day_index,
            max_spread_bps_stock=params.max_spread_bps_stock,
            max_spread_bps_fut=params.max_spread_bps_fut,
        )
        penalty_event = np.where(features.event_blocked[day_index], float(params.k_event), 0.0)
        tp_net = float(params.tp_pct) + rtc_pct
        score_alpha = p_hit_tp * tp_net - p_hit_sl * float(params.sl_pct) - rtc_pct
        total_score = (
            float(params.w_floor) * score_floor
            + float(params.w_alpha) * score_alpha
            - float(params.w_liq) * penalty_liq
            - float(params.w_event) * penalty_event
        )
        results.append(total_score)
    return results


def _fill_day_features(
    *,
    snapshots: Iterable[SnapshotPerPair],
    pair_index: Mapping[str, int],
    day_idx: int,
    floor_rate: np.ndarray,
    floor_pass: np.ndarray,
    rtc_pct: np.ndarray,
    spread_bps_stock: np.ndarray,
    spread_bps_fut: np.ndarray,
    liquidity_pass: np.ndarray,
    event_blocked: np.ndarray,
    dte: np.ndarray,
    spread_pct: np.ndarray,
) -> None:
    for snapshot in snapshots:
        pair_id = pair_key(snapshot.stock_secid, snapshot.future_secid)
        idx = pair_index.get(pair_id)
        if idx is None:
            continue
        floor_rate[day_idx, idx] = snapshot.floor_rate_annual if snapshot.floor_rate_annual is not None else np.nan
        floor_pass[day_idx, idx] = snapshot.floor_pass is not False
        rtc_pct[day_idx, idx] = snapshot.rtc_pct if snapshot.rtc_pct is not None else np.nan
        spread_bps_stock[day_idx, idx] = (
            snapshot.lq.spread_bps_stock if snapshot.lq and snapshot.lq.spread_bps_stock is not None else np.nan
        )
        spread_bps_fut[day_idx, idx] = (
            snapshot.lq.spread_bps_fut if snapshot.lq and snapshot.lq.spread_bps_fut is not None else np.nan
        )
        liquidity_pass[day_idx, idx] = snapshot.lq.liquidity_pass is not False if snapshot.lq else True
        dte[day_idx, idx] = float(snapshot.dte) if snapshot.dte is not None else np.nan
        spread_pct[day_idx, idx] = snapshot.spread_pct if snapshot.spread_pct is not None else np.nan
        if snapshot.events and snapshot.events.warnings:
            lowered = {warning.lower() for warning in snapshot.events.warnings}
            if "event_blocked" in lowered or "news_blocked" in lowered:
                event_blocked[day_idx, idx] = True


def _resolve_r_cb_vector(
    days: list[date],
    resolved_config: Mapping[str, Any],
    key_rates: list[KeyRate],
) -> np.ndarray:
    rates_cfg = resolved_config.get("rates", {}) if isinstance(resolved_config, Mapping) else {}
    r_cb = rates_cfg.get("r_cb_annual")
    if r_cb is not None:
        return np.full(len(days), float(r_cb), dtype=float)
    r_cb_vector = np.zeros(len(days), dtype=float)
    for idx, day in enumerate(days):
        key_rate_row = latest_rate(key_rates, day)
        r_cb_vector[idx] = float(key_rate_row.rate) if key_rate_row else 0.0
    return r_cb_vector


def _compute_liq_penalty(
    features: FeatureMatrices,
    *,
    max_spread_bps_stock: float | None,
    max_spread_bps_fut: float | None,
) -> np.ndarray:
    if max_spread_bps_stock is None and max_spread_bps_fut is None:
        return np.where(features.liquidity_pass, 0.0, 1.0)
    penalty = np.zeros_like(features.spread_bps_stock, dtype=float)
    if max_spread_bps_stock is not None:
        penalty += np.maximum(0.0, np.nan_to_num(features.spread_bps_stock, nan=0.0) - float(max_spread_bps_stock))
    if max_spread_bps_fut is not None:
        penalty += np.maximum(0.0, np.nan_to_num(features.spread_bps_fut, nan=0.0) - float(max_spread_bps_fut))
    return penalty


def _compute_liq_penalty_day(
    features: FeatureMatrices,
    *,
    day_index: int,
    max_spread_bps_stock: float | None,
    max_spread_bps_fut: float | None,
) -> np.ndarray:
    if max_spread_bps_stock is None and max_spread_bps_fut is None:
        return np.where(features.liquidity_pass[day_index], 0.0, 1.0)
    penalty = np.zeros_like(features.spread_bps_stock[day_index], dtype=float)
    if max_spread_bps_stock is not None:
        penalty += np.maximum(
            0.0,
            np.nan_to_num(features.spread_bps_stock[day_index], nan=0.0) - float(max_spread_bps_stock),
        )
    if max_spread_bps_fut is not None:
        penalty += np.maximum(
            0.0,
            np.nan_to_num(features.spread_bps_fut[day_index], nan=0.0) - float(max_spread_bps_fut),
        )
    return penalty


def _coerce_params(value: ScoreParams | Mapping[str, Any]) -> ScoreParams:
    if isinstance(value, ScoreParams):
        return value
    if isinstance(value, Mapping):
        kwargs = {
            field: value.get(field)
            for field in ScoreParams.__dataclass_fields__
            if field in value and value.get(field) is not None
        }
        return ScoreParams(**kwargs)
    raise TypeError("Unsupported params type for batch_score")
