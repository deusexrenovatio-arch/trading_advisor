import { requestJson } from './http'
import type {
  BacktestReport,
  DecisionLog,
  DecisionView,
  ExecutionRow,
  ExecutionStatus,
  ForwardStatus,
  HpoResponse,
  OperatorAction,
  ParameterSpec,
  PretradeCheckResult,
  RefreshStatus,
  SignalHistoryRow,
  SpreadSeriesPoint,
} from '../../entities/decision/types'

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
  const url = query ? `/api/decision-view?${query}` : '/api/decision-view'
  return requestJson<DecisionView[]>(url, { cache: 'no-store' })
}

export const fetchDecisionLog = (decisionId: string) =>
  requestJson<DecisionLog>(`/api/decision-log/${decisionId}`)

export const fetchDecisionAction = (decisionId: string) =>
  requestJson<{ operator_action?: OperatorAction; execution_status?: ExecutionStatus }>(
    `/api/decisions/${decisionId}/action`,
    { cache: 'no-store' },
  )

export const submitDecisionAction = (decisionId: string, payload: unknown) =>
  requestJson<{ operator_action?: OperatorAction; execution_status?: ExecutionStatus }>(
    `/api/decisions/${decisionId}/action`,
    {
      method: 'POST',
      body: payload,
    },
  )

export const fetchTopPairs = (limit: number, allPairs: boolean) => {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  params.set('all', allPairs ? 'true' : 'false')
  return requestJson<Record<string, unknown>[]>(`/api/top-pairs?${params.toString()}`, {
    cache: 'no-store',
  })
}

export const fetchSignalsActive = () =>
  requestJson<Record<string, unknown>[]>('/api/signals/active', { cache: 'no-store' })

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
  return requestJson<SignalHistoryRow[]>(`/api/signals/history?${params.toString()}`, {
    cache: 'no-store',
  })
}

export const fetchSignalExecutions = (stock: string, future: string, limit = 20) => {
  const params = new URLSearchParams()
  params.set('stock', stock)
  params.set('future', future)
  params.set('limit', String(limit))
  return requestJson<ExecutionRow[]>(`/api/signals/executions?${params.toString()}`, {
    cache: 'no-store',
  })
}

export const executeSignal = (payload: unknown) =>
  requestJson('/api/signals/execute', {
    method: 'POST',
    body: payload,
  })

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
  const params = new URLSearchParams()
  params.set('stock', stock)
  params.set('future', future)
  if (options.direction) params.set('direction', options.direction)
  if (options.snapshots !== undefined) params.set('snapshots', String(options.snapshots))
  if (options.minHits !== undefined) params.set('min_hits', String(options.minHits))
  if (options.eps !== undefined) params.set('eps', String(options.eps))
  if (options.stockEps !== undefined) params.set('stock_eps', String(options.stockEps))
  if (options.futureEps !== undefined) params.set('future_eps', String(options.futureEps))
  if (options.spreadEps !== undefined) params.set('spread_eps', String(options.spreadEps))
  if (options.syncSec !== undefined) params.set('sync_sec', String(options.syncSec))
  if (options.pollSec !== undefined) params.set('poll_sec', String(options.pollSec))
  if (options.qtyFut !== undefined) params.set('qty_fut', String(options.qtyFut))
  if (options.participationRate !== undefined) {
    params.set('participation_rate', String(options.participationRate))
  }
  if (options.requireTradeflowForLast !== undefined) {
    params.set(
      'require_tradeflow_for_last',
      options.requireTradeflowForLast ? 'true' : 'false',
    )
  }
  return requestJson<PretradeCheckResult>(`/api/pretrade/check?${params.toString()}`, {
    cache: 'no-store',
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
