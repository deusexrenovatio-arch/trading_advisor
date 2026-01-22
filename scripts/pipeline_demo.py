import argparse
import time

from moex_carry.config import load_settings
from moex_carry.pipeline import compute_pairs, fetch_data, run_backtest, run_paper_trading


def _run_step(label: str, func) -> None:
    print(f"[pipeline] {label}...", flush=True)
    started = time.perf_counter()
    func()
    elapsed = time.perf_counter() - started
    print(f"[pipeline] {label} done in {elapsed:.1f}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    parser.add_argument(
        "--max-shares",
        type=int,
        default=None,
        help="Limit number of shares to fetch (demo speed-up).",
    )
    args = parser.parse_args()
    settings = load_settings(args.config)
    print("[pipeline] Starting demo pipeline (fetch -> compute -> backtest).", flush=True)
    _run_step("fetch MOEX + CBR data", lambda: fetch_data(settings, max_shares=args.max_shares))
    _run_step("compute pairs + signals", lambda: compute_pairs(settings))
    _run_step("run backtest", lambda: run_backtest(settings))
    _run_step("write decision log", lambda: run_paper_trading(settings))
    print("[pipeline] Done.", flush=True)


if __name__ == "__main__":
    main()
