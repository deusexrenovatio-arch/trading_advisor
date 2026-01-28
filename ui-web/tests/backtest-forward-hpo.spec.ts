import { expect, test } from '@playwright/test'

const paramSpecs = [
  { key: 'test.start_date', value_type: 'str', default: '2025-01-01' },
  { key: 'test.end_date', value_type: 'str', default: '2025-12-31' },
  { key: 'strategy.z_window', value_type: 'int', default: 60 },
  { key: 'strategy.TP_pct', value_type: 'float', default: 0.01 },
  { key: 'strategy.min_total_score', value_type: 'float', default: null },
  { key: 'allocation.weights', value_type: 'dict', default: { fundamental: 0.4 } },
  { key: 'liquidity.use_adv', value_type: 'bool', default: true },
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

const registerBaseRoutes = async (page) => {
  await page.route('**/api/decision-view**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/top-pairs**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/signals/active**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/backtests**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/signals/refresh-status**', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/signals/refresh', (route) => route.fulfill({ json: {} }))
}

test.describe('Backtest v2 + Forward + HPO UI', () => {
  test('Backtest v2 run renders summary, equity, and trades', async ({ page }) => {
    await registerBaseRoutes(page)
    await page.route('**/api/params/specs**', (route) => route.fulfill({ json: paramSpecs }))
    await page.route('**/api/backtest/run', (route) => route.fulfill({ json: backtestReport }))

    await page.goto('/')
    await page.getByRole('tab', { name: 'Бэктест v2' }).click()

    await expect(page.getByRole('textbox', { name: 'Дата начала' })).toBeVisible()
    await page.getByRole('button', { name: /Аллокация/ }).click()
    await expect(page.getByText('Вес корзин')).toBeVisible()
    await expect(page.getByText('Фундаментальная', { exact: true })).toBeVisible()
    await expect(page.getByText('test.start_date', { exact: true })).toHaveCount(0)
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

    await page.goto('/')
    await page.getByRole('tab', { name: 'Статус форварда' }).click()
    await page.getByRole('button', { name: 'Загрузить статус' }).click()

    await expect(page.getByText('Прогон: fwd-123')).toBeVisible()
    await expect(page.getByText('Статус: готово')).toBeVisible()
    await expect(page.getByText('DATA_STALE')).toBeVisible()
  })

  test('HPO leaderboard renders objective rows', async ({ page }) => {
    await registerBaseRoutes(page)
    await page.route('**/api/params/specs**', (route) => route.fulfill({ json: paramSpecs }))
    await page.route('**/api/hpo/run', (route) => route.fulfill({ json: hpoResponse }))

    await page.goto('/')
    await page.getByRole('tab', { name: 'HPO' }).click()
    await page.getByRole('button', { name: 'Запустить HPO' }).click()

    await expect(page.getByText('Лидерборд')).toBeVisible()
    await expect(page.getByText('1.2000')).toBeVisible()
  })
})
