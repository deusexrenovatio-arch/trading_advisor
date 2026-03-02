from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from moex_carry.signal_engine.core.math_utils import normalize_three_way_probabilities
from moex_carry.signal_engine.core.types import OutcomeForecast, OutcomeLabel

BinOutcome = Literal["TP", "SL", "EXIT"]


@dataclass(frozen=True)
class BinningCalibrationConfig:
    bins: int = 15
    min_bin_count: int = 30
    smoothing_alpha: float = 1.0
    source_suffix: str = "_bin15_ovr_renorm"


@dataclass(frozen=True)
class _OutcomeCalibration:
    default_freq: float
    bin_freqs: tuple[float, ...]


@dataclass(frozen=True)
class BinningCalibrationModel:
    bins: int
    tp: _OutcomeCalibration
    sl: _OutcomeCalibration
    exit: _OutcomeCalibration
    source_suffix: str


def _clip_probability(p: float) -> float:
    return float(min(max(float(p), 0.0), 1.0))


def _bin_index(p: float, bins: int) -> int:
    bins_value = max(int(bins), 1)
    idx = int(_clip_probability(p) * bins_value)
    if idx >= bins_value:
        idx = bins_value - 1
    return idx


def _fit_outcome_calibration(
    *,
    probs: list[float],
    labels: Sequence[OutcomeLabel],
    positive_label: BinOutcome,
    config: BinningCalibrationConfig,
) -> _OutcomeCalibration:
    bins = max(int(config.bins), 1)
    alpha = max(float(config.smoothing_alpha), 0.0)
    counts = [0 for _ in range(bins)]
    positives = [0.0 for _ in range(bins)]

    global_positive = 0.0
    for prob, label in zip(probs, labels):
        idx = _bin_index(prob, bins)
        counts[idx] += 1
        y = 1.0 if label == positive_label else 0.0
        positives[idx] += y
        global_positive += y

    total = len(labels)
    default_freq = (global_positive + alpha) / (max(total, 0) + 2.0 * alpha) if total > 0 else 0.5
    bin_freqs: list[float] = []
    for count, positive in zip(counts, positives):
        if count < int(config.min_bin_count):
            bin_freqs.append(float(default_freq))
            continue
        freq = (positive + alpha) / (float(count) + 2.0 * alpha)
        bin_freqs.append(float(freq))
    return _OutcomeCalibration(default_freq=float(default_freq), bin_freqs=tuple(bin_freqs))


def fit_binning_ovr_renorm(
    *,
    predictions: Sequence[OutcomeForecast],
    outcomes: Sequence[OutcomeLabel],
    config: BinningCalibrationConfig = BinningCalibrationConfig(),
) -> BinningCalibrationModel | None:
    if not predictions or not outcomes:
        return None
    size = min(len(predictions), len(outcomes))
    if size <= 0:
        return None
    preds = [prediction.normalized() for prediction in predictions[:size]]
    labels = list(outcomes[:size])
    tp = _fit_outcome_calibration(
        probs=[prediction.p_tp for prediction in preds],
        labels=labels,
        positive_label="TP",
        config=config,
    )
    sl = _fit_outcome_calibration(
        probs=[prediction.p_sl for prediction in preds],
        labels=labels,
        positive_label="SL",
        config=config,
    )
    exit_model = _fit_outcome_calibration(
        probs=[prediction.p_exit for prediction in preds],
        labels=labels,
        positive_label="EXIT",
        config=config,
    )
    return BinningCalibrationModel(
        bins=max(int(config.bins), 1),
        tp=tp,
        sl=sl,
        exit=exit_model,
        source_suffix=str(config.source_suffix),
    )


def calibrate_forecast(
    *,
    forecast: OutcomeForecast,
    model: BinningCalibrationModel | None,
) -> OutcomeForecast:
    if model is None:
        return forecast.normalized()
    normalized = forecast.normalized()
    idx_tp = _bin_index(normalized.p_tp, model.bins)
    idx_sl = _bin_index(normalized.p_sl, model.bins)
    idx_exit = _bin_index(normalized.p_exit, model.bins)

    p_tp_raw = model.tp.bin_freqs[idx_tp]
    p_sl_raw = model.sl.bin_freqs[idx_sl]
    p_exit_raw = model.exit.bin_freqs[idx_exit]
    p_tp, p_sl, p_exit = normalize_three_way_probabilities(p_tp_raw, p_sl_raw, p_exit_raw)

    return OutcomeForecast(
        p_tp=p_tp,
        p_sl=p_sl,
        p_exit=p_exit,
        n_effective=normalized.n_effective,
        confidence_tier=normalized.confidence_tier,
        probability_source=f"{normalized.probability_source}{model.source_suffix}",
    )
