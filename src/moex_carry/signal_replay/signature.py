from __future__ import annotations

import hashlib
import json

from moex_carry.signal_replay.minute_loader import PRELOAD_SCHEMA_VERSION

REPLAY_CORE_VERSION = "minute_replay_canon_v1"


def replay_parity_signature() -> str:
    payload = {
        "replay_core_version": REPLAY_CORE_VERSION,
        "minute_preload_schema_version": PRELOAD_SCHEMA_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
