from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SignalDecision:
    action: str
    direction: Optional[str]
    score: float
    reasons: list[str]
    metrics: dict[str, Any]
