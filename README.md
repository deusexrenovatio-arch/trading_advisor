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
