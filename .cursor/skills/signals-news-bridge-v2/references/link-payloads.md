# Link payload templates

## Bridge record
```json
{
  "link_id": "lnk-news-001-sig-123-used_in_decision-20260213T1000Z",
  "news_event_id": "news-001",
  "signal_id": "sig-123",
  "decision_id": "dec-456",
  "link_type": "used_in_decision",
  "window_start": "2026-02-13T10:00:00Z",
  "window_end": "2026-02-13T13:00:00Z",
  "news_gate_action": "reduce",
  "news_severity": "high",
  "source": "runtime"
}
```

## Signal active fields
```json
{
  "signal_id": "sig-123",
  "signal_action_effective": "hold_pretrade",
  "news_gate_action": "reduce",
  "news_severity": "high",
  "matched_news_event_ids": ["news-001", "news-014"]
}
```

## News feed link fields
```json
{
  "news_event_id": "news-001",
  "decision_ref": {
    "decision_id": "dec-456"
  },
  "signal_refs": [
    {"signal_id": "sig-123", "link_type": "used_in_decision"}
  ]
}
```

