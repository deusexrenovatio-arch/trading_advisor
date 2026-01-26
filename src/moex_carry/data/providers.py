from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Optional

from moex_carry.data.moex_iss import MoexIssClient


class MarketDataProvider(ABC):
    @abstractmethod
    def list_securities(self, engine: str, market: str, board: Optional[str]) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_candles(
        self,
        engine: str,
        market: str,
        secid: str,
        board: Optional[str],
        from_date: date,
        till_date: date,
        interval: int,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


class MoexIssProvider(MarketDataProvider):
    def __init__(self, client: MoexIssClient) -> None:
        self.client = client

    def list_securities(self, engine: str, market: str, board: Optional[str]) -> list[dict[str, Any]]:
        return list(self.client.iter_securities(engine, market, board))

    def get_candles(
        self,
        engine: str,
        market: str,
        secid: str,
        board: Optional[str],
        from_date: date,
        till_date: date,
        interval: int,
    ) -> list[dict[str, Any]]:
        return self.client.get_candles(engine, market, secid, board, from_date, till_date, interval)
