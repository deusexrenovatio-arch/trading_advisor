from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
import requests

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig, TelegramConfig
from moex_carry.integrations.telegram_worker import TelegramWorker, run_telegram_worker
from moex_carry.news_root_maintenance import RootMaintenanceConfig, refresh_root_maintenance
from moex_carry.news_shock_store import upsert_live_shock_rows
from moex_carry.signals_ack import parse_ack_note


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status:{self.status_code}")

    def json(self):
        return self._payload


class _FakeTelegramSession:
    def __init__(
        self,
        updates_batches: list[list[dict[str, object]]] | None = None,
        *,
        get_updates_failures: int = 0,
    ):
        self._updates_batches = list(updates_batches or [])
        self._get_updates_failures = max(int(get_updates_failures), 0)
        self.sent_messages: list[dict[str, object]] = []
        self.answered_callbacks: list[dict[str, object]] = []
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, json: dict[str, object], timeout: int) -> _FakeResponse:
        method = url.rstrip("/").rsplit("/", 1)[-1]
        self.calls.append((method, json))
        if method == "getUpdates":
            if self._get_updates_failures > 0:
                self._get_updates_failures -= 1
                raise requests.ConnectionError("telegram-connection-dropped")
            batch = self._updates_batches.pop(0) if self._updates_batches else []
            return _FakeResponse({"ok": True, "result": batch})
        if method == "sendMessage":
            self.sent_messages.append(json)
            return _FakeResponse({"ok": True, "result": {"message_id": 1}})
        if method == "answerCallbackQuery":
            self.answered_callbacks.append(json)
            return _FakeResponse({"ok": True, "result": True})
        raise AssertionError(f"unexpected telegram method: {method}")


class _FakeBackendSession:
    def __init__(
        self,
        active_batches: list[list[dict[str, object]]] | None = None,
        post_responses: list[tuple[int, dict[str, object]]] | None = None,
    ):
        self._active_batches = list(active_batches or [[]])
        self._active_index = 0
        self._post_responses = list(post_responses or [])
        self.execute_payloads: list[dict[str, object]] = []
        self.post_calls: list[tuple[str, dict[str, object]]] = []
        self.get_calls: list[str] = []

    def get(self, url: str, timeout: int) -> _FakeResponse:
        self.get_calls.append(url)
        if self._active_index < len(self._active_batches):
            payload = self._active_batches[self._active_index]
        else:
            payload = []
        self._active_index += 1
        return _FakeResponse(payload)

    def post(self, url: str, json: dict[str, object], timeout: int) -> _FakeResponse:
        self.post_calls.append((url, json))
        self.execute_payloads.append(json)
        if self._post_responses:
            status_code, payload = self._post_responses.pop(0)
            return _FakeResponse(payload, status_code=status_code)
        return _FakeResponse({"status": "ok"})


class _FailingBackendSession(_FakeBackendSession):
    def get(self, url: str, timeout: int) -> _FakeResponse:
        raise requests.ConnectionError("backend-down")


