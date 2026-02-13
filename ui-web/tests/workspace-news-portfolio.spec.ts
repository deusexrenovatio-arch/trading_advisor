import { expect, test } from '@playwright/test'

const decisionView = [
  {
    decision_id: 'decision-1',
    created_at: '2026-02-12T10:00:00Z',
    strategy_type: 'arbitrage',
    primary_instrument: 'SBER',
    action: 'approve',
    risk_state: 'green',
    news_severity: 'low',
  },
]

const refreshStatus = {
  enabled: true,
  interval_sec: 3600,
  status: 'ok',
  last_success_at: '2026-02-12T10:05:00Z',
}

const newsFeed = [
  {
    news_event_id: 'news-1',
    published_at: '2026-02-12T09:00:00Z',
    severity: 'high',
    headline: 'Central bank update',
    entity_links: [{ entity_type: 'instrument', entity_id: 'SBER:SRH6', ticker: 'SBER' }],
    decision_ref: { decision_id: 'decision-1' },
  },
  {
    news_event_id: 'news-2',
    published_at: '2026-02-12T09:30:00Z',
    severity: 'low',
    headline: 'Commodity flow snapshot',
    entity_links: [{ entity_type: 'instrument', entity_id: 'GAZP:GZH6', ticker: 'GAZP' }],
  },
]

const rebalancePreview = {
  rebalance_plan_id: 'plan-1',
  generated_at: '2026-02-12T10:10:00Z',
  positions: [
    {
      entity_ref: { entity_type: 'pair', entity_id: 'SBER:SRH6' },
      target_weight: 0.2,
      signal_id: 'signal-1',
      lifecycle_state: 'ready',
      signal_action: 'enter',
      signal_score: 0.71,
    },
  ],
  risk_checks: [{ name: 'turnover_limit', status: 'pass' }],
}

const registerBaseRoutes = async (page) => {
  await page.route('**/api/v2/decision-view**', (route) => route.fulfill({ json: decisionView }))
  await page.route('**/api/decision-log/**', (route) =>
    route.fulfill({ json: { decision: { action: 'approve' }, aggregation: {}, proposal: {}, facts: [] } }),
  )
  await page.route('**/api/decisions/**/action', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: { operator_action: {}, execution_status: {} } })
      return
    }
    await route.fulfill({
      json: {
        status: 'ok',
        operator_action: { action: 'approve', status: 'recorded' },
        execution_status: { status: 'queued' },
      },
    })
  })

  await page.route('**/api/top-pairs**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v2/signals/active**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/backtests**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/signals/refresh-status**', (route) =>
    route.fulfill({ json: refreshStatus }),
  )
  await page.route('**/api/signals/refresh**', (route) => route.fulfill({ json: refreshStatus }))
}

test.describe('Workspace News + Portfolio', () => {
  test('News workspace route and filters', async ({ page }) => {
    await registerBaseRoutes(page)
    await page.route('**/api/v2/news/feed**', (route) => {
      const url = new URL(route.request().url())
      const severity = (url.searchParams.get('severity') ?? '').toLowerCase()
      const ticker = (url.searchParams.get('ticker') ?? '').toUpperCase()
      const data = newsFeed.filter((row) => {
        if (severity && row.severity !== severity) return false
        if (ticker && row.entity_links?.[0]?.ticker !== ticker) return false
        return true
      })
      route.fulfill({ json: data })
    })

    await page.goto('/')
    await page.getByRole('tab', { name: 'News Intelligence' }).click()
    await expect(page).toHaveURL(/\/news-intelligence$/)
    await expect(page.getByRole('heading', { name: 'News Intelligence' })).toBeVisible()
    await expect(page.getByText('Central bank update')).toBeVisible()

    await page.getByLabel('Ticker').fill('SBER')
    await page.getByRole('button', { name: 'Reload' }).click()
    await expect(page.getByText('Central bank update')).toBeVisible()
    await expect(page.getByText('Commodity flow snapshot')).toHaveCount(0)

    await expect(page.getByText(/tab_switch_count: [1-9]\d*/)).toBeVisible()
  })

  test('Portfolio workspace preview and commit', async ({ page }) => {
    let commitPayload: Record<string, unknown> | null = null
    await registerBaseRoutes(page)
    await page.route('**/api/v2/news/feed**', (route) => route.fulfill({ json: [] }))
    await page.route('**/api/v2/portfolio/rebalance/preview**', (route) =>
      route.fulfill({ json: rebalancePreview }),
    )
    await page.route('**/api/v2/portfolio/rebalance/commit', (route) => {
      commitPayload = route.request().postDataJSON() as Record<string, unknown>
      route.fulfill({
        json: {
          status: 'ok',
          commit_id: 'commit-1',
          rebalance_plan_id: 'plan-1',
          positions_committed: 1,
          committed_at: '2026-02-12T10:11:00Z',
        },
      })
    })

    await page.goto('/')
    await page.getByRole('tab', { name: 'Portfolio Control' }).click()
    await expect(page).toHaveURL(/\/portfolio-control$/)
    await expect(page.getByRole('heading', { name: 'Portfolio Control' })).toBeVisible()
    await expect(page.getByText('SBER:SRH6')).toBeVisible()

    await page.getByRole('button', { name: 'Commit Rebalance' }).click()
    await expect(page.getByText('Committed 1 positions (commit-1)')).toBeVisible()
    await expect
      .poll(() => commitPayload?.rebalance_plan_id)
      .toBe('plan-1')
  })
})
