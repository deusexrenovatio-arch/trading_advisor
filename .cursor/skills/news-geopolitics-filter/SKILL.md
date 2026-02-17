---
name: news-geopolitics-filter
description: Deterministic gate for high-impact news and geopolitics events. Use when event risk can block/reduce trading actions and during strategy rechecks before push. Co-use with intraday-futures-trading-advisor and risk-profile-gates.
---

# News and Geopolitics Filter

## Purpose
Protect strategy decisions during high-impact events with deterministic gating rules and explicit audit output.

## Skill dependencies and lifecycle gates
- Planning phase: use with `intraday-futures-trading-advisor` for strategy context.
- Risk phase: pair with `risk-profile-gates` to keep event and risk controls consistent.
- Recheck/pre-push phase: rerun this gate when event feed logic, severity mapping, or blocking thresholds change.

## Required inputs
- `news_items` (`id`, `timestamp`, `source`, `title`, `severity`, `impact_score`)
- `lookback_minutes`
- `block_severity_threshold`
- `reduce_severity_threshold`

## Deterministic checks
- Each news item includes timestamp and severity.
- `block_severity_threshold > reduce_severity_threshold`.
- `impact_score` is within `[0, 1]`.
- If any item severity is above or equal to block threshold within lookback, action is `block`.
- Else if any item severity is above or equal to reduce threshold within lookback, action is `reduce`.
- Otherwise action is `allow`.

## Output JSON template
```json
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