def _build_settings(
    tmp_path,
    *,
    telegram_enabled: bool = True,
    bot_token: str | None = "test-token",
    allowed_user_ids: list[int] | None = None,
    callback_ttl_hours: int = 72,
    enter_resend_cooldown_minutes: int = 60,
    daily_healthcheck_enabled: bool = True,
    daily_healthcheck_time_local: str = "00:00",
    root_alerts_enabled: bool = False,
    root_min_primary_count: int = 1,
    root_max_alerts_per_cycle: int = 20,
    root_sent_fingerprint_ttl_hours: int = 24 * 21,
    shock_alerts_enabled: bool = False,
    shock_feed_path: str | None = None,
    shock_primary_min_z: float = 2.5,
    shock_aftershock_min_z: float = 2.0,
    shock_topic_reopen_after_hours: int = 168,
    shock_aftershock_cooldown_minutes: int = 60,
    shock_max_alerts_per_cycle: int = 20,
    shock_sent_fingerprint_ttl_hours: int = 24 * 21,
    news_alerts_enabled: bool = False,
    news_feed_path: str | None = None,
    news_min_impact_score: float = 0.35,
    news_min_confidence: float = 0.9,
    news_max_alerts_per_cycle: int = 20,
    news_sent_fingerprint_ttl_hours: int = 24 * 21,
) -> AppSettings:
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/telegram-worker.db"),
        telegram=TelegramConfig(
            enabled=telegram_enabled,
            bot_token=bot_token,
            backend_base_url="http://backend.local",
            allowed_user_ids=allowed_user_ids if allowed_user_ids is not None else [111],
            poll_timeout_sec=0,
            signal_fetch_interval_sec=1,
            hold_open_daily_limit=1,
            enter_resend_cooldown_minutes=enter_resend_cooldown_minutes,
            callback_ttl_hours=callback_ttl_hours,
            daily_healthcheck_enabled=daily_healthcheck_enabled,
            daily_healthcheck_time_local=daily_healthcheck_time_local,
            state_path=str(tmp_path / "telegram-state.json"),
            ui_base_url=None,
            root_alerts_enabled=root_alerts_enabled,
            root_min_primary_count=root_min_primary_count,
            root_max_alerts_per_cycle=root_max_alerts_per_cycle,
            root_sent_fingerprint_ttl_hours=root_sent_fingerprint_ttl_hours,
            shock_alerts_enabled=shock_alerts_enabled,
            shock_feed_path=shock_feed_path,
            shock_primary_min_z=shock_primary_min_z,
            shock_aftershock_min_z=shock_aftershock_min_z,
            shock_topic_reopen_after_hours=shock_topic_reopen_after_hours,
            shock_aftershock_cooldown_minutes=shock_aftershock_cooldown_minutes,
            shock_max_alerts_per_cycle=shock_max_alerts_per_cycle,
            shock_sent_fingerprint_ttl_hours=shock_sent_fingerprint_ttl_hours,
            news_alerts_enabled=news_alerts_enabled,
            news_feed_path=news_feed_path,
            news_min_impact_score=news_min_impact_score,
            news_min_confidence=news_min_confidence,
            news_max_alerts_per_cycle=news_max_alerts_per_cycle,
            news_sent_fingerprint_ttl_hours=news_sent_fingerprint_ttl_hours,
        ),
    )


def test_run_telegram_worker_fails_fast_on_missing_required_config(tmp_path):
    missing_token = _build_settings(tmp_path, bot_token=None)
    with pytest.raises(ValueError, match="bot_token"):
        run_telegram_worker(missing_token)

    missing_whitelist = _build_settings(tmp_path, allowed_user_ids=[])
    with pytest.raises(ValueError, match="allowed_user_ids"):
        run_telegram_worker(missing_whitelist)


def test_worker_registers_only_whitelisted_users(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111])
    telegram_session = _FakeTelegramSession(
        updates_batches=[
            [
                {
                    "update_id": 1,
                    "message": {
                        "text": "/start",
                        "from": {"id": 222},
                        "chat": {"id": 222},
                    },
                },
                {
                    "update_id": 2,
                    "message": {
                        "text": "/start",
                        "from": {"id": 111},
                        "chat": {"id": 111},
                    },
                },
            ]
        ]
    )
    backend_session = _FakeBackendSession()
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )

    worker._process_updates()

    assert worker._state["registered_chats"] == {"111": 111}
    assert worker._state["last_update_id"] == 2
    assert [payload["chat_id"] for payload in telegram_session.sent_messages] == [222, 111]


def test_worker_retries_get_updates_after_connection_drop(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111])
    telegram_session = _FakeTelegramSession(
        updates_batches=[
            [
                {
                    "update_id": 1,
                    "message": {
                        "text": "/start",
                        "from": {"id": 111},
                        "chat": {"id": 111},
                    },
                }
            ]
        ],
        get_updates_failures=1,
    )
    backend_session = _FakeBackendSession()
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
        sleep_fn=lambda _seconds: None,
    )

    worker._process_updates()

    get_updates_calls = [method for method, _payload in telegram_session.calls if method == "getUpdates"]
    assert len(get_updates_calls) == 2
    assert worker._state["last_update_id"] == 1
    assert worker._state["registered_chats"] == {"111": 111}


def test_worker_fetch_updates_returns_empty_after_repeated_connection_drop(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111])
    telegram_session = _FakeTelegramSession(get_updates_failures=2)
    backend_session = _FakeBackendSession()
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
        sleep_fn=lambda _seconds: None,
    )

    worker._process_updates()

    get_updates_calls = [method for method, _payload in telegram_session.calls if method == "getUpdates"]
    assert len(get_updates_calls) == 2
    assert worker._state["last_update_id"] == 0
    assert worker._state["registered_chats"] == {}


