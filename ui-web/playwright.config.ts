import { defineConfig } from '@playwright/test'

const baseURL = process.env.UI_BASE_URL ?? 'http://127.0.0.1:5176'

export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  expect: { timeout: 5000 },
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5176',
    url: baseURL,
    reuseExistingServer: true,
    timeout: 120000,
  },
})
