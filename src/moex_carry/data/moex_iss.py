from __future__ import annotations

from datetime import date
import time
from typing import Any, Iterable, Optional
from urllib.parse import urljoin, urlparse
import threading

import requests
from requests.adapters import HTTPAdapter


RETRYABLE_HTTP_STATUSES: set[int] = {408, 425, 429, 500, 502, 503, 504}
TRANSPORT_EXCEPTIONS = (
    requests.exceptions.SSLError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


class _HostHeaderSSLAdapter(HTTPAdapter):
    """HTTPS adapter for requests to fallback IPs with host-based TLS validation."""

    def __init__(self, hostname: str, *args, **kwargs) -> None:
        self.hostname = hostname
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["assert_hostname"] = self.hostname
        pool_kwargs["server_hostname"] = self.hostname
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


class MoexIssClient:
    _host_failover_until: dict[str, float] = {}
    _host_failover_lock = threading.Lock()

    def __init__(
        self,
        base_url: str,
        timeout_sec: int = 20,
        *,
        max_retries: int = 3,
        retry_backoff_sec: float = 0.5,
        retry_max_backoff_sec: float = 4.0,
        fallback_ips: Optional[list[str]] = None,
        fallback_failover_ttl_sec: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_sec = timeout_sec
        self.session = requests.Session()
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_sec = max(0.0, float(retry_backoff_sec))
        self.retry_max_backoff_sec = max(0.0, float(retry_max_backoff_sec))
        self.fallback_failover_ttl_sec = max(1.0, float(fallback_failover_ttl_sec))

        parsed = urlparse(self.base_url)
        self._base_scheme = parsed.scheme or "https"
        self._base_host = parsed.hostname or ""
        self._fallback_sessions: dict[str, requests.Session] = {}

        raw_fallbacks = fallback_ips or []
        dedup: list[str] = []
        seen: set[str] = set()
        for ip in raw_fallbacks:
            text = str(ip).strip()
            if not text:
                continue
            if text == self._base_host:
                continue
            if text in seen:
                continue
            seen.add(text)
            dedup.append(text)
        self.fallback_ips = dedup

    def _is_primary_in_failover(self) -> bool:
        if not self._base_host or not self.fallback_ips:
            return False
        now = time.monotonic()
        with self._host_failover_lock:
            until = self._host_failover_until.get(self._base_host, 0.0)
        return now < until

    def _mark_primary_failed(self) -> None:
        if not self._base_host or not self.fallback_ips:
            return
        until = time.monotonic() + self.fallback_failover_ttl_sec
        with self._host_failover_lock:
            self._host_failover_until[self._base_host] = until

    def _clear_primary_failover(self) -> None:
        if not self._base_host:
            return
        with self._host_failover_lock:
            self._host_failover_until.pop(self._base_host, None)

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_backoff_sec <= 0:
            return
        wait = self.retry_backoff_sec * (2 ** max(0, attempt - 1))
        if self.retry_max_backoff_sec > 0:
            wait = min(wait, self.retry_max_backoff_sec)
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _is_retryable_http_error(exc: requests.HTTPError) -> bool:
        response = exc.response
        if response is None:
            return False
        return int(response.status_code) in RETRYABLE_HTTP_STATUSES

    @staticmethod
    def _is_transport_error(exc: BaseException) -> bool:
        return isinstance(exc, TRANSPORT_EXCEPTIONS)

    def _normalize_path(self, path: str) -> str:
        clean_path = path.lstrip("/")
        base = self.base_url.rstrip("/")
        if base.endswith("/iss") and clean_path.startswith("iss/"):
            clean_path = clean_path[len("iss/") :]
        return clean_path

    def _request_with_retries(
        self,
        session: requests.Session,
        url: str,
        params: Optional[dict[str, Any]],
        *,
        headers: Optional[dict[str, str]] = None,
        max_retries_override: Optional[int] = None,
    ) -> dict[str, Any]:
        retries = self.max_retries if max_retries_override is None else max(0, int(max_retries_override))
        attempts = retries + 1
        for attempt in range(1, attempts + 1):
            try:
                request_kwargs: dict[str, Any] = {"params": params, "timeout": self.timeout_sec}
                if headers:
                    request_kwargs["headers"] = headers
                response = session.get(url, **request_kwargs)
                if int(response.status_code) in RETRYABLE_HTTP_STATUSES:
                    raise requests.HTTPError(
                        f"retryable HTTP status {response.status_code} for {url}",
                        response=response,
                    )
                response.raise_for_status()
                return response.json()
            except TRANSPORT_EXCEPTIONS:
                if attempt >= attempts:
                    raise
                self._sleep_before_retry(attempt)
            except requests.HTTPError as exc:
                if attempt >= attempts or not self._is_retryable_http_error(exc):
                    raise
                self._sleep_before_retry(attempt)

        raise RuntimeError("request retry loop ended unexpectedly")

    def _get_fallback_session(self, ip: str) -> requests.Session:
        cached = self._fallback_sessions.get(ip)
        if cached is not None:
            return cached

        session = requests.Session()
        if self._base_scheme.lower() == "https" and self._base_host:
            session.mount("https://", _HostHeaderSSLAdapter(self._base_host))
        self._fallback_sessions[ip] = session
        return session

    def _request_via_fallback_ips(
        self,
        clean_path: str,
        params: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        if not self.fallback_ips:
            raise RuntimeError("fallback request called without configured fallback IPs")
        if not self._base_host:
            raise RuntimeError("fallback request called without base host")

        last_exc: BaseException | None = None
        for ip in self.fallback_ips:
            fallback_base = f"{self._base_scheme}://{ip}"
            fallback_url = urljoin(fallback_base.rstrip("/") + "/", clean_path)
            fallback_headers = {"Host": self._base_host}
            fallback_session = self._get_fallback_session(ip)
            try:
                return self._request_with_retries(
                    fallback_session,
                    fallback_url,
                    params,
                    headers=fallback_headers,
                )
            except requests.HTTPError as exc:
                if not self._is_retryable_http_error(exc):
                    raise
                last_exc = exc
            except TRANSPORT_EXCEPTIONS as exc:
                last_exc = exc

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("fallback request retry loop ended unexpectedly")

    def _request(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        clean_path = self._normalize_path(path)
        base = self.base_url.rstrip("/")
        primary_url = urljoin(base + "/", clean_path)
        if self._is_primary_in_failover():
            return self._request_via_fallback_ips(clean_path, params)

        primary_retries = 0 if self.fallback_ips else None
        try:
            payload = self._request_with_retries(
                self.session,
                primary_url,
                params,
                max_retries_override=primary_retries,
            )
            self._clear_primary_failover()
            return payload
        except Exception as exc:
            if not self._is_transport_error(exc):
                raise
            if not self.fallback_ips or not self._base_host:
                raise
            self._mark_primary_failed()
            return self._request_via_fallback_ips(clean_path, params)

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
