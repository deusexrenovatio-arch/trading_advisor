import pytest

from moex_carry.config_resolver import resolve_backtest_request
from moex_carry.contracts.strategy_test import (
    BacktestCostsConfig,
    BacktestExecutionConfig,
    BacktestLiquidityConfig,
    BacktestPortfolioConfig,
    BacktestRequest,
    BacktestStrategyConfig,
    BacktestTestConfig,
    BacktestUniverseConfig,
)


def test_resolver_auto_to_number():
    request = BacktestRequest(
        test=BacktestTestConfig(cost_stress_mult=1.0),
        universe=BacktestUniverseConfig(max_pairs=5),
        liquidity=BacktestLiquidityConfig(
            min_avg_dollarvol_stock="AUTO",
            min_avg_dollarvol_fut="AUTO",
            participation_rate=0.1,
            max_days_to_exit=5.0,
        ),
        portfolio=BacktestPortfolioConfig(capital_allocated_per_trade=100_000.0),
    )
    resolved = resolve_backtest_request(request)
    stock_value = resolved.resolved_config["liquidity"]["min_avg_dollarvol_stock"]
    fut_value = resolved.resolved_config["liquidity"]["min_avg_dollarvol_fut"]
    assert isinstance(stock_value, float)
    assert isinstance(fut_value, float)
    assert stock_value == pytest.approx(200_000.0)
    assert fut_value == pytest.approx(200_000.0)


def test_resolver_cost_stress_mult_applies():
    request = BacktestRequest(
        test=BacktestTestConfig(cost_stress_mult=2.0),
        costs=BacktestCostsConfig(
            stock_commission_bps=1.0,
            futures_commission_bps=1.5,
            exchange_fee_bps=0.2,
            fee_stock_per_share=0.01,
            fee_stock_bps=0.5,
            fee_fut_per_contract=2.0,
        ),
        execution=BacktestExecutionConfig(
            slip_stock_bps=0.4,
            slip_fut_bps=0.2,
            slip_fut_ticks=1.0,
        ),
    )
    resolved = resolve_backtest_request(request)
    costs = resolved.resolved_config["costs"]
    execution = resolved.resolved_config["execution"]
    assert costs["stock_commission_bps"] == pytest.approx(2.0)
    assert costs["futures_commission_bps"] == pytest.approx(3.0)
    assert costs["exchange_fee_bps"] == pytest.approx(0.4)
    assert costs["fee_stock_per_share"] == pytest.approx(0.02)
    assert costs["fee_stock_bps"] == pytest.approx(1.0)
    assert costs["fee_fut_per_contract"] == pytest.approx(4.0)
    assert execution["slip_stock_bps"] == pytest.approx(0.8)
    assert execution["slip_fut_bps"] == pytest.approx(0.4)
    assert execution["slip_fut_ticks"] == pytest.approx(2.0)


def test_resolver_validates_weights_sum():
    request = BacktestRequest(
        strategy=BacktestStrategyConfig(w_floor=0.6, w_alpha=0.3)
    )
    with pytest.raises(ValueError, match="w_floor"):
        resolve_backtest_request(request)
