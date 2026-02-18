# News HITL Route (Low-Cost Pilot)

## Goal
Run early product-value validation without paid API token usage by using manual ChatGPT-web labeling on top event tasks.

## Flow
1. Export top event tasks from DB.
2. Paste task prompt into ChatGPT web.
3. Save JSON response.
4. Import JSON back into runtime DB as `human` labels and annotations.
5. Re-run backtest/compare/validation endpoints with human labels available.

## Commands
Use your project config (example: `configs/news-smoke-ng.yaml`):

```powershell
python -m moex_carry.cli news_hitl_export --config configs/news-smoke-ng.yaml --max-items 10 --format md
```

For one commodity only (example `NG_US`):

```powershell
python -m moex_carry.cli news_hitl_export --config configs/news-smoke-ng.yaml --ticker NG_US --max-items 10 --format md
```

This writes a task file to:
- `data/output/news_hitl_tasks.md` (or `.jsonl`/`.json` if selected).

To include already labeled events:

```powershell
python -m moex_carry.cli news_hitl_export --config configs/news-smoke-ng.yaml --max-items 10 --include-labeled
```

After manual labeling, import:

```powershell
python -m moex_carry.cli news_hitl_import --config configs/news-smoke-ng.yaml --input data/output/news_hitl_labels.jsonl --author-id admin --reason chatgpt_web_manual
```

## Import payload format
Each row in `jsonl`:

```json
{
  "event_id": "evt-123",
  "label": {
    "commodity": ["NG_US"],
    "market_scope": "futures",
    "instrument_candidates": [{"symbol": "NG=F", "exchange": "NYMEX"}],
    "relevance": 0.9,
    "news_type": ["SUP_DEC"],
    "direction": "positive",
    "magnitude": 0.7,
    "lag_bucket": "short",
    "confidence": 0.8,
    "uncertainty_type": "none",
    "geo_scope": "US",
    "evidence_spans": [{"text": "inventory draw larger than expected"}]
  }
}
```

## Notes
- This route avoids API spending, but throughput is manual.
- Imported labels are stored with:
  - `label_source=human`
  - `model_version=chatgpt-web`
  - annotation source `chatgpt_web_manual`.
