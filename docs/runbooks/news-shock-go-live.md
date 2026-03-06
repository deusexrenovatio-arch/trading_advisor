# News Shock Go-Live Runbook

## Scope
- Production runtime for commodity-news discovery, verified attribution, shock-row maintenance, strategy gate input, and Telegram delivery.
- Instruments: configured MOEX-linked commodities in `configs/news-livecheck-ng.yaml`.

## Production Truth
- Production command: `python -m moex_carry.cli news_root_cycle`
- Production scheduler: `scripts/manage_news_root_cycle_task.ps1`
- Production launcher: `scripts/start_news_root_cycle.ps1`
- Strategy gate input: `data/output/news_live/live_news_discovery.csv`
- Telegram news input: `telegram.news_feed_path`
- Telegram shock input: `telegram.shock_feed_path`

`news_root_cycle` is the only production route. It runs ingest, story-first commodity attribution, discovery/verified feed export, shock-row persistence, and optional root maintenance in one cycle.

## Feed Contract
`news_root_cycle` exports two news feeds:

- `data/output/news_live/live_news_discovery.csv`
- `data/output/news_live/live_news_verified.csv`

Discovery feed:
- high-recall causal profile (`causal_profile: discovery`)
- no post-move verification requirement
- one row per `(story_id, commodity)`
- used by `news_live_bridge` and Telegram news alerts

Verified feed:
- requires post-move verification
- used only for retrospective attribution, quality review, and calibration

Required discovery/verified columns:
- `feed_role`
- `story_id`
- `commodity`
- `commodity_link_score`
- `story_scope_json`
- `link_reason`

## One-Shot Production Commands
Live cycle:

```powershell
$env:PYTHONPATH='src'
python -m moex_carry.cli news_root_cycle `
  --news-config configs/news-livecheck-ng.yaml `
  --ingest-mode live `
  --lookback-hours 6 `
  --bar-minutes 5 `
  --min-abs-z 2.0 `
  --root-min-fundamental-score 0.45 `
  --root-min-cause-confidence 0.45 `
  --aftershock-max-gap-min 2880 `
  --enable-candidate-newsapi-enrichment `
  --enrichment-window-min 90 `
  --enrichment-max-requests-per-symbol 4
```

Backfill cycle:

```powershell
$env:PYTHONPATH='src'
python -m moex_carry.cli news_root_cycle `
  --news-config configs/news-livecheck-ng.yaml `
  --ingest-mode backfill `
  --lookback-hours 24 `
  --bar-minutes 5 `
  --min-abs-z 2.0 `
  --root-min-fundamental-score 0.45 `
  --root-min-cause-confidence 0.45 `
  --aftershock-max-gap-min 2880
```

`moex-carry news_ingest` remains available only as a debug one-shot and must not be scheduled in production.

## Scheduler
Validate launcher without starting a cycle:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_news_root_cycle.ps1 -CheckOnly
```

Dry-run scheduler install:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_news_root_cycle_task.ps1 -Action Install -DryRun
```

Install production tasks:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_news_root_cycle_task.ps1 -Action Install
```

Status:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_news_root_cycle_task.ps1 -Action Status
```

Manual runs:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_news_root_cycle_task.ps1 -Action RunLive
powershell -ExecutionPolicy Bypass -File scripts/manage_news_root_cycle_task.ps1 -Action RunBackfill
```

Remove tasks:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_news_root_cycle_task.ps1 -Action Remove
```

Task names:
- `MoexCarry-NewsRootLive`
- `MoexCarry-NewsRootBackfill`

## Telegram
- Ensure `telegram.enabled=true`, bot token, and `telegram.allowed_user_ids` are configured.
- `telegram.news_feed_path` should point to `data/output/news_live/live_news_discovery.csv`.
- `telegram.shock_feed_path` should point to `data/output/shock_alerts/live_shocks.csv`.

Run worker:

```powershell
$env:PYTHONPATH='src'
python -m moex_carry.cli telegram_bot --config configs/default.yaml
```

Discovery Telegram contract:
- header `NEWS DISCOVERY ALERT`
- one message per `story_id`
- all linked commodities listed in one message
- no `verified_move_*` or move-verification fields

Shock Telegram contract stays separate:
- `SHOCK PRIMARY`
- `SHOCK AFTERSHOCK`

## Strategy Gate
- `news_live_bridge` reads per-commodity rows from `data/output/news_live/live_news_discovery.csv`.
- `configs/default.yaml` sets `news_filter.live_feed_path` to the discovery feed.
- Verified feed must not be used for forward gate decisions.

## Offline Validation
Research and validation tooling remains non-production:
- `python -m moex_carry.cli news_shock_backfill ...`
- `python scripts/news_known_events_walkforward.py ...`
- `python scripts/news_multi_commodity_benchmark.py ...`
- `python scripts/news_forward_synthetic.py ...`
- `python scripts/run_news_shock_silver_cycle.py ...`
- `python scripts/news_shock_readiness.py ...`

Mandatory checks before enabling or changing forward routing:
- `python scripts/run_lean_gate.py`
- `python scripts/validate_quality_scorecards.py`
- `python scripts/news_multi_commodity_benchmark.py --benchmark-csv docs/research/news_multi_commodity_benchmark.csv --output-dir data/output/news_multi_commodity_benchmark`
- `python -m pytest tests/test_news_live_runtime.py tests/test_news_live_feed.py tests/test_telegram_news_broadcast.py tests/test_telegram_worker.py tests/test_news_shock_live_input.py tests/test_news_operational_contract.py -q`

Quality targets for discovery validation:
- `window_pass_rate >= 0.9`
- `avg_known_event_coverage >= 0.9`
- `avg_exact_event_recall >= 0.65`
- `avg_precision >= 0.4`
- false multi-commodity assignment rate `<= 10%`

Multi-commodity attribution benchmark contract:
- fixture: `docs/research/news_multi_commodity_benchmark.csv`
- evaluator: `scripts/news_multi_commodity_benchmark.py`
- settings: configured commodity universe from `configs/news-livecheck-ng.yaml` and discovery min-link threshold
