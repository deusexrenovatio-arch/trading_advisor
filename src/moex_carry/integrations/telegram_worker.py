from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from moex_carry.config import AppSettings
from moex_carry.signals_ack import build_ack_note, build_signal_fingerprint
from moex_carry.signals_delivery import (
    DELIVERY_ACTIONS,
    entry_plan_from_row as _entry_plan_from_row,
    entry_plan_has_bounds as _entry_plan_has_bounds,
    entry_range_eligible_for_plan as _entry_range_eligible_for_plan,
    first_numeric as _first_numeric,
    parse_iso_utc as _parse_iso,
    signal_delivery_state,
    to_float as _to_float,
)


logger = logging.getLogger(__name__)

_SIGNAL_ACTIONS = set(DELIVERY_ACTIONS)
_SENT_FINGERPRINT_TTL_HOURS = 168


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_hhmm(value: object, *, fallback: tuple[int, int] = (9, 0)) -> tuple[int, int]:
    if isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) == 2:
            hour = _safe_int(parts[0])
            minute = _safe_int(parts[1])
            if hour is not None and minute is not None and 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour, minute
    logger.warning(
        "Invalid telegram.daily_healthcheck_time_local '%s', fallback to %02d:%02d.",
        value,
        fallback[0],
        fallback[1],
    )
    return fallback


