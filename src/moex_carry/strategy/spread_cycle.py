from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpreadCycleState:
    position: str | None = None
    cycle_counter: int = 0
    entry_spread: float | None = None
    entry_spot: float | None = None
    entry_direction: str | None = None


@dataclass
class SpreadCycleUpdate:
    entry_flag: bool
    exit_flag: bool
    entry_cycle: int | None
    exit_cycle: int | None
    cycle_id: int | None
    cycle_return_pct: float | None


def _cycle_return_pct(
    entry_spread: float | None,
    entry_spot: float | None,
    entry_direction: str | None,
    spread: float,
) -> float | None:
    if entry_spread is not None and entry_spot:
        if entry_direction == "cash_and_carry":
            return (entry_spread - spread) / entry_spot * 100.0
        if entry_direction == "reverse":
            return (spread - entry_spread) / entry_spot * 100.0
    return None


def update_spread_cycle(
    state: SpreadCycleState,
    action: str,
    direction: str | None,
    spread: float,
    spot: float,
) -> SpreadCycleUpdate:
    entry_flag = False
    exit_flag = False
    entry_cycle: int | None = None
    exit_cycle: int | None = None
    cycle_return_pct: float | None = None

    if state.position is None:
        if action == "enter" and direction:
            entry_flag = True
            state.cycle_counter += 1
            entry_cycle = state.cycle_counter
            state.position = direction
            state.entry_spread = spread
            state.entry_spot = spot
            state.entry_direction = direction
    else:
        if action == "exit":
            exit_flag = True
            exit_cycle = state.cycle_counter
            cycle_return_pct = _cycle_return_pct(
                state.entry_spread, state.entry_spot, state.entry_direction, spread
            )
            state.position = None
            state.entry_spread = None
            state.entry_spot = None
            state.entry_direction = None
        elif action == "enter" and direction and direction != state.position:
            exit_flag = True
            exit_cycle = state.cycle_counter
            cycle_return_pct = _cycle_return_pct(
                state.entry_spread, state.entry_spot, state.entry_direction, spread
            )
            state.position = None
            state.entry_spread = None
            state.entry_spot = None
            state.entry_direction = None

    cycle_id = state.cycle_counter if state.position else None
    return SpreadCycleUpdate(
        entry_flag=entry_flag,
        exit_flag=exit_flag,
        entry_cycle=entry_cycle,
        exit_cycle=exit_cycle,
        cycle_id=cycle_id,
        cycle_return_pct=cycle_return_pct,
    )
