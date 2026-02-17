from __future__ import annotations

from types import SimpleNamespace

from moex_carry.contracts.strategy_test import HpoRequest
from moex_carry.hpo.runtime import _build_quality_review
from moex_carry.hpo.types import HpoResult, TrialResult


def test_quality_review_applies_gates_and_penalty(monkeypatch, tmp_path):
    request = HpoRequest()
    request.optimization.quality_top_n = 2
    request.optimization.quality_min_trades_closed_total = 1
    result = HpoResult(
        trials=[
            TrialResult(params={}, objective=1.2),
            TrialResult(params={"strategy.TP_pct": 0.02}, objective=1.0),
        ],
        mode="max",
    )

    responses = [
        {
            "unfilled_entry_rate_mean": 0.2,
            "forced_exit_rate_mean": 0.2,
            "avg_entry_wait_min_closed_mean": 100.0,
            "avg_exit_wait_min_closed_mean": 90.0,
            "trades_closed_total": 12,
            "pairs_ok": 10,
            "pairs_total": 10,
        },
        {
            "unfilled_entry_rate_mean": 0.8,  # should fail gate
            "forced_exit_rate_mean": 0.7,  # should fail gate
            "avg_entry_wait_min_closed_mean": 400.0,  # should fail gate
            "avg_exit_wait_min_closed_mean": 350.0,  # should fail gate
            "trades_closed_total": 1,
            "pairs_ok": 10,
            "pairs_total": 10,
        },
    ]

    def _fake_backtest(*_args, **_kwargs):
        payload = responses.pop(0)
        return SimpleNamespace(fill_quality_summary=payload)

    monkeypatch.setattr("moex_carry.hpo.runtime.run_backtest_v2_cached", _fake_backtest)

    review = _build_quality_review(
        request=request,
        result=result,
        data_dir=tmp_path,
        precompute=True,
    )
    assert review is not None
    assert review["top_n_evaluated"] == 2
    assert review["quality_gate_pass_count"] == 1
    assert isinstance(review["candidates"], list)
    assert review["candidates"][0]["quality_gate_pass"] is True
    assert review["candidates"][1]["quality_gate_pass"] is False
    assert review["candidates"][0]["objective_quality"] >= review["candidates"][1]["objective_quality"]


def test_quality_review_skips_for_non_intraday_mode(tmp_path):
    request = HpoRequest()
    request.base.execution.mode = "DAILY_EOD"
    result = HpoResult(trials=[TrialResult(params={}, objective=1.0)], mode="max")

    review = _build_quality_review(
        request=request,
        result=result,
        data_dir=tmp_path,
        precompute=True,
    )
    assert review is not None
    assert review["skipped"] is True
    assert review["reason"] == "execution_mode_not_intraday_minute"
