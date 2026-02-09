import { expect, test } from '@playwright/test'

const topPairsFirst = [
  {
    stock: 'SBER',
    stock_name: 'Sberbank',
    future: 'SRH6',
    expiry: '2026-03-19',
    spot: 220.12,
    future_price: 223.45,
    spread_mid: 1.2,
    spread_pct: 0.012,
    rtc_pct: 0.001,
    floor_rate_annual: 0.18,
    score_floor: 0.02,
    avg_trade_return_annual_recent: 0.14,
    score_alpha: 0.005,
    total_score: 0.025,
    decision: 'ENTER_OK',
    signal_action: 'enter',
    signal_direction: 'cash_and_carry',
    signal_score: 0.025,
  },
  {
    stock: 'GAZP',
    stock_name: 'Gazprom',
    future: 'GZH6',
    expiry: '2026-03-19',
    spot: 156.7,
    future_price: 158.3,
    spread_mid: -0.4,
    spread_pct: -0.004,
    rtc_pct: 0.001,
    floor_rate_annual: 0.09,
    score_floor: -0.01,
    avg_trade_return_annual_recent: 0.05,
    score_alpha: 0.002,
    total_score: -0.008,
    decision: 'SKIP_FLOOR',
    signal_action: 'hold',
    signal_direction: 'reverse',
    signal_score: -0.008,
  },
]

const topPairsSecond = [
  {
    stock: 'ALRS',
    stock_name: 'Alrosa',
    future: 'ALH6',
    expiry: '2026-06-18',
    spot: 65.2,
    future_price: 66.1,
    spread_mid: 0.5,
    spread_pct: 0.008,
    rtc_pct: 0.001,
    floor_rate_annual: 0.11,
    score_floor: 0.01,
    avg_trade_return_annual_recent: 0.09,
    score_alpha: 0.004,
    total_score: 0.014,
    decision: 'ENTER_OK',
    signal_action: 'enter',
    signal_direction: 'cash_and_carry',
    signal_score: 0.014,
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
    spread_pct: 0.011,
    entry_spread_pct_min: 0.009,
    entry_spread_pct_max: 0.013,
    tp_spread_pct_level: 0.021,
    sl_spread_pct_level: 0.001,
    forecast_exit_days: 5,
    forecast_exit_date: '2026-01-17',
    signal_metrics: {
      entry_spread_pct_min: 0.009,
      entry_spread_pct_max: 0.013,
      tp_spread_pct_level: 0.021,
      sl_spread_pct_level: 0.001,
      forecast_exit_days: 5,
    },
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
    spread_mid: 1.2,
    spread_pct: 0.012,
    entry_flag: true,
    exit_flag: false,
  },
]
const refreshStatus = {
  enabled: true,
  interval_sec: 3600,
  status: 'ok',
  last_success_at: '2026-01-26T15:00:00Z',
}

