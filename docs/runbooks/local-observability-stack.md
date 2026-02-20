# Local Observability Stack

## Scope
Run isolated local observability services for logs, metrics, and traces.

## Services
- `grafana` on `http://127.0.0.1:3000`
- `prometheus` on `http://127.0.0.1:9090`
- `jaeger` on `http://127.0.0.1:16686`

## Start
```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
```

## Stop
```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml down
```

## Backend Signals to Inspect
- `GET /api/v2/ops/health`
- `GET /api/v2/ops/slo`

## Validation
- `python scripts/validate_observability_stack.py`
