from __future__ import annotations

from datetime import datetime, time as dt_time, timedelta, timezone
import logging
import threading
from typing import Callable


class SignalRefreshScheduler:
    def __init__(
        self,
        *,
        enabled: bool,
        refresh_interval_sec: int,
        refresh_daily_time: dt_time | None,
        refresh_tz,
        refresh_singleton: bool,
        refresh_lease_sec: int,
        refresh_lease_renew_sec: int,
        refresh_state: dict[str, object],
        refresh_stop: threading.Event,
        run_signal_refresh: Callable[[str, bool], bool],
        acquire_lease: Callable[[], bool],
        renew_lease: Callable[[], bool],
        release_lease: Callable[[], None],
        next_daily_run: Callable[[datetime, dt_time, object], datetime],
        logger: logging.Logger,
        daily_time_label: str | None,
    ) -> None:
        self.enabled = bool(enabled)
        self.refresh_interval_sec = int(refresh_interval_sec)
        self.refresh_daily_time = refresh_daily_time
        self.refresh_tz = refresh_tz
        self.refresh_singleton = bool(refresh_singleton)
        self.refresh_lease_sec = int(refresh_lease_sec)
        self.refresh_lease_renew_sec = int(refresh_lease_renew_sec)
        self.refresh_state = refresh_state
        self.refresh_stop = refresh_stop
        self.run_signal_refresh = run_signal_refresh
        self.acquire_lease = acquire_lease
        self.renew_lease = renew_lease
        self.release_lease = release_lease
        self.next_daily_run = next_daily_run
        self.logger = logger
        self.daily_time_label = daily_time_label
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        if self.refresh_daily_time is None and self.refresh_interval_sec <= 0:
            return
        self.refresh_state["status"] = "scheduled"
        self.thread = threading.Thread(
            target=self._refresh_loop,
            name="signal-refresh",
            daemon=True,
        )
        self.thread.start()
        if self.refresh_daily_time is not None:
            self.logger.info(
                "Signal refresh scheduler enabled (daily=%s singleton=%s lease_sec=%s)",
                self.daily_time_label,
                self.refresh_singleton,
                self.refresh_lease_sec,
            )
        else:
            self.logger.info(
                "Signal refresh scheduler enabled (interval=%ss singleton=%s lease_sec=%s)",
                self.refresh_interval_sec,
                self.refresh_singleton,
                self.refresh_lease_sec,
            )

    def _wait_with_optional_lease(
        self,
        wait_seconds: float,
        *,
        lease_held_now: bool,
    ) -> tuple[bool, bool]:
        remaining = max(float(wait_seconds), 0.0)
        current_lease = bool(lease_held_now)
        while remaining > 0:
            wait_slice = min(remaining, float(self.refresh_lease_renew_sec))
            if self.refresh_stop.wait(wait_slice):
                return True, current_lease
            remaining -= wait_slice
            if self.refresh_singleton and current_lease:
                current_lease = self.renew_lease()
                if not current_lease:
                    self.refresh_state["scheduler_role"] = "follower"
                    self.refresh_state["status"] = "scheduled_follower"
                    return False, False
        return False, current_lease

    def _refresh_loop(self) -> None:
        if self.refresh_daily_time is None and self.refresh_interval_sec <= 0:
            return
        lease_held = False
        try:
            while not self.refresh_stop.is_set():
                if self.refresh_singleton:
                    if lease_held:
                        lease_held = self.renew_lease()
                    if not lease_held:
                        lease_held = self.acquire_lease()
                    if not lease_held:
                        self.refresh_state["scheduler_role"] = "follower"
                        self.refresh_state["status"] = "scheduled_follower"
                        stopped, lease_held = self._wait_with_optional_lease(
                            float(self.refresh_lease_renew_sec),
                            lease_held_now=False,
                        )
                        if stopped:
                            break
                        continue
                    self.refresh_state["scheduler_role"] = "leader"
                else:
                    self.refresh_state["scheduler_role"] = "leader"

                if self.refresh_daily_time is not None:
                    next_run = self.next_daily_run(datetime.now(timezone.utc), self.refresh_daily_time, self.refresh_tz)
                    self.refresh_state["next_run_at"] = next_run.isoformat().replace("+00:00", "Z")
                    wait_seconds = max((next_run - datetime.now(timezone.utc)).total_seconds(), 0.0)
                    stopped, lease_held = self._wait_with_optional_lease(
                        wait_seconds,
                        lease_held_now=lease_held,
                    )
                    if stopped:
                        break
                    if self.refresh_singleton and not lease_held:
                        continue
                    self.run_signal_refresh("daily", False)
                else:
                    self.run_signal_refresh("interval", False)
                    self.refresh_state["next_run_at"] = (
                        datetime.now(timezone.utc) + timedelta(seconds=self.refresh_interval_sec)
                    ).isoformat().replace("+00:00", "Z")
                    stopped, lease_held = self._wait_with_optional_lease(
                        float(self.refresh_interval_sec),
                        lease_held_now=lease_held,
                    )
                    if stopped:
                        break
        finally:
            if self.refresh_singleton and lease_held:
                self.release_lease()
