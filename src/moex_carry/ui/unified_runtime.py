from __future__ import annotations

# Compatibility shim for legacy imports from moex_carry.ui.unified_runtime.
from moex_carry import unified_runtime as _runtime
from moex_carry.unified_runtime import (  # noqa: F401
    UnifiedMarketSnapshot,
    build_unified_market_snapshot,
    build_unified_spread_series,
    get_last_refresh_telemetry,
    list_unified_ingest_pairs,
    persist_snapshot_to_csv,
)


# Delegate all unresolved attributes (including private helpers used by tests)
# to the canonical runtime module.
def __getattr__(name: str):  # pragma: no cover - trivial delegation
    return getattr(_runtime, name)


__all__ = [
    "UnifiedMarketSnapshot",
    "build_unified_market_snapshot",
    "build_unified_spread_series",
    "get_last_refresh_telemetry",
    "list_unified_ingest_pairs",
    "persist_snapshot_to_csv",
]
