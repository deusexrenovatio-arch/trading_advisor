from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence

from moex_carry.signal_engine.core.types import HistoricalOutcome, OutcomeForecast


class ProbabilityModel(Protocol):
    def estimate(
        self,
        *,
        outcomes: Sequence[HistoricalOutcome],
        as_of_ts: datetime,
    ) -> OutcomeForecast:
        ...
