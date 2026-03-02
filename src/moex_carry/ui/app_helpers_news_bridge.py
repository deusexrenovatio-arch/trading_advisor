from __future__ import annotations


def normalize_silver_direction(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"up", "positive", "+1", "1", "bullish"}:
        return "up"
    if raw in {"down", "negative", "-1", "bearish"}:
        return "down"
    if raw in {"hold", "neutral", "0", "flat"}:
        return "hold"
    return "unknown"


def build_silver_explain_payload(
    events: list[dict[str, object]],
    news_score: dict[str, object],
    silver_label_by_event_id: dict[str, dict[str, object] | None],
    *,
    preview_limit: int = 10,
) -> dict[str, object]:
    if preview_limit <= 0:
        preview_limit = 10
    if not events:
        return {
            "matched_event_count": 0,
            "silver_event_count": 0,
            "silver_coverage": 0.0,
            "direction_votes": {"up": 0, "down": 0, "hold": 0, "unknown": 0},
            "dominant_silver_direction": "unknown",
            "live_direction": str(news_score.get("direction") or "neutral"),
            "agreement_with_live": None,
            "preview_limit": preview_limit,
            "events": [],
        }

    dedup_event_ids: list[str] = []
    seen_ids: set[str] = set()
    for event in events:
        event_id = str(event.get("news_event_id") or "").strip()
        if not event_id or event_id in seen_ids:
            continue
        seen_ids.add(event_id)
        dedup_event_ids.append(event_id)

    votes = {"up": 0, "down": 0, "hold": 0, "unknown": 0}
    silver_event_count = 0
    event_rows: list[dict[str, object]] = []
    for event in events[:preview_limit]:
        event_id = str(event.get("news_event_id") or "").strip()
        news_id = str(event.get("news_id") or "").strip()
        label = silver_label_by_event_id.get(event_id) if event_id else None
        direction = normalize_silver_direction((label or {}).get("direction_label"))
        if label is not None:
            silver_event_count += 1
        votes[direction] = votes.get(direction, 0) + 1
        event_rows.append(
            {
                "event_id": event_id or None,
                "news_id": news_id or None,
                "headline": str(event.get("headline") or "").strip() or None,
                "published_at": event.get("published_at"),
                "silver": {
                    "present": bool(label),
                    "direction": direction,
                    "event_family": (label or {}).get("event_family"),
                    "phase": (label or {}).get("phase"),
                    "confidence": (label or {}).get("confidence"),
                    "source": (label or {}).get("source"),
                    "quality": (label or {}).get("quality"),
                    "created_at": (label or {}).get("created_at"),
                },
            }
        )

    direction_candidates = {k: v for k, v in votes.items() if k in {"up", "down", "hold"}}
    top_count = max(direction_candidates.values()) if direction_candidates else 0
    top_dirs = [key for key, value in direction_candidates.items() if value == top_count and value > 0]
    dominant = top_dirs[0] if len(top_dirs) == 1 else "unknown"

    live_direction = str(news_score.get("direction") or "neutral").strip().lower() or "neutral"
    mapped_dominant = "neutral" if dominant == "hold" else dominant
    agreement: bool | None = None
    if mapped_dominant in {"up", "down", "neutral"} and live_direction in {"up", "down", "neutral"}:
        agreement = mapped_dominant == live_direction

    matched_event_count = max(len(dedup_event_ids), len(events))
    coverage = float(silver_event_count) / float(matched_event_count) if matched_event_count > 0 else 0.0
    return {
        "matched_event_count": matched_event_count,
        "silver_event_count": silver_event_count,
        "silver_coverage": round(coverage, 6),
        "direction_votes": votes,
        "dominant_silver_direction": dominant,
        "live_direction": live_direction,
        "agreement_with_live": agreement,
        "preview_limit": preview_limit,
        "events": event_rows,
    }
