---
name: news-geopolitics-filter
description: Deterministic gate for high-impact news and geopolitics events.
---

# News and Geopolitics Filter

## Purpose
Protect strategy decisions during high-impact events using deterministic gating
rules with explicit audit outputs.

## Required inputs
- news_items (id, timestamp, source, title, severity, impact_score)
- lookback_minutes
- block_severity_threshold
- reduce_severity_threshold

## Deterministic checks
- Each news item must include timestamp and severity.
- block_severity_threshold > reduce_severity_threshold.
- impact_score between 0 and 1.
- If any item severity >= block threshold within lookback, action = "block".
- If any item severity >= reduce threshold within lookback, action = "reduce".
- Otherwise, action = "allow".

## Output JSON template
```
{
  "news_gate": {
    "lookback_minutes": 180,
    "block_severity_threshold": "high",
    "reduce_severity_threshold": "medium"
  },
  "result": {
    "action": "reduce",
    "highest_severity": "high",
    "matched_items": [
      {
        "id": "news-001",
        "timestamp": "2025-01-21T10:00:00Z",
        "source": "trusted-feed",
        "severity": "high",
        "impact_score": 0.9,
        "title": "Unexpected policy announcement"
      }
    ]
  }
}
```
