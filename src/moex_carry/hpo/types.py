from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

AggregationMode = Literal["median", "p25", "mean"]
Algorithm = Literal["RANDOM", "TPE"]
EvaluationMode = Literal["WARMUP_THEN_FLAT", "CONTINUOUS"]
ObjectiveMode = Literal["max", "min"]


@dataclass(frozen=True)
class WalkForwardFold:
    train_start: date
    train_end: date
    val_start: date
    val_end: date
    test_start: date
    test_end: date


@dataclass(frozen=True)
class ObjectiveConfig:
    metric: str = "excess_ann"
    mode: ObjectiveMode = "max"
    scope: Literal["PAIR_MEAN", "PORTFOLIO"] = "PORTFOLIO"
    portfolio_metric: Literal["utility", "excess_ann", "cagr"] = "utility"
    lambda_dd: float = 2.0
    dd_max: float | None = None
    lambda_to: float = 0.0
    to_max: float | None = None
    dd_soft_limit: float = 0.20
    lambda_idle: float = 0.6
    lambda_forced: float = 0.4
    lambda_unfilled: float = 0.3
    lambda_turnover: float = 0.1
    hard_max_dd: float | None = 0.30
    hard_max_idle_ratio: float | None = 0.75
    hard_max_forced_exit_rate: float | None = 0.40
    hard_max_unfilled_entry_rate: float | None = 0.50


@dataclass(frozen=True)
class SearchSpaceParam:
    key: str
    kind: Literal["int", "float", "categorical", "bool"]
    min_value: float | None = None
    max_value: float | None = None
    options: list[Any] | None = None
    step: float | None = None
    log: bool = False


@dataclass
class FoldResult:
    fold: WalkForwardFold
    val_metrics: dict[str, float]
    test_metrics: dict[str, float] | None
    val_objective: float


@dataclass
class TrialResult:
    params: dict[str, Any]
    objective: float
    fold_objectives: list[float] = field(default_factory=list)
    fold_results: list[FoldResult] = field(default_factory=list)
    evaluation_scope: str | None = None
    objective_breakdown: dict[str, float] | None = None


@dataclass
class HpoResult:
    trials: list[TrialResult]
    mode: Literal["max", "min"] = "max"

    def leaderboard(self) -> list[TrialResult]:
        reverse = self.mode == "max"
        return sorted(self.trials, key=lambda trial: trial.objective, reverse=reverse)

    @property
    def best_trial(self) -> TrialResult | None:
        board = self.leaderboard()
        return board[0] if board else None

    @property
    def best_config(self) -> dict[str, Any] | None:
        trial = self.best_trial
        return dict(trial.params) if trial else None
