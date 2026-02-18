from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from moex_carry.config import AppSettings
from moex_carry.news.llm_gateway import (
    _label_schema,
    _normalize_event_input,
    _normalize_label_payload,
    _render_prompt,
)
from moex_carry.storage.repositories import (
    load_news_annotations,
    load_news_entity_links,
    load_news_event_items,
    load_news_events,
    load_news_impact_scores,
    load_news_items_by_ids,
    load_news_labels,
    upsert_news_annotations,
    upsert_news_labels,
)


@dataclass(frozen=True)
class NewsHitlTask:
    task_id: str
    event_id: str
    published_at: str | None
    event_status: str
    impact_estimate: float
    news_count: int
    prompt_version: str
    input_payload: dict[str, object]
    system_prompt: str
    user_prompt: str

    def to_dict(self) -> dict[str, object]:
        response_template = {
            "event_id": self.event_id,
            "label": {
                "commodity": [],
                "market_scope": "futures",
                "instrument_candidates": [],
                "relevance": 0.5,
                "news_type": [],
                "direction": "neutral",
                "magnitude": 0.5,
                "lag_bucket": "short",
                "confidence": 0.5,
                "uncertainty_type": "none",
                "geo_scope": "",
                "evidence_spans": [],
            },
        }
        return {
            "task_id": self.task_id,
            "event_id": self.event_id,
            "published_at": self.published_at,
            "event_status": self.event_status,
            "impact_estimate": self.impact_estimate,
            "news_count": self.news_count,
            "prompt_version": self.prompt_version,
            "input_payload": self.input_payload,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "schema": _label_schema(),
            "response_template": response_template,
        }


def _parse_iso_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _event_impact(
    *,
    event_news_ids: list[str],
    score_rows_by_news: dict[str, list[dict[str, object]]],
) -> float:
    best = 0.0
    for news_id in event_news_ids:
        for score in score_rows_by_news.get(news_id, []):
            impact = float(score.get("impact_score") or 0.0)
            directional = abs(float(score.get("prob_up") or 0.0) - float(score.get("prob_down") or 0.0))
            candidate = max(impact, directional)
            if candidate > best:
                best = candidate
    return max(min(best, 1.0), 0.0)


def _task_id(event_id: str, prompt_version: str) -> str:
    digest = hashlib.sha1(f"{event_id}|{prompt_version}".encode("utf-8")).hexdigest()[:12]
    return f"hitl-{digest}"


