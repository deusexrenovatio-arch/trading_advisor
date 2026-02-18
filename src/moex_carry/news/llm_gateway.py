from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime

import requests
from sqlalchemy.orm import Session

from moex_carry.config import AppSettings
from moex_carry.storage.repositories import (
    load_news_event_items,
    load_news_events,
    load_news_impact_scores,
    load_news_items_by_ids,
    load_news_llm_runs,
    upsert_news_labels,
    upsert_news_llm_runs,
)


_ALLOWED_MARKET_SCOPE = {"futures", "spot", "curve"}
_ALLOWED_DIRECTION = {"positive", "negative", "neutral", "uncertain"}
_ALLOWED_LAG = {"immediate", "short", "medium", "long"}
_ALLOWED_UNCERTAINTY = {"rumor", "forecast", "conflicting", "none"}


@dataclass(frozen=True)
class NewsLlmPassReport:
    processed_count: int
    completed_count: int
    skipped_count: int
    failed_count: int
    labeled_count: int
    provider: str
    model_id: str
    prompt_version: str
    token_in_total: int = 0
    token_out_total: int = 0
    budget_exhausted: bool = False
    budget_reason: str | None = None


def _clamp(value: object, minimum: float, maximum: float, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float(default)
    return max(min(numeric, maximum), minimum)


def _to_text(value: object) -> str:
    return str(value or "").strip()


def _truncate(value: str, limit: int) -> str:
    text = _to_text(value)
    if limit <= 0:
        return text
    return text[:limit]


def _label_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "commodity": {
                "type": "array",
                "items": {"type": "string"},
            },
            "market_scope": {
                "type": "string",
                "enum": sorted(_ALLOWED_MARKET_SCOPE),
            },
            "instrument_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "symbol": {"type": "string"},
                        "exchange": {"type": "string"},
                        "contract_hint": {"type": "string"},
                    },
                    "required": ["symbol"],
                },
            },
            "relevance": {"type": "number"},
            "news_type": {
                "type": "array",
                "items": {"type": "string"},
            },
            "direction": {
                "type": "string",
                "enum": sorted(_ALLOWED_DIRECTION),
            },
            "magnitude": {"type": "number"},
            "lag_bucket": {
                "type": "string",
                "enum": sorted(_ALLOWED_LAG),
            },
            "confidence": {"type": "number"},
            "uncertainty_type": {
                "type": "string",
                "enum": sorted(_ALLOWED_UNCERTAINTY),
            },
            "geo_scope": {"type": "string"},
            "evidence_spans": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "start": {"type": "integer"},
                        "end": {"type": "integer"},
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
            },
        },
        "required": [
            "commodity",
            "market_scope",
            "instrument_candidates",
            "relevance",
            "news_type",
            "direction",
            "magnitude",
            "lag_bucket",
            "confidence",
            "uncertainty_type",
            "geo_scope",
            "evidence_spans",
        ],
    }


