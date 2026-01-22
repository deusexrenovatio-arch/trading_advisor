import { expect, test } from '@playwright/test'

const topPairsFirst = [
  {
    stock: 'SBER',
    stock_name: 'Sberbank',
    future: 'SRH6',
    spot: 220.12,
    future_price: 223.45,
    implied_rate_net: 0.12,
    required_rate: 0.08,
    expected_net_irr: 0.12,
    signal_action: 'enter',
    signal_direction: 'cash_and_carry',
    score: 1.2,
  },
  {
    stock: 'GAZP',
    stock_name: 'Gazprom',
    future: 'GZH6',
    spot: 156.7,
    future_price: 158.3,
    implied_rate_net: 0.09,
    required_rate: 0.08,
    expected_net_irr: 0.09,
    signal_action: 'exit',
    signal_direction: 'reverse',
    score: 0.6,
  },
]

const topPairsSecond = [
  {
    stock: 'ALRS',
    stock_name: 'Alrosa',
    future: 'ALH6',
    spot: 65.2,
    future_price: 66.1,
    implied_rate_net: 0.07,
    required_rate: 0.06,
    expected_net_irr: 0.07,
    signal_action: 'enter',
    signal_direction: 'cash_and_carry',
    score: 0.9,
  },
]

const activeSignals = [
  {
    run_id: 'run-1',
    timestamp: '2026-01-12T10:00:00Z',
    stock: 'SBER',
    future: 'SRH6',
    signal_action: 'enter',
    signal_direction: 'cash_and_carry',
    signal_score: 0.42,
  },
  {
    run_id: 'run-1',
    timestamp: '2026-01-12T10:00:00Z',
    stock: 'GAZP',
    future: 'GZH6',
    signal_action: 'exit',
    signal_direction: null,
    signal_score: 0.21,
  },
]

const historyAll = [
  {
    run_id: 'run-1',
    timestamp: '2026-01-12T10:00:00Z',
    stock: 'SBER',
    future: 'SRH6',
    signal_action: 'enter',
    signal_direction: 'cash_and_carry',
    signal_score: 0.42,
  },
  {
    run_id: 'run-1',
    timestamp: '2026-01-12T11:00:00Z',
    stock: 'GAZP',
    future: 'GZH6',
    signal_action: 'exit',
    signal_direction: null,
    signal_score: 0.21,
  },
]

const historyFiltered = [historyAll[0]]

const executionRow = {
  timestamp: '2026-01-12T12:00:00Z',
  stock: 'SBER',
  future: 'SRH6',
  direction: 'cash_and_carry',
  action: 'enter',
  price: 225.5,
  quantity: 2,
  side: 'buy',
  status: 'filled',
  note: 'manual',
}

const backtests = [
  {
    cagr: 0.12,
    sharpe: 1.1,
    max_drawdown: 0.1,
  },
]

const spreadSeries = [
  {
    date: '2026-01-10',
    spread: 1.2,
    zscore: 2.1,
    z_entry: 2.0,
    z_exit: 0.5,
    entry_flag: true,
    exit_flag: false,
    entry_cycle: 1,
    exit_cycle: null,
  },
]

const registerCommonRoutes = async (
  page,
  options: {
    activeSignalsOverride?: typeof activeSignals
    historyResolver?: (url: URL) => typeof historyAll
  } = {},
) => {
  const { activeSignalsOverride, historyResolver } = options
  await page.route('**/api/decision-view**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/backtests**', (route) => route.fulfill({ json: backtests }))
  await page.route('**/api/signals/active**', (route) =>
    route.fulfill({ json: activeSignalsOverride ?? activeSignals }),
  )
  await page.route('**/api/spread-series**', (route) => route.fulfill({ json: spreadSeries }))
  await page.route('**/api/signals/history**', (route) => {
    const url = new URL(route.request().url())
    const data = historyResolver
      ? historyResolver(url)
      : (() => {
          const from = url.searchParams.get('from')
          const to = url.searchParams.get('to')
          return from === '2026-01-12' && to === '2026-01-12' ? historyFiltered : historyAll
        })()
    route.fulfill({ json: data })
  })
}