def test_worker_deduplicates_messages_and_limits_hold_open_per_day(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111])
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    now_iso_next = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    rows_cycle_1 = [
        {
            "run_id": "run-1",
            "timestamp": now_iso,
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.2,
        },
        {
            "run_id": "run-1",
            "timestamp": now_iso,
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.2,
        },
        {
            "run_id": "run-1",
            "timestamp": now_iso,
            "stock": "BBB",
            "future": "BBH6",
            "signal_action": "hold_open",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.1,
        },
    ]
    rows_cycle_2 = [
        {
            "run_id": "run-2",
            "timestamp": now_iso_next,
            "stock": "BBB",
            "future": "BBH6",
            "signal_action": "hold_open",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.1,
        }
    ]
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[rows_cycle_1, rows_cycle_2])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker._broadcast_signals()
    worker._broadcast_signals()

    assert len(telegram_session.sent_messages) == 2
    callbacks = worker._state["pending_callbacks"]
    assert isinstance(callbacks, dict)
    assert len(callbacks) == 2
    sent = worker._state["sent_fingerprints"]
    assert isinstance(sent, dict)
    assert len(sent) == 2
    hold_open_last = worker._state["hold_open_last_sent_date_by_pair"]
    assert isinstance(hold_open_last, dict)
    assert any(str(key).startswith("BBB|BBH6|") for key in hold_open_last)


def test_worker_skips_enter_signal_when_already_used(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111])
    rows = [
        {
            "run_id": "run-used-enter",
            "timestamp": "2025-01-01T10:00:00Z",
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.2,
            "signal_used": True,
        },
        {
            "run_id": "run-used-enter",
            "timestamp": "2025-01-01T10:00:00Z",
            "stock": "BBB",
            "future": "BBH6",
            "signal_action": "exit",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.1,
        },
    ]
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[rows])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker._broadcast_signals()

    assert len(telegram_session.sent_messages) == 1
    assert "BBB/BBH6" in str(telegram_session.sent_messages[0]["text"])


def test_worker_skips_expired_enter_signal(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111], callback_ttl_hours=1)
    rows = [
        {
            "run_id": "run-expired",
            "timestamp": (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.2,
        }
    ]
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[rows])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker._broadcast_signals()

    assert telegram_session.sent_messages == []


def test_worker_respects_entry_ranges_for_both_legs(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111], callback_ttl_hours=24)
    rows = [
        {
            "run_id": "run-ranges",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.2,
            "spot_mid": 100.0,
            "future_mid": 101.0,
            "entry_stock_min": 90.0,
            "entry_stock_max": 95.0,
            "entry_future_min_per_share": 100.0,
            "entry_future_max_per_share": 102.0,
        },
        {
            "run_id": "run-ranges",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "stock": "BBB",
            "future": "BBH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.2,
            "spot_mid": 92.0,
            "future_mid": 101.0,
            "entry_stock_min": 90.0,
            "entry_stock_max": 95.0,
            "entry_future_min_per_share": 100.0,
            "entry_future_max_per_share": 102.0,
        },
    ]
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[rows])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker._broadcast_signals()

    assert len(telegram_session.sent_messages) == 1
    assert "BBB/BBH6" in str(telegram_session.sent_messages[0]["text"])


def test_worker_uses_signal_fingerprint_from_api_for_enter_dedup(tmp_path):
    settings = _build_settings(
        tmp_path,
        allowed_user_ids=[111],
        enter_resend_cooldown_minutes=0,
    )
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    later_iso = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    rows_cycle_1 = [
        {
            "run_id": "run-1",
            "timestamp": now_iso,
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.2,
            "signal_fingerprint": "fp-enter-stable-1",
            "spot_mid": 100.0,
            "future_mid": 101.0,
            "entry_stock_min": 99.0,
            "entry_stock_max": 101.0,
        }
    ]
    rows_cycle_2 = [
        {
            "run_id": "run-2",
            "timestamp": later_iso,
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.21,
            "signal_fingerprint": "fp-enter-stable-1",
            "spot_mid": 100.2,
            "future_mid": 101.1,
            "entry_stock_min": 99.0,
            "entry_stock_max": 101.0,
        }
    ]
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[rows_cycle_1, rows_cycle_2])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker._broadcast_signals()
    worker._broadcast_signals()

    assert len(telegram_session.sent_messages) == 1
    callbacks = worker._state["pending_callbacks"]
    assert isinstance(callbacks, dict)
    callback_values = list(callbacks.values())
    assert len(callback_values) == 1
    assert callback_values[0]["fingerprint"] == "fp-enter-stable-1"


