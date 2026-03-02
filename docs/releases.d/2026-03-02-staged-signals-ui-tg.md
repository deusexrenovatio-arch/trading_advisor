# 2026-03-02 - Staged Signals In Strategy, Telegram, And UI

Added
- Sequential staged entry/exit protocol support in strategy runtime and replay outputs.
- Dedicated staged default config profile: `configs/default.sequential_staged.yaml`.
- Telegram signal instructions for staged execution: first leg order, max leg gap, and fallback actions.
- UI signal plan fields for staged protocol visibility (`entry/exit protocol`, first leg, wait bounds, penalties).

Changed
- Strategy defaults and config validation for staged execution parameters.
- Tests for staged defaults, replay execution behavior, and Telegram formatting.

Notes
- This fragment is added to satisfy PR release-note policy and documents user-facing staged execution behavior.
