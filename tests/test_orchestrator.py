import moex_carry.strategy.orchestrator as orchestrator
from moex_carry.strategy.models import SignalDecision


def _call_generate_signal():
    return orchestrator.generate_signal(
        spread_series=[0.1, 0.2, 0.15],
        implied_rate_net=0.1,
        required_rate=0.05,
        days_to_expiry=30,
        days_to_exdiv=20,
        z_window=10,
        z_min_window=5,
        z_entry=2.0,
        z_exit=0.5,
        implied_rate_buffer=0.01,
        min_days_to_expiry=5,
        min_days_to_exdiv=5,
    )


def test_generate_signal_requires_both_confirm(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "stat_signal",
        lambda *args, **kwargs: SignalDecision(
            action="enter",
            direction="cash_and_carry",
            score=2.0,
            reasons=["stat_enter"],
            metrics={},
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "carry_signal",
        lambda *args, **kwargs: SignalDecision(
            action="hold",
            direction=None,
            score=0.0,
            reasons=["carry_hold"],
            metrics={},
        ),
    )
    result = _call_generate_signal()
    assert result.action == "hold"
    assert "carry_not_confirmed" in result.reasons


def test_generate_signal_enters_when_both_match(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "stat_signal",
        lambda *args, **kwargs: SignalDecision(
            action="enter",
            direction="reverse",
            score=2.0,
            reasons=["stat_enter"],
            metrics={},
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "carry_signal",
        lambda *args, **kwargs: SignalDecision(
            action="enter",
            direction="reverse",
            score=1.0,
            reasons=["carry_enter"],
            metrics={},
        ),
    )
    result = _call_generate_signal()
    assert result.action == "enter"
    assert result.direction == "reverse"


def test_generate_signal_exit_has_priority(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "stat_signal",
        lambda *args, **kwargs: SignalDecision(
            action="exit",
            direction=None,
            score=0.5,
            reasons=["stat_exit"],
            metrics={},
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "carry_signal",
        lambda *args, **kwargs: SignalDecision(
            action="enter",
            direction="cash_and_carry",
            score=1.0,
            reasons=["carry_enter"],
            metrics={},
        ),
    )
    result = _call_generate_signal()
    assert result.action == "exit"