def test_worker_notifies_once_when_sent_enter_goes_out_of_range(tmp_path):
    settings = _build_settings(
        tmp_path,
        allowed_user_ids=[111],
        enter_resend_cooldown_minutes=0,
    )
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows_in_range = [
        {
            "run_id": "run-1",
            "timestamp": now_iso,
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.2,
            "signal_fingerprint": "fp-enter-range-1",
            "spot_mid": 100.0,
            "future_mid": 101.0,
            "spread_mid": 1.0,
            "spread_pct": 0.01,
            "entry_stock_min": 99.0,
            "entry_stock_max": 101.0,
            "entry_future_min_per_share": 100.0,
            "entry_future_max_per_share": 102.0,
            "entry_spread_min": 0.5,
            "entry_spread_max": 1.5,
            "entry_spread_pct_min": 0.005,
            "entry_spread_pct_max": 0.015,
        }
    ]
    rows_out_of_range = [
        {
            "run_id": "run-2",
            "timestamp": now_iso,
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.25,
            "signal_fingerprint": "fp-enter-range-1",
            "spot_mid": 105.0,
            "future_mid": 101.0,
            "spread_mid": 4.0,
            "spread_pct": 0.04,
            "entry_stock_min": 104.0,
            "entry_stock_max": 106.0,
        }
    ]
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(
        active_batches=[rows_in_range, rows_out_of_range, rows_out_of_range]
    )
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker._broadcast_signals()
    worker._broadcast_signals()
    worker._broadcast_signals()

    assert len(telegram_session.sent_messages) == 2
    first_text = str(telegram_session.sent_messages[0]["text"])
    second_text = str(telegram_session.sent_messages[1]["text"])
    assert "Новый сигнал" in first_text
    assert "вышла за диапазон" in second_text


def test_worker_throttles_new_enter_fingerprints_per_pair(tmp_path):
    settings = _build_settings(
        tmp_path,
        allowed_user_ids=[111],
        enter_resend_cooldown_minutes=120,
    )
    now = datetime.now(timezone.utc)
    rows_cycle_1 = [
        {
            "run_id": "run-1",
            "timestamp": now.isoformat().replace("+00:00", "Z"),
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.2,
            "signal_fingerprint": "fp-enter-cooldown-1",
            "spot_mid": 100.0,
            "entry_stock_min": 99.0,
            "entry_stock_max": 101.0,
        }
    ]
    rows_cycle_2 = [
        {
            "run_id": "run-2",
            "timestamp": (now + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.3,
            "signal_fingerprint": "fp-enter-cooldown-2",
            "spot_mid": 100.1,
            "entry_stock_min": 99.0,
            "entry_stock_max": 101.5,
        }
    ]
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[rows_cycle_1, rows_cycle_2])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker._broadcast_signals()
    worker._broadcast_signals()

    assert len(telegram_session.sent_messages) == 1


def test_worker_separates_enter_cooldown_by_strategy_stream(tmp_path):
    settings = _build_settings(
        tmp_path,
        allowed_user_ids=[111],
        enter_resend_cooldown_minutes=120,
    )
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows = [
        {
            "run_id": "run-strategy-split",
            "timestamp": now,
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.2,
            "strategy_type": "arbitrage",
            "strategy_stream": "arbitrage",
            "spot_mid": 100.0,
            "entry_stock_min": 99.0,
            "entry_stock_max": 101.0,
        },
        {
            "run_id": "run-strategy-split",
            "timestamp": now,
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.31,
            "strategy_type": "speculative",
            "strategy_stream": "commodity_futures",
            "spot_mid": 100.2,
            "entry_stock_min": 99.0,
            "entry_stock_max": 101.5,
        },
    ]
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[rows])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker._broadcast_signals()

    assert len(telegram_session.sent_messages) == 2
    enter_last_sent = worker._state["enter_last_sent_at_by_pair"]
    assert isinstance(enter_last_sent, dict)
    assert "AAA|AAH6|arbitrage" in enter_last_sent
    assert "AAA|AAH6|commodity_futures" in enter_last_sent