def build_news_hitl_tasks(
    session: Session,
    settings: AppSettings,
    *,
    max_items: int,
    min_impact: float = 0.0,
    only_unlabeled: bool = True,
    ticker: str | None = None,
) -> list[NewsHitlTask]:
    effective_limit = max(int(max_items), 0)
    if effective_limit <= 0:
        return []
    events = load_news_events(session, limit=max(effective_limit * 8, 200))
    if not events:
        return []
    event_ids = [str(row.get("event_id") or "").strip() for row in events if row.get("event_id")]
    if not event_ids:
        return []
    event_items = load_news_event_items(session, event_ids=event_ids, limit=max(len(event_ids) * 30, 2000))
    event_to_news: dict[str, list[str]] = {}
    for row in event_items:
        event_id = str(row.get("event_id") or "").strip()
        news_id = str(row.get("news_id") or "").strip()
        if not event_id or not news_id:
            continue
        event_to_news.setdefault(event_id, []).append(news_id)
    all_news_ids = sorted({news_id for values in event_to_news.values() for news_id in values if news_id})
    news_by_id = {
        str(item.get("news_id") or "").strip(): item
        for item in load_news_items_by_ids(session, all_news_ids)
        if isinstance(item, dict)
    }
    ticker_filter = str(ticker or "").strip().upper()
    eligible_news_ids: set[str] | None = None
    if ticker_filter:
        entity_rows = load_news_entity_links(
            session,
            news_ids=all_news_ids,
            ticker=ticker_filter,
            limit=max(len(all_news_ids) * 8, 5000),
        )
        eligible_news_ids = {
            str(row.get("news_id") or "").strip() for row in entity_rows if str(row.get("news_id") or "").strip()
        }
        if not eligible_news_ids:
            return []

    score_news_ids = (
        [news_id for news_id in all_news_ids if news_id in eligible_news_ids]
        if isinstance(eligible_news_ids, set)
        else all_news_ids
    )
    score_rows = load_news_impact_scores(session, news_ids=score_news_ids, limit=max(len(score_news_ids) * 6, 5000))
    score_rows_by_news: dict[str, list[dict[str, object]]] = {}
    for row in score_rows:
        news_id = str(row.get("news_id") or "").strip()
        if not news_id:
            continue
        score_rows_by_news.setdefault(news_id, []).append(row)

    human_labeled_ids: set[str] = set()
    if only_unlabeled:
        existing = load_news_labels(
            session,
            target_level="event",
            target_ids=event_ids,
            label_source="human",
            limit=max(len(event_ids) * 4, 5000),
        )
        human_labeled_ids = {str(row.get("target_id") or "").strip() for row in existing if row.get("target_id")}

    ranked: list[tuple[float, datetime, dict[str, object]]] = []
    for event_row in events:
        event_id = str(event_row.get("event_id") or "").strip()
        if not event_id:
            continue
        if only_unlabeled and event_id in human_labeled_ids:
            continue
        event_news_ids = event_to_news.get(event_id, [])
        if isinstance(eligible_news_ids, set):
            event_news_ids = [news_id for news_id in event_news_ids if news_id in eligible_news_ids]
            if not event_news_ids:
                continue
        impact = _event_impact(event_news_ids=event_news_ids, score_rows_by_news=score_rows_by_news)
        if impact < float(min_impact):
            continue
        published_at_dt = _parse_iso_datetime(event_row.get("event_first_published_at_utc")) or datetime.min
        ranked.append((impact, published_at_dt, event_row))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    prompt_version = str(settings.news_llm.prompt_version or "news-v1").strip() or "news-v1"
    max_chars = max(int(settings.news_llm.max_input_chars), 512)
    tasks: list[NewsHitlTask] = []
    for impact, _, event_row in ranked[:effective_limit]:
        event_id = str(event_row.get("event_id") or "").strip()
        linked_news = [news_by_id[news_id] for news_id in event_to_news.get(event_id, []) if news_id in news_by_id]
        input_payload = _normalize_event_input(
            event_row=event_row,
            news_rows=linked_news,
            max_input_chars=max_chars,
        )
        system_prompt, user_prompt = _render_prompt(input_payload, prompt_version)
        tasks.append(
            NewsHitlTask(
                task_id=_task_id(event_id, prompt_version),
                event_id=event_id,
                published_at=str(event_row.get("event_first_published_at_utc") or "").strip() or None,
                event_status=str(event_row.get("event_status") or "").strip() or "active",
                impact_estimate=impact,
                news_count=len(linked_news),
                prompt_version=prompt_version,
                input_payload=input_payload,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        )
    return tasks


def export_news_hitl_tasks(
    *,
    tasks: Iterable[NewsHitlTask],
    output_path: str | Path,
    output_format: str = "jsonl",
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_format = str(output_format).strip().lower()
    task_rows = [task.to_dict() for task in tasks]
    if normalized_format == "json":
        path.write_text(json.dumps(task_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    if normalized_format == "md":
        lines: list[str] = ["# News HITL Tasks", ""]
        for idx, row in enumerate(task_rows, start=1):
            lines.append(f"## {idx}. {row.get('event_id')}")
            lines.append(f"- `task_id`: `{row.get('task_id')}`")
            lines.append(f"- `impact_estimate`: `{row.get('impact_estimate')}`")
            lines.append(f"- `news_count`: `{row.get('news_count')}`")
            lines.append("")
            lines.append("### Prompt")
            lines.append("```text")
            lines.append(f"SYSTEM:\n{row.get('system_prompt')}")
            lines.append("")
            lines.append(f"USER:\n{row.get('user_prompt')}")
            lines.append("```")
            lines.append("")
            lines.append("### Expected JSON")
            lines.append("```json")
            lines.append(json.dumps(row.get("response_template") or {}, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    if normalized_format == "batch":
        if not task_rows:
            path.write_text("No tasks exported.\n", encoding="utf-8")
            return path
        schema = task_rows[0].get("schema") or _label_schema()
        lines = [
            "You are a commodity futures event labeler.",
            "Task: label each event payload below.",
            "Return ONLY JSONL (one JSON object per line), no markdown fences, no comments.",
            "",
            "Output format per line:",
            '{"event_id":"...","label":{"commodity":[],"market_scope":"futures","instrument_candidates":[],"relevance":0.5,"news_type":[],"direction":"neutral","magnitude":0.5,"lag_bucket":"short","confidence":0.5,"uncertainty_type":"none","geo_scope":"","evidence_spans":[{"text":""}]}}',
            "",
            "Schema (for label object):",
            json.dumps(schema, ensure_ascii=False),
            "",
            "Events:",
        ]
        for idx, row in enumerate(task_rows, start=1):
            lines.append(f"{idx}. event_id={row.get('event_id')}")
            lines.append(json.dumps(row.get("input_payload") or {}, ensure_ascii=False))
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    with path.open("w", encoding="utf-8") as handle:
        for row in task_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def load_hitl_label_rows(path: str | Path) -> list[dict[str, object]]:
    source = Path(path)
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        return []
    rows: list[dict[str, object]] = []

    def _parse_json_like(block: str) -> list[dict[str, object]]:
        payload = json.loads(block)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            return [payload]
        return []

    if source.suffix.lower() == ".json":
        return _parse_json_like(text)

    # Try whole text as JSON/JSONL first.
    try:
        return _parse_json_like(text)
    except Exception:
        pass

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            rows.append(value)
    if rows:
        return rows

    # Fallback: markdown fenced block, then parse JSON/JSONL inside it.
    fenced_blocks = re.findall(r"```(?:json|jsonl)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    for block in fenced_blocks:
        block_text = str(block or "").strip()
        if not block_text:
            continue
        try:
            parsed_rows = _parse_json_like(block_text)
            if parsed_rows:
                return parsed_rows
        except Exception:
            pass
        block_rows: list[dict[str, object]] = []
        for line in block_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except Exception:
                continue
            if isinstance(value, dict):
                block_rows.append(value)
        if block_rows:
            return block_rows
    return rows


def apply_news_hitl_labels(
    session: Session,
    *,
    label_rows: Iterable[dict[str, object]],
    author_id: str,
    reason: str,
    label_version: str = "v1",
    prompt_version: str = "news-v1",
) -> dict[str, int]:
    normalized_labels: list[dict[str, object]] = []
    normalized_annotations: list[dict[str, object]] = []
    parsed = 0
    skipped = 0
    now = datetime.utcnow().isoformat() + "Z"
    existing_by_event: dict[str, dict[str, object]] = {}
    for row in label_rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        event_id = str(row.get("event_id") or row.get("target_id") or "").strip()
        label = row.get("label")
        if not isinstance(label, dict):
            label = row
        if not event_id or not isinstance(label, dict):
            skipped += 1
            continue
        parsed += 1
        normalized = _normalize_label_payload(label)
        if event_id in existing_by_event:
            skipped += 1
            continue
        existing_by_event[event_id] = normalized
        normalized_labels.append(
            {
                "target_level": "event",
                "target_id": event_id,
                **normalized,
                "label_source": "human",
                "label_version": str(label_version or "v1"),
                "model_version": "chatgpt-web",
                "prompt_version": str(prompt_version or "news-v1"),
                "created_at": now,
            }
        )
        normalized_annotations.append(
            {
                "target_level": "event",
                "target_id": event_id,
                "payload_json": {
                    "source": "chatgpt_web_manual",
                    "label": normalized,
                    "raw": row,
                },
                "author_id": str(author_id or "operator"),
                "reason": str(reason or "manual_label"),
                "version": str(label_version or "v1"),
                "created_at": now,
            }
        )
    labels_stored = upsert_news_labels(session, normalized_labels) if normalized_labels else 0
    annotations_stored = (
        upsert_news_annotations(session, normalized_annotations) if normalized_annotations else 0
    )
    return {
        "parsed": parsed,
        "skipped": skipped,
        "labels_stored": labels_stored,
        "annotations_stored": annotations_stored,
    }


def summarize_news_hitl_state(session: Session, *, limit: int = 200) -> dict[str, object]:
    events = load_news_events(session, limit=max(int(limit), 1))
    event_ids = [str(row.get("event_id") or "").strip() for row in events if row.get("event_id")]
    labels = load_news_labels(session, target_level="event", target_ids=event_ids, label_source="human", limit=5000)
    annotations = load_news_annotations(session, target_level="event", limit=5000)
    labeled_ids = {str(row.get("target_id") or "").strip() for row in labels if row.get("target_id")}
    return {
        "events_seen": len(events),
        "human_labels_total": len(labels),
        "human_annotations_total": len(annotations),
        "human_labeled_event_ids": len(labeled_ids),
    }
