from __future__ import annotations

from datetime import datetime, timedelta
from moex_carry.news.research_metrics import (
    _classification_metrics,
    _normalize_prob_triplet,
    _normalize_target_mode,
    _safe_import,
)

def _build_fold_windows(
    *,
    period_from: datetime,
    period_to: datetime,
    folds: int,
) -> list[tuple[datetime, datetime]]:
    normalized_folds = max(int(folds), 1)
    if normalized_folds == 1 or period_to <= period_from:
        return [(period_from, period_to)]
    total_seconds = (period_to - period_from).total_seconds()
    if total_seconds <= 0.0:
        return [(period_from, period_to)]

    step_seconds = total_seconds / float(normalized_folds)
    windows: list[tuple[datetime, datetime]] = []
    for idx in range(normalized_folds):
        start = period_from + timedelta(seconds=step_seconds * idx)
        if idx == normalized_folds - 1:
            end = period_to
        else:
            end = period_from + timedelta(seconds=step_seconds * (idx + 1))
        if end < start:
            continue
        windows.append((start, end))
    return windows or [(period_from, period_to)]


def _fit_binary_calibrator(mode: str, train_x: list[float], train_y: list[int]):
    if len(train_x) == 0 or len(train_y) == 0 or len(train_x) != len(train_y):
        return None, "empty_train"
    if len(set(train_y)) < 2:
        return None, "single_class_train"

    if mode == "isotonic":
        sklearn_isotonic = _safe_import("sklearn.isotonic")
        if sklearn_isotonic is None:
            return None, "sklearn_missing"
        try:
            calibrator = sklearn_isotonic.IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            calibrator.fit(train_x, train_y)
            return calibrator, "ok"
        except Exception:
            return None, "fit_failed"

    if mode == "platt":
        sklearn_linear = _safe_import("sklearn.linear_model")
        if sklearn_linear is None:
            return None, "sklearn_missing"
        try:
            calibrator = sklearn_linear.LogisticRegression(solver="lbfgs")
            calibrator.fit([[float(value)] for value in train_x], train_y)
            return calibrator, "ok"
        except Exception:
            return None, "fit_failed"

    return None, "unsupported_mode"


def _predict_binary_calibrator(mode: str, calibrator, test_x: list[float]) -> list[float] | None:
    try:
        if mode == "isotonic":
            raw = calibrator.transform(test_x)
            return [min(max(float(value), 0.0), 1.0) for value in raw]
        if mode == "platt":
            raw = calibrator.predict_proba([[float(value)] for value in test_x])
            return [min(max(float(row[1]), 0.0), 1.0) for row in raw]
    except Exception:
        return None
    return None


