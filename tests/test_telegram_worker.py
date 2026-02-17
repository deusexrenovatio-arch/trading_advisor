from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import requests

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig, TelegramConfig
from moex_carry.integrations.telegram_worker import TelegramWorker, run_telegram_worker
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
    def __init__(self, updates_batches: list[list[dict[str, object]]] | None = None):
        self._updates_batches = list(updates_batches or [])
        self.sent_messages: list[dict[str, object]] = []
        self.answered_callbacks: list[dict[str, object]] = []
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, json: dict[str, object], timeout: int) -> _FakeResponse:
        method = url.rstrip("/").rsplit("/", 1)[-1]
        self.calls.append((method, json))
        if method == "getUpdates":
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
    def __init__(self, active_batches: list[list[dict[str, object]]] | None = None):
        self._active_batches = list(active_batches or [[]])
        self._active_index = 0
        self.execute_payloads: list[dict[str, object]] = []
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
        self.execute_payloads.append(json)
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
    daily_healthcheck_enabled: bool = True,
    daily_healthcheck_time_local: str = "00:00",
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
            callback_ttl_hours=callback_ttl_hours,
            daily_healthcheck_enabled=daily_healthcheck_enabled,
            daily_healthcheck_time_local=daily_healthcheck_time_local,
            state_path=str(tmp_path / "telegram-state.json"),
            ui_base_url=None,
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
    assert "BBB|BBH6" in hold_open_last


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
    assert payload["status"] == "acknowledged"
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