def test_worker_message_shows_staged_entry_exit_protocol(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111], callback_ttl_hours=24)
    rows = [
        {
            "run_id": "run-staged-msg",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.2,
            "signal_fingerprint": "fp-staged-msg-1",
            "spot_mid": 100.0,
            "future_mid": 101.0,
            "entry_stock_min": 99.0,
            "entry_stock_max": 101.0,
            "entry_future_min_per_share": 100.0,
            "entry_future_max_per_share": 102.0,
            "signal_metrics": {
                "entry_execution_protocol": "sequential",
                "sequential_entry_enabled": True,
                "sequential_entry_first_leg": "future",
                "sequential_entry_second_leg_max_wait_minutes": 5,
                "sequential_entry_unwind_penalty_bps": 2.0,
                "exit_execution_protocol": "sequential",
                "sequential_exit_enabled": True,
                "sequential_exit_first_leg": "stock",
                "sequential_exit_second_leg_max_wait_minutes": 7,
                "sequential_exit_force_penalty_bps": 3.5,
            },
        }
    ]
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[rows])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker._broadcast_signals()

    assert len(telegram_session.sent_messages) == 1
    text = str(telegram_session.sent_messages[0]["text"])
    assert "staged (" in text
    assert "unwind 1" in text
    assert "force-close" in text


def test_worker_prefers_pair_actionability_endpoint(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111], callback_ttl_hours=24)
    rows = [
        {
            "run_id": "run-v2-endpoint",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "exit",
            "signal_direction": "cash_and_carry",
            "signal_score": 0.2,
        }
    ]
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[rows])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker._broadcast_signals()

    assert backend_session.get_calls
    assert "/api/v2/pairs/actionability" in backend_session.get_calls[0]


def test_worker_callback_ack_happy_path(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111])
    token = "abc123"
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    telegram_session = _FakeTelegramSession(
        updates_batches=[
            [
                {
                    "update_id": 1,
                    "callback_query": {
                        "id": "cb-1",
                        "data": f"ack:{token}",
                        "from": {"id": 111, "username": "alice"},
                        "message": {"chat": {"id": 111}},
                    },
                }
            ]
        ]
    )
    backend_session = _FakeBackendSession()
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["pending_callbacks"] = {
        token: {
            "fingerprint": "fp123",
            "run_id": "run-1",
            "timestamp": "2025-01-01T10:00:00",
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "chat_id": 111,
            "created_at": now_iso,
        }
    }

    worker._process_updates()

    assert len(backend_session.execute_payloads) == 1
    payload = backend_session.execute_payloads[0]
    assert payload["action"] == "ack"
    assert payload["source"] == "telegram"
    assert str(payload.get("idempotency_key") or "").startswith("telegram-ack:")
    assert backend_session.post_calls
    assert backend_session.post_calls[0][0].endswith("/api/v2/entities/pair/AAA__AAH6/signals/actions")
    note_payload = parse_ack_note(payload["note"])
    assert note_payload is not None
    assert note_payload["fingerprint"] == "fp123"
    assert note_payload["telegram_user_id"] == 111
    assert note_payload["telegram_username"] == "alice"
    assert token not in worker._state["pending_callbacks"]
    assert len(telegram_session.answered_callbacks) == 1


def test_worker_callback_rejects_expired_token(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111], callback_ttl_hours=1)
    token = "expired1"
    expired_iso = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    telegram_session = _FakeTelegramSession(
        updates_batches=[
            [
                {
                    "update_id": 1,
                    "callback_query": {
                        "id": "cb-expired",
                        "data": f"ack:{token}",
                        "from": {"id": 111, "username": "alice"},
                        "message": {"chat": {"id": 111}},
                    },
                }
            ]
        ]
    )
    backend_session = _FakeBackendSession()
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["pending_callbacks"] = {
        token: {
            "fingerprint": "fp123",
            "run_id": "run-1",
            "timestamp": "2025-01-01T10:00:00",
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "chat_id": 111,
            "created_at": expired_iso,
        }
    }

    worker._process_updates()

    assert backend_session.execute_payloads == []
    assert token not in worker._state["pending_callbacks"]
    assert len(telegram_session.answered_callbacks) == 1


