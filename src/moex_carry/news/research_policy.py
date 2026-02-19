from __future__ import annotations

import math
import random
from datetime import datetime
from statistics import mean, stdev
from moex_carry.news.research_metrics import (
    _classification_metrics,
    _horizon_to_delta,
    _normalize_prob_triplet,
    _safe_div,
    _slice_metrics,
)


def _build_gate_check(*, check_id: str, value: float, threshold: float, operator: str, passed: bool) -> dict[str, object]:
    return {
        "check_id": check_id,
        "value": float(value),
        "threshold": float(threshold),
        "operator": operator,
        "passed": bool(passed),
    }

def _two_stage_thresholds_for_horizon(horizon: str) -> tuple[float, float, float]:
    key = str(horizon or "1d").strip().lower()
    mapping = {
        "5m": (0.65, 0.55, 0.45),
        "1h": (0.60, 0.55, 0.45),
        "4h": (0.55, 0.55, 0.45),
        "1d": (0.50, 0.55, 0.45),
        "5d": (0.50, 0.55, 0.45),
    }
    return mapping.get(key, (0.55, 0.55, 0.45))


def _apply_two_stage_policy(
    samples: list[dict[str, object]],
    *,
    horizon: str,
) -> list[dict[str, object]]:
    move_threshold, up_threshold, down_threshold = _two_stage_thresholds_for_horizon(horizon)
    rows: list[dict[str, object]] = []
    for sample in samples:
        prob_up = float(sample.get("prob_up") or 0.0)
        prob_down = float(sample.get("prob_down") or 0.0)
        prob_neutral = float(sample.get("prob_neutral") or 0.0)
        prob_up, prob_down, prob_neutral = _normalize_prob_triplet(prob_up, prob_down, prob_neutral)
        p_move = max(0.0, min(1.0, 1.0 - prob_neutral))
        directional_total = prob_up + prob_down
        p_up_given_move = (prob_up / directional_total) if directional_total > 1e-9 else 0.5

        pred_label = "neutral"
        if p_move >= move_threshold:
            if p_up_given_move >= up_threshold:
                pred_label = "up"
            elif p_up_given_move <= down_threshold:
                pred_label = "down"

        row = dict(sample)
        row["prob_up"] = prob_up
        row["prob_down"] = prob_down
        row["prob_neutral"] = prob_neutral
        row["pred_label"] = pred_label
        row["pred_confidence"] = (
            p_move * max(p_up_given_move, 1.0 - p_up_given_move)
            if pred_label in {"up", "down"}
            else 1.0 - p_move
        )
        row["p_move"] = p_move
        row["p_up_given_move"] = p_up_given_move
        row["two_stage_applied"] = True
        rows.append(row)
    return rows


def _periods_per_year_for_horizon(horizon: str) -> float:
    key = str(horizon or "1d").strip().lower()
    if key == "5m":
        return float(252 * 24 * 12)
    if key == "1h":
        return float(252 * 24)
    if key == "4h":
        return float(252 * 6)
    if key in {"1d", "5d"}:
        return float(252)
    return float(252)


def _bootstrap_block_key(ts: datetime, horizon: str) -> str:
    key = str(horizon or "1d").strip().lower()
    if key in {"5m", "1h"}:
        return ts.date().isoformat()
    iso = ts.isocalendar()
    return f"{iso.year}-W{int(iso.week):02d}"


def _compute_utility_metrics(
    samples: list[dict[str, object]],
    *,
    horizon: str,
    cost_per_trade: float = 0.00075,
    bootstrap_iters: int = 2000,
) -> dict[str, object]:
    ordered = sorted(
        (item for item in samples if isinstance(item.get("published_at"), datetime)),
        key=lambda item: item["published_at"],
    )
    trades: list[dict[str, object]] = []
    for item in ordered:
        pred = str(item.get("pred_label") or "").strip().lower()
        if pred not in {"up", "down"}:
            continue
        signed_return = float(item.get("signed_return") or 0.0)
        gross = signed_return if pred == "up" else -signed_return
        net = gross - float(cost_per_trade)
        trades.append(
            {
                "published_at": item["published_at"],
                "gross": gross,
                "net": net,
            }
        )
    n_trades = len(trades)
    if n_trades == 0:
        return {
            "n_trades": 0,
            "mean_net_return_per_trade": 0.0,
            "hit_rate": 0.0,
            "sharpe_annualized": 0.0,
            "max_drawdown": 0.0,
            "bootstrap_ci_95": [0.0, 0.0],
            "bootstrap_iters": int(max(bootstrap_iters, 0)),
            "cost_per_trade": float(cost_per_trade),
        }

    net_returns = [float(item["net"]) for item in trades]
    mean_net = mean(net_returns)
    std_net = stdev(net_returns) if len(net_returns) >= 2 else 0.0
    sharpe = 0.0
    if std_net > 1e-12:
        sharpe = (mean_net / std_net) * math.sqrt(_periods_per_year_for_horizon(horizon))
    hit_rate = _safe_div(sum(1 for item in net_returns if item > 0.0), n_trades)

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for value in net_returns:
        equity *= (1.0 + value)
        if equity > peak:
            peak = equity
        drawdown = (peak - equity) / peak if peak > 0.0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown

    blocks: dict[str, list[float]] = {}
    for trade in trades:
        block_key = _bootstrap_block_key(trade["published_at"], horizon)
        blocks.setdefault(block_key, []).append(float(trade["net"]))
    block_keys = sorted(blocks.keys())

    ci_low = mean_net
    ci_high = mean_net
    normalized_iters = max(int(bootstrap_iters), 0)
    if len(block_keys) >= 2 and normalized_iters > 0:
        rng = random.Random(42)
        samples_mean: list[float] = []
        for _ in range(normalized_iters):
            picked = [rng.choice(block_keys) for __ in range(len(block_keys))]
            values: list[float] = []
            for key in picked:
                values.extend(blocks.get(key, []))
            if values:
                samples_mean.append(mean(values))
        if samples_mean:
            ordered_mean = sorted(samples_mean)
            lo_idx = max(int(0.025 * (len(ordered_mean) - 1)), 0)
            hi_idx = min(int(0.975 * (len(ordered_mean) - 1)), len(ordered_mean) - 1)
            ci_low = float(ordered_mean[lo_idx])
            ci_high = float(ordered_mean[hi_idx])

    return {
        "n_trades": n_trades,
        "mean_net_return_per_trade": float(mean_net),
        "hit_rate": float(hit_rate),
        "sharpe_annualized": float(sharpe),
        "max_drawdown": float(max_dd),
        "bootstrap_ci_95": [float(ci_low), float(ci_high)],
        "bootstrap_iters": normalized_iters,
        "cost_per_trade": float(cost_per_trade),
    }


