import { expect, test } from '@playwright/test'

const decisionViewFirst = [
  {
    decision_id: 'decision-1',
    created_at: '2026-01-12T10:00:00Z',
    strategy_type: 'arbitrage',
    primary_instrument: 'SBER',
    action: 'approve',
    risk_state: 'green',
    news_severity: 'low',
    proposal_summary: {
      type: 'rebalance',
      cadence: 'weekly',
      effective_date: '2026-01-15T00:00:00Z',
      summary: 'Shift from speculative to fundamental.',
    },
    execution_status: {
      status: 'queued',
      requested_at: '2026-01-12T10:05:00Z',
    },
  },
  {
    decision_id: 'decision-2',
    created_at: '2026-01-12T11:00:00Z',
    strategy_type: 'stat',
    primary_instrument: 'GAZP',
    action: 'reject',
    risk_state: 'red',
    news_severity: 'high',
  },
]

const decisionViewSecond = [
  {
    decision_id: 'decision-3',
    created_at: '2026-01-12T12:00:00Z',
    strategy_type: 'carry',
    primary_instrument: 'LKOH',
    action: 'approve',
    risk_state: 'yellow',
    news_severity: 'medium',
  },
]

const decisionLogs: Record<string, Record<string, unknown>> = {
  'decision-1': {
    decision_id: 'decision-1',
    created_at: '2026-01-12T10:00:00Z',
    decision: { action: 'approve', risk_state: 'green' },
    strategies: [{ type: 'arbitrage' }],
    proposal: {
      type: 'rebalance',
      cadence: 'weekly',
      effective_date: '2026-01-15T00:00:00Z',
      summary: 'Shift from speculative to fundamental.',
    },
    basket_allocations: {
      current: [
        { basket: 'fundamental', weight: 0.5 },
        { basket: 'speculative', weight: 0.3 },
        { basket: 'arbitrage', weight: 0.2 },
      ],
      target: [
        { basket: 'fundamental', weight: 0.6 },
        { basket: 'speculative', weight: 0.2 },
        { basket: 'arbitrage', weight: 0.2 },
      ],
      delta: [
        { basket: 'fundamental', weight: 0.1 },
        { basket: 'speculative', weight: -0.1 },
        { basket: 'arbitrage', weight: 0.0 },
      ],
    },
    facts: [
      {
        category: 'news_sentiment',
        label: 'News sentiment',
        value: 'negative',
        source: 'news-feed',
        confidence: 0.72,
      },
    ],
    aggregation: { reasons: ['risk_limit_breach'] },
  },
}
const refreshStatus = {
  enabled: true,
  interval_sec: 3600,
  status: 'ok',
  last_success_at: '2026-01-26T15:00:00Z',
}

const registerBaseRoutes = async (page) => {
  await page.route('**/api/top-pairs**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/signals/active**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/backtests**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/signals/refresh-status**', (route) =>
    route.fulfill({ json: refreshStatus }),
  )
  await page.route('**/api/signals/refresh**', (route) =>
    route.fulfill({ json: refreshStatus }),
  )
  await page.route('**/api/decisions/**/action', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        json: {
          operator_action: {},
          execution_status: {},
        },
      })
      return
    }
    await route.fulfill({
      json: {
        status: 'ok',
        operator_action: {
          action: 'approve',
          status: 'recorded',
          actor: 'operator',
          created_at: '2026-01-12T10:05:00Z',
        },
        execution_status: {
          status: 'queued',
          requested_at: '2026-01-12T10:05:00Z',
        },
      },
    })
  })
}

test.describe('Decisions UI', () => {
  test('filters, quick search, refresh, and detail', async ({ page }) => {
    let decisionCalls = 0
    await registerBaseRoutes(page)
    await page.route('**/api/decision-view**', (route) => {
      decisionCalls += 1
      const data = decisionCalls > 2 ? decisionViewSecond : decisionViewFirst
      route.fulfill({ json: data })
    })
    await page.route('**/api/decision-log/**', (route) => {
      const url = new URL(route.request().url())
      const decisionId = url.pathname.split('/').pop() ?? ''
      const payload = decisionLogs[decisionId]
      if (!payload) {
        route.fulfill({ status: 404, json: { error: 'not_found' } })
        return
      }
      route.fulfill({ json: payload })
    })

    const decisionResponse = page.waitForResponse('**/api/decision-view**')
    await page.goto('/')
    await expect(page.getByText('Trading Advisor Decisions')).toBeVisible()
    await decisionResponse
    await expect(page.getByRole('button', { name: 'Refresh' })).toBeVisible()

    await page.getByRole('tab', { name: 'Decisions' }).click()

    const decisionCell1 = page.getByText('decision-1', { exact: true })
    const decisionCell2 = page.getByText('decision-2', { exact: true })
    const decisionCell3 = page.getByText('decision-3', { exact: true })
    await expect(decisionCell1).toBeVisible()
    await expect(decisionCell2).toBeVisible()

    const filters = page.locator('[role="combobox"]')
    await filters.nth(0).click()
    await page.getByRole('option', { name: 'arbitrage' }).click()
    await expect(decisionCell1).toBeVisible()
    await expect(decisionCell2).toHaveCount(0)

    await filters.nth(0).click()
    await page.getByRole('option', { name: 'All' }).click()

    await filters.nth(1).click()
    await page.getByRole('option', { name: 'GAZP' }).click()
    await expect(decisionCell2).toBeVisible()
    await expect(decisionCell1).toHaveCount(0)

    await filters.nth(1).click()
    await page.getByRole('option', { name: 'All' }).click()

    await page.getByLabel('Quick search').fill('SBER')
    await expect(decisionCell1).toBeVisible()
    await expect(decisionCell2).toHaveCount(0)
    await page.getByLabel('Quick search').fill('')

    await decisionCell1.click()
    await expect(page.getByText('Orchestrator proposal')).toBeVisible()
    await expect(page.getByText('Basket allocations (by strategy type)')).toBeVisible()
    await expect(page.getByText('News sentiment: negative')).toBeVisible()

    await page.getByRole('button', { name: 'Approve & execute' }).click()
    await expect(page.getByText('Execution: queued')).toBeVisible()

    await page.getByRole('button', { name: 'Refresh' }).click()
    await expect(decisionCell3).toBeVisible()
  })
})