def test_worker_callback_marks_stale_intent_and_drops_token(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111])
    token = "stale-intent-1"
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    telegram_session = _FakeTelegramSession(
        updates_batches=[
            [
                {
                    "update_id": 1,
                    "callback_query": {
                        "id": "cb-stale",
                        "data": f"ack:{token}",
                        "from": {"id": 111, "username": "alice"},
                        "message": {"chat": {"id": 111}},
                    },
                }
            ]
        ]
    )
    backend_session = _FakeBackendSession(
        post_responses=[
            (
                409,
                {
                    "status": "blocked",
                    "message": "intent_superseded_or_stale",
                    "error": "intent_mismatch",
                },
            )
        ]
    )
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["pending_callbacks"] = {
        token: {
            "fingerprint": "fp-stale-1",
            "run_id": "run-1",
            "timestamp": "2025-01-01T10:00:00",
            "stock": "AAA",
            "future": "AAH6",
            "signal_action": "enter",
            "signal_direction": "cash_and_carry",
            "chat_id": 111,
            "created_at": now_iso,
            "pair_id": "AAA__AAH6",
            "intent_id": "intent-stale",
        }
    }

    worker._process_updates()

    assert token not in worker._state["pending_callbacks"]
    assert len(telegram_session.answered_callbacks) == 1
    answer_text = str(telegram_session.answered_callbacks[0]["text"])
    assert "устарел" in answer_text


def test_worker_daily_healthcheck_sent_once_per_day(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111], daily_healthcheck_time_local="00:00")
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(
        active_batches=[
            [
                {"stock": "AAA", "future": "AAH6"},
                {"stock": "BBB", "future": "BBH6"},
            ]
        ]
    )
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker._send_daily_healthcheck()
    worker._send_daily_healthcheck()

    assert len(telegram_session.sent_messages) == 1
    message_text = str(telegram_session.sent_messages[0]["text"])
    assert "Утренний health-check" in message_text
    assert "Backend: OK" in message_text
    assert "Активных сигналов: 2" in message_text
    sent_state = worker._state["daily_healthcheck_last_sent_date_by_chat"]
    assert isinstance(sent_state, dict)
    assert str(sent_state.get("111") or "").strip() != ""


def test_worker_daily_healthcheck_reports_backend_error(tmp_path):
    settings = _build_settings(tmp_path, allowed_user_ids=[111], daily_healthcheck_time_local="00:00")
    telegram_session = _FakeTelegramSession()
    backend_session = _FailingBackendSession()
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker._send_daily_healthcheck()

    assert len(telegram_session.sent_messages) == 1
    message_text = str(telegram_session.sent_messages[0]["text"])
    assert "Backend: ERROR" in message_text
    assert "проверить не удалось" in message_text


def test_worker_broadcasts_shock_primary_and_aftershock(tmp_path):
    shock_feed = tmp_path / "shocks.csv"
    shock_feed.write_text(
        "\n".join(
            [
                "shock_ts,symbol,shock_direction,z_score,abs_move_pct,headline,url,topic_key",
                "2026-02-28T07:00:00Z,BRN,up,3.20,2.10,Israel strikes Iran facilities,https://example.com/a,iran-attack",
                "2026-03-02T09:00:00Z,BRN,up,2.40,1.30,Oil extends gains amid Iran risk premium,https://example.com/b,iran-attack",
            ]
        ),
        encoding="utf-8",
    )
    settings = _build_settings(
        tmp_path,
        allowed_user_ids=[111],
        daily_healthcheck_enabled=False,
        shock_alerts_enabled=True,
        shock_feed_path=str(shock_feed),
        shock_aftershock_cooldown_minutes=0,
    )
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[[]])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker.run_cycle()
    worker.run_cycle()

    assert len(telegram_session.sent_messages) == 2
    text_1 = str(telegram_session.sent_messages[0]["text"])
    text_2 = str(telegram_session.sent_messages[1]["text"])
    assert "ПЕРВИЧНЫЙ ШОК" in text_1
    assert "ПОВТОРНЫЙ ШОК" in text_2
    assert "🧩 Тема: iran-attack" in text_1
    assert "⏳ Возраст темы: 2д" in text_2


