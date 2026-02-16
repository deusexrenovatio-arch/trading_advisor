from __future__ import annotations

import argparse
from datetime import date, datetime
import sys
from typing import Any

import requests
import yaml


def _print_result(name: str, ok: bool, detail: str) -> None:
    status = "ok" if ok else "fail"
    print(f"{name}: {status} ({detail})")


def _print_skip(name: str, detail: str) -> None:
    print(f"{name}: skip ({detail})")


def _get_json(url: str) -> tuple[bool, str, Any]:
    try:
        response = requests.get(url, timeout=10)
    except requests.RequestException as exc:
        return False, f"request_error:{exc}", None
    if not response.ok:
        return False, f"status:{response.status_code}", None
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return False, f"content_type:{content_type}", None
    try:
        return True, "json", response.json()
    except ValueError as exc:
        return False, f"json_error:{exc}", None


def _require_list(data: Any) -> bool:
    return isinstance(data, list)


def _first_object(items: list[Any]) -> dict[str, Any] | None:
    for item in items:
        if isinstance(item, dict):
            return item
    return None


def _json_compatible(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_compatible(item) for item in value]
    return value


def _check_non_empty(name: str, data: list[Any], allow_empty: bool) -> tuple[bool, str]:
    if data:
        return True, f"len={len(data)}"
    if allow_empty:
        return True, "len=0 (allowed)"
    return False, "len=0"


def _to_status_set(raw: Any, default: int | None = None) -> set[int]:
    if raw is None:
        return {int(default)} if default is not None else set()
    if isinstance(raw, (int, str)):
        raw = [raw]
    if not isinstance(raw, list):
        return {int(default)} if default is not None else set()
    statuses: set[int] = set()
    for item in raw:
        try:
            statuses.add(int(item))
        except (TypeError, ValueError):
            continue
    if not statuses and default is not None:
        statuses.add(int(default))
    return statuses


def _extract_response_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "").strip()
    if isinstance(payload, dict):
        for key in ("message", "error", "detail", "details"):
            value = payload.get(key)
            if value is not None:
                return str(value).strip()
    return str(payload).strip()


def _should_skip_response(scenario: dict[str, Any], response: requests.Response) -> tuple[bool, str]:
    skip_statuses = _to_status_set(scenario.get("skip_on_statuses"))
    if response.status_code not in skip_statuses:
        return False, ""
    filters = scenario.get("skip_on_error_messages")
    if isinstance(filters, str):
        filters = [filters]
    message = _extract_response_message(response)
    if not filters:
        return True, f"status:{response.status_code}"
    normalized = [str(item) for item in filters if str(item).strip()]
    if not normalized:
        return True, f"status:{response.status_code}"
    lowered = message.lower()
    if any(token.lower() in lowered for token in normalized):
        return True, f"status:{response.status_code};message:{message}"
    return False, ""


