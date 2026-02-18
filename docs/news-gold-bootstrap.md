# News Gold Bootstrap

Purpose: pull external seed labels for News Impact research and validate minimum QC gates.

## Command

```powershell
python scripts/bootstrap_news_gold.py --output-dir data/external/news_gold --years 2020-2026
```

Optional flags:
- `--hf-max-rows N` cap rows per HF source
- `--eia-max-pages N` cap EIA archive pages
- `--skip-hf` / `--skip-eia`

## Output

- `data/external/news_gold/news_gold_seed.jsonl` combined normalized dataset
- `data/external/news_gold/hf_fiqa.jsonl`
- `data/external/news_gold/hf_phrasebank_mirror.jsonl`
- `data/external/news_gold/hf_nifty.jsonl`
- `data/external/news_gold/eia_ng_archive.jsonl`
- `data/external/news_gold/manifest.json`
- `data/external/news_gold/qc_report.json`

## Runtime SoT mapping

After import, external gold can be persisted in two layers:
- `news_labels` (`label_source=external_gold`) for backward-compatible API/research flows.
- `news_gold_labels` for dedicated supervised gates and promotion audit.

Event identity and crosswalk support:
- `news_event_updates` keeps episodic updates (`phase`, `severity`, `facts_json`, `factor_delta_json`).
- `news_event_links` keeps external/internal event crosswalk with confidence.
- `news_model_eval_records` stores market + supervised gate outcomes for promotion decisions.

Taxonomy source:
- `configs/news-taxonomy.yaml` defines event families, anchor sources, and factor schema.

## QC gates

`qc_report.json` contains PASS/FAIL for:
- source document uniqueness (`gold_id`)
- required text present
- valid direction labels (`positive|negative|neutral|uncertain`)
- provenance required

## Notes

- HF pull works without token, but rate limits are lower.
- EIA archive rows are heuristic labels for `NG_US` based on extracted Henry Hub move from weekly archive pages.