def _calibrate_fold_probabilities(
    *,
    train_samples: list[dict[str, object]],
    test_samples: list[dict[str, object]],
    calibration_mode: str,
    min_train_samples: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if not test_samples:
        return [], {
            "calibration_mode": calibration_mode,
            "calibration_applied": False,
            "calibration_reason": "empty_test",
            "calibrated_classes": [],
        }

    if calibration_mode == "none":
        return [dict(sample) for sample in test_samples], {
            "calibration_mode": "none",
            "calibration_applied": False,
            "calibration_reason": "disabled",
            "calibrated_classes": [],
        }

    if len(train_samples) < max(int(min_train_samples), 1):
        return [dict(sample) for sample in test_samples], {
            "calibration_mode": calibration_mode,
            "calibration_applied": False,
            "calibration_reason": "insufficient_train_samples",
            "calibrated_classes": [],
        }

    class_order = ("up", "down", "neutral")
    raw_test = {
        label: [float(sample.get(f"prob_{label}") or 0.0) for sample in test_samples]
        for label in class_order
    }
    transformed = dict(raw_test)
    class_meta: dict[str, str] = {}
    calibrated_classes: list[str] = []

    for label in class_order:
        train_x = [float(sample.get(f"prob_{label}") or 0.0) for sample in train_samples]
        train_y = [1 if str(sample.get("actual_label") or "") == label else 0 for sample in train_samples]
        calibrator, status = _fit_binary_calibrator(calibration_mode, train_x, train_y)
        if calibrator is None:
            class_meta[label] = status
            continue
        predicted = _predict_binary_calibrator(calibration_mode, calibrator, raw_test[label])
        if predicted is None:
            class_meta[label] = "predict_failed"
            continue
        transformed[label] = predicted
        class_meta[label] = "ok"
        calibrated_classes.append(label)

    if not calibrated_classes:
        return [dict(sample) for sample in test_samples], {
            "calibration_mode": calibration_mode,
            "calibration_applied": False,
            "calibration_reason": "no_class_calibrated",
            "calibrated_classes": [],
            "class_status": class_meta,
        }

    calibrated_rows: list[dict[str, object]] = []
    for idx, sample in enumerate(test_samples):
        prob_up, prob_down, prob_neutral = _normalize_prob_triplet(
            transformed["up"][idx],
            transformed["down"][idx],
            transformed["neutral"][idx],
        )
        row = dict(sample)
        row["prob_up"] = prob_up
        row["prob_down"] = prob_down
        row["prob_neutral"] = prob_neutral
        row["pred_confidence"] = max(prob_up, prob_down, prob_neutral)
        row["calibrated"] = True
        row["calibration_mode"] = calibration_mode
        calibrated_rows.append(row)

    return calibrated_rows, {
        "calibration_mode": calibration_mode,
        "calibration_applied": True,
        "calibration_reason": "ok",
        "calibrated_classes": calibrated_classes,
        "class_status": class_meta,
    }


def _evaluate_walk_forward(
    *,
    samples: list[dict[str, object]],
    period_from: datetime,
    period_to: datetime,
    folds: int,
    embargo_minutes: int,
    calibration_mode: str,
    calibration_min_train_samples: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if not samples:
        return [], []

    embargo = timedelta(minutes=max(int(embargo_minutes), 0))
    windows = _build_fold_windows(period_from=period_from, period_to=period_to, folds=folds)
    ordered = sorted(samples, key=lambda row: row["published_at"])

    oos_samples: list[dict[str, object]] = []
    fold_reports: list[dict[str, object]] = []
    for idx, (test_from, test_to) in enumerate(windows, start=1):
        effective_test_from = test_from + embargo
        if effective_test_from > test_to:
            continue
        effective_train_to = test_from - embargo
        train_samples = [
            sample
            for sample in ordered
            if period_from <= sample["published_at"] <= effective_train_to
        ]
        test_samples_raw = [
            sample
            for sample in ordered
            if effective_test_from <= sample["published_at"] <= test_to
        ]
        if not test_samples_raw:
            continue

        test_samples, calibration_meta = _calibrate_fold_probabilities(
            train_samples=train_samples,
            test_samples=test_samples_raw,
            calibration_mode=calibration_mode,
            min_train_samples=calibration_min_train_samples,
        )

        oos_samples.extend(test_samples)
        fold_reports.append(
            {
                "fold_index": idx,
                "train_period": {
                    "from": period_from.isoformat() + "Z",
                    "to": effective_train_to.isoformat() + "Z",
                },
                "test_period": {
                    "from": effective_test_from.isoformat() + "Z",
                    "to": test_to.isoformat() + "Z",
                },
                "train_sample_count": len(train_samples),
                "sample_count": len(test_samples),
                "metrics": _classification_metrics(test_samples),
                **calibration_meta,
            }
        )
    return oos_samples, fold_reports


def _ticker_stability_score(report: dict[str, object]) -> float:
    slices_raw = report.get("slices") if isinstance(report.get("slices"), dict) else {}
    ticker_slices = slices_raw.get("ticker") if isinstance(slices_raw.get("ticker"), dict) else {}
    per_ticker: list[float] = []
    for metrics in ticker_slices.values():
        if not isinstance(metrics, dict):
            continue
        sample_count = int(metrics.get("sample_count") or 0)
        if sample_count < 3:
            continue
        per_ticker.append(float(metrics.get("accuracy") or 0.0))
    if per_ticker:
        return min(per_ticker)
    top_metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    return float(top_metrics.get("accuracy") or 0.0)


def _build_gate_check(*, check_id: str, value: float, threshold: float, operator: str, passed: bool) -> dict[str, object]:
    return {
        "check_id": check_id,
        "value": value,
        "threshold": threshold,
        "operator": operator,
        "passed": bool(passed),
    }


def _evaluate_promotion_gate(
    report: dict[str, object] | None,
    *,
    min_accuracy: float,
    min_coverage: float,
    max_brier: float,
    min_sample_count: int,
    min_ticker_stability: float,
) -> dict[str, object]:
    if not isinstance(report, dict):
        return {
            "pass": False,
            "checks": [
                {
                    "check_id": "winner_present",
                    "passed": False,
                    "operator": "exists",
                    "value": 0,
                    "threshold": 1,
                }
            ],
        }

    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    accuracy = float(metrics.get("accuracy") or 0.0)
    coverage = float(metrics.get("coverage") or 0.0)
    brier = float(metrics.get("brier") or 1.0)
    sample_count = int(report.get("sample_count") or metrics.get("sample_count") or 0)
    stability = _ticker_stability_score(report)

    checks = [
        _build_gate_check(
            check_id="sample_count_min",
            value=float(sample_count),
            threshold=float(min_sample_count),
            operator=">=",
            passed=sample_count >= max(int(min_sample_count), 0),
        ),
        _build_gate_check(
            check_id="accuracy_min",
            value=accuracy,
            threshold=float(min_accuracy),
            operator=">=",
            passed=accuracy >= float(min_accuracy),
        ),
        _build_gate_check(
            check_id="coverage_min",
            value=coverage,
            threshold=float(min_coverage),
            operator=">=",
            passed=coverage >= float(min_coverage),
        ),
        _build_gate_check(
            check_id="brier_max",
            value=brier,
            threshold=float(max_brier),
            operator="<=",
            passed=brier <= float(max_brier),
        ),
        _build_gate_check(
            check_id="ticker_stability_min",
            value=stability,
            threshold=float(min_ticker_stability),
            operator=">=",
            passed=stability >= float(min_ticker_stability),
        ),
    ]

    return {
        "pass": all(bool(item.get("passed")) for item in checks),
        "checks": checks,
        "summary": {
            "sample_count": sample_count,
            "accuracy": accuracy,
            "coverage": coverage,
            "brier": brier,
            "ticker_stability": stability,
        },
    }


def _utility_sharpe_threshold(horizon: str) -> float:
    key = str(horizon or "1d").strip().lower()
    if key in {"5m", "1h"}:
        return 0.30
    return 0.50


def _evaluate_utility_gate(
    report: dict[str, object] | None,
    *,
    horizon: str,
    target_mode: str,
    min_trades: int = 30,
    max_drawdown: float = 0.20,
) -> dict[str, object]:
    normalized_target_mode = _normalize_target_mode(target_mode)
    if normalized_target_mode != "v2":
        return {
            "pass": True,
            "checks": [],
            "summary": {
                "enabled": False,
                "reason": "target_mode_not_v2",
            },
        }
    if not isinstance(report, dict):
        return {
            "pass": False,
            "checks": [
                {
                    "check_id": "utility_report_present",
                    "operator": "exists",
                    "value": 0,
                    "threshold": 1,
                    "passed": False,
                    "reason": "missing_report",
                }
            ],
        }
    utility = report.get("utility") if isinstance(report.get("utility"), dict) else {}
    n_trades = int(utility.get("n_trades") or 0)
    mean_net = float(utility.get("mean_net_return_per_trade") or 0.0)
    sharpe = float(utility.get("sharpe_annualized") or 0.0)
    max_dd = float(utility.get("max_drawdown") or 0.0)
    ci = utility.get("bootstrap_ci_95")
    ci_low = float(ci[0]) if isinstance(ci, list) and len(ci) >= 2 else mean_net
    checks = [
        _build_gate_check(
            check_id="utility_min_trades",
            value=float(n_trades),
            threshold=float(max(int(min_trades), 0)),
            operator=">=",
            passed=n_trades >= max(int(min_trades), 0),
        ),
        _build_gate_check(
            check_id="utility_mean_net_positive",
            value=mean_net,
            threshold=0.0,
            operator=">",
            passed=mean_net > 0.0,
        ),
        _build_gate_check(
            check_id="utility_bootstrap_ci_low_positive",
            value=ci_low,
            threshold=0.0,
            operator=">",
            passed=ci_low > 0.0,
        ),
        _build_gate_check(
            check_id="utility_sharpe_min",
            value=sharpe,
            threshold=float(_utility_sharpe_threshold(horizon)),
            operator=">=",
            passed=sharpe >= _utility_sharpe_threshold(horizon),
        ),
        _build_gate_check(
            check_id="utility_max_drawdown_max",
            value=max_dd,
            threshold=float(max_drawdown),
            operator="<=",
            passed=max_dd <= float(max_drawdown),
        ),
    ]
    return {
        "pass": all(bool(item.get("passed")) for item in checks),
        "checks": checks,
        "summary": {
            "n_trades": n_trades,
            "mean_net_return_per_trade": mean_net,
            "bootstrap_ci_95": ci if isinstance(ci, list) else [mean_net, mean_net],
            "sharpe_annualized": sharpe,
            "max_drawdown": max_dd,
        },
    }

__all__ = [
    "_build_fold_windows",
    "_fit_binary_calibrator",
    "_predict_binary_calibrator",
    "_calibrate_fold_probabilities",
    "_evaluate_walk_forward",
    "_ticker_stability_score",
    "_build_gate_check",
    "_evaluate_promotion_gate",
    "_utility_sharpe_threshold",
    "_evaluate_utility_gate",
]
