# 2026-03-02 - Add June Futures To Default Universe

Changed
- Updated `spread_carry_alpha.allowed_expiry_months` to `[3, 6]` in:
  - `configs/default.yaml`
  - `configs/default.sequential_staged.yaml`
- Disabled `ui.unified_front_only` in both configs to allow multi-contract universe selection.

Impact
- Runtime universe now includes both March and June contracts instead of front-only March.
- On current data this expands pair universe from 55 to 110 pairs.
