from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional


STRUCTURED_API_LOG_REQUIRED_FIELDS = (
    "event",
    "timestamp_utc",
    "component",
    "path",
    "method",
    "status_code",
    "request_id",
    "duration_ms",
)


def configure_logging(level: str = "INFO", log_format: Optional[str] = None) -> None:
    if log_format is None:
        log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    logging.basicConfig(level=level, format=log_format)


def build_api_log_event(
    *,
    component: str,
    path: str,
    method: str,
    status_code: int,
    request_id: str,
    duration_ms: float,
    event: str = "api_request_completed",
) -> dict[str, Any]:
    return {
        "event": str(event).strip() or "api_request_completed",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "component": str(component).strip(),
        "path": str(path).strip(),
        "method": str(method).strip().upper(),
        "status_code": int(status_code),
        "request_id": str(request_id).strip(),
        "duration_ms": round(max(float(duration_ms), 0.0), 3),
    }


def emit_api_log(
    logger: logging.Logger,
    *,
    component: str,
    path: str,
    method: str,
    status_code: int,
    request_id: str,
    duration_ms: float,
) -> None:
    payload = build_api_log_event(
        component=component,
        path=path,
        method=method,
        status_code=status_code,
        request_id=request_id,
        duration_ms=duration_ms,
    )
    logger.info(json.dumps(payload, sort_keys=True))
