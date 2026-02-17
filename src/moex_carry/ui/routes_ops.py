from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Callable

from flask import Flask, jsonify

from moex_carry.observability.runtime_metrics import ApiObservability


def register_ops_routes(
    server: Flask,
    *,
    session_factory,
    load_latest_signal_run_fn: Callable[[Any], Any],
    logger: logging.Logger,
    refresh_state: dict[str, object],
    iso_now: Callable[[], str],
    observe_request: Callable[[str, datetime, Any], Any],
    observability: ApiObservability,
) -> None:
    @server.route("/api/v2/ops/health", methods=["GET"])
    def ops_health_v2_api():
        started_at = datetime.now(timezone.utc)
        checks: dict[str, dict[str, object]] = {}
        db_status = "ok"
        db_message: str | None = None
        try:
            with session_factory() as session:
                load_latest_signal_run_fn(session)
        except Exception as exc:
            db_status = "error"
            db_message = str(exc)
            logger.exception("Ops health DB check failed")
        checks["database"] = {
            "status": db_status,
            "message": db_message,
        }
        checks["signal_refresh"] = {
            "status": str(refresh_state.get("status") or "unknown"),
            "enabled": bool(refresh_state.get("enabled")),
            "last_success_at": refresh_state.get("last_success_at"),
            "last_error": refresh_state.get("last_error"),
        }
        overall_status = "ok" if db_status == "ok" else "degraded"
        status_code = 200 if db_status == "ok" else 503
        result = (
            jsonify(
                {
                    "status": overall_status,
                    "timestamp": iso_now(),
                    "checks": checks,
                }
            ),
            status_code,
        )
        return observe_request("v2_ops_health", started_at, result)

    @server.route("/api/v2/ops/slo", methods=["GET"])
    def ops_slo_v2_api():
        started_at = datetime.now(timezone.utc)
        snapshot = observability.snapshot()
        endpoints = snapshot.get("endpoints")
        endpoint_stats = endpoints if isinstance(endpoints, dict) else {}
        actions_stats = (
            endpoint_stats.get("v2_signals_actions")
            if isinstance(endpoint_stats.get("v2_signals_actions"), dict)
            else {}
        )
        pretrade_stats = (
            endpoint_stats.get("v2_pretrade_check")
            if isinstance(endpoint_stats.get("v2_pretrade_check"), dict)
            else {}
        )
        auto_unwind_stats = (
            endpoint_stats.get("v2_auto_unwind_run")
            if isinstance(endpoint_stats.get("v2_auto_unwind_run"), dict)
            else {}
        )
        news_feed_stats = (
            endpoint_stats.get("v2_news_feed")
            if isinstance(endpoint_stats.get("v2_news_feed"), dict)
            else {}
        )
        news_backtest_stats = (
            endpoint_stats.get("v2_news_backtest")
            if isinstance(endpoint_stats.get("v2_news_backtest"), dict)
            else {}
        )
        news_compare_stats = (
            endpoint_stats.get("v2_news_compare")
            if isinstance(endpoint_stats.get("v2_news_compare"), dict)
            else {}
        )

        pretrade_failures_15m = observability.count_recent("pretrade_failure", window_sec=900)
        pretrade_degraded_15m = observability.count_recent("pretrade_degraded", window_sec=900)
        pretrade_errors_15m = observability.count_recent("pretrade_error", window_sec=900)
        execution_rejections_15m = observability.count_recent(
            "execution_rejected_fail_closed", window_sec=900
        )
        auto_unwind_triggered_15m = observability.count_recent("auto_unwind_triggered", window_sec=900)
        auto_unwind_errors_15m = observability.count_recent("auto_unwind_error", window_sec=900)
        news_gate_block_15m = observability.count_recent("news_gate_block", window_sec=900)
        news_gate_reduce_15m = observability.count_recent("news_gate_reduce", window_sec=900)
        news_signal_links_15m = observability.count_recent("news_signal_links", window_sec=900)
        news_feed_events_15m = observability.count_recent("news_feed_events", window_sec=900)
        news_feed_high_15m = observability.count_recent("news_feed_high_severity_events", window_sec=900)
        news_compare_runs_15m = observability.count_recent("news_compare_runs", window_sec=900)
        news_compare_win_finbert_15m = observability.count_recent("news_compare_win_finbert", window_sec=900)
        news_compare_win_nli_15m = observability.count_recent("news_compare_win_nli", window_sec=900)
        compare_win_total_15m = news_compare_win_finbert_15m + news_compare_win_nli_15m
        compare_win_rate = {
            "finbert": (
                float(news_compare_win_finbert_15m) / float(compare_win_total_15m)
                if compare_win_total_15m > 0
                else 0.0
            ),
            "nli": (
                float(news_compare_win_nli_15m) / float(compare_win_total_15m)
                if compare_win_total_15m > 0
                else 0.0
            ),
        }

        alerts: list[dict[str, object]] = []
        pretrade_p95 = float(((pretrade_stats.get("latency_ms") or {}).get("p95") or 0.0))
        action_p95 = float(((actions_stats.get("latency_ms") or {}).get("p95") or 0.0))
        if pretrade_p95 > 1_500.0:
            alerts.append(
                {
                    "code": "PRETRADE_LATENCY_HIGH",
                    "severity": "warning",
                    "message": "Pretrade p95 latency exceeds 1500 ms.",
                    "value": pretrade_p95,
                }
            )
        if action_p95 > 800.0:
            alerts.append(
                {
                    "code": "ACTION_LATENCY_HIGH",
                    "severity": "warning",
                    "message": "Signal action p95 latency exceeds 800 ms.",
                    "value": action_p95,
                }
            )
        if execution_rejections_15m >= 5:
            alerts.append(
                {
                    "code": "EXECUTION_REJECTION_SPIKE",
                    "severity": "critical",
                    "message": "Fail-closed execution rejections in the last 15m reached threshold.",
                    "value": execution_rejections_15m,
                }
            )
        if pretrade_failures_15m >= 10:
            alerts.append(
                {
                    "code": "PRETRADE_FAILURE_SPIKE",
                    "severity": "warning",
                    "message": "Pretrade failures in the last 15m reached threshold.",
                    "value": pretrade_failures_15m,
                }
            )
        if auto_unwind_errors_15m >= 1:
            alerts.append(
                {
                    "code": "AUTO_UNWIND_ERRORS",
                    "severity": "critical",
                    "message": "Auto-unwind errors detected in the last 15m.",
                    "value": auto_unwind_errors_15m,
                }
            )
        if news_gate_block_15m >= 10:
            alerts.append(
                {
                    "code": "NEWS_GATE_BLOCK_SPIKE",
                    "severity": "warning",
                    "message": "News gate block actions spiked in the last 15m.",
                    "value": news_gate_block_15m,
                }
            )

        result = jsonify(
            {
                "generated_at": snapshot.get("generated_at"),
                "slo_targets": {
                    "pretrade_p95_ms": 1500.0,
                    "signals_actions_p95_ms": 800.0,
                    "execution_rejections_15m": 5,
                    "pretrade_failures_15m": 10,
                    "auto_unwind_errors_15m": 1,
                    "news_gate_blocks_15m": 10,
                },
                "api": {
                    "v2_signals_actions": actions_stats,
                    "v2_pretrade_check": pretrade_stats,
                    "v2_auto_unwind_run": auto_unwind_stats,
                    "v2_news_feed": news_feed_stats,
                    "v2_news_backtest": news_backtest_stats,
                    "v2_news_compare": news_compare_stats,
                },
                "events_15m": {
                    "pretrade_failures": pretrade_failures_15m,
                    "pretrade_degraded": pretrade_degraded_15m,
                    "pretrade_errors": pretrade_errors_15m,
                    "execution_rejections_fail_closed": execution_rejections_15m,
                    "auto_unwind_triggered": auto_unwind_triggered_15m,
                    "auto_unwind_errors": auto_unwind_errors_15m,
                    "news_gate_blocks": news_gate_block_15m,
                    "news_gate_reduces": news_gate_reduce_15m,
                    "news_signal_links": news_signal_links_15m,
                    "news_feed_events": news_feed_events_15m,
                    "news_feed_high_severity_events": news_feed_high_15m,
                    "news_compare_runs": news_compare_runs_15m,
                    "news_compare_wins_finbert": news_compare_win_finbert_15m,
                    "news_compare_wins_nli": news_compare_win_nli_15m,
                },
                "signal_refresh_runtime": {
                    "status": refresh_state.get("status"),
                    "duration_ms": {
                        "p50": float(refresh_state.get("refresh_duration_ms_p50") or 0.0),
                        "p95": float(refresh_state.get("refresh_duration_ms_p95") or 0.0),
                    },
                    "ingest_lag_sec": refresh_state.get("ingest_lag_sec"),
                    "cache_hit_ratio": float(refresh_state.get("cache_hit_ratio") or 0.0),
                    "skip_reason": refresh_state.get("skip_reason"),
                    "fallback_full_replay_count": int(refresh_state.get("fallback_full_replay_count") or 0),
                },
                "news_compare_win_rate": compare_win_rate,
                "alerts": alerts,
            }
        )
        return observe_request("v2_ops_slo", started_at, result)
