from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class TimeWindow:
    start: time
    end: time


def parse_time_window(raw_start: str, raw_end: str) -> TimeWindow:
    return TimeWindow(start=time.fromisoformat(raw_start), end=time.fromisoformat(raw_end))


class MarketCalendar:
    def __init__(
        self,
        tz_name: str,
        sessions: list[TimeWindow],
        clearing: list[TimeWindow],
        forbid_margin_min: int,
    ) -> None:
        if not sessions:
            raise ValueError("sessions must not be empty")
        self.tz = ZoneInfo(str(tz_name))
        self.sessions = list(sessions)
        self.clearing = list(clearing)
        self.forbid_margin_min = max(int(forbid_margin_min), 0)

    def is_trading_time(self, ts: datetime) -> bool:
        local_ts = self._as_exchange_ts(ts)
        if not self._in_windows(local_ts, self.sessions):
            return False
        if self._in_windows(local_ts, self.clearing):
            return False
        return True

    def is_in_clearing_window(self, ts: datetime) -> bool:
        local_ts = self._as_exchange_ts(ts)
        return self._in_windows(local_ts, self.clearing)

    def next_session_end(self, ts: datetime) -> datetime:
        local_ts = self._as_exchange_ts(ts)
        for offset in range(0, 8):
            day = local_ts.date() + timedelta(days=offset)
            windows = sorted(self._iter_windows_for_date(day, self.sessions), key=lambda item: item[0])
            for start_dt, end_dt in windows:
                if local_ts <= end_dt:
                    if local_ts <= start_dt or (start_dt <= local_ts <= end_dt):
                        return end_dt
        raise ValueError("unable_to_resolve_next_session_end")

    def recommended_entry_expiry(self, ts: datetime, policy: str) -> datetime:
        normalized = str(policy or "SESSION_END").upper()
        if normalized == "SESSION_END":
            return self.next_session_end(ts)
        if normalized == "EOD_BEFORE_EVENING_CLEARING":
            return self._eod_before_evening_clearing(ts)
        raise ValueError(f"unsupported_expiry_policy:{policy}")

    def forbid_new_position(self, ts: datetime) -> bool:
        local_ts = self._as_exchange_ts(ts)
        margin = timedelta(minutes=self.forbid_margin_min)
        for day_offset in (-1, 0, 1):
            day = local_ts.date() + timedelta(days=day_offset)
            for start_dt, end_dt in self._iter_windows_for_date(day, self.clearing):
                if (start_dt - margin) <= local_ts <= (end_dt + margin):
                    return True
        return False

    def _as_exchange_ts(self, ts: datetime) -> datetime:
        if ts.tzinfo is None:
            return ts.replace(tzinfo=self.tz)
        return ts.astimezone(self.tz)

    def _eod_before_evening_clearing(self, ts: datetime) -> datetime:
        local_ts = self._as_exchange_ts(ts)
        for offset in range(0, 8):
            day = local_ts.date() + timedelta(days=offset)
            starts = sorted(start for start, _ in self._iter_windows_for_date(day, self.clearing))
            if not starts:
                continue
            evening_start = starts[-1]
            expiry = evening_start - timedelta(seconds=1)
            if local_ts < expiry:
                return expiry
        return self.next_session_end(ts)

    def _in_windows(self, ts: datetime, windows: list[TimeWindow]) -> bool:
        for day_offset in (-1, 0, 1):
            day = ts.date() + timedelta(days=day_offset)
            for start_dt, end_dt in self._iter_windows_for_date(day, windows):
                if start_dt <= ts <= end_dt:
                    return True
        return False

    def _iter_windows_for_date(self, day: date, windows: list[TimeWindow]) -> list[tuple[datetime, datetime]]:
        result: list[tuple[datetime, datetime]] = []
        for window in windows:
            start_dt = datetime.combine(day, window.start, tzinfo=self.tz)
            end_dt = datetime.combine(day, window.end, tzinfo=self.tz)
            if end_dt < start_dt:
                end_dt = end_dt + timedelta(days=1)
            result.append((start_dt, end_dt))
        return result
