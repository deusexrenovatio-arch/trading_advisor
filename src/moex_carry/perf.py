from __future__ import annotations

import os


def resolve_pair_workers(
    requested: int | None,
    *,
    env_var: str = "MOEX_CARRY_PAIR_WORKERS",
    hard_cap: int = 32,
) -> int:
    if requested is not None:
        workers = int(requested)
    else:
        env_value = os.getenv(env_var)
        if env_value:
            try:
                workers = int(env_value)
            except ValueError:
                workers = 0
        else:
            workers = 0
        if workers <= 0:
            workers = int(os.cpu_count() or 1)

    workers = max(workers, 1)
    if hard_cap > 0:
        workers = min(workers, hard_cap)
    return workers
