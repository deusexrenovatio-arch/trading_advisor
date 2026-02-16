import { expect, test, type Page } from '@playwright/test'

const paramSpecs = [
  { key: 'test.start_date', value_type: 'str', default: '2025-01-01' },
  { key: 'test.end_date', value_type: 'str', default: '2025-12-31' },
  { key: 'strategy.z_window', value_type: 'int', default: 60 },
  { key: 'strategy.TP_pct', value_type: 'float', default: 0.01 },
  { key: 'allocation.weights', value_type: 'dict', default: { fundamental: 0.4 } },
]

const backtestReport = {
  summary_metrics: { cagr: 0.12, max_drawdown: 0.1, sharpe: 1.23 },
  equity_curve: [
    {
      date: '2026-01-10',
      equity: 1000000,
      cash: 500000,
      drawdown: 0,
      turnover: 0.02,
      positions: 2,
    },
  ],
  trades: [
    {
      pair_id: 'SBER-SRH6',
      stock_secid: 'SBER',
      future_secid: 'SRH6',
      direction: 'cash_and_carry',
      entry_date: '2026-01-02',
      exit_date: '2026-01-10',
      pnl: 1234.56,
      hold_days: 8,
      exit_reason: 'TP',
    },
  ],
  warnings: ['cache_miss'],
  resolved_config: { test: { start_date: '2025-01-01' } },
}

const forwardStatus = {
  run_id: 'fwd-123',
  status: 'ready',
  last_equity: { date: '2026-01-20', equity: 1005000, drawdown: 0.02 },
  last_trade: { timestamp: '2026-01-20T00:00:00Z', action: 'enter', stock: 'SBER' },
  last_alert: { code: 'DATA_STALE', message: 'Missing quotes' },
  state: { phase: 'EOD' },
}

const hpoResponse = {
  status: 'ok',
  mode: 'max',
  leaderboard: [
    { objective: 1.2, params: { 'strategy.z_window': 60 }, fold_objectives: [1.1, 1.3] },
    { objective: 0.9, params: { 'strategy.z_window': 30 }, fold_objectives: [0.8, 1.0] },
  ],
}

const refreshStatus = {
  enabled: true,
  interval_sec: 3600,
  status: 'ok',
  last_success_at: '2026-01-26T15:00:00Z',
}

const registerBaseRoutes = async (page: Page) => {
  await page.route('**/api/v2/decision-view**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v2/top-pairs**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v2/signals/active**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/backtests**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/signals/refresh-status**', (route) =>
    route.fulfill({ json: refreshStatus }),
  )
  await page.route('**/api/signals/refresh**', (route) => route.fulfill({ json: refreshStatus }))
}

test.describe('Backtest v2 + Forward + HPO UI', () => {
  test('Backtest v2 run renders summary, equity, and trades', async ({ page }) => {
    await registerBaseRoutes(page)
    await page.route('**/api/params/specs**', (route) => route.fulfill({ json: paramSpecs }))
    await page.route('**/api/backtest/run**', (route) => route.fulfill({ json: backtestReport }))

    await page.goto('/research-system/backtest-v2')

    await page.getByRole('button', { name: 'Загрузить параметры' }).click()
    await expect(page.getByRole('button', { name: 'Запустить бэктест' })).toBeVisible()
    await page.getByRole('button', { name: 'Запустить бэктест' }).click()

    await expect(page.getByText('Итоговые метрики')).toBeVisible()
    await expect(page.getByText('Кривая эквити')).toBeVisible()
    await expect(page.getByText('Сделки')).toBeVisible()
    await expect(page.getByText('Предупреждение: cache_miss')).toBeVisible()
    await expect(page.getByRole('cell', { name: 'SBER', exact: true })).toBeVisible()
  })

  test('Forward status loads and renders last alert', async ({ page }) => {
    await registerBaseRoutes(page)
    await page.route('**/api/forward/status**', (route) => route.fulfill({ json: forwardStatus }))

    await page.goto('/research-system/forward')
    await page.getByRole('button', { name: 'Загрузить статус' }).click()

    await expect(page.getByText('Прогон: fwd-123')).toBeVisible()
    await expect(page.getByText(/Статус:/)).toBeVisible()
    await expect(page.getByText('DATA_STALE')).toBeVisible()
  })

  test('HPO leaderboard renders objective rows', async ({ page }) => {
    await registerBaseRoutes(page)
    await page.route('**/api/params/specs**', (route) => route.fulfill({ json: paramSpecs }))
    await page.route('**/api/hpo/run**', (route) => route.fulfill({ json: hpoResponse }))

    await page.goto('/research-system/hpo')
    await page.getByRole('button', { name: 'Загрузить параметры' }).click()
    await page.getByRole('button', { name: 'Запустить HPO' }).click()

    await expect(page.getByText('Лидерборд')).toBeVisible()
    await expect(page.locator('table tbody tr')).toHaveCount(2)
  })
})
