# trading_advisor

MOEX Carry MVP

This project builds a cash-and-carry analytics and backtesting stack for MOEX
stock-futures pairs. It ingests MOEX ISS data and CBR key rate history, models
dividends, costs, and taxes, then ranks pairs and generates signals. A React/Vite
UI (ui-web) provides the dashboard for top pairs, signals, backtests, and
Backtest v2 / Forward / HPO workflows.

Note: MOEX ISS free data can be delayed. Real-time requires a paid feed or
broker streaming API. The system exposes interfaces for real-time providers.

## Quickstart

One-command demo (creates venv, installs deps, runs pipeline, starts UI):

```
python scripts/build.py
```

1) Create a venv and install dependencies:

```
python -m venv .venv
. .venv/Scripts/activate
pip install -e .[dev]
```

2) Run the demo pipeline (defaults to `configs/default.yaml` if `--config` is omitted):

```
python -m moex_carry.cli fetch
python -m moex_carry.cli compute
python -m moex_carry.cli backtest
python -m moex_carry.cli paper
python -m moex_carry.cli ui
```

3) Start the UI (React + Vite):

```
cd ui-web
npm install
npm run dev -- --host 127.0.0.1 --port 5176
```

Open `http://127.0.0.1:5176` (Vite proxy forwards `/api/*` to the backend).

To use a different config file, pass `--config path/to/config.yaml`.

Or use the demo scripts:

```
python scripts/pipeline_demo.py
python scripts/run_ui.py
```

## Development workflow

See `docs/DEV_WORKFLOW.md` for required checks (backend tests, UI lint/build)
and optional acceptance/E2E smoke checks.
Documentation system index: `docs/README.md`.

Recommended: enable pre-push blocker checks once per clone:

```
python scripts/install_git_hooks.py
```

By default, pre-push enforces PR-only policy for `main`.
Emergency override (incident/hotfix only, requires explicit reason):

```
MOEX_CARRY_EMERGENCY_MAIN_PUSH=1 MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON="<ticket/incident>" git push
```

PowerShell variant:

```
$env:MOEX_CARRY_EMERGENCY_MAIN_PUSH='1'; $env:MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON='<ticket/incident>'; git push
```

If `npm ci` fails on Windows with `EPERM` lock errors for `esbuild.exe`,
use this temporary pre-push workaround:

```
$env:MOEX_CARRY_SKIP_NPM_CI='1'; git push
```

## Telegram Worker (MVP)

The project includes a Telegram worker that sends actionable signals from
`/api/signals/active` and accepts ACK via an inline button.

1) Create a bot via `@BotFather` and copy the token.
2) Find your Telegram user id (for whitelist).
3) Copy `.env.example` values into your environment (or set in config):

```
MOEX_CARRY_TELEGRAM__ENABLED=true
MOEX_CARRY_TELEGRAM__BOT_TOKEN=<your-bot-token>
MOEX_CARRY_TELEGRAM__ALLOWED_USER_IDS=[123456789]
MOEX_CARRY_TELEGRAM__BACKEND_BASE_URL=http://127.0.0.1:8050
MOEX_CARRY_TELEGRAM__UI_BASE_URL=http://127.0.0.1:5176
MOEX_CARRY_TELEGRAM__DAILY_HEALTHCHECK_ENABLED=true
MOEX_CARRY_TELEGRAM__DAILY_HEALTHCHECK_TIME_LOCAL=09:00
```

4) Start backend:

```
python -m moex_carry.cli ui --config configs/default.yaml
```

5) Start Telegram worker:

```
python -m moex_carry.cli telegram_bot --config configs/default.yaml
```

Then send `/start` to the bot and wait for signal messages. ACK is recorded as
`action=ack` in `signal_executions` and reflected in `Signals` table fields
(`signal_used`, `signal_used_at`, `signal_details_pending`).
If `daily_healthcheck_enabled=true`, the worker also sends one daily morning
heartbeat with backend status and active signals count.

### Windows auto-start (backend + Telegram worker)

Use helper scripts in `scripts/` to avoid manual restart after reboot:

1) Create local env file with token/whitelist:

```
Copy-Item scripts/moex-carry.local.example.ps1 scripts/moex-carry.local.ps1
```

2) Validate scripts without starting services:

```
powershell -ExecutionPolicy Bypass -File scripts/start_backend.ps1 -CheckOnly
powershell -ExecutionPolicy Bypass -File scripts/start_telegram_worker.ps1 -CheckOnly
```

3) Install startup tasks (as `SYSTEM`, worker delayed by 30s):

```
powershell -ExecutionPolicy Bypass -File scripts/install_autostart_tasks.ps1
```

Note: run this command from an elevated PowerShell (Run as Administrator).

4) Remove startup tasks if needed:

```
powershell -ExecutionPolicy Bypass -File scripts/remove_autostart_tasks.ps1
```

### Live Paper Forward Launch (signals + Telegram + forward run)

To start paper forward-test from today on the live MOEX contour using existing
Telegram signal formats:

```
powershell -ExecutionPolicy Bypass -File scripts/start_forward_paper_live.ps1
```

By default, the launcher loads `scripts/moex-carry.local.ps1` (if present) for
Telegram env vars. If `/api/forward/start` returns `Missing raw data`, the
launcher runs `moex_carry.cli fetch` automatically and retries forward start.

Useful flags:

```
# dry-run checks only
powershell -ExecutionPolicy Bypass -File scripts/start_forward_paper_live.ps1 -CheckOnly

# force full signal refresh before forward start
powershell -ExecutionPolicy Bypass -File scripts/start_forward_paper_live.ps1 -ForceFullRefresh

# start backend + forward only (skip Telegram worker)
powershell -ExecutionPolicy Bypass -File scripts/start_forward_paper_live.ps1 -SkipTelegramWorker

# skip loading scripts/moex-carry.local.ps1
powershell -ExecutionPolicy Bypass -File scripts/start_forward_paper_live.ps1 -NoLocalEnv
```

## HPO

See `docs/hpo-howto.md` for running HPO locally with Backtest v2 as a black box.

## Incremental History Collection

To gradually collect historical candles in the background:

```
python scripts/collect_history.py --loop
```

This stores data under `data/history/candles/` and keeps progress in
`data/history/state.json`. You can also run a single batch:

```
python -m moex_carry.cli history --symbols-per-run 20 --max-days-per-run 60
```

Optional: start the history collector alongside the demo UI:

```
python scripts/build.py --collect-history
```

## Data Sources

- MOEX ISS: https://iss.moex.com/iss
- CBR key rate (downloadable series)

## Project Layout

- `src/moex_carry/` core package
- `scripts/` demo scripts
- `tests/` unit and integration tests
- `configs/` example configs

## Postgres (optional)

Use docker-compose to run Postgres if you want to switch off SQLite:

```
docker compose up -d
```

Then set `database.url` in the config.
