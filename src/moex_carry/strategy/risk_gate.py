from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from moex_carry.domain.decision import RiskProfile


@dataclass
class RiskCheckResult:
    check_id: str
    description: str
    limit: float | str
    value: float | str
    unit: str
    passed: bool
    action: str


@dataclass
class RiskGateResult:
    passed: bool
    action: str
    checks: list[RiskCheckResult]


def _range_check(
    check_id: str,
    description: str,
    value: float,
    min_value: float,
    max_value: float,
    unit: str,
) -> RiskCheckResult:
    passed = min_value <= value <= max_value
    return RiskCheckResult(
        check_id=check_id,
        description=description,
        limit=f"{min_value}-{max_value}",
        value=value,
        unit=unit,
        passed=passed,
        action="allow" if passed else "block",
    )


def evaluate_risk_profile(
    profile: RiskProfile, allocations: Iterable[dict[str, object]]
) -> RiskGateResult:
    checks: list[RiskCheckResult] = []
    allocation_list = list(allocations)
    checks.append(
        _range_check(
            "risk_limits_range",
            "All percentage limits within 0.1-10.0",
            profile.max_risk_per_trade_pct,
            0.1,
            10.0,
            "pct",
        )
    )
    checks.append(
        _range_check(
            "open_risk_range",
            "max_open_risk_pct within 0.1-10.0",
            profile.max_open_risk_pct,
            0.1,
            10.0,
            "pct",
        )
    )
    checks.append(
        _range_check(
            "daily_loss_range",
            "Max daily loss within 0.1-10.0",
            profile.max_daily_loss_pct,
            0.1,
            10.0,
            "pct",
        )
    )
    checks.append(
        RiskCheckResult(
            check_id="open_risk_vs_trade",
            description="max_open_risk_pct >= max_risk_per_trade_pct",
            limit=profile.max_risk_per_trade_pct,
            value=profile.max_open_risk_pct,
            unit="pct",
            passed=profile.max_open_risk_pct >= profile.max_risk_per_trade_pct,
            action="allow"
            if profile.max_open_risk_pct >= profile.max_risk_per_trade_pct
            else "block",
        )
    )
    checks.append(
        RiskCheckResult(
            check_id="daily_loss_vs_trade",
            description="max_daily_loss_pct >= 2 * max_risk_per_trade_pct",
            limit=2 * profile.max_risk_per_trade_pct,
            value=profile.max_daily_loss_pct,
            unit="pct",
            passed=profile.max_daily_loss_pct >= 2 * profile.max_risk_per_trade_pct,
            action="allow"
            if profile.max_daily_loss_pct >= 2 * profile.max_risk_per_trade_pct
            else "block",
        )
    )
    checks.append(
        _range_check(
            "max_leverage_range",
            "max_leverage within 1-10",
            profile.max_leverage,
            1.0,
            10.0,
            "x",
        )
    )
    checks.append(
        _range_check(
            "max_margin_range",
            "max_margin_pct within 10-100",
            profile.max_margin_pct,
            10.0,
            100.0,
            "pct",
        )
    )
    checks.append(
        _range_check(
            "correlated_exposure_range",
            "max_correlated_exposure_pct within 0-100",
            profile.max_correlated_exposure_pct,
            0.0,
            100.0,
            "pct",
        )
    )
    checks.append(
        RiskCheckResult(
            check_id="contracts_per_instrument",
            description="max_contracts_per_instrument is positive",
            limit=">=1",
            value=profile.max_contracts_per_instrument,
            unit="count",
            passed=profile.max_contracts_per_instrument >= 1,
            action="allow" if profile.max_contracts_per_instrument >= 1 else "block",
        )
    )
    checks.append(
        RiskCheckResult(
            check_id="max_positions",
            description="max_positions is positive",
            limit=">=1",
            value=profile.max_positions,
            unit="count",
            passed=profile.max_positions >= 1,
            action="allow" if profile.max_positions >= 1 else "block",
        )
    )
    checks.append(
        RiskCheckResult(
            check_id="stop_loss_required",
            description="stop_loss_required must be true",
            limit=True,
            value=profile.stop_loss_required,
            unit="bool",
            passed=profile.stop_loss_required is True,
            action="allow" if profile.stop_loss_required is True else "block",
        )
    )
    checks.append(
        _range_check(
            "time_stop_range",
            "time_stop_minutes within 1-240",
            float(profile.time_stop_minutes),
            1.0,
            240.0,
            "minutes",
        )
    )
    checks.append(
        _range_check(
            "slippage_tolerance_range",
            "slippage_tolerance_ticks within 0-10",
            float(profile.slippage_tolerance_ticks),
            0.0,
            10.0,
            "ticks",
        )
    )

    allocation_count = len(allocation_list)
    checks.append(
        RiskCheckResult(
            check_id="positions_count",
            description="Allocations count within max_positions",
            limit=profile.max_positions,
            value=allocation_count,
            unit="count",
            passed=allocation_count <= profile.max_positions,
            action="allow" if allocation_count <= profile.max_positions else "block",
        )
    )

    passed = all(check.passed for check in checks)
    action = "allow" if passed else "block"
    return RiskGateResult(passed=passed, action=action, checks=checks)
