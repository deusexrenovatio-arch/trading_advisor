# 2026-03-06 - News Runtime Unification And Discovery Rollout

Added
- Unified `news_root_cycle` production entrypoint for news and shock processing.
- Discovery and verified live feeds with discovery wired into the gate and Telegram delivery.
- Multi-commodity news attribution benchmark and grouped Telegram discovery alerts.

Changed
- Production news scheduling now routes through the unified runtime instead of legacy parallel launchers.
- Legacy production-looking news/shock launch paths were removed from active operational documentation.

Notes
- This fragment documents the rollout contract for the unified news runtime and satisfies PR release-note policy.
