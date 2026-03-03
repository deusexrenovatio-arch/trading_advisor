from __future__ import annotations

import logging
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests


def parse_hhmm(
    value: object,
    *,
    logger: logging.Logger,
    fallback: tuple[int, int] = (9, 0),
) -> tuple[int, int]:
    if isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) == 2:
            try:
                hour = int(parts[0])
                minute = int(parts[1])
            except (TypeError, ValueError):
                hour = None
                minute = None
            if hour is not None and minute is not None and 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour, minute
    logger.warning(
        "Invalid telegram.daily_healthcheck_time_local '%s', fallback to %02d:%02d.",
        value,
        fallback[0],
        fallback[1],
    )
    return fallback


def resolve_display_timezone(name: str, *, logger: logging.Logger) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown timezone '%s', fallback to UTC.", name)
        return timezone.utc


def is_retryable_telegram_http_error(exc: requests.HTTPError) -> bool:
    response = exc.response
    if response is None:
        return False
    return int(response.status_code) in {408, 425, 429, 500, 502, 503, 504}
