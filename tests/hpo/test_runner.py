from __future__ import annotations

from datetime import date
from pathlib import Path

from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.hpo.runner import _default_backtest_runner


def test_default_backtest_runner_disables_fill_quality(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_runner(request, data_dir, *, precompute=None, compute_fill_quality=True):
        captured["request"] = request
        captured["data_dir"] = data_dir
        captured["precompute"] = precompute
        captured["compute_fill_quality"] = compute_fill_quality
        return "ok"

    monkeypatch.setattr("moex_carry.hpo.runner.run_backtest_v2_cached", _fake_runner)

    request = BacktestRequest()
    request.test.start_date = date(2025, 1, 1)
    request.test.end_date = date(2025, 1, 31)
    result = _default_backtest_runner(request, Path("data"), precompute=True)

    assert result == "ok"
    assert captured["request"] is request
    assert captured["data_dir"] == Path("data")
    assert captured["precompute"] is True
    assert captured["compute_fill_quality"] is False