def _load_config(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except FileNotFoundError:
        return {}


def _build_url(base: str, url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not url.startswith("/"):
        url = f"/{url}"
    return f"{base}{url}"


def run(args: argparse.Namespace) -> int:
    failures = 0
    backend = args.backend_url.rstrip("/")
    frontend = args.frontend_url.rstrip("/")
    config = _load_config(args.config)
    scenarios = config.get("scenarios") or []
    cache: dict[str, Any] = {}

    for scenario in scenarios:
        scenario_id = str(scenario.get("id", "scenario"))
        scope = str(scenario.get("scope", "backend"))
        allow_empty = bool(scenario.get("allow_empty", args.allow_empty))
        require_non_empty = bool(scenario.get("require_non_empty", False))

        if scope == "frontend" and args.skip_frontend:
            _print_skip(scenario_id, "skip-frontend flag")
            continue

        if scenario.get("type") == "http_status":
            url = _build_url(frontend if scope == "frontend" else backend, scenario.get("url", "/"))
            expected_statuses = _to_status_set(
                scenario.get("expected_statuses"),
                default=200,
            )
            try:
                response = requests.get(url, timeout=5)
                should_skip, reason = _should_skip_response(scenario, response)
                if should_skip:
                    _print_skip(scenario_id, reason)
                    continue
                ok = response.status_code in expected_statuses
                detail = f"status:{response.status_code}"
            except requests.RequestException as exc:
                ok = False
                detail = f"request_error:{exc}"
            _print_result(scenario_id, ok, detail)
            failures += 0 if ok else 1
            continue

        if scenario.get("type") == "spread_series":
            pair_source = scenario.get("pair_source", "top-pairs")
            pair_list = cache.get(pair_source)
            if not pair_list:
                source_url = str(scenario.get("source_url", "/api/top-pairs?limit=1"))
                ok, detail, pair_list = _get_json(_build_url(backend, source_url))
                if not (ok and _require_list(pair_list) and pair_list):
                    if allow_empty:
                        _print_skip(scenario_id, "missing_pair_source")
                    else:
                        _print_result(scenario_id, False, "missing_pair_source")
                        failures += 1
                    continue
            pair = _first_object(pair_list)
            if not pair:
                _print_result(scenario_id, False, "invalid_pair_source")
                failures += 1
                continue
            stock = pair.get("stock")
            future = pair.get("future")
            if not stock or not future:
                _print_result(scenario_id, False, "missing_pair_fields")
                failures += 1
                continue
            window_days = int(scenario.get("window_days", 60))
            try:
                path = str(
                    scenario.get("url_template", "/api/spread-series?stock={stock}&future={future}&window_days={window_days}")
                ).format(stock=stock, future=future, window_days=window_days)
            except KeyError as exc:
                _print_result(scenario_id, False, f"missing_template_key:{exc}")
                failures += 1
                continue
            url = _build_url(backend, path)
            ok, detail, data = _get_json(url)
            required = set(scenario.get("required_keys", []))
            if ok and _require_list(data):
                if data:
                    if required:
                        missing = required.difference(set(data[0].keys()))
                        if missing:
                            ok = False
                            detail = f"missing_fields:{sorted(missing)}"
                        else:
                            detail = f"len={len(data)}"
                    else:
                        detail = f"len={len(data)}"
                elif require_non_empty and not allow_empty:
                    ok, detail = _check_non_empty(scenario_id, data, allow_empty)
            else:
                ok = False
            _print_result(scenario_id, ok, detail)
            failures += 0 if ok else 1
            continue

        if scenario.get("type") == "signal_action":
            active_url = str(scenario.get("active_url", "/api/v2/signals/active?limit=1"))
            ok, detail, rows = _get_json(_build_url(backend, active_url))
            if not (ok and _require_list(rows)):
                _print_result(scenario_id, False, f"active_source_error:{detail}")
                failures += 1
                continue
            if not rows:
                if allow_empty or not require_non_empty:
                    _print_skip(scenario_id, "no_active_rows")
                    continue
                _print_result(scenario_id, False, "no_active_rows")
                failures += 1
                continue

            row = _first_object(rows)
            if not row:
                _print_result(scenario_id, False, "invalid_active_row")
                failures += 1
                continue

            signal_id_value = row.get("signal_id")
            signal_id = str(signal_id_value).strip() if signal_id_value is not None else ""
            if not signal_id:
                _print_result(scenario_id, False, "missing_signal_id")
                failures += 1
                continue

            template = str(scenario.get("url_template", "/api/v2/signals/{signal_id}/actions"))
            try:
                path = template.format(**{**row, "signal_id": signal_id})
            except KeyError as exc:
                _print_result(scenario_id, False, f"missing_template_key:{exc}")
                failures += 1
                continue
            url = _build_url(backend, path)

            payload_raw = scenario.get("payload", {})
            if not isinstance(payload_raw, dict):
                _print_result(scenario_id, False, "invalid_payload")
                failures += 1
                continue
            payload = _json_compatible(dict(payload_raw))
            if not str(payload.get("idempotency_key") or "").strip():
                payload["idempotency_key"] = f"acceptance-{scenario_id}-{signal_id}"

            expected_http_statuses_raw = scenario.get("expected_http_statuses")
            if expected_http_statuses_raw is None:
                expected_http_statuses_raw = [int(scenario.get("expected_status", 200))]
            if isinstance(expected_http_statuses_raw, (int, str)):
                expected_http_statuses_raw = [expected_http_statuses_raw]
            try:
                expected_http_statuses = {int(status) for status in expected_http_statuses_raw}
            except (TypeError, ValueError):
                _print_result(scenario_id, False, "invalid_expected_http_statuses")
                failures += 1
                continue

            try:
                response = requests.post(url, json=payload, timeout=10)
            except requests.RequestException as exc:
                _print_result(scenario_id, False, f"request_error:{exc}")
                failures += 1
                continue
            if response.status_code not in expected_http_statuses:
                _print_result(scenario_id, False, f"status:{response.status_code}")
                failures += 1
                continue
            try:
                data = response.json()
            except ValueError as exc:
                _print_result(scenario_id, False, f"json_error:{exc}")
                failures += 1
                continue
            if not isinstance(data, dict):
                _print_result(scenario_id, False, "non_object_response")
                failures += 1
                continue

            required_keys = scenario.get("required_keys", [])
            if required_keys:
                missing = set(required_keys).difference(set(data.keys()))
                if missing:
                    _print_result(scenario_id, False, f"missing_keys:{sorted(missing)}")
                    failures += 1
                    continue

            allowed_statuses_raw = scenario.get("allowed_response_status", [])
            allowed_statuses = {str(status) for status in allowed_statuses_raw}
            if allowed_statuses:
                response_status = str(data.get("status") or "")
                if response_status not in allowed_statuses:
                    _print_result(
                        scenario_id,
                        False,
                        f"invalid_response_status:{response_status}",
                    )
                    failures += 1
                    continue

            required_keys_by_status = scenario.get("required_keys_by_status", {})
            if isinstance(required_keys_by_status, dict):
                response_status = str(data.get("status") or "")
                status_required = required_keys_by_status.get(response_status)
                if isinstance(status_required, list) and status_required:
                    missing = set(status_required).difference(set(data.keys()))
                    if missing:
                        _print_result(
                            scenario_id,
                            False,
                            f"missing_keys_for_{response_status}:{sorted(missing)}",
                        )
                        failures += 1
                        continue

            _print_result(scenario_id, True, f"status:{response.status_code}")
            continue

        if scenario.get("type") == "api_object":
            template = str(scenario.get("url_template") or scenario.get("url") or "/")
            context: dict[str, Any] = {}
            pair_source = scenario.get("pair_source")
            if pair_source:
                pair_list = cache.get(pair_source)
                if not pair_list:
                    source_url = scenario.get("source_url", "/api/top-pairs?limit=1")
                    ok, detail, pair_list = _get_json(_build_url(backend, source_url))
                    if not (ok and _require_list(pair_list) and pair_list):
                        if allow_empty:
                            _print_skip(scenario_id, "missing_pair_source")
                            continue
                        _print_result(scenario_id, False, "missing_pair_source")
                        failures += 1
                        continue
                pair = pair_list[0]
                if not isinstance(pair, dict):
                    _print_result(scenario_id, False, "invalid_pair_source")
                    failures += 1
                    continue
                context.update(pair)
            try:
                path = template.format(**context)
            except KeyError as exc:
                _print_result(scenario_id, False, f"missing_template_key:{exc}")
                failures += 1
                continue

            url = _build_url(frontend if scope == "frontend" else backend, path)
            ok, detail, data = _get_json(url)
            if ok and isinstance(data, dict):
                required_keys = scenario.get("required_keys", [])
                if required_keys:
                    missing = set(required_keys).difference(set(data.keys()))
                    if missing:
                        ok = False
                        detail = f"missing_keys:{sorted(missing)}"
                    else:
                        detail = "ok"
                else:
                    detail = "ok"
            else:
                ok = False
            _print_result(scenario_id, ok, detail)
            failures += 0 if ok else 1
            continue

        if scenario.get("type") == "decision_log_detail":
            source_url = scenario.get("source_url", "/api/decision-view?limit=1")
            ok, detail, data = _get_json(_build_url(backend, source_url))
            if not (ok and _require_list(data)):
                _print_result(scenario_id, False, f"source_error:{detail}")
                failures += 1
                continue
            if not data:
                if allow_empty or not require_non_empty:
                    _print_skip(scenario_id, "no_decision_rows")
                    continue
                _print_result(scenario_id, False, "no_decision_rows")
                failures += 1
                continue
            id_field = scenario.get("id_field", "decision_id")
            decision_id = data[0].get(id_field)
            if not decision_id:
                _print_result(scenario_id, False, "missing_decision_id")
                failures += 1
                continue
            template = scenario.get("url_template", "/api/decision-log/{decision_id}")
            url = _build_url(backend, template.format(decision_id=decision_id))
            ok, detail, payload = _get_json(url)
            if not (ok and isinstance(payload, dict)):
                _print_result(scenario_id, False, f"log_error:{detail}")
                failures += 1
                continue
            required_keys = scenario.get("required_keys", [])
            if required_keys:
                missing = set(required_keys).difference(set(payload.keys()))
                if missing:
                    _print_result(scenario_id, False, f"missing_keys:{sorted(missing)}")
                    failures += 1
                    continue
            _print_result(scenario_id, True, "ok")
            continue

        if scenario.get("type") == "decision_action":
            source_url = scenario.get("source_url", "/api/decision-view?limit=1")
            ok, detail, data = _get_json(_build_url(backend, source_url))
            if not (ok and _require_list(data)):
                _print_result(scenario_id, False, f"source_error:{detail}")
                failures += 1
                continue
            if not data:
                if allow_empty or not require_non_empty:
                    _print_skip(scenario_id, "no_decision_rows")
                    continue
                _print_result(scenario_id, False, "no_decision_rows")
                failures += 1
                continue
            id_field = scenario.get("id_field", "decision_id")
            decision_id = data[0].get(id_field)
            if not decision_id:
                _print_result(scenario_id, False, "missing_decision_id")
                failures += 1
                continue
            template = scenario.get("url_template", "/api/decisions/{decision_id}/action")
            url = _build_url(backend, template.format(decision_id=decision_id))
            payload = scenario.get("payload", {})
            payload = _json_compatible(payload)
            try:
                response = requests.post(url, json=payload, timeout=10)
            except requests.RequestException as exc:
                _print_result(scenario_id, False, f"request_error:{exc}")
                failures += 1
                continue
            if response.status_code != int(scenario.get("expected_status", 200)):
                _print_result(scenario_id, False, f"status:{response.status_code}")
                failures += 1
                continue
            try:
                data = response.json()
            except ValueError as exc:
                _print_result(scenario_id, False, f"json_error:{exc}")
                failures += 1
                continue
            required_keys = scenario.get("required_keys", [])
            if required_keys and isinstance(data, dict):
                missing = set(required_keys).difference(set(data.keys()))
                if missing:
                    _print_result(scenario_id, False, f"missing_keys:{sorted(missing)}")
                    failures += 1
                    continue
            _print_result(scenario_id, True, "ok")
            continue

        if scenario.get("type") == "backtest_run":
            pair_source = scenario.get("pair_source", "top_pairs")
            pair_list = cache.get(pair_source)
            if not pair_list:
                source_url = str(scenario.get("source_url", "/api/top-pairs?limit=1"))
                ok, detail, pair_list = _get_json(_build_url(backend, source_url))
                if not (ok and _require_list(pair_list) and pair_list):
                    if allow_empty:
                        _print_skip(scenario_id, "missing_pair_source")
                    else:
                        _print_result(scenario_id, False, "missing_pair_source")
                        failures += 1
                    continue
            pair = _first_object(pair_list)
            if not pair:
                _print_result(scenario_id, False, "invalid_pair_source")
                failures += 1
                continue
            stock = pair.get("stock")
            future = pair.get("future")
            if not stock or not future:
                _print_result(scenario_id, False, "missing_pair_fields")
                failures += 1
                continue
            window_days = int(scenario.get("window_days", 60))
            try:
                series_path = str(
                    scenario.get(
                        "series_url_template",
                        "/api/spread-series?stock={stock}&future={future}&window_days={window_days}",
                    )
                ).format(stock=stock, future=future, window_days=window_days)
            except KeyError as exc:
                _print_result(scenario_id, False, f"missing_template_key:{exc}")
                failures += 1
                continue
            series_url = _build_url(backend, series_path)
            ok, detail, series = _get_json(series_url)
            if not (ok and _require_list(series) and series):
                _print_result(scenario_id, False, "missing_spread_series")
                failures += 1
                continue
            start_date = series[0].get("date")
            end_date = series[-1].get("date")
            if not start_date or not end_date:
                _print_result(scenario_id, False, "missing_series_dates")
                failures += 1
                continue
            payload = {
                "test": {"start_date": start_date, "end_date": end_date},
                "universe": {"include_stocks": [stock], "include_futures": [future], "max_pairs": 1},
            }
            precompute = scenario.get("precompute")
            if precompute is not None:
                payload["precompute"] = bool(precompute)
            expected_status = int(scenario.get("expected_status", 200))
            url = _build_url(backend, scenario.get("url", "/api/backtest/run"))
            try:
                response = requests.post(url, json=_json_compatible(payload), timeout=30)
            except requests.RequestException as exc:
                _print_result(scenario_id, False, f"request_error:{exc}")
                failures += 1
                continue
            if response.status_code != expected_status:
                _print_result(scenario_id, False, f"status:{response.status_code}")
                failures += 1
                continue
            try:
                data = response.json()
            except ValueError as exc:
                _print_result(scenario_id, False, f"json_error:{exc}")
                failures += 1
                continue
            required_keys = scenario.get("required_keys", [])
            if required_keys and isinstance(data, dict):
                missing = set(required_keys).difference(set(data.keys()))
                if missing:
                    _print_result(scenario_id, False, f"missing_keys:{sorted(missing)}")
                    failures += 1
                    continue
            _print_result(scenario_id, True, "ok")
            continue

        if scenario.get("type") == "history_date_range":
            history_source = scenario.get("history_source")
            history_list = cache.get(history_source) if history_source else None
            if not history_list:
                history_url = scenario.get("source_url", "/api/signals/history?limit=1")
                ok, detail, history_list = _get_json(_build_url(backend, history_url))
                if not (ok and _require_list(history_list) and history_list):
                    if allow_empty:
                        _print_skip(scenario_id, "no_history_rows")
                        continue
                    _print_result(scenario_id, False, "missing_history_rows")
                    failures += 1
                    continue
            timestamp_field = scenario.get("timestamp_field", "timestamp")
            timestamp = str(history_list[0].get(timestamp_field, ""))
            if not timestamp:
                _print_result(scenario_id, False, "missing_timestamp")
                failures += 1
                continue
            date_value = timestamp.split("T")[0].split(" ")[0]
            try:
                history_path = str(
                    scenario.get("url_template", "/api/signals/history?from={date_from}&to={date_to}")
                ).format(date_from=date_value, date_to=date_value)
            except KeyError as exc:
                _print_result(scenario_id, False, f"missing_template_key:{exc}")
                failures += 1
                continue
            url = _build_url(backend, history_path)
            ok, detail, data = _get_json(url)
            if ok and _require_list(data):
                if data:
                    detail = f"len={len(data)}"
                    required_keys = scenario.get("required_keys", [])
                    if required_keys:
                        missing = set(required_keys).difference(set(data[0].keys()))
                        if missing:
                            ok = False
                            detail = f"missing_keys:{sorted(missing)}"
                else:
                    ok = False
                    detail = "len=0"
            else:
                ok = False
            _print_result(scenario_id, ok, detail)
            failures += 0 if ok else 1
            continue

        if scenario.get("type") == "post_json":
            url = _build_url(frontend if scope == "frontend" else backend, scenario.get("url", "/"))
            payload = scenario.get("payload", {})
            payload = _json_compatible(payload)
            expected_statuses = _to_status_set(
                scenario.get("expected_statuses"),
                default=int(scenario.get("expected_status", 200)),
            )
            try:
                response = requests.post(url, json=payload, timeout=10)
            except requests.RequestException as exc:
                _print_result(scenario_id, False, f"request_error:{exc}")
                failures += 1
                continue
            should_skip, reason = _should_skip_response(scenario, response)
            if should_skip:
                _print_skip(scenario_id, reason)
                continue
            if response.status_code not in expected_statuses:
                _print_result(scenario_id, False, f"status:{response.status_code}")
                failures += 1
                continue
            try:
                data = response.json()
            except ValueError as exc:
                _print_result(scenario_id, False, f"json_error:{exc}")
                failures += 1
                continue
            required_keys = scenario.get("required_keys", [])
            if required_keys and isinstance(data, dict):
                missing = set(required_keys).difference(set(data.keys()))
                if missing:
                    _print_result(scenario_id, False, f"missing_keys:{sorted(missing)}")
                    failures += 1
                    continue
            _print_result(scenario_id, True, "ok")
            continue

        url = _build_url(frontend if scope == "frontend" else backend, scenario.get("url", "/"))
        ok, detail, data = _get_json(url)
        if ok and _require_list(data):
            if require_non_empty and not allow_empty:
                ok, detail = _check_non_empty(scenario_id, data, allow_empty)
            else:
                detail = f"len={len(data)}"
            required_keys = scenario.get("required_keys", [])
            if ok and required_keys and data:
                missing = set(required_keys).difference(set(data[0].keys()))
                if missing:
                    ok = False
                    detail = f"missing_keys:{sorted(missing)}"
            forbid_keys = scenario.get("forbid_keys", [])
            if ok and forbid_keys and data:
                if any(key in data[0] for key in forbid_keys):
                    ok = False
                    detail = f"forbidden_keys:{forbid_keys}"
            allowed_values = scenario.get("allowed_field_values", {})
            if ok and allowed_values and data:
                for field, allowed in allowed_values.items():
                    invalid = [row.get(field) for row in data if row.get(field) not in set(allowed)]
                    if invalid:
                        ok = False
                        detail = f"invalid_{field}:{invalid[:3]}"
                        break
        else:
            ok = False
        _print_result(scenario_id, ok, detail)
        failures += 0 if ok else 1

        cache_as = scenario.get("cache_as")
        if cache_as and ok:
            cache[str(cache_as)] = data

    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Acceptance smoke checks")
    parser.add_argument("--config", default="configs/acceptance_scenarios.yaml")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8050")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:5176")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--allow-empty", action="store_true")
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
