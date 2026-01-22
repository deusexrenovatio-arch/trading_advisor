from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BrokerAdapter(ABC):
    @abstractmethod
    def place_order(self, symbol: str, side: str, quantity: float, order_type: str, price: float | None) -> str:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_order_status(self, order_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_limits(self) -> dict[str, Any]:
        raise NotImplementedError