class TelegramWorker:
    def __init__(
        self,
        settings: AppSettings,
        *,
        telegram_session: requests.Session | None = None,
        backend_session: requests.Session | None = None,
        sleep_fn=time.sleep,
        monotonic_fn=time.monotonic,
    ) -> None:
        self.settings = settings
        self.cfg = settings.telegram
        self._allowed_user_ids = {int(item) for item in self.cfg.allowed_user_ids}
        self._backend_base_url = str(self.cfg.backend_base_url).rstrip("/")
        self._telegram_api_base = f"https://api.telegram.org/bot{self.cfg.bot_token}"
        self._state_path = self._resolve_state_path(self.cfg.state_path)
        self._telegram_session = telegram_session or requests.Session()
        self._backend_session = backend_session or requests.Session()
        self._sleep_fn = sleep_fn
        self._monotonic_fn = monotonic_fn
        self._display_timezone_name = str(settings.environment.timezone or "UTC").strip() or "UTC"
        self._display_timezone = self._resolve_display_timezone(self._display_timezone_name)
        self._daily_healthcheck_time = _parse_hhmm(self.cfg.daily_healthcheck_time_local, fallback=(9, 0))
        self._state = self._load_state()
        self._next_signal_fetch_at = 0.0

    @staticmethod
    def _resolve_state_path(raw_path: str) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path

    @staticmethod
    def _resolve_display_timezone(name: str) -> timezone | ZoneInfo:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            logger.warning("Unknown timezone '%s', fallback to UTC.", name)
            return timezone.utc

    @staticmethod
    def _empty_state() -> dict[str, object]:
        return {
            "last_update_id": 0,
            "registered_chats": {},
            "sent_fingerprints": {},
            "hold_open_last_sent_date_by_pair": {},
            "enter_last_sent_at_by_pair": {},
            "enter_tracking_by_fingerprint": {},
            "daily_healthcheck_last_sent_date_by_chat": {},
            "pending_callbacks": {},
        }

    def _load_state(self) -> dict[str, object]:
        if not self._state_path.exists():
            return self._empty_state()
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load Telegram worker state, using empty state.")
            return self._empty_state()
        if not isinstance(payload, dict):
            return self._empty_state()
        state = self._empty_state()
        state["last_update_id"] = _safe_int(payload.get("last_update_id")) or 0
        state["registered_chats"] = {
            str(key): int(value)
            for key, value in (payload.get("registered_chats") or {}).items()
            if _safe_int(value) is not None
        }
        state["sent_fingerprints"] = {
            str(key): str(value)
            for key, value in (payload.get("sent_fingerprints") or {}).items()
            if isinstance(key, str) and isinstance(value, str)
        }
        state["hold_open_last_sent_date_by_pair"] = {
            str(key): str(value)
            for key, value in (payload.get("hold_open_last_sent_date_by_pair") or {}).items()
            if isinstance(key, str) and isinstance(value, str)
        }
        state["enter_last_sent_at_by_pair"] = {
            str(key): str(value)
            for key, value in (payload.get("enter_last_sent_at_by_pair") or {}).items()
            if isinstance(key, str) and isinstance(value, str)
        }
        raw_tracking = payload.get("enter_tracking_by_fingerprint") or {}
        if isinstance(raw_tracking, dict):
            normalized_tracking: dict[str, dict[str, object]] = {}
            for key, value in raw_tracking.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                normalized_tracking[key] = dict(value)
            state["enter_tracking_by_fingerprint"] = normalized_tracking
        state["daily_healthcheck_last_sent_date_by_chat"] = {
            str(key): str(value)
            for key, value in (payload.get("daily_healthcheck_last_sent_date_by_chat") or {}).items()
            if isinstance(key, str) and isinstance(value, str)
        }
        callbacks = payload.get("pending_callbacks") or {}
        if isinstance(callbacks, dict):
            normalized_callbacks: dict[str, dict[str, object]] = {}
            for key, value in callbacks.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                normalized_callbacks[key] = dict(value)
            state["pending_callbacks"] = normalized_callbacks
        return state

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._state_path.with_suffix(f"{self._state_path.suffix}.tmp")
        tmp_path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self._state_path)

    def _telegram_api(self, method: str, payload: dict[str, object], *, timeout: int = 30) -> object:
        url = f"{self._telegram_api_base}/{method}"
        response = self._telegram_session.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not data.get("ok", False):
            raise RuntimeError(f"telegram_api_error:{method}")
        return data.get("result")

    def _send_text(self, chat_id: int, text: str) -> None:
        self._telegram_api(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )

    def _answer_callback(self, callback_query_id: str, text: str) -> None:
        self._telegram_api(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": False,
            },
            timeout=20,
        )

    def _send_signal_message(
        self,
        *,
        chat_id: int,
        text: str,
        token: str,
    ) -> None:
        keyboard: list[list[dict[str, object]]] = [
            [{"text": "✅ Использовал сигнал", "callback_data": f"ack:{token}"}]
        ]
        if isinstance(self.cfg.ui_base_url, str) and self.cfg.ui_base_url.strip():
            keyboard.append([{"text": "🔎 Открыть UI", "url": str(self.cfg.ui_base_url).strip()}])
        self._telegram_api(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
                "reply_markup": {"inline_keyboard": keyboard},
            },
            timeout=20,
        )
    def _fetch_updates(self) -> list[dict[str, object]]:
        offset = int(self._state.get("last_update_id") or 0) + 1
        result = self._telegram_api(
            "getUpdates",
            {
                "offset": offset,
                "timeout": max(int(self.cfg.poll_timeout_sec), 0),
                "allowed_updates": ["message", "callback_query"],
            },
            timeout=max(int(self.cfg.poll_timeout_sec), 0) + 10,
        )
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]

    def _is_allowed_user(self, user_id: int) -> bool:
        return user_id in self._allowed_user_ids

    def _registered_chats(self) -> list[int]:
        registered = self._state.get("registered_chats")
        if not isinstance(registered, dict):
            return []
        chats: list[int] = []
        for raw_user_id, raw_chat_id in registered.items():
            user_id = _safe_int(raw_user_id)
            chat_id = _safe_int(raw_chat_id)
            if user_id is None or chat_id is None:
                continue
            if user_id not in self._allowed_user_ids:
                continue
            chats.append(chat_id)
        return chats

    def _handle_start(self, message: dict[str, object]) -> None:
        from_user = message.get("from")
        chat = message.get("chat")
        if not isinstance(from_user, dict) or not isinstance(chat, dict):
            return
        user_id = _safe_int(from_user.get("id"))
        chat_id = _safe_int(chat.get("id"))
        if user_id is None or chat_id is None:
            return
        if not self._is_allowed_user(user_id):
            self._send_text(chat_id, "Доступ запрещен: ваш user_id не в whitelist.")
            return
        registered = self._state.get("registered_chats")
        if not isinstance(registered, dict):
            registered = {}
            self._state["registered_chats"] = registered
        registered[str(user_id)] = chat_id
        self._save_state()
        self._send_text(
            chat_id,
            "Бот подключен.\nБуду присылать actionable-сигналы и принимать ACK.",
        )
    def _handle_help(self, message: dict[str, object]) -> None:
        from_user = message.get("from")
        chat = message.get("chat")
        if not isinstance(from_user, dict) or not isinstance(chat, dict):
            return
        user_id = _safe_int(from_user.get("id"))
        chat_id = _safe_int(chat.get("id"))
        if user_id is None or chat_id is None:
            return
        if not self._is_allowed_user(user_id):
            self._send_text(chat_id, "Доступ запрещен: ваш user_id не в whitelist.")
            return
        self._send_text(
            chat_id,
            "Команды:\n/start — зарегистрировать чат для рассылки\n/help — показать эту справку",
        )
    def _post_ack(self, callback_entry: dict[str, object], *, user_id: int, username: str | None, chat_id: int) -> None:
        run_id = str(callback_entry.get("run_id") or "").strip()
        timestamp = str(callback_entry.get("timestamp") or "").strip()
        stock = str(callback_entry.get("stock") or "").strip()
        future = str(callback_entry.get("future") or "").strip()
        signal_action = str(callback_entry.get("signal_action") or "").strip().lower()
        signal_direction = callback_entry.get("signal_direction")
        fingerprint = str(callback_entry.get("fingerprint") or "").strip()
        if not all([run_id, timestamp, stock, future, signal_action, fingerprint]):
            raise ValueError("invalid_callback_entry")

        note = build_ack_note(
            fingerprint=fingerprint,
            signal_run_id=run_id,
            signal_timestamp=timestamp,
            signal_action=signal_action,
            telegram_user_id=user_id,
            telegram_username=username,
            telegram_chat_id=chat_id,
        )
        payload = {
            "stock": stock,
            "future": future,
            "direction": signal_direction,
            "action": "ack",
            "status": "acknowledged",
            "note": note,
        }
        response = self._backend_session.post(
            f"{self._backend_base_url}/api/signals/execute",
            json=payload,
            timeout=20,
        )
        response.raise_for_status()

    def _is_callback_expired(self, callback_entry: dict[str, object]) -> bool:
        created_at = _parse_iso(callback_entry.get("created_at"))
        if created_at is None:
            return True
        ttl_hours = max(int(self.cfg.callback_ttl_hours), 1)
        return datetime.now(timezone.utc) > (created_at + timedelta(hours=ttl_hours))

    def _format_out_of_range_update(
        self,
        *,
        row: dict[str, object],
        baseline_plan: dict[str, float | None],
    ) -> str:
        stock = str(row.get("stock") or "").strip() or "N/A"
        future = str(row.get("future") or "").strip() or "N/A"
        stock_now = _first_numeric(row, "spot_mid", "stock_mid", "stock_price", "stock_last_price")
        future_now = _first_numeric(row, "future_mid", "future_price", "future_last_price")
        spread_now = _first_numeric(row, "spread_mid", "spread")
        spread_pct_now = _first_numeric(row, "spread_pct")

        def _fmt(value: float | None, digits: int = 4) -> str:
            return "n/a" if value is None else f"{value:.{digits}f}"

        def _fmt_pct(value: float | None, digits: int = 2) -> str:
            return "n/a" if value is None else f"{value * 100:.{digits}f}%"

        lines = [
            "⚠️ Обновление по сигналу ENTER",
            f"📈 Пара: {stock}/{future}",
            "Цена вышла за диапазон первоначального плана входа.",
            f"• Текущий {stock}: {_fmt(stock_now)}",
            (
                "• План {0}: {1} .. {2}".format(
                    stock,
                    _fmt(baseline_plan.get("entry_stock_min")),
                    _fmt(baseline_plan.get("entry_stock_max")),
                )
            ),
            f"• Текущий {future}: {_fmt(future_now)}",
            (
                "• План {0}: {1} .. {2}".format(
                    future,
                    _fmt(baseline_plan.get("entry_future_min_per_share")),
                    _fmt(baseline_plan.get("entry_future_max_per_share")),
                )
            ),
            f"• Текущий spread: {_fmt(spread_now)}",
            (
                "• План spread: {0} .. {1}".format(
                    _fmt(baseline_plan.get("entry_spread_min")),
                    _fmt(baseline_plan.get("entry_spread_max")),
                )
            ),
            f"• Текущий spread (%): {_fmt_pct(spread_pct_now)}",
            (
                "• План spread (%): {0} .. {1}".format(
                    _fmt_pct(baseline_plan.get("entry_spread_pct_min")),
                    _fmt_pct(baseline_plan.get("entry_spread_pct_max")),
                )
            ),
        ]
        return "\n".join(lines)

    def _handle_callback(self, query: dict[str, object]) -> None:
        callback_query_id = str(query.get("id") or "")
        data = str(query.get("data") or "")
        from_user = query.get("from")
        message = query.get("message")
        if not isinstance(from_user, dict) or not isinstance(message, dict):
            return
        user_id = _safe_int(from_user.get("id"))
        chat = message.get("chat")
        chat_id = _safe_int(chat.get("id")) if isinstance(chat, dict) else None
        if user_id is None or chat_id is None:
            return
        if not self._is_allowed_user(user_id):
            if callback_query_id:
                self._answer_callback(callback_query_id, "Нет доступа.")
            return
        if not data.startswith("ack:"):
            if callback_query_id:
                self._answer_callback(callback_query_id, "Неизвестное действие.")
            return
        token = data.split(":", 1)[1].strip()
        if not token:
            if callback_query_id:
                self._answer_callback(callback_query_id, "Некорректный token.")
            return
        callbacks = self._state.get("pending_callbacks")
        if not isinstance(callbacks, dict):
            callbacks = {}
            self._state["pending_callbacks"] = callbacks
        entry = callbacks.get(token)
        if not isinstance(entry, dict):
            if callback_query_id:
                self._answer_callback(callback_query_id, "ACK уже обработан или истек.")
            return
        entry_chat_id = _safe_int(entry.get("chat_id"))
        if entry_chat_id is not None and entry_chat_id != chat_id:
            if callback_query_id:
                self._answer_callback(callback_query_id, "ACK token не для этого чата.")
            return
        if self._is_callback_expired(entry):
            callbacks.pop(token, None)
            self._save_state()
            if callback_query_id:
                self._answer_callback(callback_query_id, "ACK token истек.")
            return

        username_raw = from_user.get("username")
        username = str(username_raw).strip() if isinstance(username_raw, str) and username_raw.strip() else None
        try:
            self._post_ack(entry, user_id=user_id, username=username, chat_id=chat_id)
        except Exception:
            logger.exception("Failed to store Telegram ACK.")
            if callback_query_id:
                self._answer_callback(callback_query_id, "Не удалось записать ACK.")
            return

        callbacks.pop(token, None)
        self._save_state()
        if callback_query_id:
            self._answer_callback(callback_query_id, "ACK записан.")
    def _process_updates(self) -> None:
        updates = self._fetch_updates()
        if not updates:
            return
        max_update_id = int(self._state.get("last_update_id") or 0)
        for update in updates:
            update_id = _safe_int(update.get("update_id"))
            if update_id is not None:
                max_update_id = max(max_update_id, update_id)
            message = update.get("message")
            if isinstance(message, dict):
                text = str(message.get("text") or "").strip()
                if text.startswith("/start"):
                    self._handle_start(message)
                elif text.startswith("/help"):
                    self._handle_help(message)
            callback_query = update.get("callback_query")
            if isinstance(callback_query, dict):
                self._handle_callback(callback_query)
        self._state["last_update_id"] = max_update_id
        self._save_state()

    def _cleanup_state(self) -> None:
        now = datetime.now(timezone.utc)
        changed = False

        callbacks = self._state.get("pending_callbacks")
        if isinstance(callbacks, dict):
            expired_tokens = [
                token
                for token, entry in callbacks.items()
                if not isinstance(entry, dict) or self._is_callback_expired(entry)
            ]
            for token in expired_tokens:
                callbacks.pop(token, None)
                changed = True

        sent = self._state.get("sent_fingerprints")
        if isinstance(sent, dict):
            for key in list(sent.keys()):
                ts = _parse_iso(sent.get(key))
                if ts is None or now > (ts + timedelta(hours=_SENT_FINGERPRINT_TTL_HOURS)):
                    sent.pop(key, None)
                    changed = True

        enter_last_sent = self._state.get("enter_last_sent_at_by_pair")
        if isinstance(enter_last_sent, dict):
            for key in list(enter_last_sent.keys()):
                ts = _parse_iso(enter_last_sent.get(key))
                if ts is None or now > (ts + timedelta(hours=_SENT_FINGERPRINT_TTL_HOURS)):
                    enter_last_sent.pop(key, None)
                    changed = True

        tracking = self._state.get("enter_tracking_by_fingerprint")
        if isinstance(tracking, dict):
            valid_fingerprints = set(sent.keys()) if isinstance(sent, dict) else set()
            for key in list(tracking.keys()):
                if key not in valid_fingerprints:
                    tracking.pop(key, None)
                    changed = True

        if changed:
            self._save_state()

    def _fetch_active_signals(self) -> list[dict[str, object]]:
        endpoints = (
            f"{self._backend_base_url}/api/v2/signals/active",
            f"{self._backend_base_url}/api/signals/active",
        )
        last_error: Exception | None = None
        for url in endpoints:
            try:
                response = self._backend_session.get(url, timeout=20)
                response.raise_for_status()
            except Exception as exc:
                last_error = exc
                continue
            payload = response.json()
            if not isinstance(payload, list):
                return []
            return [item for item in payload if isinstance(item, dict)]
        if last_error is not None:
            raise last_error
        return []

    def _format_daily_healthcheck_message(
        self,
        *,
        now_local: datetime,
        backend_ok: bool,
        active_rows: list[dict[str, object]],
        backend_error: str | None,
    ) -> str:
        tz_label = now_local.tzname() or self._display_timezone_name
        lines = [
            "✅ Утренний health-check",
            f"⏱ Время: {now_local.strftime('%d.%m.%Y %H:%M')} {tz_label}",
            "🤖 Статус бота: online",
            f"🌐 Backend: {'OK' if backend_ok else 'ERROR'}",
        ]
        if backend_ok:
            active_count = len(active_rows)
            lines.append(f"📊 Активных сигналов: {active_count}")
            if active_rows:
                sample_pairs = [
                    f"{str(row.get('stock') or '').strip()}/{str(row.get('future') or '').strip()}"
                    for row in active_rows
                ]
                sample_pairs = [value for value in sample_pairs if value != "/"]
                if sample_pairs:
                    lines.append(f"🔎 Примеры: {', '.join(sample_pairs[:3])}")
            else:
                lines.append("📦 Данные: активных сигналов сейчас нет.")
        else:
            lines.append("📦 Данные: проверить не удалось.")
            if isinstance(backend_error, str) and backend_error.strip():
                lines.append(f"⚠️ Ошибка backend: {backend_error.strip()[:160]}")
        return "\n".join(lines)

    def _send_daily_healthcheck(self) -> None:
        if not bool(self.cfg.daily_healthcheck_enabled):
            return
        target_chats = self._registered_chats()
        if not target_chats:
            return

        now_local = datetime.now(timezone.utc).astimezone(self._display_timezone)
        if (now_local.hour, now_local.minute) < self._daily_healthcheck_time:
            return
        today_local = now_local.date().isoformat()

        sent_map = self._state.get("daily_healthcheck_last_sent_date_by_chat")
        if not isinstance(sent_map, dict):
            sent_map = {}
            self._state["daily_healthcheck_last_sent_date_by_chat"] = sent_map

        due_chats = [
            chat_id
            for chat_id in target_chats
            if str(sent_map.get(str(chat_id)) or "").strip() != today_local
        ]
        if not due_chats:
            return

        backend_ok = False
        active_rows: list[dict[str, object]] = []
        backend_error: str | None = None
        try:
            active_rows = self._fetch_active_signals()
            backend_ok = True
        except Exception as exc:
            backend_error = str(exc).strip().splitlines()[0] if str(exc).strip() else "unknown error"

        message = self._format_daily_healthcheck_message(
            now_local=now_local,
            backend_ok=backend_ok,
            active_rows=active_rows,
            backend_error=backend_error,
        )
        changed = False
        for chat_id in due_chats:
            try:
                self._send_text(chat_id, message)
            except Exception:
                logger.exception("Failed to send daily health-check to chat_id=%s", chat_id)
                continue
            sent_map[str(chat_id)] = today_local
            changed = True
        if changed:
            self._save_state()

    def _format_signal_message(self, row: dict[str, object]) -> str:
        def _to_float(value: object) -> float | None:
            try:
                if value is None:
                    return None
                return float(value)
            except (TypeError, ValueError):
                return None

        def _fmt_number(value: object, digits: int = 4) -> str:
            parsed = _to_float(value)
            if parsed is None:
                return "n/a"
            return f"{parsed:.{digits}f}"

        def _fmt_percent(value: object, digits: int = 2) -> str:
            parsed = _to_float(value)
            if parsed is None:
                return "n/a"
            return f"{parsed * 100:.{digits}f}%"

        def _fmt_timestamp(value: object) -> str:
            raw = str(value or "").strip()
            parsed = _parse_iso(raw)
            if parsed is None:
                return raw or "n/a"
            localized = parsed.astimezone(self._display_timezone)
            tz_label = localized.tzname() or self._display_timezone_name
            return f"{localized.strftime('%d.%m.%Y %H:%M')} {tz_label}"

        action_raw = str(row.get("signal_action") or "").strip().lower()
        action_label = {
            "enter": "🟢 ENTER",
            "exit": "🔴 EXIT",
            "hold_open": "🟡 HOLD_OPEN",
        }.get(action_raw, f"⚪ {action_raw.upper() or 'UNKNOWN'}")

        direction_raw = str(row.get("signal_direction") or "").strip().lower()
        direction_label = {
            "cash_and_carry": "Cash-and-carry",
            "reverse": "Reverse",
            "neutral": "Neutral",
        }.get(direction_raw, direction_raw or "n/a")

        stock = str(row.get("stock") or "").strip() or "N/A"
        future = str(row.get("future") or "").strip() or "N/A"
        timestamp = _fmt_timestamp(row.get("timestamp"))

        entry_stock_min = row.get("entry_stock_min")
        entry_stock_max = row.get("entry_stock_max")
        entry_future_min = row.get("entry_future_min_per_share")
        entry_future_max = row.get("entry_future_max_per_share")
        entry_spread_min = row.get("entry_spread_min")
        entry_spread_max = row.get("entry_spread_max")
        entry_spread_pct_min = row.get("entry_spread_pct_min")
        entry_spread_pct_max = row.get("entry_spread_pct_max")
        current_spread_pct = row.get("spread_pct")
        tp = row.get("tp_spread_pct_level")
        sl = row.get("sl_spread_pct_level")
        forecast_days = row.get("forecast_exit_days")

        lines = [
            "📣 Новый сигнал",
            f"{action_label}",
            f"📈 Пара: {stock}/{future}",
            f"🧭 Направление: {direction_label}",
            f"⭐ Score: {_fmt_number(row.get('signal_score'))}",
            f"⏱ Время: {timestamp}",
        ]

        has_entry_plan = any(
            value is not None
            for value in [
                entry_stock_min,
                entry_stock_max,
                entry_future_min,
                entry_future_max,
                entry_spread_min,
                entry_spread_max,
                entry_spread_pct_min,
                entry_spread_pct_max,
            ]
        )
        if has_entry_plan:
            lines.append("📍 План входа")
            if entry_stock_min is not None or entry_stock_max is not None:
                lines.append(
                    f"• {stock}: {_fmt_number(entry_stock_min)} .. {_fmt_number(entry_stock_max)}"
                )
            if entry_future_min is not None or entry_future_max is not None:
                lines.append(
                    f"• {future}: {_fmt_number(entry_future_min)} .. {_fmt_number(entry_future_max)}"
                )
            if entry_spread_min is not None or entry_spread_max is not None:
                lines.append(
                    f"• Допустимый spread: {_fmt_number(entry_spread_min)} .. {_fmt_number(entry_spread_max)}"
                )
            if entry_spread_pct_min is not None or entry_spread_pct_max is not None:
                lines.append(
                    f"• Допустимый spread (%): {_fmt_percent(entry_spread_pct_min)} .. {_fmt_percent(entry_spread_pct_max)}"
                )
            if current_spread_pct is not None:
                lines.append(f"• Текущий spread (%): {_fmt_percent(current_spread_pct)}")

        if tp is not None or sl is not None:
            lines.append(f"• TP/SL spread: {_fmt_percent(tp)} / {_fmt_percent(sl)}")
        if forecast_days is not None:
            lines.append(f"• Прогноз выхода: {forecast_days} дн")

        lines.append("")
        lines.append("Нажмите кнопку ниже, если использовали сигнал.")

        return "\n".join(lines)
    def _broadcast_signals(self) -> None:
        target_chats = self._registered_chats()
        if not target_chats:
            return
        rows = self._fetch_active_signals()
        if not rows:
            return

        sent_map = self._state.get("sent_fingerprints")
        if not isinstance(sent_map, dict):
            sent_map = {}
            self._state["sent_fingerprints"] = sent_map
        hold_open_map = self._state.get("hold_open_last_sent_date_by_pair")
        if not isinstance(hold_open_map, dict):
            hold_open_map = {}
            self._state["hold_open_last_sent_date_by_pair"] = hold_open_map
        enter_last_sent_map = self._state.get("enter_last_sent_at_by_pair")
        if not isinstance(enter_last_sent_map, dict):
            enter_last_sent_map = {}
            self._state["enter_last_sent_at_by_pair"] = enter_last_sent_map
        enter_tracking_map = self._state.get("enter_tracking_by_fingerprint")
        if not isinstance(enter_tracking_map, dict):
            enter_tracking_map = {}
            self._state["enter_tracking_by_fingerprint"] = enter_tracking_map
        callbacks = self._state.get("pending_callbacks")
        if not isinstance(callbacks, dict):
            callbacks = {}
            self._state["pending_callbacks"] = callbacks

        now_iso = _iso_now()
        now_dt = datetime.now(timezone.utc)
        today = datetime.now(timezone.utc).date().isoformat()
        changed = False

        for row in rows:
            delivery = signal_delivery_state(
                row,
                callback_ttl_hours=int(self.cfg.callback_ttl_hours),
                now_utc=now_dt,
            )
            action = str(delivery.get("delivery_action") or "").strip().lower()
            if action not in _SIGNAL_ACTIONS:
                continue
            pair_key = f"{str(row.get('stock') or '').strip()}|{str(row.get('future') or '').strip()}"
            fingerprint_raw = str(row.get("signal_fingerprint") or "").strip()
            if action == "enter" and bool(delivery.get("signal_used")):
                continue
            if action == "enter" and bool(delivery.get("entry_signal_expired")):
                continue
            run_id = str(row.get("run_id") or "").strip()
            timestamp = str(row.get("timestamp") or "").strip()
            stock = str(row.get("stock") or "").strip()
            future = str(row.get("future") or "").strip()
            direction = row.get("signal_direction")
            if not run_id or not timestamp or not stock or not future:
                continue
            fingerprint = (
                fingerprint_raw
                if fingerprint_raw
                else build_signal_fingerprint(
                    run_id=run_id,
                    timestamp=timestamp,
                    stock=stock,
                    future=future,
                    signal_action=action,
                )
            )

            if action == "enter":
                if fingerprint in sent_map:
                    tracking_entry = enter_tracking_map.get(fingerprint)
                    if isinstance(tracking_entry, dict):
                        baseline_raw = tracking_entry.get("baseline_plan")
                        baseline_plan = (
                            {
                                key: _to_float(value)
                                for key, value in baseline_raw.items()
                                if isinstance(key, str)
                            }
                            if isinstance(baseline_raw, dict)
                            else {}
                        )
                        out_of_range_notified = str(tracking_entry.get("out_of_range_notified_at") or "").strip()
                        if (
                            _entry_plan_has_bounds(baseline_plan)
                            and not out_of_range_notified
                            and not _entry_range_eligible_for_plan(row, baseline_plan)
                        ):
                            update_text = self._format_out_of_range_update(
                                row=row,
                                baseline_plan=baseline_plan,
                            )
                            delivered_update = False
                            for chat_id in target_chats:
                                try:
                                    self._send_text(chat_id, update_text)
                                except Exception:
                                    logger.exception(
                                        "Failed to send out-of-range update to chat_id=%s",
                                        chat_id,
                                    )
                                    continue
                                delivered_update = True
                            if delivered_update:
                                tracking_entry["out_of_range_notified_at"] = now_iso
                                changed = True
                    continue

                cooldown_minutes = max(int(self.cfg.enter_resend_cooldown_minutes or 0), 0)
                if cooldown_minutes > 0:
                    last_sent = _parse_iso(enter_last_sent_map.get(pair_key))
                    if last_sent is not None and now_dt < (last_sent + timedelta(minutes=cooldown_minutes)):
                        continue
                if not bool(delivery.get("entry_range_eligible")):
                    continue
            elif fingerprint in sent_map:
                continue

            if action == "hold_open" and int(self.cfg.hold_open_daily_limit or 0) >= 1:
                last_sent_date = str(hold_open_map.get(pair_key) or "")
                if last_sent_date == today:
                    continue

            message = self._format_signal_message(row)
            delivered = False
            for chat_id in target_chats:
                token = uuid.uuid4().hex[:10]
                callbacks[token] = {
                    "fingerprint": fingerprint,
                    "run_id": run_id,
                    "timestamp": timestamp,
                    "stock": stock,
                    "future": future,
                    "signal_action": action,
                    "signal_direction": direction,
                    "chat_id": chat_id,
                    "created_at": now_iso,
                }
                try:
                    self._send_signal_message(chat_id=chat_id, text=message, token=token)
                except Exception:
                    callbacks.pop(token, None)
                    logger.exception("Failed to send signal message to chat_id=%s", chat_id)
                    continue
                delivered = True
                changed = True

            if delivered:
                sent_map[fingerprint] = now_iso
                if action == "hold_open":
                    hold_open_map[pair_key] = today
                if action == "enter":
                    enter_last_sent_map[pair_key] = now_iso
                    enter_tracking_map[fingerprint] = {
                        "pair_key": pair_key,
                        "created_at": now_iso,
                        "out_of_range_notified_at": None,
                        "baseline_plan": _entry_plan_from_row(row),
                    }
                changed = True

        if changed:
            self._save_state()

    def run_cycle(self) -> None:
        self._cleanup_state()
        self._process_updates()
        self._send_daily_healthcheck()
        now = self._monotonic_fn()
        if now >= self._next_signal_fetch_at:
            self._broadcast_signals()
            interval = max(int(self.cfg.signal_fetch_interval_sec), 1)
            self._next_signal_fetch_at = now + interval

    def run_forever(self) -> None:
        logger.info("Telegram worker started.")
        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                logger.info("Telegram worker stopped.")
                return
            except Exception:
                logger.exception("Telegram worker cycle failed.")
                self._sleep_fn(1.0)


def run_telegram_worker(settings: AppSettings) -> None:
    cfg = settings.telegram
    if not cfg.enabled:
        raise ValueError("telegram.enabled=false, worker is disabled by config")
    if not isinstance(cfg.bot_token, str) or not cfg.bot_token.strip():
        raise ValueError("telegram.bot_token is required when telegram.enabled=true")
    if not cfg.allowed_user_ids:
        raise ValueError("telegram.allowed_user_ids is required when telegram.enabled=true")
    worker = TelegramWorker(settings)
    worker.run_forever()

