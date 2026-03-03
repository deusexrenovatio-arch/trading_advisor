from __future__ import annotations

from datetime import datetime, timezone

from moex_carry.shock_alert_delivery import ShockAlertPolicy, apply_shock_alert_policy


def _row(
    *,
    shock_ts: str,
    symbol: str = "BRN",
    direction: str = "up",
    z_score: float = 3.0,
    topic_key: str = "iran-attack",
    headline: str = "Oil jumps after attack",
) -> dict[str, object]:
    return {
        "shock_ts": shock_ts,
        "symbol": symbol,
        "shock_direction": direction,
        "z_score": z_score,
        "abs_move_pct": 1.0,
        "topic_key": topic_key,
        "headline": headline,
    }


def test_policy_keeps_aftershock_in_same_episode_across_days():
    rows = [
        _row(shock_ts="2026-02-28T07:00:00Z", z_score=3.1),
        _row(
            shock_ts="2026-03-02T11:00:00Z",
            z_score=2.4,
            headline="Aftershock after weekend escalation",
        ),
    ]
    state: dict[str, object] = {}
    policy = ShockAlertPolicy(
        primary_min_z=2.5,
        aftershock_min_z=2.0,
        topic_reopen_after_hours=168,
        aftershock_cooldown_minutes=0,
        max_alerts_per_cycle=10,
        sent_fingerprint_ttl_hours=24 * 21,
    )

    alerts, changed = apply_shock_alert_policy(
        rows,
        now_utc=datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc),
        state=state,
        policy=policy,
    )

    assert changed is True
    assert [item["role"] for item in alerts] == ["primary", "aftershock"]
    assert alerts[0]["episode_id"] == alerts[1]["episode_id"]
    assert alerts[0]["episode_event_index"] == 1
    assert alerts[1]["episode_event_index"] == 2


def test_policy_respects_aftershock_cooldown():
    rows = [
        _row(shock_ts="2026-02-28T07:00:00Z", z_score=3.0),
        _row(
            shock_ts="2026-02-28T07:30:00Z",
            z_score=2.6,
            headline="Fast follow-up headline",
        ),
    ]
    state: dict[str, object] = {}
    policy = ShockAlertPolicy(
        primary_min_z=2.5,
        aftershock_min_z=2.0,
        topic_reopen_after_hours=168,
        aftershock_cooldown_minutes=60,
        max_alerts_per_cycle=10,
        sent_fingerprint_ttl_hours=24 * 21,
    )

    alerts, _ = apply_shock_alert_policy(
        rows,
        now_utc=datetime(2026, 2, 28, 8, 0, tzinfo=timezone.utc),
        state=state,
        policy=policy,
    )

    assert len(alerts) == 1
    assert alerts[0]["role"] == "primary"


def test_policy_deduplicates_and_cleans_old_fingerprints():
    state: dict[str, object] = {
        "sent_shock_fingerprints": {
            "stale_fp": "2026-01-01T00:00:00Z",
            "fresh_fp": "2026-03-01T00:00:00Z",
        }
    }
    rows = [
        _row(shock_ts="2026-03-02T09:00:00Z", z_score=3.0, headline="Unique event"),
        _row(shock_ts="2026-03-02T09:00:00Z", z_score=3.0, headline="Unique event"),
    ]
    policy = ShockAlertPolicy(
        primary_min_z=2.5,
        aftershock_min_z=2.0,
        topic_reopen_after_hours=168,
        aftershock_cooldown_minutes=0,
        max_alerts_per_cycle=10,
        sent_fingerprint_ttl_hours=24 * 7,
    )

    alerts, changed = apply_shock_alert_policy(
        rows,
        now_utc=datetime(2026, 3, 3, 0, 0, tzinfo=timezone.utc),
        state=state,
        policy=policy,
    )

    assert changed is True
    assert len(alerts) == 1
    sent = state.get("sent_shock_fingerprints")
    assert isinstance(sent, dict)
    assert "stale_fp" not in sent
    assert "fresh_fp" in sent
