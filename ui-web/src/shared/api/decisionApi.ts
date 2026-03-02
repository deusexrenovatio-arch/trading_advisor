import { requestJson } from './http'
import type {
  BacktestReport,
  DecisionLog,
  DecisionView,
  DecisionRefV2,
  ExecutionRow,
  ExecutionRefV2,
  ExecutionStatus,
  ForwardStatus,
  HpoResponse,
  NewsEventV2,
  OperatorAction,
  ParameterSpec,
  PretradeCheckResult,
  RebalanceCommitV2,
  RebalancePreviewV2,
  RefreshStatus,
  SignalActiveV2,
  SignalHistoryRow,
  SpreadSeriesPoint,
} from '../../entities/decision/types'

export type DecisionActionResponse = {
  operator_action?: OperatorAction
  execution_status?: ExecutionStatus
  decision_ref?: DecisionRefV2
  execution_ref?: ExecutionRefV2
}

export type DecisionViewFilters = {
  limit?: number
  strategy_type?: string
  primary_instrument?: string
  risk_state?: string
  news_severity?: string
  created_from?: string
  created_to?: string
}

export const fetchDecisionView = (filters: DecisionViewFilters) => {
  const params = new URLSearchParams()
  if (filters.limit) params.set('limit', String(filters.limit))
  if (filters.strategy_type) params.set('strategy_type', filters.strategy_type)
  if (filters.primary_instrument) params.set('primary_instrument', filters.primary_instrument)
  if (filters.risk_state) params.set('risk_state', filters.risk_state)
  if (filters.news_severity) params.set('news_severity', filters.news_severity)
  if (filters.created_from) params.set('created_from', filters.created_from)
  if (filters.created_to) params.set('created_to', filters.created_to)
  const query = params.toString()
  const url = query ? `/api/v2/decision-view?${query}` : '/api/v2/decision-view'
  return requestJson<DecisionView[]>(url, { cache: 'no-store' })
}

export const fetchDecisionLog = (decisionId: string) =>
  requestJson<DecisionLog>(`/api/decision-log/${decisionId}`)

export const submitDecisionAction = (decisionId: string, payload: unknown) =>
  requestJson<DecisionActionResponse>(
    `/api/v2/decisions/${decisionId}/actions`,
    {
      method: 'POST',
      body: payload,
    },
  )

export const fetchTopPairs = (limit: number, allPairs: boolean) => {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  params.set('all', allPairs ? 'true' : 'false')
  return requestJson<Record<string, unknown>[]>(`/api/v2/top-pairs?${params.toString()}`, {
    cache: 'no-store',
  })
}

export const fetchSignalsActive = () =>
  requestJson<Record<string, unknown>[]>('/api/signals/active', { cache: 'no-store' })

export const fetchSignalsActiveV2 = () =>
  requestJson<SignalActiveV2[]>('/api/v2/signals/active', { cache: 'no-store' })

export const submitSignalActionV2 = (signalId: string, payload: Record<string, unknown>) =>
  requestJson<Record<string, unknown>>(`/api/v2/signals/${signalId}/actions`, {
    method: 'POST',
    body: payload,
  })

export const fetchBacktests = (limit = 500) =>
  requestJson<Record<string, unknown>[]>(`/api/backtests?limit=${limit}`, { cache: 'no-store' })

export const fetchRefreshStatus = () =>
  requestJson<RefreshStatus>('/api/signals/refresh-status', { cache: 'no-store' })

export const refreshSignals = () =>
  requestJson<RefreshStatus>('/api/signals/refresh', { method: 'POST' })

export const fetchSignalHistory = (
  from: string | undefined,
  to: string | undefined,
  limit: number,
  stock?: string,
  future?: string,
  action?: string,
) => {
  const params = new URLSearchParams()
  if (from) params.set('from', from)
  if (to) params.set('to', to)
  params.set('limit', String(limit))
  if (stock) params.set('stock', stock)
  if (future) params.set('future', future)
  if (action) params.set('signal_action', action)
  return requestJson<SignalHistoryRow[]>(`/api/v2/signals/history?${params.toString()}`, {
    cache: 'no-store',
  })
}

export const fetchSignalExecutions = (stock: string, future: string, limit = 20) => {
  const params = new URLSearchParams()
  params.set('stock', stock)
  params.set('future', future)
  params.set('limit', String(limit))
  return requestJson<ExecutionRow[]>(`/api/v2/signals/executions?${params.toString()}`, {
    cache: 'no-store',
  })
}

