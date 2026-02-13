# Copy this file to scripts/moex-carry.local.ps1 and fill your local values.
# This file is loaded by start_backend.ps1 and start_telegram_worker.ps1.

$env:MOEX_CARRY_TELEGRAM__ENABLED = "true"
$env:MOEX_CARRY_TELEGRAM__BOT_TOKEN = "<PUT_BOT_TOKEN_HERE>"
$env:MOEX_CARRY_TELEGRAM__ALLOWED_USER_IDS = "[186419048]"
$env:MOEX_CARRY_TELEGRAM__BACKEND_BASE_URL = "http://127.0.0.1:8050"
$env:MOEX_CARRY_TELEGRAM__STATE_PATH = "D:/wt-bot/data/telegram/bot_state.json"

$env:MOEX_CARRY_ENVIRONMENT__TIMEZONE = "Europe/Moscow"
$env:MOEX_CARRY_TELEGRAM__DAILY_HEALTHCHECK_ENABLED = "true"
$env:MOEX_CARRY_TELEGRAM__DAILY_HEALTHCHECK_TIME_LOCAL = "09:00"
