# 2026-02-20 - PR-only main hardening

- Enforced PR-only flow for `main` in `.githooks/pre-push`.
- Added emergency override contract requiring explicit reason:
  - `MOEX_CARRY_EMERGENCY_MAIN_PUSH=1`
  - `MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON='<ticket/incident>'`
- Added machine check `python scripts/validate_pr_only_policy.py` and wired it into lean governance gate.
