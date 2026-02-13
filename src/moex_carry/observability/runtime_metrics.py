from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Iterable


@dataclass(frozen=True)
class _LatencySample:
    ts: datetime
    duration_ms: float


class ApiObservability:
    """In-memory runtime metrics for operational SLO endpoints."""

    def __init__(self, *, latency_window_size: int = 500) -> None:
        self._lock = Lock()
        self._latency_window_size = max(int(latency_window_size), 50)
        self._request_total: dict[str, int] = defaultdict(int)
        self._request_status: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._latency: dict[str, deque[_LatencySample]] = defaultdict(
            lambda: deque(maxlen=self._latency_window_size)
        )
        self._events: dict[str, deque[datetime]] = defaultdict(deque)

    def record_request(self, endpoint: str, *, status_code: int, duration_ms: float) -> None:
        endpoint_key = str(endpoint or "").strip() or "unknown_endpoint"
        group = _status_group(status_code)
        now = datetime.now(timezone.utc)
        with self._lock:
            self._request_total[endpoint_key] += 1
            self._request_status[endpoint_key][group] += 1
            self._latency[endpoint_key].append(
                _LatencySample(ts=now, duration_ms=max(float(duration_ms), 0.0))
            )

    def mark_event(self, event_name: str, *, count: int = 1) -> None:
        key = str(event_name or "").strip()
        if not key:
            return
        bounded_count = max(int(count), 0)
        if bounded_count == 0:
            return
        now = datetime.now(timezone.utc)
        with self._lock:
            bucket = self._events[key]
            for _ in range(bounded_count):
                bucket.append(now)

    def count_recent(self, event_name: str, *, window_sec: int) -> int:
        key = str(event_name or "").strip()
        if not key:
            return 0
        window = max(int(window_sec), 1)
        cutoff = datetime.now(timezone.utc).timestamp() - float(window)
        with self._lock:
            bucket = self._events[key]
            _trim_event_bucket(bucket, cutoff)
            return len(bucket)

    def snapshot(self) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with self._lock:
            endpoints: dict[str, object] = {}
            for endpoint, total in self._request_total.items():
                status_map = dict(self._request_status.get(endpoint, {}))
                samples = list(self._latency.get(endpoint, ()))
                p50 = _percentile([sample.duration_ms for sample in samples], 50.0)
                p95 = _percentile([sample.duration_ms for sample in samples], 95.0)
                endpoints[endpoint] = {
                    "request_total": int(total),
                    "status_groups": status_map,
                    "latency_ms": {
                        "sample_size": len(samples),
                        "p50": p50,
                        "p95": p95,
                    },
                }

            events = {name: len(values) for name, values in self._events.items()}
        return {
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "endpoints": endpoints,
            "events_total": events,
        }

    def error_rate(self, endpoint: str) -> float:
        endpoint_key = str(endpoint or "").strip()
        if not endpoint_key:
            return 0.0
        with self._lock:
            total = float(self._request_total.get(endpoint_key, 0))
            if total <= 0.0:
                return 0.0
            groups = self._request_status.get(endpoint_key, {})
            errors = float(groups.get("4xx", 0) + groups.get("5xx", 0))
        return errors / total


def _status_group(status_code: int) -> str:
    code = int(status_code)
    if code >= 500:
        return "5xx"
    if code >= 400:
        return "4xx"
    if code >= 300:
        return "3xx"
    if code >= 200:
        return "2xx"
    return "1xx"


def _percentile(values: Iterable[float], percentile: float) -> float:
    data = sorted(float(value) for value in values)
    if not data:
        return 0.0
    p = min(max(float(percentile), 0.0), 100.0)
    if len(data) == 1:
        return data[0]
    rank = (len(data) - 1) * p / 100.0
    lower = int(rank)
    upper = min(lower + 1, len(data) - 1)
    if lower == upper:
        return data[lower]
    weight = rank - lower
    return data[lower] * (1.0 - weight) + data[upper] * weight


def _trim_event_bucket(bucket: deque[datetime], cutoff_ts: float) -> None:
    while bucket and bucket[0].timestamp() < cutoff_ts:
        bucket.popleft()