test.describe('Top pairs + Signals UI', () => {
  test('Top pairs filters and Reload button', async ({ page }) => {
    let topPairsCalls = 0
    await registerCommonRoutes(page)
    await page.route('**/api/top-pairs**', (route) => {
      topPairsCalls += 1
      const data = topPairsCalls > 2 ? topPairsSecond : topPairsFirst
      route.fulfill({ json: data })
    })

    await page.goto('/')
    await page.getByRole('tab', { name: 'Top pairs' }).click()
    await expect(page.getByText('SRH6')).toBeVisible()

    await expect(page.locator('[role="combobox"]').first()).toBeVisible()
    await page.locator('[role="combobox"]').first().click()
    await page.getByRole('option', { name: 'SBER' }).click()

    const tableRows = page.locator('table tbody tr')
    await expect(tableRows).toHaveCount(1)

    await page.locator('[role="combobox"]').first().click()
    await page.getByRole('option', { name: 'All' }).click()

    await page.getByRole('button', { name: 'Reload' }).click()
    await expect(page.getByText('ALH6')).toBeVisible()
    await expect(page.getByText('SRH6')).toHaveCount(0)
  })

  test('Top pairs details load spread chart', async ({ page }) => {
    let spreadCalls = 0
    await registerCommonRoutes(page)
    await page.route('**/api/top-pairs**', (route) => route.fulfill({ json: topPairsFirst }))
    await page.route('**/api/spread-series**', (route) => {
      spreadCalls += 1
      route.fulfill({ json: spreadSeries })
    })

    await page.goto('/')
    await page.getByRole('tab', { name: 'Top pairs' }).click()
    await page.locator('table tbody tr').first().getByRole('button', { name: 'Details' }).click()

    await expect(page.getByText('Spread chart (60d)')).toBeVisible()
    await expect.poll(() => spreadCalls).toBeGreaterThan(0)
  })

  test('Backtests table renders', async ({ page }) => {
    await registerCommonRoutes(page)
    await page.route('**/api/top-pairs**', (route) => route.fulfill({ json: topPairsFirst }))

    await page.goto('/')
    await page.getByRole('tab', { name: 'Backtests' }).click()

    const tableRows = page.locator('table tbody tr')
    await expect(tableRows).toHaveCount(1)
    await expect(tableRows.first().getByText('1.10')).toBeVisible()
  })

  test('Signals filters and date range', async ({ page }) => {
    await registerCommonRoutes(page)
    await page.route('**/api/top-pairs**', (route) => route.fulfill({ json: topPairsFirst }))

    await page.goto('/')
    await page.getByRole('tab', { name: 'Signals' }).click()
    await expect(page.getByText('SBER')).toBeVisible()

    await page.getByLabel('History from (YYYY-MM-DD)').fill('2026-01-12')
    await page.getByLabel('History to (YYYY-MM-DD)').fill('2026-01-12')
    await page.getByRole('button', { name: 'Load history' }).click()

    const historySection = page.getByText('Signal history').locator('..')
    const historyTable = historySection.locator('table')
    await expect(historyTable.locator('tbody tr')).toHaveCount(1)

    await page.getByLabel('History from (YYYY-MM-DD)').fill('')
    await page.getByLabel('History to (YYYY-MM-DD)').fill('')
    await page.getByRole('button', { name: 'Load history' }).click()
    await expect(historyTable.locator('tbody tr')).toHaveCount(2)

    await expect(page.locator('[role="combobox"]').first()).toBeVisible()
    await page.locator('[role="combobox"]').first().click()
    await page.getByRole('option', { name: 'GAZP' }).click()
    await expect(historyTable.locator('tbody tr')).toHaveCount(1)

    await page.locator('[role="combobox"]').first().click()
    await page.getByRole('option', { name: 'All' }).click()

    await page.locator('[role="combobox"]').nth(2).click()
    await page.getByRole('option', { name: 'exit' }).click()
    await expect(historyTable.locator('tbody tr')).toHaveCount(1)
  })

  test('Signals history filters apply without active signals', async ({ page }) => {
    await registerCommonRoutes(page, {
      activeSignalsOverride: [],
      historyResolver: () => historyAll,
    })
    await page.route('**/api/top-pairs**', (route) => route.fulfill({ json: topPairsFirst }))

    await page.goto('/')
    await page.getByRole('tab', { name: 'Signals' }).click()
    await page.getByRole('button', { name: 'Load history' }).click()

    const historySection = page.getByText('Signal history').locator('..')
    const historyTable = historySection.locator('table')
    await expect(historyTable.locator('tbody tr')).toHaveCount(2)

    await page.locator('[role="combobox"]').first().click()
    await page.getByRole('option', { name: 'GAZP' }).click()
    await expect(historyTable.locator('tbody tr')).toHaveCount(1)
  })

  test('Signals execute posts and shows history', async ({ page }) => {
    let executionPayload = null
    let executionCalls = 0
    await registerCommonRoutes(page)
    await page.route('**/api/top-pairs**', (route) => route.fulfill({ json: topPairsFirst }))
    await page.route('**/api/signals/execute', async (route) => {
      executionPayload = route.request().postDataJSON()
      await route.fulfill({ json: { status: 'ok' } })
    })
    await page.route('**/api/signals/executions**', (route) => {
      executionCalls += 1
      const data = executionCalls > 1 ? [executionRow] : []
      route.fulfill({ json: data })
    })

    await page.goto('/')
    await page.getByRole('tab', { name: 'Signals' }).click()
    await page.locator('table tbody tr').first().getByRole('button', { name: 'Details' }).click()

    await expect(page.getByText('Execute signal')).toBeVisible()
    await page.getByLabel('Price').fill('225.5')
    await page.getByLabel('Qty').fill('2')
    await page.getByLabel('Side').fill('buy')
    await page.getByLabel('Status').fill('filled')
    await page.getByLabel('Note').fill('manual')
    await page.getByRole('button', { name: 'Execute' }).click()

    await expect(page.getByText('Execution history')).toBeVisible()
    await expect(page.getByText('filled')).toBeVisible()
    await expect.poll(() => executionPayload).not.toBeNull()
    await expect.poll(() => executionCalls).toBeGreaterThan(1)
    expect(executionPayload).toMatchObject({
      stock: 'SBER',
      future: 'SRH6',
      action: 'enter',
      direction: 'cash_and_carry',
      price: 225.5,
      quantity: 2,
      side: 'buy',
      status: 'filled',
      note: 'manual',
    })
  })
})
