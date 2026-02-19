# News Data Bootstrap and Flow

## Scope
Initial commodity set:
- `BRN` (Brent crude oil)
- `GOLD`
- `NG_US` (US natural gas / Henry Hub)

## Source Mapping

`news_ingest.commodity_profiles` in `configs/default.yaml` defines:
- commodity ticker
- GDELT query for historical backfill
- optional NewsAPI query for historical backfill (`newsapi_query`, falls back to `gdelt_query`)
- RSS feeds for regular incremental flow
- price source and symbol:
  - `BRN` -> yfinance `BZ=F`
  - `GOLD` -> yfinance `GC=F`
  - `NG_US` -> yfinance `NG=F`

## Runtime Flow

Regular worker (`news_sync`):
1. Pull latest RSS news from global + per-commodity RSS URLs.
2. Normalize and deduplicate in `news_items`.
3. Link commodity and tags:
   - If source URL belongs to commodity profile -> `link_stage=source_profile` with high confidence.
   - Otherwise dictionary/linking rules are used.
4. Optionally run dual-model inference (FinBERT + NLI) and store scores.
5. Build deterministic event clusters.
6. Seed canonical scheduled anchor events (EIA weekly NG/Oil releases).
7. Link fresh news to nearest scheduled anchors and create crosswalk links.
8. News gate uses linked events and selected model scores.

## Historical Backfill Flow

Backfill worker (`news_backfill`):
1. Split requested period into windows (`backfill_chunk_days`).
2. For each commodity window:
   - Pull GDELT articles (rate-limited by `gdelt_min_request_interval_sec`).
   - Optionally pull NewsAPI articles (`newsapi_enabled=true`) with hard daily budget (`newsapi_daily_limit`).
   - Upsert into `news_items`.
   - Create deterministic commodity links (`source_profile`) and taxonomy tags.
   - Optional model inference.
3. Pull price series for each commodity and upsert into `quotes`.
4. For each window, seed scheduled anchor events and link news to anchors.
5. Build QC/backtest-readiness report:
   - news count per ticker
   - quote points per ticker
   - per-year news distribution
   - 1-day backtest-ready sample count

## Commands

Run live sync worker:
```bash
moex-carry news_sync --config configs/default.yaml --interval-sec 300
```

Backfill 5+ years:
```bash
moex-carry news_backfill --config configs/default.yaml --from-date 2018-01-01 --to-date 2026-02-16 --commodities BRN,GOLD,NG_US
```

Accelerated first pass (larger windows, limited depth):
```bash
moex-carry news_backfill --config configs/default.yaml --from-date 2018-01-01 --to-date 2026-02-16 --commodities BRN,GOLD,NG_US --chunk-days 30 --max-windows-per-commodity 48
```

Backfill with model scoring:
```bash
moex-carry news_backfill --config configs/default.yaml --from-date 2018-01-01 --to-date 2026-02-16 --run-inference
```

Backfill with NewsAPI (100 req/day budget):
```bash
$env:NEWSAPI_API_KEY="<your_key>"
moex-carry news_backfill --config configs/default.yaml --from-date 2026-01-01 --to-date 2026-02-19 --commodities BRN,GOLD,NG_US
```

Run QC report only:
```bash
moex-carry news_qc --config configs/default.yaml --from-date 2018-01-01 --to-date 2026-02-16 --commodities BRN,GOLD,NG_US
```

Stage C (LLM full-pass and Batch export):
```bash
moex-carry news_llm_pass --config configs/default.yaml --max-items 50
moex-carry news_llm_batch_export --config configs/default.yaml --max-items 200 --output data/output/news_llm_batch_requests.jsonl
```

Stage D (event reactions by published or ingested event-time anchor):
```bash
moex-carry news_reactions --config configs/default.yaml --from-date 2025-01-01 --to-date 2025-12-31 --event-time-mode published
moex-carry news_reactions --config configs/default.yaml --from-date 2025-01-01 --to-date 2025-12-31 --event-time-mode ingested
```

## Quality Gates

Thresholds are configurable in `news_ingest`:
- `qc_min_news_per_ticker`
- `qc_min_price_points_per_ticker`

If thresholds fail, dataset is not ready for reliable multi-year backtests.

## Anchor Controls

`news_events` config supports staged rollout:
- `anchor_seed_enabled`
- `anchor_link_enabled`
- `anchor_cluster_version`
- `anchor_match_window_minutes`
- `anchor_seed_padding_days`
- `anchor_episode_seed_enabled` (default: `false`, enables live episodic pulls)
- `anchor_episode_cluster_version`
- `anchor_episode_sources` (`nws_alerts`, `nhc`, `ukmto`)
- `anchor_episode_match_window_minutes`
- `anchor_request_timeout_sec`, `anchor_nhc_url`, `anchor_ukmto_url`
