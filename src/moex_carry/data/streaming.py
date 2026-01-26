from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from moex_carry.domain.models import Quote


class StreamingProvider(ABC):
    @abstractmethod
    def subscribe_quotes(self, secids: list[str], handler: Callable[[Quote], None]) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
