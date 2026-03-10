from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from moex_carry.signal_engine.core.types import AlphaProposal, Candle


class StrategyPlugin(Protocol):
    strategy_id: str

    def generate(
        self,
        *,
        instrument_id: str,
        candles: Sequence[Candle],
        tick_size: float,
        context: dict[str, Any] | None = None,
    ) -> AlphaProposal | None:
        ...