def _build_report_from_samples(
    *,
    model_id: str,
    horizon: str,
    period_from: datetime,
    period_to: datetime,
    epsilon: float,
    samples: list[dict[str, object]],
    utility_cost_per_trade: float = 0.00075,
    utility_bootstrap_iters: int = 2000,
) -> dict[str, object]:
    metrics = _classification_metrics(samples)
    utility = _compute_utility_metrics(
        samples,
        horizon=horizon,
        cost_per_trade=utility_cost_per_trade,
        bootstrap_iters=utility_bootstrap_iters,
    )
    return {
        "model_id": model_id,
        "horizon": horizon,
        "period": {
            "from": period_from.isoformat() + "Z",
            "to": period_to.isoformat() + "Z",
        },
        "protocol": {
            "mode": "single_pass",
            "folds": 1,
            "embargo_minutes": 0,
            "horizon_minutes": int(_horizon_to_delta(horizon).total_seconds() // 60),
            "calibration_mode": "none",
            "calibration_min_train_samples": 0,
        },
        "fold_reports": [],
        "total_samples": len(samples),
        "dropped_by_embargo": 0,
        "sample_count": len(samples),
        "epsilon": epsilon,
        "metrics": metrics,
        "utility": utility,
        "slices": {
            "ticker": _slice_metrics(samples, "ticker"),
            "source": _slice_metrics(samples, "source"),
            "event_family": _slice_metrics(samples, "event_family"),
        },
    }


def _evaluate_baseline_superiority_gate(
    winner: dict[str, object] | None,
    baseline_reports: list[dict[str, object]],
    *,
    min_accuracy_delta: float = 0.0,
    max_brier_delta: float = 0.0,
    required_baselines: tuple[str, ...] = ("baseline_majority_class", "baseline_calendar_only"),
) -> dict[str, object]:
    if not isinstance(winner, dict):
        return {
            "pass": False,
            "checks": [
                {
                    "check_id": "winner_present_for_baseline_gate",
                    "operator": "exists",
                    "value": 0,
                    "threshold": 1,
                    "passed": False,
                    "reason": "missing_winner",
                }
            ],
        }

    winner_metrics = winner.get("metrics") if isinstance(winner.get("metrics"), dict) else {}
    winner_accuracy = float(winner_metrics.get("accuracy") or 0.0)
    winner_brier = float(winner_metrics.get("brier") or 1.0)

    baseline_map = {
        str(item.get("model_id") or "").strip(): item
        for item in baseline_reports
        if isinstance(item, dict)
    }
    checks: list[dict[str, object]] = []
    for baseline_id in required_baselines:
        baseline = baseline_map.get(baseline_id)
        if not isinstance(baseline, dict):
            checks.append(
                {
                    "check_id": f"{baseline_id}_present",
                    "operator": "exists",
                    "value": 0,
                    "threshold": 1,
                    "passed": False,
                    "reason": "baseline_missing",
                }
            )
            continue

        baseline_metrics = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else {}
        baseline_accuracy = float(baseline_metrics.get("accuracy") or 0.0)
        baseline_brier = float(baseline_metrics.get("brier") or 1.0)
        checks.append(
            _build_gate_check(
                check_id=f"{baseline_id}_accuracy_superiority",
                value=winner_accuracy,
                threshold=baseline_accuracy + float(min_accuracy_delta),
                operator=">",
                passed=winner_accuracy > (baseline_accuracy + float(min_accuracy_delta)),
            )
        )
        checks.append(
            _build_gate_check(
                check_id=f"{baseline_id}_brier_not_worse",
                value=winner_brier,
                threshold=baseline_brier + float(max_brier_delta),
                operator="<=",
                passed=winner_brier <= (baseline_brier + float(max_brier_delta)),
            )
        )

    return {
        "pass": all(bool(item.get("passed")) for item in checks),
        "checks": checks,
        "summary": {
            "winner_accuracy": winner_accuracy,
            "winner_brier": winner_brier,
            "required_baselines": list(required_baselines),
            "min_accuracy_delta": float(min_accuracy_delta),
            "max_brier_delta": float(max_brier_delta),
        },
    }


def _label_from_v2_int(value: int) -> str:
    if int(value) > 0:
        return "up"
    if int(value) < 0:
        return "down"
    return "neutral"

__all__ = [
    "_two_stage_thresholds_for_horizon",
    "_apply_two_stage_policy",
    "_periods_per_year_for_horizon",
    "_bootstrap_block_key",
    "_compute_utility_metrics",
    "_build_report_from_samples",
    "_evaluate_baseline_superiority_gate",
    "_label_from_v2_int",
]
