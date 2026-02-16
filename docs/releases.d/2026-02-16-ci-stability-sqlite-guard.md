# 2026-02-16 - CI Stability And SQLite Path Guard

Fixed
- Commit message lint in CI now installs commitlint packages explicitly before execution.
- SQLite parent directory is now created automatically before SQLAlchemy engine initialization.

Added
- Release note fragment for PR #3 merge gate compliance.

Notes
- These changes only affect CI reliability and environment bootstrap behavior.
