from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Optional
from urllib.parse import urljoin

import requests


class MoexIssClient:
    def __init__(self, base_url: str, timeout_sec: int = 20) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_sec = timeout_sec
        self.session = requests.Session()

    def _request(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        clean_path = path.lstrip("/")
        base = self.base_url.rstrip("/")
        if base.endswith("/iss") and clean_path.startswith("iss/"):
            clean_path = clean_path[len("iss/") :]
        url = urljoin(base + "/", clean_path)
        response = self.session.get(url, params=params, timeout=self.timeout_sec)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _parse_table(payload: dict[str, Any], table: str) -> list[dict[str, Any]]:
        data = payload.get(table, {})
        columns = data.get("columns", [])
        rows = data.get("data", [])
        return [dict(zip(columns, row)) for row in rows]

    @staticmethod
    def _parse_cursor_total(payload: dict[str, Any], table: str) -> Optional[int]:
        data = payload.get(table, {})
        columns = [str(col).lower() for col in data.get("columns", [])]
        rows = data.get("data", [])
        if not rows:
            return None
        first = {col: value for col, value in zip(columns, rows[0])}
        total = first.get("total")
        if total is None:
            return None
        try:
            return int(total)
        except (TypeError, ValueError):
            return None

    def get_securities(
        self,
        engine: str,
        market: str,
        board: Optional[str] = None,
        limit: int = 100,
        start: int = 0,
    ) -> list[dict[str, Any]]:
        rows, _ = self.get_securities_page(engine, market, board=board, limit=limit, start=start)
        return rows

    def get_securities_page(
        self,
        engine: str,
        market: str,
        board: Optional[str] = None,
        limit: int = 100,
        start: int = 0,
    ) -> tuple[list[dict[str, Any]], Optional[int]]:
        path = f"/iss/engines/{engine}/markets/{market}/securities.json"
        if board:
            path = f"/iss/engines/{engine}/markets/{market}/boards/{board}/securities.json"
        params = {"start": start, "limit": limit}
        payload = self._request(path, params=params)
        rows = self._parse_table(payload, "securities")
        total = self._parse_cursor_total(payload, "securities.cursor")
        return rows, total

    def iter_securities(
        self, engine: str, market: str, board: Optional[str] = None, batch: int = 100
    ) -> Iterable[dict[str, Any]]:
        start = 0
        total: Optional[int] = None
        prev_first: Optional[str] = None
        while True:
            chunk, total = self.get_securities_page(
                engine, market, board=board, limit=batch, start=start
            )
            if not chunk:
                break
            if start == 0 and len(chunk) > batch:
                for item in chunk:
                    yield item
                break
            current_first = str(chunk[0].get("SECID") or "")
            if prev_first is not None and current_first == prev_first:
                break
            for item in chunk:
                yield item
            prev_first = current_first
            start += batch
            if total is not None and start >= total:
                break
            if total is None and len(chunk) < batch:
                break

    def get_marketdata(
        self, engine: str, market: str, board: str, secid: str
    ) -> list[dict[str, Any]]:
        path = f"/iss/engines/{engine}/markets/{market}/boards/{board}/securities/{secid}.json"
        payload = self._request(path, params={"iss.only": "marketdata"})
        return self._parse_table(payload, "marketdata")

    def get_candles(
        self,
        engine: str,
        market: str,
        secid: str,
        board: Optional[str],
        from_date: date,
        till_date: date,
        interval: int = 24,
    ) -> list[dict[str, Any]]:
        if board:
            path = f"/iss/engines/{engine}/markets/{market}/boards/{board}/securities/{secid}/candles.json"
        else:
            path = f"/iss/engines/{engine}/markets/{market}/securities/{secid}/candles.json"
        params = {
            "from": from_date.isoformat(),
            "till": till_date.isoformat(),
            "interval": interval,
        }
        payload = self._request(path, params=params)
        return self._parse_table(payload, "candles")

    def get_dividends(self, secid: str) -> list[dict[str, Any]]:
        path = f"/iss/securities/{secid}/dividends.json"
        payload = self._request(path)
        return self._parse_table(payload, "dividends")

    def get_futures_specs(self, board: Optional[str] = None) -> list[dict[str, Any]]:
        path = "/iss/engines/futures/markets/forts/securities.json"
        if board:
            path = f"/iss/engines/futures/markets/forts/boards/{board}/securities.json"
        payload = self._request(path)
        return self._parse_table(payload, "securities")