def test_worker_broadcasts_root_event_once(tmp_path):
    frame = pd.DataFrame(
        [
            {
                "symbol": "BRN",
                "shock_ts": "2026-02-01T10:00:00Z",
                "bar_minutes": 5,
                "prev_price": 80.0,
                "price": 81.2,
                "logret": 0.0148,
                "abs_move_pct": 1.5,
                "shock_direction": "up",
                "rolling_sigma": 0.003,
                "z_score": 3.8,
                "selected_event_source": "root",
                "selected_event_id": "evt-1",
                "selected_event_ts": "2026-02-01T09:55:00Z",
                "selected_delay_min": 5.0,
                "selected_match_mode": "root_strict",
                "selected_title": "Shipping halted near Hormuz",
                "selected_url": "https://example.com/root-1",
                "selected_cause_event": "chokepoint_closure",
                "selected_cause_route_key": "chokepoint:hormuz->seaborne_crude->BRN",
                "selected_cause_claim_status": "confirmed",
                "selected_cause_classification": "cause",
                "selected_cause_confidence": 0.88,
                "selected_fundamental_score": 0.91,
                "selected_direction_alignment": 1.0,
                "selected_is_primary_cause": 1,
                "root_link_type": "primary",
                "root_primary_shock_ts": "2026-02-01T10:00:00Z",
                "root_episode_event_index": 1,
                "root_topic_id": "root:BRN:mideast_geopolitics",
            },
            {
                "symbol": "BRN",
                "shock_ts": "2026-02-01T11:00:00Z",
                "bar_minutes": 5,
                "prev_price": 81.2,
                "price": 81.8,
                "logret": 0.0073,
                "abs_move_pct": 0.74,
                "shock_direction": "up",
                "rolling_sigma": 0.0029,
                "z_score": 2.5,
                "selected_event_source": "root",
                "selected_event_id": "evt-1",
                "selected_event_ts": "2026-02-01T10:50:00Z",
                "selected_delay_min": 10.0,
                "selected_match_mode": "root_context",
                "selected_title": "Insurers raise war-risk premiums",
                "selected_url": "https://example.com/root-2",
                "selected_cause_event": "chokepoint_closure",
                "selected_cause_route_key": "chokepoint:hormuz->seaborne_crude->BRN",
                "selected_cause_claim_status": "confirmed",
                "selected_cause_classification": "mixed",
                "selected_cause_confidence": 0.73,
                "selected_fundamental_score": 0.77,
                "selected_direction_alignment": 1.0,
                "selected_is_primary_cause": 0,
                "root_link_type": "aftershock",
                "root_primary_shock_ts": "2026-02-01T10:00:00Z",
                "root_episode_event_index": 2,
                "root_topic_id": "root:BRN:mideast_geopolitics",
            },
        ]
    )
    live_db_url = f"sqlite:///{(tmp_path / 'news_root.db').as_posix()}"
    upsert_live_shock_rows(frame=frame, database_url=live_db_url, data_dir=tmp_path)
    refresh_root_maintenance(
        database_url=live_db_url,
        data_dir=tmp_path,
        cfg=RootMaintenanceConfig(bar_minutes=5),
    )

    settings = _build_settings(
        tmp_path,
        allowed_user_ids=[111],
        daily_healthcheck_enabled=False,
        root_alerts_enabled=True,
        news_alerts_enabled=False,
        shock_alerts_enabled=False,
    )
    settings.news_filter.live_db_url = live_db_url

    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[[]])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker.run_cycle()
    worker._next_signal_fetch_at = 0.0
    worker.run_cycle()

    assert len(telegram_session.sent_messages) == 1
    text = str(telegram_session.sent_messages[0]["text"])
    assert "КОРНЕВОЕ СОБЫТИЕ" in text
    assert "🧩 Тема: root:BRN:mideast_geopolitics" in text
    assert "📊 Счетчики: всего=2 | первичных=1 | повторных=1" in text
    assert "⏳ Возраст темы: 1ч 0м" in text
    assert "📰 Shipping halted near Hormuz" in text
    assert worker._state["root_last_processed_ts"] == "2026-02-01T10:00:00Z"
    sent = worker._state["sent_root_fingerprints"]
    assert isinstance(sent, dict)
    assert len(sent) == 1


