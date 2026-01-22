import argparse
import time
from datetime import date

from moex_carry.config import load_settings
from moex_carry.history import collect_history


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    parser.add_argument("--kind", choices=["shares", "futures", "both"], default="both")
    parser.add_argument("--symbols-per-run", type=int, default=20)
    parser.add_argument("--max-days-per-run", type=int, default=60)
    parser.add_argument("--chunk-days", type=int, default=30)
    parser.add_argument("--start-date", type=str, default="2010-01-01")
    parser.add_argument("--end-date", type=str, default=None)
    parser.add_argument("--sleep-sec", type=float, default=0.2)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-backoff-sec", type=float, default=2.0)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-sec", type=int, default=300)
    args = parser.parse_args()

    settings = load_settings(args.config)
    while True:
        collect_history(
            settings,
            kind=args.kind,
            symbols_per_run=args.symbols_per_run,
            max_days_per_run=args.max_days_per_run,
            chunk_days=args.chunk_days,
            start_date=_parse_date(args.start_date),
            end_date=_parse_date(args.end_date),
            sleep_sec=args.sleep_sec,
            retries=args.retries,
            retry_backoff_sec=args.retry_backoff_sec,
        )
        if not args.loop:
            break
        print(f"[history] Sleeping {args.interval_sec}s before next run.", flush=True)
        time.sleep(args.interval_sec)


if __name__ == "__main__":
    main()
