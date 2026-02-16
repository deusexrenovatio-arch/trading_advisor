from datetime import date

import responses
import requests
import pytest

from moex_carry.data.moex_iss import MoexIssClient


@pytest.fixture(autouse=True)
def _reset_host_failover_state():
    MoexIssClient._host_failover_until.clear()
    yield
    MoexIssClient._host_failover_until.clear()


def test_parse_table():
    payload = {"securities": {"columns": ["SECID", "SHORTNAME"], "data": [["SBER", "Sberbank"]]}}
    client = MoexIssClient("https://iss.moex.com")
    parsed = client._parse_table(payload, "securities")
    assert parsed[0]["SECID"] == "SBER"


@responses.activate
def test_get_securities():
    payload = {"securities": {"columns": ["SECID"], "data": [["SBER"]]}}
    responses.add(
        responses.GET,
        "https://iss.moex.com/iss/engines/stock/markets/shares/securities.json",
        json=payload,
        status=200,
    )
    client = MoexIssClient("https://iss.moex.com")
    data = client.get_securities("stock", "shares")
    assert data[0]["SECID"] == "SBER"


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}", response=self)

    def json(self) -> dict:
        return self._payload


def test_request_retries_ssl_eof_and_then_succeeds(monkeypatch):
    client = MoexIssClient("https://iss.moex.com", max_retries=2, retry_backoff_sec=0.0)
    calls = {"count": 0}

    def _fake_get(_url, params=None, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")
        return _FakeResponse(
            200,
            {"marketdata": {"columns": ["SECID"], "data": [["SBER"]]}},
        )

    monkeypatch.setattr(client.session, "get", _fake_get)

    rows = client.get_marketdata("stock", "shares", "TQBR", "SBER")
    assert calls["count"] == 2
    assert rows[0]["SECID"] == "SBER"


def test_request_retries_on_503_then_succeeds(monkeypatch):
    client = MoexIssClient("https://iss.moex.com", max_retries=2, retry_backoff_sec=0.0)
    calls = {"count": 0}

    def _fake_get(_url, params=None, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return _FakeResponse(503, {"error": "temporary"})
        return _FakeResponse(200, {"securities": {"columns": ["SECID"], "data": [["GAZP"]]}})

    monkeypatch.setattr(client.session, "get", _fake_get)

    rows = client.get_securities("stock", "shares")
    assert calls["count"] == 2
    assert rows[0]["SECID"] == "GAZP"


def test_request_does_not_retry_on_404(monkeypatch):
    client = MoexIssClient("https://iss.moex.com", max_retries=3, retry_backoff_sec=0.0)
    calls = {"count": 0}

    def _fake_get(_url, params=None, timeout=None):
        calls["count"] += 1
        return _FakeResponse(404, {"error": "not found"})

    monkeypatch.setattr(client.session, "get", _fake_get)

    with pytest.raises(requests.HTTPError):
        client.get_securities("stock", "shares")
    assert calls["count"] == 1


def test_request_falls_back_to_ip_on_primary_transport_error(monkeypatch):
    MoexIssClient._host_failover_until.clear()
    client = MoexIssClient(
        "https://iss.moex.com",
        max_retries=3,
        retry_backoff_sec=0.0,
        fallback_ips=["85.118.181.8"],
    )
    calls: list[tuple[str, str]] = []

    def _primary_get(_url, params=None, timeout=None):
        calls.append(("primary", _url))
        raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")

    class _FallbackSession:
        def get(self, _url, params=None, timeout=None, headers=None):
            calls.append(("fallback", _url))
            assert headers == {"Host": "iss.moex.com"}
            return _FakeResponse(
                200,
                {"marketdata": {"columns": ["SECID"], "data": [["SBER"]]}}
            )

    monkeypatch.setattr(client.session, "get", _primary_get)
    monkeypatch.setattr(client, "_get_fallback_session", lambda _ip: _FallbackSession())

    rows = client.get_marketdata("stock", "shares", "TQBR", "SBER")
    assert rows[0]["SECID"] == "SBER"
    primary_calls = [kind for kind, _url in calls if kind == "primary"]
    assert len(primary_calls) == 1
    assert calls[0][0] == "primary"
    assert calls[1][0] == "fallback"
    assert calls[1][1].startswith("https://85.118.181.8/")


def test_request_does_not_use_fallback_on_non_retryable_http(monkeypatch):
    MoexIssClient._host_failover_until.clear()
    client = MoexIssClient(
        "https://iss.moex.com",
        max_retries=0,
        retry_backoff_sec=0.0,
        fallback_ips=["85.118.181.8"],
    )

    def _primary_get(_url, params=None, timeout=None):
        return _FakeResponse(404, {"error": "not found"})

    monkeypatch.setattr(client.session, "get", _primary_get)
    monkeypatch.setattr(
        client,
        "_get_fallback_session",
        lambda _ip: (_ for _ in ()).throw(AssertionError("fallback must not be used for 404")),
    )

    with pytest.raises(requests.HTTPError):
        client.get_securities("stock", "shares")


def test_request_uses_fallback_on_retryable_http(monkeypatch):
    MoexIssClient._host_failover_until.clear()
    client = MoexIssClient(
        "https://iss.moex.com",
        max_retries=0,
        retry_backoff_sec=0.0,
        fallback_ips=["85.118.181.8"],
    )
    calls: list[str] = []

    def _primary_get(_url, params=None, timeout=None):
        calls.append("primary")
        return _FakeResponse(503, {"error": "temporary"})

    class _FallbackSession:
        def get(self, _url, params=None, timeout=None, headers=None):
            calls.append("fallback")
            return _FakeResponse(
                200,
                {"marketdata": {"columns": ["SECID"], "data": [["SBER"]]}},
            )

    monkeypatch.setattr(client.session, "get", _primary_get)
    monkeypatch.setattr(client, "_get_fallback_session", lambda _ip: _FallbackSession())

    rows = client.get_marketdata("stock", "shares", "TQBR", "SBER")
    assert rows[0]["SECID"] == "SBER"
    assert calls == ["primary", "fallback"]


def test_force_fallback_skips_primary(monkeypatch):
    MoexIssClient._host_failover_until.clear()
    client = MoexIssClient(
        "https://iss.moex.com",
        max_retries=0,
        retry_backoff_sec=0.0,
        fallback_ips=["85.118.181.8"],
        force_fallback=True,
    )
    calls: list[str] = []

    def _must_not_call_primary(_url, params=None, timeout=None):
        raise AssertionError("primary must be skipped in force_fallback mode")

    class _FallbackSession:
        def get(self, _url, params=None, timeout=None, headers=None):
            calls.append("fallback")
            return _FakeResponse(
                200,
                {"marketdata": {"columns": ["SECID"], "data": [["SBER"]]}},
            )

    monkeypatch.setattr(client.session, "get", _must_not_call_primary)
    monkeypatch.setattr(client, "_get_fallback_session", lambda _ip: _FallbackSession())

    rows = client.get_marketdata("stock", "shares", "TQBR", "SBER")
    assert rows[0]["SECID"] == "SBER"
    assert calls == ["fallback"]


def test_primary_failover_state_is_reused_across_clients(monkeypatch):
    MoexIssClient._host_failover_until.clear()
    first = MoexIssClient(
        "https://iss.moex.com",
        max_retries=0,
        retry_backoff_sec=0.0,
        fallback_ips=["85.118.181.8"],
        fallback_failover_ttl_sec=60.0,
    )
    calls: list[str] = []

    def _first_primary(_url, params=None, timeout=None):
        calls.append("first_primary")
        raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")

    class _FallbackSession:
        def get(self, _url, params=None, timeout=None, headers=None):
            calls.append("fallback")
            return _FakeResponse(
                200,
                {"marketdata": {"columns": ["SECID"], "data": [["SBER"]]}}
            )

    monkeypatch.setattr(first.session, "get", _first_primary)
    monkeypatch.setattr(first, "_get_fallback_session", lambda _ip: _FallbackSession())

    rows_first = first.get_marketdata("stock", "shares", "TQBR", "SBER")
    assert rows_first[0]["SECID"] == "SBER"

    second = MoexIssClient(
        "https://iss.moex.com",
        max_retries=0,
        retry_backoff_sec=0.0,
        fallback_ips=["85.118.181.8"],
        fallback_failover_ttl_sec=60.0,
    )

    def _must_not_call_primary(_url, params=None, timeout=None):
        raise AssertionError("primary must be skipped while failover TTL is active")

    monkeypatch.setattr(second.session, "get", _must_not_call_primary)
    monkeypatch.setattr(second, "_get_fallback_session", lambda _ip: _FallbackSession())

    rows_second = second.get_marketdata("stock", "shares", "TQBR", "SBER")
    assert rows_second[0]["SECID"] == "SBER"
    assert calls.count("first_primary") == 1
    assert calls.count("fallback") >= 2


def test_get_candles_paginates_using_cursor_total(monkeypatch):
    client = MoexIssClient("https://iss.moex.com")
    calls: list[dict[str, object]] = []
    payloads = [
        {
            "candles": {
                "columns": ["begin", "close"],
                "data": [
                    ["2026-01-01 10:00:00", 100.0],
                    ["2026-01-01 10:01:00", 101.0],
                ],
            },
            "candles.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[0, 3, 2]]},
        },
        {
            "candles": {
                "columns": ["begin", "close"],
                "data": [["2026-01-01 10:02:00", 102.0]],
            },
            "candles.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[2, 3, 2]]},
        },
    ]

    def _fake_request(_path: str, params=None):
        calls.append(dict(params or {}))
        return payloads[len(calls) - 1]

    monkeypatch.setattr(client, "_request", _fake_request)
    rows = client.get_candles("stock", "shares", "SBER", "TQBR", date(2026, 1, 1), date(2026, 1, 1), interval=1)
    assert len(rows) == 3
    assert [int(call.get("start", 0)) for call in calls] == [0, 2]


def test_get_candles_uses_start_pagination_without_cursor(monkeypatch):
    client = MoexIssClient("https://iss.moex.com")
    calls: list[dict[str, object]] = []
    full_page = [[f"b{i}", float(i)] for i in range(500)]
    payloads = [
        {"candles": {"columns": ["begin", "close"], "data": full_page}},
        {"candles": {"columns": ["begin", "close"], "data": [["tail", 999.0]]}},
    ]

    def _fake_request(_path: str, params=None):
        calls.append(dict(params or {}))
        return payloads[len(calls) - 1]

    monkeypatch.setattr(client, "_request", _fake_request)
    rows = client.get_candles("stock", "shares", "SBER", "TQBR", date(2026, 1, 1), date(2026, 1, 1), interval=1)
    assert len(rows) == 501
    assert [int(call.get("start", 0)) for call in calls] == [0, 500]


def test_get_candles_stops_on_repeated_page_signature(monkeypatch):
    client = MoexIssClient("https://iss.moex.com")
    calls: list[dict[str, object]] = []
    repeating_payload = {
        "candles": {
            "columns": ["begin", "close"],
            "data": [[f"b{i}", float(i)] for i in range(500)],
        }
    }

    def _fake_request(_path: str, params=None):
        calls.append(dict(params or {}))
        if len(calls) > 2:
            raise AssertionError("pagination loop should stop after repeated page")
        return repeating_payload

    monkeypatch.setattr(client, "_request", _fake_request)
    rows = client.get_candles("stock", "shares", "SBER", "TQBR", date(2026, 1, 1), date(2026, 1, 1), interval=1)
    assert len(rows) == 500
    assert len(calls) == 2
