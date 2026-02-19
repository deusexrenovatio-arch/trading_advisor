from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from moex_carry.news.research_metrics import (
    _apply_baseline_calendar_only,
    _apply_baseline_calendar_plus_text,
    _apply_baseline_majority_class,
    _apply_baseline_no_news,
    _build_ablation_reports,
    _build_calendar_direction_by_news,
    _classification_metrics,
    _horizon_to_delta,
    _normalize_calibration_mode,
    _normalize_target_mode,
    _slice_metrics,
)
from moex_carry.news.research_policy import (
    _apply_two_stage_policy,
    _build_report_from_samples,
    _compute_utility_metrics,
    _evaluate_baseline_superiority_gate,
)
from moex_carry.news.research_samples import _build_backtest_samples
from moex_carry.news.research_supervised import (
    _build_supervised_gold_metrics,
    _evaluate_supervised_gate,
    _store_gate_run_v2,
    _store_model_eval_record,
)
from moex_carry.news.research_walkforward import (
    _evaluate_promotion_gate,
    _evaluate_utility_gate,
    _ticker_stability_score,
    _evaluate_walk_forward,
)

def run_news_backtest(
    session: Session,
    *,
    model_id: str,
    horizon: str,
    period_from: datetime,
    period_to: datetime,
    epsilon: float,
    folds: int = 5,
    embargo_minutes: int = 0,
    walk_forward: bool = True,
    calibration_mode: str = "none",
    calibration_min_train_samples: int = 30,
    evaluation_level: str = "event",
    strict_anchor_window_minutes: int = 120,
    target_mode: str = "legacy",
    two_stage_for_v2: bool = True,
    utility_cost_per_trade: float = 0.00075,
    utility_bootstrap_iters: int = 2000,
) -> dict[str, object]:
    delta = _horizon_to_delta(horizon)
    normalized_folds = max(int(folds), 1)
    normalized_embargo = max(int(embargo_minutes), 0)
    normalized_calibration_mode = _normalize_calibration_mode(calibration_mode)
    normalized_calibration_min_train = max(int(calibration_min_train_samples), 1)
    normalized_target_mode = _normalize_target_mode(target_mode)

    samples = _build_backtest_samples(
        session,
        model_id=model_id,
        period_from=period_from,
        period_to=period_to,
        delta=delta,
        epsilon=epsilon,
        strict_anchor_window_minutes=strict_anchor_window_minutes,
        evaluation_level=evaluation_level,
        target_mode=target_mode,
        horizon=horizon,
    )

    if not samples:
        return {
            "model_id": model_id,
            "horizon": horizon,
            "period": {
                "from": period_from.isoformat() + "Z",
                "to": period_to.isoformat() + "Z",
            },
            "protocol": {
                "mode": "walk_forward" if walk_forward else "single_pass",
                "folds": normalized_folds,
                "embargo_minutes": normalized_embargo,
                "horizon_minutes": int(delta.total_seconds() // 60),
                "calibration_mode": normalized_calibration_mode,
                "calibration_min_train_samples": normalized_calibration_min_train,
                "evaluation_level": str(evaluation_level or "event").strip().lower(),
                "strict_anchor_window_minutes": max(int(strict_anchor_window_minutes), 0),
                "target_mode": normalized_target_mode,
                "decision_policy": "two_stage" if (normalized_target_mode == "v2" and two_stage_for_v2) else "argmax",
                "utility_cost_per_trade": float(utility_cost_per_trade),
                "utility_bootstrap_iters": max(int(utility_bootstrap_iters), 0),
            },
            "fold_reports": [],
            "total_samples": 0,
            "dropped_by_embargo": 0,
            "sample_count": 0,
            "metrics": _classification_metrics([]),
            "utility": _compute_utility_metrics(
                [],
                horizon=horizon,
                cost_per_trade=utility_cost_per_trade,
                bootstrap_iters=utility_bootstrap_iters,
            ),
            "slices": {
                "ticker": {},
                "source": {},
            },
        }

    if walk_forward:
        oos_samples, fold_reports = _evaluate_walk_forward(
            samples=samples,
            period_from=period_from,
            period_to=period_to,
            folds=normalized_folds,
            embargo_minutes=normalized_embargo,
            calibration_mode=normalized_calibration_mode,
            calibration_min_train_samples=normalized_calibration_min_train,
        )
    else:
        oos_samples = sorted((dict(sample) for sample in samples), key=lambda row: row["published_at"])
        fold_reports = [
            {
                "fold_index": 1,
                "train_period": {
                    "from": period_from.isoformat() + "Z",
                    "to": period_to.isoformat() + "Z",
                },
                "test_period": {
                    "from": period_from.isoformat() + "Z",
                    "to": period_to.isoformat() + "Z",
                },
                "train_sample_count": len(samples),
                "sample_count": len(oos_samples),
                "metrics": _classification_metrics(oos_samples),
                "calibration_mode": normalized_calibration_mode,
                "calibration_applied": False,
                "calibration_reason": "disabled_single_pass",
                "calibrated_classes": [],
            }
        ]

    if normalized_target_mode == "v2" and bool(two_stage_for_v2):
        oos_samples = _apply_two_stage_policy(oos_samples, horizon=horizon)

    metrics = _classification_metrics(oos_samples)
    utility = _compute_utility_metrics(
        oos_samples,
        horizon=horizon,
        cost_per_trade=utility_cost_per_trade,
        bootstrap_iters=utility_bootstrap_iters,
    )
    dropped_by_embargo = max(len(samples) - len(oos_samples), 0)
    return {
        "model_id": model_id,
        "horizon": horizon,
        "period": {
            "from": period_from.isoformat() + "Z",
            "to": period_to.isoformat() + "Z",
        },
        "protocol": {
            "mode": "walk_forward" if walk_forward else "single_pass",
            "folds": normalized_folds,
            "embargo_minutes": normalized_embargo,
            "horizon_minutes": int(delta.total_seconds() // 60),
            "calibration_mode": normalized_calibration_mode,
            "calibration_min_train_samples": normalized_calibration_min_train,
            "evaluation_level": str(evaluation_level or "event").strip().lower(),
            "strict_anchor_window_minutes": max(int(strict_anchor_window_minutes), 0),
            "target_mode": normalized_target_mode,
            "decision_policy": "two_stage" if (normalized_target_mode == "v2" and two_stage_for_v2) else "argmax",
            "utility_cost_per_trade": float(utility_cost_per_trade),
            "utility_bootstrap_iters": max(int(utility_bootstrap_iters), 0),
        },
        "fold_reports": fold_reports,
        "total_samples": len(samples),
        "dropped_by_embargo": dropped_by_embargo,
        "sample_count": len(oos_samples),
        "epsilon": epsilon,
        "metrics": metrics,
        "utility": utility,
        "slices": {
            "ticker": _slice_metrics(oos_samples, "ticker"),
            "source": _slice_metrics(oos_samples, "source"),
            "event_family": _slice_metrics(oos_samples, "event_family"),
        },
    }


def compare_news_models(
    session: Session,
    *,
    model_ids: list[str],
    horizon: str,
    period_from: datetime,
    period_to: datetime,
    epsilon: float,
    folds: int = 5,
    embargo_minutes: int = 0,
    walk_forward: bool = True,
    calibration_mode: str = "none",
    calibration_min_train_samples: int = 30,
    promotion_min_accuracy: float = 0.70,
    promotion_min_coverage: float = 0.20,
    promotion_max_brier: float = 0.25,
    promotion_min_sample_count: int = 30,
    promotion_min_ticker_stability: float = 0.55,
    evaluation_level: str = "event",
    strict_anchor_window_minutes: int = 120,
    target_mode: str = "legacy",
    two_stage_for_v2: bool = True,
    utility_cost_per_trade: float = 0.00075,
    utility_bootstrap_iters: int = 2000,
    promotion_utility_min_trades: int = 30,
    promotion_utility_max_drawdown: float = 0.20,
    promotion_require_baseline_superiority: bool = True,
    promotion_baseline_min_accuracy_delta: float = 0.0,
    promotion_baseline_max_brier_delta: float = 0.0,
) -> dict[str, object]:
    reports: list[dict[str, object]] = []
    for model_id in model_ids:
        report = run_news_backtest(
                session,
                model_id=model_id,
                horizon=horizon,
                period_from=period_from,
                period_to=period_to,
                epsilon=epsilon,
                folds=folds,
                embargo_minutes=embargo_minutes,
                walk_forward=walk_forward,
                calibration_mode=calibration_mode,
                calibration_min_train_samples=calibration_min_train_samples,
                evaluation_level=evaluation_level,
                strict_anchor_window_minutes=strict_anchor_window_minutes,
                target_mode=target_mode,
                two_stage_for_v2=two_stage_for_v2,
                utility_cost_per_trade=utility_cost_per_trade,
                utility_bootstrap_iters=utility_bootstrap_iters,
            )
        report["supervised_metrics"] = _build_supervised_gold_metrics(
            session,
            model_id=model_id,
            period_from=period_from,
            period_to=period_to,
        )
        reports.append(report)

    baseline_reports: list[dict[str, object]] = []
    ablation_reports: dict[str, dict[str, object]] = {}

    def _score(report: dict[str, Any]) -> tuple[float, float, float, float, int]:
        metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
        accuracy = float(metrics.get("accuracy") or 0.0)
        balanced = float(metrics.get("balanced_accuracy") or 0.0)
        stability = _ticker_stability_score(report)
        brier = float(metrics.get("brier") or 0.0)
        coverage = float(metrics.get("coverage") or 0.0)
        utility = report.get("utility") if isinstance(report.get("utility"), dict) else {}
        mean_net = float(utility.get("mean_net_return_per_trade") or 0.0)
        sharpe = float(utility.get("sharpe_annualized") or 0.0)
        sample_count = int(report.get("sample_count") or 0)
        if _normalize_target_mode(target_mode) == "v2":
            return (mean_net, sharpe, balanced, stability, sample_count)
        return (accuracy, stability, coverage, -brier, sample_count)

    sorted_reports = sorted(reports, key=_score, reverse=True)
    winner = sorted_reports[0] if sorted_reports else None

    reference_model_id = str(winner.get("model_id") or "").strip() if isinstance(winner, dict) else ""
    if not reference_model_id and model_ids:
        reference_model_id = str(model_ids[0] or "").strip()
    if reference_model_id:
        reference_samples = _build_backtest_samples(
            session,
            model_id=reference_model_id,
            period_from=period_from,
            period_to=period_to,
            delta=_horizon_to_delta(horizon),
            epsilon=epsilon,
            strict_anchor_window_minutes=strict_anchor_window_minutes,
            evaluation_level=evaluation_level,
            target_mode=target_mode,
            horizon=horizon,
        )
        if reference_samples:
            news_ids = [str(item.get("news_id") or "").strip() for item in reference_samples if item.get("news_id")]
            calendar_direction_by_news = _build_calendar_direction_by_news(session, news_ids=news_ids)
            majority_samples = _apply_baseline_majority_class(reference_samples)
            no_news_samples = _apply_baseline_no_news(reference_samples)
            calendar_only_samples = _apply_baseline_calendar_only(
                reference_samples,
                direction_by_news=calendar_direction_by_news,
            )
            calendar_plus_text_samples = _apply_baseline_calendar_plus_text(
                reference_samples,
                direction_by_news=calendar_direction_by_news,
            )
            baseline_reports = [
                _build_report_from_samples(
                    model_id="baseline_majority_class",
                    horizon=horizon,
                    period_from=period_from,
                    period_to=period_to,
                    epsilon=epsilon,
                    samples=majority_samples,
                    utility_cost_per_trade=utility_cost_per_trade,
                    utility_bootstrap_iters=utility_bootstrap_iters,
                ),
                _build_report_from_samples(
                    model_id="baseline_no_news",
                    horizon=horizon,
                    period_from=period_from,
                    period_to=period_to,
                    epsilon=epsilon,
                    samples=no_news_samples,
                    utility_cost_per_trade=utility_cost_per_trade,
                    utility_bootstrap_iters=utility_bootstrap_iters,
                ),
                _build_report_from_samples(
                    model_id="baseline_calendar_only",
                    horizon=horizon,
                    period_from=period_from,
                    period_to=period_to,
                    epsilon=epsilon,
                    samples=calendar_only_samples,
                    utility_cost_per_trade=utility_cost_per_trade,
                    utility_bootstrap_iters=utility_bootstrap_iters,
                ),
                _build_report_from_samples(
                    model_id="baseline_text_only",
                    horizon=horizon,
                    period_from=period_from,
                    period_to=period_to,
                    epsilon=epsilon,
                    samples=reference_samples,
                    utility_cost_per_trade=utility_cost_per_trade,
                    utility_bootstrap_iters=utility_bootstrap_iters,
                ),
                _build_report_from_samples(
                    model_id="baseline_calendar_plus_text",
                    horizon=horizon,
                    period_from=period_from,
                    period_to=period_to,
                    epsilon=epsilon,
                    samples=calendar_plus_text_samples,
                    utility_cost_per_trade=utility_cost_per_trade,
                    utility_bootstrap_iters=utility_bootstrap_iters,
                ),
            ]
            ablation_reports = _build_ablation_reports(reference_samples)

    market_gate = _evaluate_promotion_gate(
        winner,
        min_accuracy=promotion_min_accuracy,
        min_coverage=promotion_min_coverage,
        max_brier=promotion_max_brier,
        min_sample_count=promotion_min_sample_count,
        min_ticker_stability=promotion_min_ticker_stability,
    )
    supervised_gate = _evaluate_supervised_gate(
        winner.get("supervised_metrics") if isinstance(winner, dict) else None,
        min_accuracy=promotion_min_accuracy,
        min_coverage=promotion_min_coverage,
        max_brier=promotion_max_brier,
        min_sample_count=promotion_min_sample_count,
    )
    baseline_gate = (
        _evaluate_baseline_superiority_gate(
            winner if isinstance(winner, dict) else None,
            baseline_reports,
            min_accuracy_delta=promotion_baseline_min_accuracy_delta,
            max_brier_delta=promotion_baseline_max_brier_delta,
        )
        if promotion_require_baseline_superiority
        else {
            "pass": True,
            "checks": [],
            "summary": {
                "enabled": False,
                "reason": "promotion_require_baseline_superiority_disabled",
            },
        }
    )
    utility_gate = _evaluate_utility_gate(
        winner if isinstance(winner, dict) else None,
        horizon=horizon,
        target_mode=target_mode,
        min_trades=promotion_utility_min_trades,
        max_drawdown=promotion_utility_max_drawdown,
    )
    quality_gate = {
        "pass": bool(market_gate.get("pass"))
        and bool(supervised_gate.get("pass"))
        and bool(baseline_gate.get("pass"))
        and bool(utility_gate.get("pass")),
        "market_gate": market_gate,
        "supervised_gate": supervised_gate,
        "baseline_gate": baseline_gate,
        "utility_gate": utility_gate,
        "checks": [
            *(market_gate.get("checks") if isinstance(market_gate.get("checks"), list) else []),
            *(supervised_gate.get("checks") if isinstance(supervised_gate.get("checks"), list) else []),
            *(baseline_gate.get("checks") if isinstance(baseline_gate.get("checks"), list) else []),
            *(utility_gate.get("checks") if isinstance(utility_gate.get("checks"), list) else []),
        ],
    }
    decision = "promote" if bool(quality_gate.get("pass")) else "hold"
    comparison_hash = hashlib.sha1(
        f"{horizon}|{period_from.isoformat()}|{period_to.isoformat()}|{','.join(model_ids)}".encode("utf-8")
    ).hexdigest()[:20]
    winner_reason = (
        "best_oos_utility_then_balanced_accuracy"
        if _normalize_target_mode(target_mode) == "v2"
        else "best_oos_accuracy_stability_coverage_then_brier"
    )
    _store_model_eval_record(
        session,
        comparison_hash=comparison_hash,
        horizon=horizon,
        winner=winner if isinstance(winner, dict) else None,
        market_gate=market_gate,
        supervised_gate=supervised_gate,
        quality_gate=quality_gate,
        decision=decision,
    )
    if _normalize_target_mode(target_mode) == "v2":
        _store_gate_run_v2(
            session,
            comparison_hash=comparison_hash,
            horizon=horizon,
            period_from=period_from,
            period_to=period_to,
            quality_gate=quality_gate,
            winner=winner if isinstance(winner, dict) else None,
        )

    comparison = {
        "horizon": horizon,
        "period": {
            "from": period_from.isoformat() + "Z",
            "to": period_to.isoformat() + "Z",
        },
        "epsilon": epsilon,
        "protocol": {
            "mode": "walk_forward" if walk_forward else "single_pass",
            "folds": max(int(folds), 1),
            "embargo_minutes": max(int(embargo_minutes), 0),
            "calibration_mode": _normalize_calibration_mode(calibration_mode),
            "calibration_min_train_samples": max(int(calibration_min_train_samples), 1),
            "evaluation_level": str(evaluation_level or "event").strip().lower(),
            "strict_anchor_window_minutes": max(int(strict_anchor_window_minutes), 0),
            "target_mode": _normalize_target_mode(target_mode),
            "two_stage_for_v2": bool(two_stage_for_v2),
            "utility_cost_per_trade": float(utility_cost_per_trade),
            "utility_bootstrap_iters": max(int(utility_bootstrap_iters), 0),
            "promotion_utility_min_trades": max(int(promotion_utility_min_trades), 0),
            "promotion_utility_max_drawdown": float(promotion_utility_max_drawdown),
            "require_baseline_superiority": bool(promotion_require_baseline_superiority),
            "baseline_min_accuracy_delta": float(promotion_baseline_min_accuracy_delta),
            "baseline_max_brier_delta": float(promotion_baseline_max_brier_delta),
        },
        "reports": reports,
        "baselines": baseline_reports,
        "ablations": ablation_reports,
        "winner": {
            "model_id": winner.get("model_id") if isinstance(winner, dict) else None,
            "reason": winner_reason,
        },
        "audit": {
            "decision": decision,
            "quality_gate": quality_gate,
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "comparison_hash": comparison_hash,
        },
    }
    return comparison

__all__ = [
    "run_news_backtest",
    "compare_news_models",
]