def test_worker_root_cursor_respects_cycle_limit(tmp_path):
    frame = pd.DataFrame(
        [
            {
                "symbol": "BRN",
                "shock_ts": "2026-02-01T10:00:00Z",
                "bar_minutes": 5,
                "abs_move_pct": 1.5,
                "shock_direction": "up",
                "z_score": 3.8,
                "selected_event_source": "root",
                "selected_event_id": "evt-1",
                "selected_event_ts": "2026-02-01T09:55:00Z",
                "selected_title": "Shipping halted near Hormuz",
                "selected_url": "https://example.com/root-1",
                "selected_cause_event": "chokepoint_closure",
                "selected_cause_route_key": "chokepoint:hormuz->seaborne_crude->BRN",
                "selected_cause_claim_status": "confirmed",
                "selected_cause_classification": "cause",
                "selected_cause_confidence": 0.88,
                "selected_fundamental_score": 0.91,
                "selected_is_primary_cause": 1,
                "root_link_type": "primary",
                "root_primary_shock_ts": "2026-02-01T10:00:00Z",
                "root_episode_event_index": 1,
                "root_topic_id": "root:BRN:mideast_geopolitics",
            },
            {
                "symbol": "NG_US",
                "shock_ts": "2026-02-01T11:00:00Z",
                "bar_minutes": 5,
                "abs_move_pct": 1.1,
                "shock_direction": "up",
                "z_score": 3.1,
                "selected_event_source": "root",
                "selected_event_id": "evt-2",
                "selected_event_ts": "2026-02-01T10:50:00Z",
                "selected_title": "Freeze risk hits US gas flows",
                "selected_url": "https://example.com/root-2",
                "selected_cause_event": "weather_disruption",
                "selected_cause_route_key": "weather:gulf->lng->NG_US",
                "selected_cause_claim_status": "confirmed",
                "selected_cause_classification": "cause",
                "selected_cause_confidence": 0.79,
                "selected_fundamental_score": 0.84,
                "selected_is_primary_cause": 1,
                "root_link_type": "primary",
                "root_primary_shock_ts": "2026-02-01T11:00:00Z",
                "root_episode_event_index": 1,
                "root_topic_id": "root:NG_US:us_weather",
            },
        ]
    )
    live_db_url = f"sqlite:///{(tmp_path / 'news_root_limit.db').as_posix()}"
    upsert_live_shock_rows(frame=frame, database_url=live_db_url, data_dir=tmp_path)
    refresh_root_maintenance(
        database_url=live_db_url,
        data_dir=tmp_path,
        cfg=RootMaintenanceConfig(bar_minutes=5),
    )

    settings = _build_settings(
        tmp_path,
        allowed_user_ids=[111],
        daily_healthcheck_enabled=False,
        root_alerts_enabled=True,
        root_max_alerts_per_cycle=1,
        news_alerts_enabled=False,
        shock_alerts_enabled=False,
    )
    settings.news_filter.live_db_url = live_db_url

    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[[], []])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker.run_cycle()
    worker._next_signal_fetch_at = 0.0
    worker.run_cycle()

    assert len(telegram_session.sent_messages) == 2
    assert "root:BRN:mideast_geopolitics" in str(telegram_session.sent_messages[0]["text"])
    assert "root:NG_US:us_weather" in str(telegram_session.sent_messages[1]["text"])
    assert worker._state["root_last_processed_ts"] == "2026-02-01T11:00:00Z"


def test_worker_broadcasts_live_news_alert_once(tmp_path):
    news_feed = tmp_path / "live_news_discovery.csv"
    news_feed.write_text(
        "\n".join(
            [
                "feed_role,story_id,published_at_utc,commodity,commodity_link_score,direction,severity,impact_score,confidence,source_name,provider,title,url",
                "discovery,story-iran-attack,2026-03-04T07:00:00Z,BRN,0.93,up,critical,0.95,0.95,reuters.com,newsapi,Oil jumps after Iran escalation,https://example.com/news-1",
                "discovery,story-iran-attack,2026-03-04T07:00:00Z,GOLD,0.71,up,critical,0.95,0.95,reuters.com,newsapi,Oil jumps after Iran escalation,https://example.com/news-1",
            ]
        ),
        encoding="utf-8",
    )
    settings = _build_settings(
        tmp_path,
        allowed_user_ids=[111],
        daily_healthcheck_enabled=False,
        news_alerts_enabled=True,
        news_feed_path=str(news_feed),
        news_min_impact_score=0.8,
        news_min_confidence=0.9,
    )
    telegram_session = _FakeTelegramSession()
    backend_session = _FakeBackendSession(active_batches=[[]])
    worker = TelegramWorker(
        settings,
        telegram_session=telegram_session,
        backend_session=backend_session,
    )
    worker._state["registered_chats"] = {"111": 111}

    worker.run_cycle()
    worker._next_signal_fetch_at = 0.0
    worker.run_cycle()

    assert len(telegram_session.sent_messages) == 1
    text = str(telegram_session.sent_messages[0]["text"])
    assert "НОВОСТНЫЙ АЛЕРТ" in text
    assert "🧺 Инструменты: BRN (0.93), GOLD (0.71)" in text
    assert "Oil jumps after Iran escalation" in text
