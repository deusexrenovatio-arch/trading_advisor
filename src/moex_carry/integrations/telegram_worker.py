from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from moex_carry.config import AppSettings
from moex_carry.integrations.telegram_runtime_utils import (
    is_retryable_telegram_http_error,
    parse_hhmm,
    resolve_display_timezone,
)
from moex_carry.integrations.telegram_news_broadcast import broadcast_news_alerts
from moex_carry.integrations.telegram_h4a_followup import (
    broadcast_h4a_followups,
    has_post_fill_state,
)
from moex_carry.integrations.telegram_root_broadcast import broadcast_root_alerts
from moex_carry.integrations.telegram_signal_message import format_signal_message
from moex_carry.integrations.telegram_strategy import (
    normalize_strategy_stream,
    resolve_strategy_metadata,
)
from moex_carry.integrations.telegram_worker_state import (
    iso_now as _iso_now,
    load_state as _load_state_payload,
    resolve_state_path as _resolve_state_path_payload,
    safe_int as _safe_int,
    save_state as _save_state_payload,
    empty_state as _empty_state_payload,
)
from moex_carry.integrations.telegram_shock_broadcast import broadcast_shock_alerts
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
_TELEGRAM_GET_UPDATES_MAX_ATTEMPTS = 2
_TELEGRAM_GET_UPDATES_RETRY_SLEEP_SEC = 0.25


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
        self._state_path = self._resolve_state_path(self.cfg.state_path, settings.data.data_dir)
        self._shock_feed_path = (
            self._resolve_state_path(self.cfg.shock_feed_path, settings.data.data_dir)
            if isinstance(self.cfg.shock_feed_path, str) and self.cfg.shock_feed_path.strip()
            else None
        )
        self._news_feed_path = self._resolve_state_path(self.cfg.news_feed_path, settings.data.data_dir) if isinstance(self.cfg.news_feed_path, str) and self.cfg.news_feed_path.strip() else None
        self._telegram_session = telegram_session or requests.Session()
        self._backend_session = backend_session or requests.Session()
        self._sleep_fn = sleep_fn
        self._monotonic_fn = monotonic_fn
        self._display_timezone_name = str(settings.environment.timezone or "UTC").strip() or "UTC"
        self._display_timezone = resolve_display_timezone(self._display_timezone_name, logger=logger)
        self._daily_healthcheck_time = parse_hhmm(
            self.cfg.daily_healthcheck_time_local,
            logger=logger,
            fallback=(9, 0),
        )
        self._state = self._load_state()
        self._next_signal_fetch_at = 0.0

    @staticmethod
    def _resolve_state_path(raw_path: str, data_dir: str | Path | None = None) -> Path:
        return _resolve_state_path_payload(raw_path, data_dir)

    @staticmethod
    def _empty_state() -> dict[str, object]:
        return _empty_state_payload()

    def _load_state(self) -> dict[str, object]:
        return _load_state_payload(self._state_path, logger=logger)

    def _save_state(self) -> None:
        _save_state_payload(self._state_path, self._state)

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

    def _send_message_with_keyboard(
        self,
        *,
        chat_id: int,
        text: str,
        keyboard: list[list[dict[str, object]]],
    ) -> None:
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
            [{"text": "👀 Отметить просмотр", "callback_data": f"ack:{token}"}]
        ]
        if isinstance(self.cfg.ui_base_url, str) and self.cfg.ui_base_url.strip():
            keyboard.append([{"text": "🔎 Открыть UI", "url": str(self.cfg.ui_base_url).strip()}])
        self._send_message_with_keyboard(chat_id=chat_id, text=text, keyboard=keyboard)

    def _send_followup_message(
        self,
        *,
        chat_id: int,
        text: str,
        actions: list[dict[str, str]],
    ) -> None:
        callback_buttons: list[dict[str, object]] = []
        for action in actions:
            label = str(action.get("text") or "").strip()
            callback_action = str(action.get("callback_action") or "").strip().lower()
            token = str(action.get("token") or "").strip()
            if not label or not callback_action or not token:
                continue
            callback_buttons.append(
                {"text": label, "callback_data": f"act:{callback_action}:{token}"}
            )
        keyboard: list[list[dict[str, object]]] = []
        if callback_buttons:
            keyboard.append(callback_buttons)
        if isinstance(self.cfg.ui_base_url, str) and self.cfg.ui_base_url.strip():
            keyboard.append([{"text": "🔎 Открыть UI", "url": str(self.cfg.ui_base_url).strip()}])
        self._send_message_with_keyboard(chat_id=chat_id, text=text, keyboard=keyboard)
    def _fetch_updates(self) -> list[dict[str, object]]:
        offset = int(self._state.get("last_update_id") or 0) + 1
        payload = {
            "offset": offset,
            "timeout": max(int(self.cfg.poll_timeout_sec), 0),
            "allowed_updates": ["message", "callback_query"],
        }
        timeout = max(int(self.cfg.poll_timeout_sec), 0) + 10
        result: object = []
        for attempt in range(1, _TELEGRAM_GET_UPDATES_MAX_ATTEMPTS + 1):
            try:
                result = self._telegram_api("getUpdates", payload, timeout=timeout)
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                if attempt >= _TELEGRAM_GET_UPDATES_MAX_ATTEMPTS:
                    logger.warning(
                        "Telegram getUpdates transport failed after %d attempts: %s",
                        _TELEGRAM_GET_UPDATES_MAX_ATTEMPTS,
                        exc,
                    )
                    return []
                logger.warning(
                    "Telegram getUpdates transport error (attempt %d/%d), retrying once: %s",
                    attempt,
                    _TELEGRAM_GET_UPDATES_MAX_ATTEMPTS,
                    exc,
                )
            except requests.HTTPError as exc:
                if not is_retryable_telegram_http_error(exc):
                    raise
                status_code = int(exc.response.status_code) if exc.response is not None else "unknown"
                if attempt >= _TELEGRAM_GET_UPDATES_MAX_ATTEMPTS:
                    logger.warning(
                        "Telegram getUpdates failed with HTTP %s after %d attempts.",
                        status_code,
                        _TELEGRAM_GET_UPDATES_MAX_ATTEMPTS,
                    )
                    return []
                logger.warning(
                    "Telegram getUpdates retryable HTTP %s (attempt %d/%d), retrying once.",
                    status_code,
                    attempt,
                    _TELEGRAM_GET_UPDATES_MAX_ATTEMPTS,
                )
            self._sleep_fn(_TELEGRAM_GET_UPDATES_RETRY_SLEEP_SEC)
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
            "Бот подключен.\nБуду присылать actionable-сигналы, post-fill H4A follow-up и принимать отметку просмотра.",
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
            (
                "Команды:\n"
                "/start — зарегистрировать чат для рассылки\n"
                "/help — показать эту справку\n\n"
                "После `enter_submitted` и `enter_filled` бот присылает H4A follow-up: fallback, post-fill packet, break-even/trailing и time stop.\n"
                "В follow-up сообщении используйте `Confirm`, если шаг H4A выполнен, или `Manual override`, если исполнение ушло от baseline."
            ),
        )

    @staticmethod
    def _extract_pair_from_row(row: dict[str, object]) -> tuple[str, str]:
        stock = str(row.get("stock") or "").strip()
        future = str(row.get("future") or "").strip()
        if stock and future:
            return stock, future

        pair_id = str(row.get("pair_id") or "").strip()
        if "__" in pair_id:
            stock_value, future_value = pair_id.split("__", 1)
            stock = stock_value.strip()
            future = future_value.strip()
            if stock and future:
                return stock, future

        entity_ref = row.get("entity_ref")
        if isinstance(entity_ref, dict):
            stock = str(entity_ref.get("stock") or "").strip()
            future = str(entity_ref.get("future") or "").strip()
            if stock and future:
                return stock, future
            entity_id = str(entity_ref.get("entity_id") or "").strip()
            if "__" in entity_id:
                stock_value, future_value = entity_id.split("__", 1)
                stock = stock_value.strip()
                future = future_value.strip()
                if stock and future:
                    return stock, future
        return "", ""

    def _normalize_row_for_worker(self, row: dict[str, object]) -> dict[str, object]:
        normalized = dict(row)
        stock, future = self._extract_pair_from_row(normalized)
        if stock:
            normalized["stock"] = stock
        if future:
            normalized["future"] = future
        if stock and future:
            normalized.setdefault("pair_id", f"{stock}__{future}")
        metrics = normalized.get("metrics")
        if not isinstance(normalized.get("signal_metrics"), dict) and isinstance(metrics, dict):
            normalized["signal_metrics"] = dict(metrics)
        strategy_id, strategy_type, strategy_stream = resolve_strategy_metadata(normalized)
        if strategy_id is not None:
            normalized.setdefault("strategy_id", strategy_id)
        normalized.setdefault("strategy_type", strategy_type)
        normalized.setdefault("strategy_stream", strategy_stream)
        delivery = normalized.get("delivery")
        if isinstance(delivery, dict):
            normalized.setdefault("delivery_action", delivery.get("delivery_action"))
            normalized.setdefault("delivery_allowed", delivery.get("delivery_allowed"))
            normalized.setdefault("delivery_suppressed_reason", delivery.get("delivery_suppressed_reason"))
            normalized.setdefault("signal_fingerprint", delivery.get("signal_fingerprint"))
        intent = normalized.get("intent")
        intent_status = ""
        if isinstance(intent, dict):
            intent_status = str(intent.get("status") or "").strip().lower()
            normalized.setdefault("run_id", intent.get("source_run_id"))
            normalized.setdefault("timestamp", intent.get("source_timestamp"))
            normalized.setdefault(
                "signal_used",
                intent_status in {"consumed", "submitted", "filled", "cancelled", "manual_override"},
            )
            normalized.setdefault("signal_used_at", intent.get("consumed_at"))
            normalized.setdefault("signal_viewed", intent_status == "viewed")
            normalized.setdefault("signal_viewed_at", intent.get("viewed_at"))
            normalized.setdefault("signal_viewed_by", intent.get("viewed_by"))
            normalized.setdefault("operator_signal_status", intent.get("operator_signal_status"))
            normalized.setdefault("operator_execution_mode", intent.get("operator_execution_mode"))
            normalized.setdefault("intent_id", intent.get("intent_id"))
            normalized.setdefault("entry_signal_expired", intent_status == "expired")
        else:
            intent = {}

        if not normalized.get("timestamp"):
            normalized["timestamp"] = normalized.get("snapshot_as_of")

        entry_plan = normalized.get("entry_plan")
        if isinstance(entry_plan, dict):
            normalized.setdefault("entry_stock_min", entry_plan.get("entry_stock_min"))
            normalized.setdefault("entry_stock_max", entry_plan.get("entry_stock_max"))
            normalized.setdefault("entry_future_min_per_share", entry_plan.get("entry_future_min_per_share"))
            normalized.setdefault("entry_future_max_per_share", entry_plan.get("entry_future_max_per_share"))
            normalized.setdefault("entry_spread_min", entry_plan.get("entry_spread_min"))
            normalized.setdefault("entry_spread_max", entry_plan.get("entry_spread_max"))
            normalized.setdefault("entry_spread_pct_min", entry_plan.get("entry_spread_pct_min"))
            normalized.setdefault("entry_spread_pct_max", entry_plan.get("entry_spread_pct_max"))
            if normalized.get("entry_stock_min") is None:
                normalized["entry_stock_min"] = entry_plan.get("entry_price_min")
            if normalized.get("entry_stock_max") is None:
                normalized["entry_stock_max"] = entry_plan.get("entry_price_max")
            normalized.setdefault("signal_direction", entry_plan.get("direction"))

        entry_range = normalized.get("entry_range_now")
        if isinstance(entry_range, dict):
            if normalized.get("spot_mid") is None:
                normalized["spot_mid"] = (
                    entry_range.get("stock_now")
                    if entry_range.get("stock_now") is not None
                    else entry_range.get("price_now")
                )
            normalized.setdefault("future_mid", entry_range.get("future_now"))
            normalized.setdefault("spread_mid", entry_range.get("spread_now"))
            normalized.setdefault("spread_pct", entry_range.get("spread_pct_now"))
            in_range = entry_range.get("in_range")
            if in_range is not None and normalized.get("entry_range_eligible") is None:
                normalized["entry_range_eligible"] = bool(in_range)

        if normalized.get("signal_action") is None:
            delivery_action = str(normalized.get("delivery_action") or "").strip().lower()
            if delivery_action in {"enter", "exit", "hold_open"}:
                normalized["signal_action"] = delivery_action
            else:
                state = str(normalized.get("actionability_state") or "").strip().lower()
                if state == "actionable_exit":
                    normalized["signal_action"] = "exit"
                elif state == "hold_open":
                    normalized["signal_action"] = "hold_open"
                else:
                    normalized["signal_action"] = "enter"

        if normalized.get("signal_score") is None and isinstance(metrics, dict):
            normalized["signal_score"] = metrics.get("total_score")

        return normalized

    def _post_operator_action(
        self,
        callback_entry: dict[str, object],
        *,
        action: str,
        user_id: int,
        username: str | None,
        chat_id: int,
    ) -> str:
        run_id = str(callback_entry.get("run_id") or "").strip()
        timestamp = str(callback_entry.get("timestamp") or "").strip()
        stock, future = self._extract_pair_from_row(callback_entry)
        stock = str(stock or "").strip()
        future = str(future or "").strip()
        signal_action = str(callback_entry.get("signal_action") or "").strip().lower()
        fingerprint = str(callback_entry.get("fingerprint") or "").strip()
        pair_id = str(callback_entry.get("pair_id") or "").strip()
        if not pair_id and stock and future:
            pair_id = f"{stock}__{future}"
        if not all([stock, future, fingerprint, pair_id]):
            raise ValueError("invalid_callback_entry")

        requested_action = str(action or "").strip().lower()
        if requested_action == "mark_viewed":
            if not all([run_id, timestamp, signal_action]):
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
        else:
            note = str(callback_entry.get("note") or "").strip() or f"telegram_callback:{requested_action}"
        idempotency_key = str(callback_entry.get("idempotency_key") or "").strip()
        if not idempotency_key:
            token = str(callback_entry.get("token") or "").strip()
            if requested_action == "mark_viewed":
                idempotency_key = f"telegram-ack:{token or fingerprint}"
            else:
                idempotency_key = f"telegram-{requested_action}:{token or fingerprint}"
        actor_id = (
            f"telegram:{username}"
            if isinstance(username, str) and username.strip()
            else f"telegram:{int(user_id)}"
        )
        payload = {
            "action": requested_action,
            "source": "telegram",
            "actor_id": actor_id,
            "idempotency_key": idempotency_key,
            "note": note,
        }
        if requested_action == "confirm_followup":
            payload["reason_code"] = (
                str(callback_entry.get("reason_code") or "").strip()
                or "telegram_h4a_followup_confirmed"
            )
            h4a_stage = str(callback_entry.get("h4a_stage") or "").strip()
            if h4a_stage:
                payload["h4a_stage"] = h4a_stage
        if requested_action == "manual_override":
            payload["reason_code"] = (
                str(callback_entry.get("reason_code") or "").strip() or "telegram_manual_override"
            )
        intent_id = str(callback_entry.get("intent_id") or "").strip()
        if intent_id:
            payload["intent_id"] = intent_id
        signal_id = str(callback_entry.get("signal_id") or "").strip()
        if signal_id:
            payload["signal_id"] = signal_id
        response = self._backend_session.post(
            (
                f"{self._backend_base_url}/api/v2/entities/pair/"
                f"{quote(pair_id, safe=':_|/')}/signals/actions"
            ),
            json=payload,
            timeout=20,
        )
        if int(getattr(response, "status_code", 200)) == 409:
            message = ""
            try:
                body = response.json()
            except Exception:
                body = None
            if isinstance(body, dict):
                message = str(body.get("message") or "").strip().lower()
            if message == "intent_superseded_or_stale":
                return "intent_stale"
        response.raise_for_status()
        return "ok"

    def _post_ack(
        self,
        callback_entry: dict[str, object],
        *,
        user_id: int,
        username: str | None,
        chat_id: int,
    ) -> str:
        return self._post_operator_action(
            callback_entry,
            action="mark_viewed",
            user_id=user_id,
            username=username,
            chat_id=chat_id,
        )

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
        callback_action = ""
        token = ""
        if data.startswith("ack:"):
            callback_action = "mark_viewed"
            token = data.split(":", 1)[1].strip()
        elif data.startswith("act:"):
            _, callback_action, token = (data.split(":", 2) + ["", ""])[:3]
            callback_action = str(callback_action or "").strip().lower()
            token = str(token or "").strip()
        else:
            if callback_query_id:
                self._answer_callback(callback_query_id, "Неизвестное действие.")
            return
        if callback_action not in {"mark_viewed", "confirm_followup", "manual_override"} or not token:
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
                self._answer_callback(callback_query_id, "Действие уже обработано или истекло.")
            return
        entry_chat_id = _safe_int(entry.get("chat_id"))
        if entry_chat_id is not None and entry_chat_id != chat_id:
            if callback_query_id:
                self._answer_callback(callback_query_id, "Токен не для этого чата.")
            return
        if self._is_callback_expired(entry):
            callbacks.pop(token, None)
            self._save_state()
            if callback_query_id:
                self._answer_callback(callback_query_id, "Токен действия истек.")
            return

        username_raw = from_user.get("username")
        username = str(username_raw).strip() if isinstance(username_raw, str) and username_raw.strip() else None
        expected_action = str(entry.get("callback_action") or "mark_viewed").strip().lower()
        if expected_action != callback_action:
            if callback_query_id:
                self._answer_callback(callback_query_id, "Токен не для этого действия.")
            return
        try:
            ack_result = self._post_operator_action(
                entry,
                action=callback_action,
                user_id=user_id,
                username=username,
                chat_id=chat_id,
            )
        except Exception:
            logger.exception("Failed to store Telegram callback action=%s.", callback_action)
            if callback_query_id:
                self._answer_callback(callback_query_id, "Не удалось записать действие.")
            return
        if ack_result == "intent_stale":
            callbacks.pop(token, None)
            self._save_state()
            if callback_query_id:
                stale_text = (
                    "Сигнал устарел, используйте новый enter."
                    if callback_action == "mark_viewed"
                    else "Follow-up уже устарел, откройте актуальный сигнал."
                    if callback_action == "confirm_followup"
                    else "Intent уже устарел, откройте актуальный сигнал."
                )
                self._answer_callback(callback_query_id, stale_text)
            return

        callbacks.pop(token, None)
        self._save_state()
        if callback_query_id:
            success_text = (
                "Просмотр отмечен."
                if callback_action == "mark_viewed"
                else "Подтверждение сохранено."
                if callback_action == "confirm_followup"
                else "Manual override зафиксирован."
            )
            self._answer_callback(callback_query_id, success_text)
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

        for key_name in (
            "post_fill_last_sent_at_by_fingerprint",
            "entry_fallback_reminder_sent_at_by_fingerprint",
            "break_even_trigger_sent_at_by_fingerprint",
            "trailing_trigger_sent_at_by_fingerprint",
            "time_stop_reminder_sent_at_by_fingerprint",
            "time_stop_overdue_sent_at_by_fingerprint",
        ):
            state_map = self._state.get(key_name)
            if not isinstance(state_map, dict):
                continue
            for key in list(state_map.keys()):
                ts = _parse_iso(state_map.get(key))
                if ts is None or now > (ts + timedelta(hours=_SENT_FINGERPRINT_TTL_HOURS)):
                    state_map.pop(key, None)
                    changed = True

        if changed:
            self._save_state()

    def _fetch_active_signals(self, *, include_non_actionable: bool = False) -> list[dict[str, object]]:
        include_non_actionable_qs = "true" if include_non_actionable else "false"
        endpoints = (
            (
                f"{self._backend_base_url}/api/v2/pairs/actionability"
                f"?include_non_actionable={include_non_actionable_qs}&include_open_holds=true&limit=5000"
            ),
            (
                f"{self._backend_base_url}/api/v2/signals/actionability"
                f"?entity_type=pair&include_non_actionable={include_non_actionable_qs}&limit=5000"
            ),
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
            rows = [item for item in payload if isinstance(item, dict)]
            return [self._normalize_row_for_worker(item) for item in rows]
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
        return format_signal_message(
            row,
            display_timezone=self._display_timezone,
            display_timezone_name=self._display_timezone_name,
        )

    def _broadcast_signals(self) -> None:
        target_chats = self._registered_chats()
        if not target_chats:
            return
        rows = self._fetch_active_signals(include_non_actionable=True)
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
        post_fill_map = self._state.get("post_fill_last_sent_at_by_fingerprint")
        if not isinstance(post_fill_map, dict):
            post_fill_map = {}
            self._state["post_fill_last_sent_at_by_fingerprint"] = post_fill_map
        entry_fallback_map = self._state.get("entry_fallback_reminder_sent_at_by_fingerprint")
        if not isinstance(entry_fallback_map, dict):
            entry_fallback_map = {}
            self._state["entry_fallback_reminder_sent_at_by_fingerprint"] = entry_fallback_map
        break_even_map = self._state.get("break_even_trigger_sent_at_by_fingerprint")
        if not isinstance(break_even_map, dict):
            break_even_map = {}
            self._state["break_even_trigger_sent_at_by_fingerprint"] = break_even_map
        trailing_map = self._state.get("trailing_trigger_sent_at_by_fingerprint")
        if not isinstance(trailing_map, dict):
            trailing_map = {}
            self._state["trailing_trigger_sent_at_by_fingerprint"] = trailing_map
        reminder_map = self._state.get("time_stop_reminder_sent_at_by_fingerprint")
        if not isinstance(reminder_map, dict):
            reminder_map = {}
            self._state["time_stop_reminder_sent_at_by_fingerprint"] = reminder_map
        overdue_map = self._state.get("time_stop_overdue_sent_at_by_fingerprint")
        if not isinstance(overdue_map, dict):
            overdue_map = {}
            self._state["time_stop_overdue_sent_at_by_fingerprint"] = overdue_map

        now_iso = _iso_now()
        now_dt = datetime.now(timezone.utc)
        today = datetime.now(timezone.utc).date().isoformat()
        changed = False

        for row in rows:
            delivery_payload = row.get("delivery")
            if isinstance(delivery_payload, dict):
                delivery = {
                    "delivery_action": str(delivery_payload.get("delivery_action") or "").strip().lower(),
                    "delivery_allowed": bool(delivery_payload.get("delivery_allowed")),
                    "delivery_suppressed_reason": delivery_payload.get("delivery_suppressed_reason"),
                    "signal_used": bool(row.get("signal_used")),
                    "entry_signal_expired": bool(row.get("entry_signal_expired")),
                    "entry_range_eligible": bool(row.get("entry_range_eligible")),
                }
                if "entry_range_eligible" not in row:
                    entry_range_now = row.get("entry_range_now")
                    if isinstance(entry_range_now, dict) and entry_range_now.get("in_range") is not None:
                        delivery["entry_range_eligible"] = bool(entry_range_now.get("in_range"))
            else:
                delivery = signal_delivery_state(
                    row,
                    callback_ttl_hours=int(self.cfg.callback_ttl_hours),
                    now_utc=now_dt,
                )
            action = str(delivery.get("delivery_action") or "").strip().lower()
            if action not in _SIGNAL_ACTIONS:
                continue
            actionability_state = str(row.get("actionability_state") or "").strip().lower()
            if actionability_state:
                if action == "enter" and actionability_state not in {
                    "actionable_enter",
                    "actionable_enter_repriced",
                    "enter_out_of_range",
                }:
                    continue
                if action == "exit" and actionability_state != "actionable_exit":
                    continue
                if action == "hold_open" and actionability_state != "hold_open" and not bool(row.get("hold_required")):
                    continue
            stock = str(row.get("stock") or "").strip()
            future = str(row.get("future") or "").strip()
            strategy_stream = normalize_strategy_stream(row.get("strategy_stream")) or normalize_strategy_stream(
                row.get("strategy_type")
            ) or "arbitrage"
            pair_key = f"{stock}|{future}|{strategy_stream}"
            fingerprint_raw = str(row.get("signal_fingerprint") or "").strip()
            operator_signal_status = str(
                row.get("operator_signal_status")
                or delivery.get("operator_signal_status")
                or ""
            ).strip().lower()
            if action == "enter" and operator_signal_status in {
                "enter_submitted",
                "enter_filled",
                "entry_cancelled",
                "manual_override",
            }:
                continue
            if action == "enter" and bool(delivery.get("entry_signal_expired")):
                continue
            run_id = str(row.get("run_id") or "").strip()
            timestamp = str(row.get("timestamp") or "").strip()
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
                    strategy_stream=strategy_stream,
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
                        entry_range_eligible = row.get("entry_range_eligible")
                        if entry_range_eligible is None:
                            entry_range_map = row.get("entry_range_now")
                            if isinstance(entry_range_map, dict):
                                if entry_range_map.get("in_range") is not None:
                                    entry_range_eligible = bool(entry_range_map.get("in_range"))
                        out_of_range_now = False
                        if isinstance(entry_range_eligible, bool):
                            out_of_range_now = not entry_range_eligible
                        elif _entry_plan_has_bounds(baseline_plan):
                            out_of_range_now = not _entry_range_eligible_for_plan(row, baseline_plan)
                        if (
                            _entry_plan_has_bounds(baseline_plan)
                            and not out_of_range_notified
                            and out_of_range_now
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

            if action == "hold_open" and has_post_fill_state(row):
                continue

            if action == "hold_open" and int(self.cfg.hold_open_daily_limit or 0) >= 1:
                last_sent_date = str(hold_open_map.get(pair_key) or "")
                if last_sent_date == today:
                    continue

            message = self._format_signal_message(row)
            delivered = False
            for chat_id in target_chats:
                token = uuid.uuid4().hex[:10]
                pair_id = f"{stock}__{future}"
                intent_payload = row.get("intent")
                intent_id = (
                    str(intent_payload.get("intent_id") or "").strip()
                    if isinstance(intent_payload, dict)
                    else ""
                )
                callbacks[token] = {
                    "token": token,
                    "callback_action": "mark_viewed",
                    "fingerprint": fingerprint,
                    "run_id": run_id,
                    "timestamp": timestamp,
                    "stock": stock,
                    "future": future,
                    "pair_id": pair_id,
                    "entity_type": "pair",
                    "entity_id": pair_id,
                    "intent_id": intent_id or None,
                    "signal_id": row.get("signal_id"),
                    "idempotency_key": f"telegram-ack:{token}",
                    "signal_action": action,
                    "signal_direction": direction,
                    "strategy_id": row.get("strategy_id"),
                    "strategy_type": row.get("strategy_type"),
                    "strategy_stream": row.get("strategy_stream"),
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

        if broadcast_h4a_followups(
            rows=rows,
            target_chats=target_chats,
            callbacks=callbacks,
            post_fill_map=post_fill_map,
            entry_fallback_map=entry_fallback_map,
            break_even_map=break_even_map,
            trailing_map=trailing_map,
            reminder_map=reminder_map,
            overdue_map=overdue_map,
            now_dt=now_dt,
            now_iso=now_iso,
            send_followup_message=self._send_followup_message,
            logger=logger,
        ):
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
            registered_chats = self._registered_chats()
            broadcast_root_alerts(
                cfg=self.cfg, state=self._state, registered_chats=registered_chats,
                send_text=self._send_text, save_state=self._save_state, logger=logger,
                shock_database_url=self.settings.news_filter.live_db_url, data_dir=self.settings.data.data_dir,
            )
            broadcast_shock_alerts(
                cfg=self.cfg, state=self._state, registered_chats=registered_chats,
                shock_feed_path=self._shock_feed_path,
                send_text=self._send_text, save_state=self._save_state, logger=logger,
                shock_database_url=self.settings.news_filter.live_db_url, data_dir=self.settings.data.data_dir,
            )
            broadcast_news_alerts(
                cfg=self.cfg, state=self._state, registered_chats=registered_chats,
                news_feed_path=self._news_feed_path,
                send_text=self._send_text, save_state=self._save_state, logger=logger,
            )
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