export const fetchSpreadSeries = (
  stock: string,
  future: string,
  windowDays = 60,
  fullLife?: boolean,
) => {
  const params = new URLSearchParams()
  params.set('stock', stock)
  params.set('future', future)
  params.set('window_days', String(windowDays))
  if (fullLife !== undefined) params.set('full_life', fullLife ? 'true' : 'false')
  return requestJson<SpreadSeriesPoint[]>(`/api/spread-series?${params.toString()}`, {
    cache: 'no-store',
  })
}

type PretradeCheckOptions = {
  direction?: 'cash_and_carry' | 'reverse'
  snapshots?: number
  minHits?: number
  eps?: number
  stockEps?: number
  futureEps?: number
  spreadEps?: number
  syncSec?: number
  pollSec?: number
  qtyFut?: number
  participationRate?: number
  requireTradeflowForLast?: boolean
}

export const fetchPretradeCheck = (
  stock: string,
  future: string,
  options: PretradeCheckOptions = {},
) => {
  return requestJson<PretradeCheckResult>('/api/v2/pretrade/check', {
    method: 'POST',
    body: {
      stock,
      future,
      direction: options.direction,
      snapshots: options.snapshots,
      min_hits: options.minHits,
      eps: options.eps,
      stock_eps: options.stockEps,
      future_eps: options.futureEps,
      spread_eps: options.spreadEps,
      sync_sec: options.syncSec,
      poll_sec: options.pollSec,
      qty_fut: options.qtyFut,
      participation_rate: options.participationRate,
      require_tradeflow_for_last: options.requireTradeflowForLast,
    },
  })
}

export const fetchParamSpecs = (preset?: string) => {
  const params = new URLSearchParams()
  if (preset) params.set('preset', preset)
  const url = params.toString() ? `/api/params/specs?${params.toString()}` : '/api/params/specs'
  return requestJson<ParameterSpec[]>(url, { cache: 'no-store' })
}

export const runBacktest = (payload: Record<string, unknown>) =>
  requestJson<BacktestReport>('/api/backtest/run', {
    method: 'POST',
    body: payload,
  })

export const fetchForwardStatus = (runId?: string) => {
  const params = new URLSearchParams()
  if (runId) params.set('run_id', runId)
  const url = params.toString() ? `/api/forward/status?${params.toString()}` : '/api/forward/status'
  return requestJson<ForwardStatus>(url, { cache: 'no-store' })
}

export const startForwardRun = (payload: { request?: Record<string, unknown> } = {}) =>
  requestJson<ForwardStatus>('/api/forward/start', {
    method: 'POST',
    body: payload,
  })

export const runHpo = (payload: Record<string, unknown>) =>
  requestJson<HpoResponse>('/api/hpo/run', {
    method: 'POST',
    body: payload,
  })

export const fetchHpoStatus = (runId?: string) => {
  const params = new URLSearchParams()
  if (runId) params.set('run_id', runId)
  const url = params.toString() ? `/api/hpo/status?${params.toString()}` : '/api/hpo/status'
  return requestJson<HpoResponse>(url, { cache: 'no-store' })
}

export const fetchNewsFeedV2 = (filters: {
  severity?: string
  ticker?: string
  entity_id?: string
  from?: string
  to?: string
  limit?: number
}) => {
  const params = new URLSearchParams()
  if (filters.severity) params.set('severity', filters.severity)
  if (filters.ticker) params.set('ticker', filters.ticker)
  if (filters.entity_id) params.set('entity_id', filters.entity_id)
  if (filters.from) params.set('from', filters.from)
  if (filters.to) params.set('to', filters.to)
  if (filters.limit) params.set('limit', String(filters.limit))
  const query = params.toString()
  const url = query ? `/api/v2/news/feed?${query}` : '/api/v2/news/feed'
  return requestJson<NewsEventV2[]>(url, { cache: 'no-store' })
}

export const fetchRebalancePreviewV2 = (limit = 12) =>
  requestJson<RebalancePreviewV2>(`/api/v2/portfolio/rebalance/preview?limit=${limit}`, {
    cache: 'no-store',
  })

export const commitRebalanceV2 = (payload: {
  rebalance_plan_id: string
  actor_id?: string
  note?: string
  positions: Array<Record<string, unknown>>
}) =>
  requestJson<RebalanceCommitV2>('/api/v2/portfolio/rebalance/commit', {
    method: 'POST',
    body: payload,
  })
