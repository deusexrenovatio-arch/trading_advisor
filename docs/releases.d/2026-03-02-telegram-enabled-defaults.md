# 2026-03-02 - Enable Telegram Worker By Default In Configs

Changed
- Enabled Telegram integration by default in `configs/default.yaml`.
- Enabled Telegram integration by default in `configs/default.sequential_staged.yaml`.

Notes
- Runtime validation still requires explicit `bot_token` and `allowed_user_ids` when worker starts.
- Existing scheduled task setup and local secret loading flow remain unchanged.
