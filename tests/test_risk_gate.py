from moex_carry.domain.decision import RiskProfile
from moex_carry.strategy.risk_gate import evaluate_risk_profile


def _profile(**overrides):
    base = dict(
        account_equity=1_000_000.0,
        account_currency="RUB",
        max_risk_per_trade_pct=0.5,
        max_daily_loss_pct=2.0,
        max_open_risk_pct=1.5,
        max_leverage=3.0,
        max_margin_pct=60.0,
        max_contracts_per_instrument=10,
        max_positions=6,
        max_correlated_exposure_pct=40.0,
        stop_loss_required=True,
        time_stop_minutes=90,
        slippage_tolerance_ticks=2,
    )
    base.update(overrides)
    return RiskProfile(**base)


def test_risk_gate_blocks_invalid_leverage():
    profile = _profile(max_leverage=20)
    result = evaluate_risk_profile(profile, allocations=[])
    assert result.passed is False
    assert any(check.check_id == "max_leverage_range" and not check.passed for check in result.checks)


def test_risk_gate_blocks_too_many_positions():
    profile = _profile(max_positions=1)
    allocations = [{"instrument": "SBER", "side": "long"}, {"instrument": "RIH5", "side": "short"}]
    result = evaluate_risk_profile(profile, allocations=allocations)
    assert result.passed is False
    assert any(check.check_id == "positions_count" and not check.passed for check in result.checks)


def test_risk_gate_passes_valid_profile():
    profile = _profile()
    result = evaluate_risk_profile(profile, allocations=[])
    assert result.passed is True
