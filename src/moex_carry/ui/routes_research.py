from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable

from flask import Flask, jsonify, request
from pydantic import ValidationError

from moex_carry.contracts.strategy_test import BacktestRequest, HpoRequest


def _ui_app_module():
    from moex_carry.ui import app as ui_app

    return ui_app


def register_research_routes(
    *,
    server: Flask,
    paths,
    logger: logging.Logger,
    bad_request: Callable[..., object],
    parse_bool: Callable[[object], bool | None],
) -> None:
    @server.route("/api/v2/research/backtests/run", methods=["POST"])
    def backtest_run_v2_api():
        payload = request.get_json(silent=True)
        if payload is None or not isinstance(payload, dict):
            return bad_request("invalid_json")
        experiment_id = str(payload.get("experiment_id") or f"exp-{uuid.uuid4().hex[:12]}")
        precompute = parse_bool(payload.get("precompute"))
        compute_fill_quality = parse_bool(payload.get("compute_fill_quality"))
        if precompute is None:
            precompute = True
        if compute_fill_quality is None:
            compute_fill_quality = True
        request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else payload
        if not isinstance(request_payload, dict):
            return bad_request("missing_request")
        request_payload = {
            key: value
            for key, value in request_payload.items()
            if key not in {"precompute", "compute_fill_quality"}
        }
        try:
            backtest_request = BacktestRequest.model_validate(request_payload)
        except ValidationError as exc:
            return bad_request("validation_error", details=exc.errors())
        try:
            report = _ui_app_module().run_backtest_v2_cached(
                backtest_request,
                paths.data_dir,
                precompute=precompute,
                compute_fill_quality=compute_fill_quality,
            )
        except ValueError as exc:
            return bad_request(str(exc))
        except Exception as exc:
            logger.exception("Backtest v2 failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500

        request_hash = hashlib.sha1(
            json.dumps(request_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return jsonify(
            {
                "experiment_id": experiment_id,
                "run_id": f"bt-{uuid.uuid4().hex[:12]}",
                "request_hash": request_hash,
                "status": "completed",
                "report": _ui_app_module().serialize_backtest_report(report),
            }
        )

    @server.route("/api/v2/research/hpo/run", methods=["POST"])
    def hpo_run_v2_api():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return bad_request("invalid_json")
        experiment_id = str(payload.get("experiment_id") or f"exp-{uuid.uuid4().hex[:12]}")
        precompute = parse_bool(payload.get("precompute"))
        if precompute is None:
            precompute = True
        request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else payload
        if not isinstance(request_payload, dict):
            return bad_request("missing_request")
        request_payload = {key: value for key, value in request_payload.items() if key != "precompute"}
        optimization = request_payload.get("optimization") if isinstance(request_payload, dict) else None
        max_trials_override = None
        if not (isinstance(optimization, dict) and "max_trials" in optimization):
            max_trials_override = 10
        try:
            hpo_request = HpoRequest.model_validate(request_payload)
        except ValidationError as exc:
            return bad_request("validation_error", details=exc.errors())
        try:
            run_info = _ui_app_module().start_hpo_run(
                hpo_request,
                paths.data_dir,
                precompute=precompute,
                max_trials_override=max_trials_override,
            )
        except ValueError as exc:
            return bad_request(str(exc))
        except Exception as exc:
            logger.exception("HPO run failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500

        request_hash = hashlib.sha1(
            json.dumps(request_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return jsonify(
            {
                **run_info,
                "experiment_id": experiment_id,
                "request_hash": request_hash,
            }
        )

    @server.route("/api/v2/research/hpo/status", methods=["GET"])
    def hpo_status_v2_api():
        run_id = request.args.get("run_id")
        try:
            status = _ui_app_module().load_hpo_status(paths.data_dir, run_id=run_id)
        except ValueError as exc:
            return bad_request(str(exc))
        except Exception as exc:
            logger.exception("HPO status failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500

        payload = dict(status) if isinstance(status, dict) else {"status": "unknown"}
        run_state = str(payload.get("status") or "").lower()
        result = payload.get("result")
        leaderboard = []
        quality_review = None
        if isinstance(result, dict):
            raw = result.get("leaderboard")
            if isinstance(raw, list):
                leaderboard = raw
            quality_candidate = result.get("quality_review")
            if isinstance(quality_candidate, dict):
                quality_review = quality_candidate
        if not leaderboard and isinstance(payload.get("leaderboard"), list):
            leaderboard = payload.get("leaderboard")

        quality_checks: list[str] = []
        if isinstance(quality_review, dict) and not bool(quality_review.get("skipped")):
            pass_count = int(quality_review.get("quality_gate_pass_count") or 0)
            if pass_count > 0:
                quality_checks.append("quality_gate_pass")
            else:
                quality_checks.append("quality_gate_fail")

        if run_state == "completed" and leaderboard and ("quality_gate_fail" not in quality_checks):
            promotion_gate = {"status": "pass", "checks": ["leaderboard_present", "completed"]}
            if quality_checks:
                promotion_gate["checks"].extend(quality_checks)
        elif run_state == "completed" and "quality_gate_fail" in quality_checks:
            promotion_gate = {"status": "fail", "checks": ["quality_gate_fail", "leaderboard_present"]}
        elif run_state == "completed":
            promotion_gate = {"status": "fail", "checks": ["leaderboard_missing"]}
        elif run_state == "failed":
            promotion_gate = {"status": "fail", "checks": ["run_failed"]}
        else:
            promotion_gate = {"status": "pending", "checks": ["run_in_progress"]}
        payload["promotion_gate"] = promotion_gate
        return jsonify(payload)
