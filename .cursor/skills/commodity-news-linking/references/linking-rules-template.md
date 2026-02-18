# Linking rules template

## Candidate output shape
```json
{
  "news_id": "news-102",
  "primary_commodity_id": "OIL",
  "secondary_commodity_ids": ["GAS"],
  "tag_codes": ["SUP_DEC", "GEO_POL"],
  "confidence": 0.86,
  "resolution_stage": "dictionary",
  "matched_rules": ["kw:opec", "org:saudi_aramco"],
  "unknown": false
}
```

## Stage priority
1. `dictionary`
2. `context_rule`
3. `semantic_fallback`
4. `unknown`

## Quality checks
- Missing timestamp or source: reject row.
- Empty text after normalization: mark `unknown` with reason `empty_text`.
- Ambiguous top-two candidates with close scores: keep `unknown` or multi-label, do not force single class.