const pretradeCheck = {
  status: 'CHECK',
  ready_to_place: false,
  manual_confirm_required: true,
  reasons: ['stock_volume_miss', 'spread_out_of_band'],
  order_price_bands: {
    stock_buy_max: 224.6,
    stock_sell_min: 223.4,
    future_buy_max_per_share: 226.8,
    future_sell_min_per_share: 225.2,
    future_buy_max_contract: 2268,
    future_sell_min_contract: 2252,
    spread_min: -2.1,
    spread_max: -1.8,
  },
  volume_requirements: {
    qty_fut_contracts: 2,
    qty_stock_shares: 20,
    participation_rate: 0.1,
    min_session_volume_stock: 1200,
    min_session_volume_fut_contracts: 140,
  },
  gates: {
    stock_price_pass: true,
    fut_price_pass: true,
    spread_pass: false,
    sync_pass: true,
    stock_volume_pass: false,
    fut_volume_pass: true,
  },
  hits: {
    required: 2,
    stock_price_hits: 2,
    fut_price_hits: 2,
    spread_hits: 1,
    sync_hits: 2,
    stock_volume_hits: 1,
    fut_volume_hits: 2,
    snapshots: 4,
  },
}

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
  await page.route('**/api/signals/refresh-status**', (route) =>
    route.fulfill({ json: refreshStatus }),
  )
  await page.route('**/api/signals/refresh**', (route) =>
    route.fulfill({ json: refreshStatus }),
  )
  await page.route('**/api/pretrade/check**', (route) => route.fulfill({ json: pretradeCheck }))
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
    let useSecond = false
    await registerCommonRoutes(page)
    await page.route('**/api/top-pairs**', (route) => {
      const data = useSecond ? topPairsSecond : topPairsFirst
      route.fulfill({ json: data })
    })

    await page.goto('/')
    await page.getByRole('tab', { name: 'Топ пар' }).click()
    await expect(page.getByText('SRH6')).toBeVisible()
    const headerRow = page.locator('table thead')
    await expect(headerRow.getByText('Средн. годовая доходность (посл. 5)')).toBeVisible()

    await expect(page.locator('[role="combobox"]').first()).toBeVisible()
    await page.locator('[role="combobox"]').first().click()
    await page.getByRole('option', { name: 'SBER' }).click()

    const tableRows = page.locator('table tbody tr')
    await expect(tableRows).toHaveCount(1)

    await page.locator('[role="combobox"]').first().click()
    await page.getByRole('option', { name: 'Все' }).click()

    useSecond = true
    await page.getByRole('button', { name: 'Обновить' }).click()
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
    await page.getByRole('tab', { name: 'Топ пар' }).click()
    await page.locator('table tbody tr').first().getByRole('button', { name: 'Детали' }).click()

    await expect(page.getByText('График спреда (жизнь контракта)')).toBeVisible()
    await expect.poll(() => spreadCalls).toBeGreaterThan(0)
  })

  test('Backtests table renders', async ({ page }) => {
    await registerCommonRoutes(page)
    await page.route('**/api/top-pairs**', (route) => route.fulfill({ json: topPairsFirst }))

    await page.goto('/')
    await page.getByRole('tab', { name: 'Бэктесты' }).click()

    const tableRows = page.locator('table tbody tr')
    await expect(tableRows).toHaveCount(1)
    await expect(tableRows.first().getByText('1.10')).toBeVisible()
  })

  test('Signals filters and date range', async ({ page }) => {
    await registerCommonRoutes(page)
    await page.route('**/api/top-pairs**', (route) => route.fulfill({ json: topPairsFirst }))

    await page.goto('/')
    await page.getByRole('tab', { name: 'Сигналы' }).click()
    await expect(page.getByText('SBER')).toBeVisible()
    const headerRow = page.locator('table thead')
    await expect(headerRow.getByText('Entry spread min, %')).toBeVisible()
    await expect(headerRow.getByText('SL spread level, %')).toBeVisible()

    await page.getByLabel('История с (ГГГГ-ММ-ДД)').fill('2026-01-12')
    await page.getByLabel('История по (ГГГГ-ММ-ДД)').fill('2026-01-12')
    await page.getByRole('button', { name: 'Загрузить историю' }).click()

    const historySection = page.getByText('История сигналов').locator('..')
    const historyTable = historySection.locator('table')
    await expect(historyTable.locator('tbody tr')).toHaveCount(1)

    await page.getByLabel('История с (ГГГГ-ММ-ДД)').fill('')
    await page.getByLabel('История по (ГГГГ-ММ-ДД)').fill('')
    await page.getByRole('button', { name: 'Загрузить историю' }).click()
    await expect(historyTable.locator('tbody tr')).toHaveCount(2)

    await expect(page.locator('[role="combobox"]').first()).toBeVisible()
    await page.locator('[role="combobox"]').first().click()
    await page.getByRole('option', { name: 'GAZP' }).click()
    await expect(historyTable.locator('tbody tr')).toHaveCount(1)

    await page.locator('[role="combobox"]').first().click()
    await page.getByRole('option', { name: 'Все' }).click()

    await page.locator('[role="combobox"]').nth(2).click()
    await page.getByRole('option', { name: 'Выход' }).click()
    await expect(historyTable.locator('tbody tr')).toHaveCount(1)
  })

  test('Signals history filters apply without active signals', async ({ page }) => {
    await registerCommonRoutes(page, {
      activeSignalsOverride: [],
      historyResolver: () => historyAll,
    })
    await page.route('**/api/top-pairs**', (route) => route.fulfill({ json: topPairsFirst }))

    await page.goto('/')
    await page.getByRole('tab', { name: 'Сигналы' }).click()
    await page.getByLabel('История с (ГГГГ-ММ-ДД)').fill('')
    await page.getByLabel('История по (ГГГГ-ММ-ДД)').fill('')
    await page.getByRole('button', { name: 'Загрузить историю' }).click()

    const historySection = page.getByText('История сигналов').locator('..')
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
    await page.locator('[role="tab"]').nth(2).click()
    await page.locator('table tbody tr').first().locator('button').first().click()

    const detailRow = page.locator('table tbody tr').nth(1)
    const executeInputs = detailRow.locator('input')
    await executeInputs.nth(0).fill('225.5')
    await executeInputs.nth(1).fill('2')
    await executeInputs.nth(2).fill('buy')
    await executeInputs.nth(3).fill('filled')
    await executeInputs.nth(4).fill('manual')
    await detailRow.locator('button.MuiButton-contained').first().click()

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

  test('Signals details show pre-trade block', async ({ page }) => {
    await registerCommonRoutes(page)
    await page.route('**/api/top-pairs**', (route) => route.fulfill({ json: topPairsFirst }))

    await page.goto('/')
    await page.locator('[role="tab"]').nth(2).click()
    await page.locator('table tbody tr').first().locator('button').first().click()

    await expect(page.getByRole('heading', { name: /Pre-trade/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /pre-trade/i })).toBeVisible()
    await expect(page.getByText(/buy max/i).first()).toBeVisible()
    await expect(page.getByRole('heading', { name: /Hit/i })).toBeVisible()
  })
})