def _normalize_event_input(
    *,
    event_row: dict[str, object],
    news_rows: list[dict[str, object]],
    max_input_chars: int,
) -> dict[str, object]:
    compact_news: list[dict[str, str]] = []
    for row in news_rows[:3]:
        compact_news.append(
            {
                "title": _truncate(row.get("title") or "", max_input_chars // 2),
                "content": _truncate(row.get("content") or "", max_input_chars),
                "source": _to_text(row.get("source")),
                "published_at": _to_text(row.get("published_at")),
            }
        )
    return {
        "event_id": _to_text(event_row.get("event_id")),
        "event_status": _to_text(event_row.get("event_status")),
        "canonical_summary": _truncate(event_row.get("canonical_summary") or "", max_input_chars // 2),
        "canonical_mechanism": _truncate(event_row.get("canonical_mechanism") or "", max_input_chars // 2),
        "published_at": _to_text(event_row.get("event_first_published_at_utc")),
        "linked_news": compact_news,
    }


def _build_input_hash(
    *,
    target_level: str,
    target_id: str,
    model_id: str,
    prompt_version: str,
    payload: dict[str, object],
) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    raw = "|".join([target_level.strip(), target_id.strip(), model_id.strip(), prompt_version.strip(), body])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _render_prompt(input_payload: dict[str, object], prompt_version: str) -> tuple[str, str]:
    system_prompt = (
        "You are a commodity futures news analyst. "
        "Return only valid JSON matching the provided schema. "
        "Use direction=positive when event supports higher futures prices, "
        "negative when event supports lower prices, neutral otherwise."
    )
    user_prompt = (
        f"prompt_version={prompt_version}\n"
        "Task: tag the event for futures impact.\n"
        f"Event payload:\n{json.dumps(input_payload, ensure_ascii=False)}"
    )
    return system_prompt, user_prompt


def _build_chat_completions_request(
    *,
    settings: AppSettings,
    input_payload: dict[str, object],
) -> dict[str, object]:
    system_prompt, user_prompt = _render_prompt(input_payload, settings.news_llm.prompt_version)
    return {
        "model": settings.news_llm.model_id,
        "temperature": float(settings.news_llm.temperature),
        "max_tokens": int(settings.news_llm.max_output_tokens),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "news_label",
                "strict": True,
                "schema": _label_schema(),
            },
        },
    }


def _extract_json_content(response_payload: dict[str, object]) -> dict[str, object]:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("openai_empty_choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("openai_invalid_choice")
    message = first.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("openai_missing_message")
    content = message.get("content")
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text_value = item.get("text")
            if isinstance(text_value, str):
                text_parts.append(text_value)
        content = "".join(text_parts).strip()
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("openai_empty_content")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("openai_invalid_json") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("openai_json_not_object")
    return parsed


def _normalize_label_payload(raw: dict[str, object]) -> dict[str, object]:
    commodity = raw.get("commodity")
    commodity_json = (
        sorted({str(item).strip().upper() for item in commodity if str(item).strip()})
        if isinstance(commodity, list)
        else []
    )
    news_type = raw.get("news_type")
    news_type_json = (
        sorted({str(item).strip().upper() for item in news_type if str(item).strip()})
        if isinstance(news_type, list)
        else []
    )
    instrument_candidates = raw.get("instrument_candidates")
    normalized_candidates: list[dict[str, str]] = []
    if isinstance(instrument_candidates, list):
        for item in instrument_candidates:
            if not isinstance(item, dict):
                continue
            symbol = _to_text(item.get("symbol"))
            if not symbol:
                continue
            normalized_candidates.append(
                {
                    "symbol": symbol.upper(),
                    "exchange": _to_text(item.get("exchange")),
                    "contract_hint": _to_text(item.get("contract_hint")),
                }
            )
    evidence_spans = raw.get("evidence_spans")
    normalized_evidence: list[dict[str, object]] = []
    if isinstance(evidence_spans, list):
        for item in evidence_spans:
            if not isinstance(item, dict):
                continue
            text_value = _to_text(item.get("text"))
            if not text_value:
                continue
            normalized_evidence.append(
                {
                    "start": int(item.get("start") or 0),
                    "end": int(item.get("end") or 0),
                    "text": text_value,
                }
            )

    market_scope = _to_text(raw.get("market_scope")).lower()
    if market_scope not in _ALLOWED_MARKET_SCOPE:
        market_scope = "futures"
    direction = _to_text(raw.get("direction")).lower()
    if direction not in _ALLOWED_DIRECTION:
        direction = "uncertain"
    lag_bucket = _to_text(raw.get("lag_bucket")).lower()
    if lag_bucket not in _ALLOWED_LAG:
        lag_bucket = "short"
    uncertainty_type = _to_text(raw.get("uncertainty_type")).lower()
    if uncertainty_type not in _ALLOWED_UNCERTAINTY:
        uncertainty_type = "none"

    return {
        "commodity_json": commodity_json,
        "market_scope": market_scope,
        "instrument_candidates_json": normalized_candidates,
        "relevance": _clamp(raw.get("relevance"), 0.0, 1.0, 0.0),
        "news_type_json": news_type_json,
        "direction": direction,
        "magnitude": _clamp(raw.get("magnitude"), 0.0, 3.0, 0.0),
        "lag_bucket": lag_bucket,
        "confidence": _clamp(raw.get("confidence"), 0.0, 1.0, 0.0),
        "uncertainty_type": uncertainty_type,
        "geo_scope": _to_text(raw.get("geo_scope")),
        "evidence_json": normalized_evidence,
    }


def _call_openai_structured(
    *,
    settings: AppSettings,
    input_payload: dict[str, object],
) -> tuple[dict[str, object], dict[str, int]]:
    api_key = os.getenv(settings.news_llm.api_key_env, "").strip()
    if not api_key:
        raise RuntimeError("missing_api_key")
    url = settings.news_llm.api_base_url.rstrip("/") + "/chat/completions"
    body = _build_chat_completions_request(settings=settings, input_payload=input_payload)
    started = time.perf_counter()
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=max(int(settings.news_llm.request_timeout_sec), 5),
    )
    response.raise_for_status()
    payload = response.json()
    parsed = _extract_json_content(payload)
    usage = payload.get("usage") if isinstance(payload, dict) else {}
    if not isinstance(usage, dict):
        usage = {}
    latency_ms = int((time.perf_counter() - started) * 1000.0)
    return parsed, {
        "token_in": int(usage.get("prompt_tokens") or 0),
        "token_out": int(usage.get("completion_tokens") or 0),
        "latency_ms": latency_ms,
    }


def _should_skip_cached(
    *,
    runs: list[dict[str, object]],
    provider: str,
    model_id: str,
    prompt_version: str,
    input_hash: str,
) -> bool:
    for row in runs:
        if not isinstance(row, dict):
            continue
        if str(row.get("provider") or "").strip() != provider:
            continue
        if str(row.get("model_id") or "").strip() != model_id:
            continue
        if str(row.get("prompt_version") or "").strip() != prompt_version:
            continue
        if str(row.get("input_hash") or "").strip() != input_hash:
            continue
        if str(row.get("status") or "").strip().lower() == "done":
            return True
    return False


def _load_llm_event_candidates(
    session: Session,
    *,
    llm_settings,
    model_id: str,
    prompt_version: str,
    effective_limit: int,
) -> list[dict[str, object]]:
    events = load_news_events(session, limit=max(effective_limit * 4, 200))
    if not events:
        return []

    event_ids = [str(row.get("event_id") or "").strip() for row in events if row.get("event_id")]
    event_items = load_news_event_items(session, event_ids=event_ids, limit=max(len(event_ids) * 20, 2000))
    event_to_news: dict[str, list[str]] = {}
    for row in event_items:
        event_id = _to_text(row.get("event_id"))
        news_id = _to_text(row.get("news_id"))
        if not event_id or not news_id:
            continue
        event_to_news.setdefault(event_id, []).append(news_id)
    all_news_ids = sorted(
        {
            news_id
            for values in event_to_news.values()
            for news_id in values
            if isinstance(news_id, str) and news_id
        }
    )
    news_by_id = {
        str(row.get("news_id") or "").strip(): row
        for row in load_news_items_by_ids(session, all_news_ids)
        if isinstance(row, dict)
    }
    score_rows = load_news_impact_scores(
        session,
        target_level="event",
        target_ids=event_ids,
        limit=max(len(event_ids) * 5, 2000),
    )
    impact_by_event: dict[str, float] = {}
    for row in score_rows:
        event_id = _to_text(row.get("target_id"))
        if not event_id:
            continue
        impact = abs(_clamp(row.get("impact_score"), 0.0, 1.0, 0.0))
        if impact >= float(impact_by_event.get(event_id, 0.0)):
            impact_by_event[event_id] = impact

    if llm_settings.top_impact_priority:
        events.sort(
            key=lambda row: (
                float(impact_by_event.get(_to_text(row.get("event_id")), 0.0)),
                _to_text(row.get("event_first_published_at_utc")),
            ),
            reverse=True,
        )

    candidates: list[dict[str, object]] = []
    for event_row in events:
        event_id = _to_text(event_row.get("event_id"))
        if not event_id:
            continue
        impact_value = float(impact_by_event.get(event_id, 0.0))
        if impact_value < float(llm_settings.min_impact_for_priority):
            continue
        linked_news = [news_by_id[news_id] for news_id in event_to_news.get(event_id, []) if news_id in news_by_id]
        input_payload = _normalize_event_input(
            event_row=event_row,
            news_rows=linked_news,
            max_input_chars=max(int(llm_settings.max_input_chars), 256),
        )
        input_hash = _build_input_hash(
            target_level="event",
            target_id=event_id,
            model_id=model_id,
            prompt_version=prompt_version,
            payload=input_payload,
        )
        candidates.append(
            {
                "event_id": event_id,
                "impact_value": impact_value,
                "input_payload": input_payload,
                "input_hash": input_hash,
            }
        )
        if effective_limit > 0 and len(candidates) >= effective_limit:
            break
    return candidates


def _budget_reason(
    *,
    llm_settings,
    call_count: int,
    token_in_total: int,
    token_out_total: int,
) -> str | None:
    max_calls = max(int(getattr(llm_settings, "max_calls_per_run", 0) or 0), 0)
    if max_calls > 0 and call_count >= max_calls:
        return "max_calls_per_run"

    max_prompt = max(int(getattr(llm_settings, "max_prompt_tokens_per_run", 0) or 0), 0)
    if max_prompt > 0 and token_in_total >= max_prompt:
        return "max_prompt_tokens_per_run"

    max_completion = max(int(getattr(llm_settings, "max_completion_tokens_per_run", 0) or 0), 0)
    if max_completion > 0 and token_out_total >= max_completion:
        return "max_completion_tokens_per_run"

    max_total = max(int(getattr(llm_settings, "max_total_tokens_per_run", 0) or 0), 0)
    if max_total > 0 and (token_in_total + token_out_total) >= max_total:
        return "max_total_tokens_per_run"

    return None


def build_news_llm_batch_requests(
    session: Session,
    settings: AppSettings,
    *,
    max_items: int | None = None,
    include_cached: bool = False,
) -> dict[str, object]:
    llm_settings = settings.news_llm
    provider = str(llm_settings.provider or "openai").strip() or "openai"
    model_id = str(llm_settings.model_id or "").strip() or "unknown"
    prompt_version = str(llm_settings.prompt_version or "news-v1").strip() or "news-v1"
    effective_limit = max(int(max_items or llm_settings.max_items_per_run), 0)

    if provider != "openai" or not llm_settings.enabled or effective_limit <= 0:
        return {
            "provider": provider,
            "model_id": model_id,
            "prompt_version": prompt_version,
            "requested_count": 0,
            "exported_count": 0,
            "skipped_cached_count": 0,
            "requests": [],
        }

    candidates = _load_llm_event_candidates(
        session,
        llm_settings=llm_settings,
        model_id=model_id,
        prompt_version=prompt_version,
        effective_limit=effective_limit,
    )
    if not candidates:
        return {
            "provider": provider,
            "model_id": model_id,
            "prompt_version": prompt_version,
            "requested_count": 0,
            "exported_count": 0,
            "skipped_cached_count": 0,
            "requests": [],
        }

    requests_rows: list[dict[str, object]] = []
    skipped_cached = 0
    for item in candidates:
        event_id = str(item.get("event_id") or "").strip()
        input_hash = str(item.get("input_hash") or "").strip()
        if not event_id or not input_hash:
            continue
        if not include_cached:
            existing_runs = load_news_llm_runs(
                session,
                target_level="event",
                target_id=event_id,
                limit=100,
            )
            if _should_skip_cached(
                runs=existing_runs,
                provider=provider,
                model_id=model_id,
                prompt_version=prompt_version,
                input_hash=input_hash,
            ):
                skipped_cached += 1
                continue
        body = _build_chat_completions_request(
            settings=settings,
            input_payload=item.get("input_payload") if isinstance(item.get("input_payload"), dict) else {},
        )
        requests_rows.append(
            {
                "custom_id": f"event:{event_id}:{input_hash[:12]}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": body,
            }
        )
    return {
        "provider": provider,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "requested_count": len(candidates),
        "exported_count": len(requests_rows),
        "skipped_cached_count": skipped_cached,
        "requests": requests_rows,
    }


def run_news_llm_full_pass(
    session: Session,
    settings: AppSettings,
    *,
    max_items: int | None = None,
) -> NewsLlmPassReport:
    llm_settings = settings.news_llm
    provider = str(llm_settings.provider or "openai").strip() or "openai"
    model_id = str(llm_settings.model_id or "").strip() or "unknown"
    prompt_version = str(llm_settings.prompt_version or "news-v1").strip() or "news-v1"
    effective_limit = max(int(max_items or llm_settings.max_items_per_run), 0)

    if not llm_settings.enabled or not llm_settings.full_pass_enabled or effective_limit <= 0:
        return NewsLlmPassReport(
            processed_count=0,
            completed_count=0,
            skipped_count=0,
            failed_count=0,
            labeled_count=0,
            provider=provider,
            model_id=model_id,
            prompt_version=prompt_version,
        )

    candidates = _load_llm_event_candidates(
        session,
        llm_settings=llm_settings,
        model_id=model_id,
        prompt_version=prompt_version,
        effective_limit=effective_limit,
    )
    if not candidates:
        return NewsLlmPassReport(
            processed_count=0,
            completed_count=0,
            skipped_count=0,
            failed_count=0,
            labeled_count=0,
            provider=provider,
            model_id=model_id,
            prompt_version=prompt_version,
        )

    completed = 0
    skipped = 0
    failed = 0
    labeled = 0
    processed = 0
    token_in_total = 0
    token_out_total = 0
    budget_exhausted = False
    budget_reason = None

    for candidate in candidates:
        budget_reason = _budget_reason(
            llm_settings=llm_settings,
            call_count=processed,
            token_in_total=token_in_total,
            token_out_total=token_out_total,
        )
        if budget_reason is not None:
            budget_exhausted = True
            break
        event_id = str(candidate.get("event_id") or "").strip()
        input_payload = candidate.get("input_payload") if isinstance(candidate.get("input_payload"), dict) else {}
        input_hash = str(candidate.get("input_hash") or "").strip()
        if not event_id or not input_hash:
            continue
        existing_runs = load_news_llm_runs(
            session,
            target_level="event",
            target_id=event_id,
            limit=100,
        )
        if _should_skip_cached(
            runs=existing_runs,
            provider=provider,
            model_id=model_id,
            prompt_version=prompt_version,
            input_hash=input_hash,
        ):
            skipped += 1
            continue

        retries = max(int(llm_settings.max_retries), 0) + 1
        run_status = "error"
        error_code = None
        usage_meta = {"token_in": 0, "token_out": 0, "latency_ms": None}
        normalized_label = None
        for attempt in range(retries):
            try:
                raw_label, usage_meta = _call_openai_structured(
                    settings=settings,
                    input_payload=input_payload,
                )
                normalized_label = _normalize_label_payload(raw_label)
                run_status = "done"
                error_code = None
                break
            except Exception as exc:  # pragma: no cover - exercised via tests/mocks
                error_code = str(exc).strip().lower() or exc.__class__.__name__.lower()
                run_status = "skipped" if error_code == "missing_api_key" else "error"
                if run_status == "skipped":
                    break
                if attempt < retries - 1:
                    delay = max(float(llm_settings.retry_backoff_sec), 0.0) * float(attempt + 1)
                    if delay > 0.0:
                        time.sleep(delay)

        token_in_total += int(usage_meta.get("token_in") or 0)
        token_out_total += int(usage_meta.get("token_out") or 0)

        upsert_news_llm_runs(
            session,
            [
                {
                    "target_level": "event",
                    "target_id": event_id,
                    "provider": provider,
                    "model_id": model_id,
                    "prompt_version": prompt_version,
                    "input_hash": input_hash,
                    "status": run_status,
                    "token_in": int(usage_meta.get("token_in") or 0),
                    "token_out": int(usage_meta.get("token_out") or 0),
                    "latency_ms": usage_meta.get("latency_ms"),
                    "error_code": error_code,
                    "created_at": datetime.utcnow().isoformat() + "Z",
                }
            ],
        )

        if normalized_label is not None and run_status == "done":
            upsert_news_labels(
                session,
                [
                    {
                        "target_level": "event",
                        "target_id": event_id,
                        **normalized_label,
                        "label_source": "llm",
                        "label_version": llm_settings.label_version,
                        "model_version": model_id,
                        "prompt_version": prompt_version,
                        "created_at": datetime.utcnow().isoformat() + "Z",
                    }
                ],
            )
            labeled += 1
            completed += 1
        elif run_status == "skipped":
            skipped += 1
        else:
            failed += 1
        processed += 1

    return NewsLlmPassReport(
        processed_count=processed,
        completed_count=completed,
        skipped_count=skipped,
        failed_count=failed,
        labeled_count=labeled,
        provider=provider,
        model_id=model_id,
        prompt_version=prompt_version,
        token_in_total=token_in_total,
        token_out_total=token_out_total,
        budget_exhausted=budget_exhausted,
        budget_reason=budget_reason,
    )
