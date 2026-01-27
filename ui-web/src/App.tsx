import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  Container,
  Divider,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  TextField,
  Typography,
} from '@mui/material'
import {
  DataGrid,
  type GridColDef,
  type GridRowParams,
  GridToolbar,
} from '@mui/x-data-grid'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import SpreadChart from './SpreadChart'
import './App.css'

type AggregationSummary = {
  action?: string
  score?: number
  strategies?: string[]
  blocked_strategies?: string[]
}
type ProposalSummary = {
  type?: string
  cadence?: string
  effective_date?: string
  summary?: string
}
type BasketAllocation = {
  basket?: string
  weight?: number
}
type BasketSummary = {
  current?: BasketAllocation[]
  target?: BasketAllocation[]
  delta?: BasketAllocation[]
}
type OperatorAction = {
  action?: string
  status?: string
  actor?: string
  note?: string
  created_at?: string
}
type ExecutionStatus = {
  status?: string
  requested_at?: string
  executed_at?: string
}

type DecisionView = {
  decision_id: string
  decision_view_id?: string
  created_at?: string
  strategy_type?: string
  primary_instrument?: string
  action?: string
  risk_state?: string
  news_severity?: string
  cost_summary?: {
    round_trip_cost?: number
  }
  backtest_metrics?: {
    max_drawdown?: number
  }
  aggregation_summary?: AggregationSummary
  proposal_summary?: ProposalSummary
  basket_summary?: BasketSummary
  operator_action?: OperatorAction
  execution_status?: ExecutionStatus
}

type DecisionLog = Record<string, unknown>
type GenericRow = Record<string, unknown>
type SpreadSeriesPoint = {
  date: string
  spread_mid?: number | null
  spread_pct?: number | null
  spread?: number | null
  spot_mid?: number | null
  future_mid?: number | null
  pv_div?: number | null
  div_sum?: number | null
  rtc_pct?: number | null
  tp_net?: number | null
  sl_net?: number | null
  floor_rate_annual?: number | null
  floor_pass?: boolean | null
  liquidity_pass?: boolean | null
  entry_flag?: boolean | null
  exit_flag?: boolean | null
  trade_cycle?: number | null
  trade_return_pct?: number | null
  trade_pnl_cash?: number | null
  trade_return_pct_net?: number | null
  trade_return_annual?: number | null
  trade_hold_days?: number | null
  zscore?: number | null
}
type SignalHistoryRow = {
  run_id: string
  timestamp: string
  stock: string
  future: string
  signal_action: string
  signal_direction?: string | null
  signal_score: number
  signal_reasons?: string[]
  signal_metrics?: Record<string, unknown>
}
type ExecutionRow = {
  timestamp: string
  stock: string
  future: string
  direction?: string | null
  action: string
  price?: number | null
  quantity?: number | null
  side?: string | null
  status?: string | null
  note?: string | null
}
type RefreshStatus = {
  enabled?: boolean
  interval_sec?: number
  status?: string
  last_started_at?: string | null
  last_success_at?: string | null
  last_error?: string | null
  next_run_at?: string | null
}

type ParameterSpec = {
  key: string
  value_type: string
  default?: unknown
  min_value?: number | null
  max_value?: number | null
  options?: unknown[] | null
  description?: string | null
}

type BacktestEquityPoint = {
  date: string
  equity?: number | null
  cash?: number | null
  drawdown?: number | null
  turnover?: number | null
  positions?: number | null
}

type BacktestTrade = {
  pair_id: string
  stock_secid?: string | null
  future_secid?: string | null
  direction?: string | null
  entry_date?: string | null
  exit_date?: string | null
  entry_price_stock?: number | null
  entry_price_fut?: number | null
  exit_price_stock?: number | null
  exit_price_fut?: number | null
  quantity_stock?: number | null
  quantity_fut?: number | null
  pnl?: number | null
  hold_days?: number | null
  exit_reason?: string | null
}

type BacktestReport = {
  summary_metrics?: Record<string, unknown>
  equity_curve?: BacktestEquityPoint[]
  trades?: BacktestTrade[]
  resolved_config?: Record<string, unknown>
  warnings?: string[]
}

type ForwardStatus = {
  run_id?: string
  status?: string
  state?: Record<string, unknown>
  last_trade?: Record<string, unknown> | null
  last_equity?: Record<string, unknown> | null
  last_alert?: Record<string, unknown> | null
  run_meta?: Record<string, unknown>
}

type HpoTrial = {
  objective?: number
  params?: Record<string, unknown>
  fold_objectives?: number[]
  fold_results?: unknown[]
}

type HpoResponse = {
  status?: string
  message?: string
  mode?: string
  leaderboard?: HpoTrial[]
  trials?: HpoTrial[]
  result?: {
    mode?: string
    leaderboard?: HpoTrial[]
    trials?: HpoTrial[]
  }
}

const AUTO_REFRESH_MS = 60_000
const AUTO_REFRESH_LABEL = '60s'

const formatNumber = (value?: number, digits = 2): string => {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return ''
  }
  return Number(value).toFixed(digits)
}

const formatDate = (value?: string): string => {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

const parseDateInput = (value: string, bound: 'start' | 'end') => {
  const trimmed = value.trim()
  if (!trimmed) return null
  if (!trimmed.includes('T') && !trimmed.includes(' ')) {
    const parts = trimmed.split('-').map((item) => Number(item))
    if (parts.length !== 3 || parts.some((item) => Number.isNaN(item))) return null
    const [year, month, day] = parts
    const date = new Date(
      year,
      month - 1,
      day,
      bound === 'end' ? 23 : 0,
      bound === 'end' ? 59 : 0,
      bound === 'end' ? 59 : 0,
      bound === 'end' ? 999 : 0,
    )
    return Number.isNaN(date.getTime()) ? null : date.getTime()
  }
  const parsed = new Date(trimmed)
  return Number.isNaN(parsed.getTime()) ? null : parsed.getTime()
}

const labelOverrides: Record<string, string> = {
  score: 'Rank score',
  signal_score: 'Signal score',
  signal_score_norm: 'Signal score (norm)',
  spot: 'Spot',
  future_price: 'Future price',
  fair_value: 'Fair value',
  max_drawdown: 'Max drawdown',
  spread_mid: 'Spread (mid)',
  spread_pct: 'Spread %',
  rtc_pct: 'RTC %',
  floor_rate_annual: 'Floor rate',
  score_floor: 'Floor score',
  score_alpha: 'Alpha score',
  total_score: 'Total score',
  p_hit_tp: 'P(hit TP)',
  p_hit_sl: 'P(hit SL)',
  sigma_h: 'Spread sigma (H)',
  half_life: 'Half-life',
  spread_bps_stock: 'Stock spread (bps)',
  spread_bps_fut: 'Futures spread (bps)',
  dollar_vol_stock: 'Stock $ volume',
  dollar_vol_fut: 'Futures $ volume',
  days_to_exit: 'Days to exit',
  open_interest: 'Open interest',
  r_cb_annual: 'CB rate',
  r_fund_annual: 'Funding rate',
  r_disc_annual: 'Discount rate',
  tp_net: 'TP net',
  trade_pnl_cash: 'Trade PnL (cash, pre-tax)',
  trade_return_pct_net: 'Trade return (net %, pre-tax)',
  trade_return_annual: 'Trade return (annual, pre-tax)',
  trade_hold_days: 'Trade hold days',
  pnl: 'PnL',
  entry_price_stock: 'Entry price (stock)',
  entry_price_fut: 'Entry price (fut)',
  exit_price_stock: 'Exit price (stock)',
  exit_price_fut: 'Exit price (fut)',
  quantity_stock: 'Qty (stock)',
  quantity_fut: 'Qty (fut)',
  avg_trade_return_annual_recent: 'Avg trade return (annual, last 5)',
  sl_net: 'SL net',
  share_alpha_exits: 'Alpha exits share',
  avg_hold_days: 'Avg hold days',
  decision: 'Decision',
}

const toTitleCase = (value: string) =>
  labelOverrides[value] ??
  value.replaceAll('_', ' ').replace(/\b\w/g, (match) => match.toUpperCase())

const toNumeric = (value: unknown) => {
  if (typeof value === 'number') return value
  if (typeof value !== 'string') return Number.NaN
  const cleaned = value.replace('%', '').replace(',', '.').trim()
  const parsed = Number(cleaned)
  return Number.isNaN(parsed) ? Number.NaN : parsed
}

const compareValues = (left: unknown, right: unknown) => {
  if (left === null || left === undefined) return right === null || right === undefined ? 0 : 1
  if (right === null || right === undefined) return -1
  const leftNum = toNumeric(left)
  const rightNum = toNumeric(right)
  if (!Number.isNaN(leftNum) && !Number.isNaN(rightNum)) {
    return leftNum - rightNum
  }
  return String(left).localeCompare(String(right))
}

const percentColumns = new Set([
  'spread_pct',
  'rtc_pct',
  'floor_rate_annual',
  'score_floor',
  'score_alpha',
  'total_score',
  'p_hit_tp',
  'p_hit_sl',
  'r_cb_annual',
  'r_fund_annual',
  'r_disc_annual',
  'tp_net',
  'sl_net',
  'share_alpha_exits',
  'cagr',
  'hit_rate',
  'max_drawdown',
  'cycle_return_pct',
])

const columnDigits: Record<string, number> = {
  spot: 2,
  future_price: 2,
  spread_mid: 4,
  spread_pct: 4,
  rtc_pct: 4,
  floor_rate_annual: 4,
  score_floor: 4,
  score_alpha: 4,
  total_score: 4,
  p_hit_tp: 3,
  p_hit_sl: 3,
  sigma_h: 4,
  half_life: 3,
  spread_bps_stock: 2,
  spread_bps_fut: 2,
  dollar_vol_stock: 0,
  dollar_vol_fut: 0,
  days_to_exit: 2,
  open_interest: 0,
  r_cb_annual: 2,
  r_fund_annual: 2,
  r_disc_annual: 2,
  tp_net: 4,
  sl_net: 4,
  signal_score: 4,
  signal_score_norm: 3,
  score: 4,
  turnover: 2,
  sharpe: 2,
  cost_round_trip: 2,
}

const formatValue = (value: unknown, column?: string): string => {
  if (value === null || value === undefined) return ''
  if (Array.isArray(value)) {
    return value.map((item) => formatValue(item)).join(', ')
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No'
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (!entries.length) return ''
    return entries
      .map(([key, item]) => `${toTitleCase(key)}: ${formatValue(item, key)}`)
      .join(', ')
  }
  const numeric = toNumeric(value)
  if (column && percentColumns.has(column) && !Number.isNaN(numeric)) {
    return `${formatNumber(numeric * 100, 2)}%`
  }
  if (!Number.isNaN(numeric)) {
    const digits = column && column in columnDigits ? columnDigits[column] : 4
    return formatNumber(numeric, digits)
  }
  return String(value)
}

const getObject = <T,>(value: unknown): T | null => {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as T
  }
  return null
}

const getArray = <T,>(value: unknown): T[] => {
  if (Array.isArray(value)) {
    return value as T[]
  }
  return []
}

const getString = (value: unknown) => (typeof value === 'string' ? value : '')

const getTableColumns = (rows: GenericRow[]): string[] => {
  if (!rows.length) return []
  return Object.keys(rows[0]).filter((key) => key !== 'id')
}

const formatCellValue = (value: unknown, column?: string): string => formatValue(value, column)

type ParamValue = string | boolean

const isJsonValueType = (valueType: string) =>
  ['list', 'dict', 'tuple', 'set'].includes(valueType)

const shortenText = (value: string, limit = 120) =>
  value.length > limit ? `${value.slice(0, limit)}...` : value

const compactJson = (value: unknown): string => {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

const normalizeParamDefault = (spec: ParameterSpec): ParamValue => {
  if (spec.value_type === 'bool') {
    return Boolean(spec.default)
  }
  if (spec.default === null || spec.default === undefined) {
    return ''
  }
  if (isJsonValueType(spec.value_type) || typeof spec.default === 'object') {
    return compactJson(spec.default)
  }
  return String(spec.default)
}

const buildParamDefaults = (specs: ParameterSpec[]): Record<string, ParamValue> => {
  const next: Record<string, ParamValue> = {}
  specs.forEach((spec) => {
    next[spec.key] = normalizeParamDefault(spec)
  })
  return next
}

const setNestedValue = (target: Record<string, unknown>, path: string, value: unknown) => {
  const parts = path.split('.')
  let cursor: Record<string, unknown> = target
  parts.forEach((part, index) => {
    if (index === parts.length - 1) {
      cursor[part] = value
      return
    }
    const existing = cursor[part]
    if (!existing || typeof existing !== 'object' || Array.isArray(existing)) {
      cursor[part] = {}
    }
    cursor = cursor[part] as Record<string, unknown>
  })
}

const parseParamValue = (raw: ParamValue | undefined, spec: ParameterSpec) => {
  const empty =
    raw === undefined ||
    raw === null ||
    (typeof raw === 'string' && raw.trim().length === 0)
  if (empty) {
    return { value: spec.default ?? null }
  }
  const valueType = spec.value_type
  if (valueType === 'bool') {
    if (typeof raw === 'boolean') {
      return { value: raw }
    }
    const normalized = String(raw).toLowerCase()
    if (normalized === 'true' || normalized === 'false') {
      return { value: normalized === 'true' }
    }
    return { value: null, error: `${spec.key}: invalid boolean` }
  }
  if (valueType === 'int') {
    const parsed = Number.parseInt(String(raw), 10)
    if (Number.isNaN(parsed)) {
      return { value: null, error: `${spec.key}: invalid int` }
    }
    return { value: parsed }
  }
  if (valueType === 'float') {
    const parsed = Number.parseFloat(String(raw))
    if (Number.isNaN(parsed)) {
      return { value: null, error: `${spec.key}: invalid float` }
    }
    return { value: parsed }
  }
  if (valueType === 'str') {
    return { value: String(raw) }
  }
  if (isJsonValueType(valueType) || valueType === 'union') {
    if (typeof raw !== 'string') {
      return { value: raw }
    }
    try {
      return { value: JSON.parse(raw) }
    } catch {
      return { value: null, error: `${spec.key}: invalid JSON` }
    }
  }
  if (typeof raw === 'string') {
    const trimmed = raw.trim()
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try {
        return { value: JSON.parse(trimmed) }
      } catch {
        return { value: null, error: `${spec.key}: invalid JSON` }
      }
    }
  }
  return { value: raw }
}

const collectParamRequest = (
  specs: ParameterSpec[],
  values: Record<string, ParamValue>,
) => {
  const payload: Record<string, unknown> = {}
  const errors: string[] = []
  specs.forEach((spec) => {
    const parsed = parseParamValue(values[spec.key], spec)
    if (parsed.error) {
      errors.push(parsed.error)
      return
    }
    setNestedValue(payload, spec.key, parsed.value)
  })
  return { payload, errors }
}

const isDateColumn = (column: string) =>
  column === 'date' ||
  column.endsWith('_date') ||
  column.endsWith('_at') ||
  column.includes('timestamp')

function App() {
  const [rows, setRows] = useState<DecisionView[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [auxLoading, setAuxLoading] = useState(false)
  const [auxError, setAuxError] = useState<string | null>(null)
  const [auxLastUpdated, setAuxLastUpdated] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [refreshStatus, setRefreshStatus] = useState<RefreshStatus | null>(null)
  const [recomputeLoading, setRecomputeLoading] = useState(false)
  const [recomputeError, setRecomputeError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<DecisionLog | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [decisionAction, setDecisionAction] = useState<{
    operator_action?: OperatorAction
    execution_status?: ExecutionStatus
  } | null>(null)
  const [decisionActionError, setDecisionActionError] = useState<string | null>(null)
  const [decisionActionLoading, setDecisionActionLoading] = useState(false)
  const [decisionActionSubmitting, setDecisionActionSubmitting] = useState(false)
  const [decisionActionNote, setDecisionActionNote] = useState('')
  const [tab, setTab] = useState<
    'decisions' | 'top_pairs' | 'signals' | 'backtests' | 'backtest_v2' | 'forward' | 'hpo'
  >('decisions')
  const [topPairs, setTopPairs] = useState<GenericRow[]>([])
  const [signals, setSignals] = useState<GenericRow[]>([])
  const [backtests, setBacktests] = useState<GenericRow[]>([])
  const [paramSpecs, setParamSpecs] = useState<ParameterSpec[]>([])
  const [paramValues, setParamValues] = useState<Record<string, ParamValue>>({})
  const [paramFilter, setParamFilter] = useState('')
  const [paramPreset, setParamPreset] = useState('')
  const [paramSpecsLoading, setParamSpecsLoading] = useState(false)
  const [paramSpecsError, setParamSpecsError] = useState<string | null>(null)
  const [backtestPrecompute, setBacktestPrecompute] = useState(true)
  const [backtestRunReport, setBacktestRunReport] = useState<BacktestReport | null>(null)
  const [backtestRunLoading, setBacktestRunLoading] = useState(false)
  const [backtestRunError, setBacktestRunError] = useState<string | null>(null)
  const [backtestRunParseError, setBacktestRunParseError] = useState<string | null>(null)
  const [forwardRunId, setForwardRunId] = useState('')
  const [forwardStatus, setForwardStatus] = useState<ForwardStatus | null>(null)
  const [forwardLoading, setForwardLoading] = useState(false)
  const [forwardError, setForwardError] = useState<string | null>(null)
  const [hpoSearchSpace, setHpoSearchSpace] = useState('')
  const [hpoResponse, setHpoResponse] = useState<HpoResponse | null>(null)
  const [hpoLoading, setHpoLoading] = useState(false)
  const [hpoError, setHpoError] = useState<string | null>(null)
  const [signalHistory, setSignalHistory] = useState<SignalHistoryRow[]>([])
  const [quickFilter, setQuickFilter] = useState('')
  const [strategyFilter, setStrategyFilter] = useState('')
  const [instrumentFilter, setInstrumentFilter] = useState('')
  const [riskFilter, setRiskFilter] = useState('')
  const [newsFilter, setNewsFilter] = useState('')
  const [tableFilter, setTableFilter] = useState('')
  const [tableStockFilter, setTableStockFilter] = useState('')
  const [tableFutureFilter, setTableFutureFilter] = useState('')
  const [tableSignalFilter, setTableSignalFilter] = useState('')
  const [tableSortKey, setTableSortKey] = useState('')
  const [tableSortDirection, setTableSortDirection] = useState<'asc' | 'desc'>('desc')
  const [expandedRowKey, setExpandedRowKey] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState<'overview' | 'alpha' | 'liquidity' | 'execution'>(
    'overview',
  )
  const [spreadSeries, setSpreadSeries] = useState<Record<string, SpreadSeriesPoint[]>>({})
  const [spreadLoadingKey, setSpreadLoadingKey] = useState<string | null>(null)
  const [spreadError, setSpreadError] = useState<Record<string, string>>({})
  const [executionLogs, setExecutionLogs] = useState<Record<string, ExecutionRow[]>>({})
  const [executionLoadingKey, setExecutionLoadingKey] = useState<string | null>(null)
  const [executionError, setExecutionError] = useState<Record<string, string>>({})
  const [topPairsLimit, setTopPairsLimit] = useState('25')
  const [topPairsAll, setTopPairsAll] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyFrom, setHistoryFrom] = useState('')
  const [historyTo, setHistoryTo] = useState('')
  const [executionForm, setExecutionForm] = useState({
    price: '',
    quantity: '',
    side: '',
    status: '',
    note: '',
  })
  const auxFetchInFlight = useRef(false)

  const fetchDecisionView = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch('/api/decision-view?limit=500', { cache: 'no-store' })
      if (!response.ok) {
        throw new Error(`API error: ${response.status}`)
      }
      const data: DecisionView[] = await response.json()
      setRows(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchDecisionLog = useCallback(async (decisionId: string) => {
    setDetail(null)
    setDetailError(null)
    try {
      const response = await fetch(`/api/decision-log/${decisionId}`)
      if (!response.ok) {
        throw new Error(`API error: ${response.status}`)
      }
      const data: DecisionLog = await response.json()
      setDetail(data)
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : 'Failed to load decision log')
    }
  }, [])

  const fetchDecisionAction = useCallback(async (decisionId: string) => {
    setDecisionAction(null)
    setDecisionActionError(null)
    setDecisionActionLoading(true)
    try {
      const response = await fetch(`/api/decisions/${decisionId}/action`, { cache: 'no-store' })
      if (!response.ok) {
        throw new Error(`API error: ${response.status}`)
      }
      const data = (await response.json()) as {
        operator_action?: OperatorAction
        execution_status?: ExecutionStatus
      }
      setDecisionAction(data)
    } catch (err) {
      setDecisionActionError(err instanceof Error ? err.message : 'Failed to load decision action')
    } finally {
      setDecisionActionLoading(false)
    }
  }, [])

  const fetchAuxData = useCallback(
    async (options: { topPairsLimit: string; topPairsAll: boolean }) => {
      if (auxFetchInFlight.current) return
      auxFetchInFlight.current = true
      setAuxLoading(true)
      setAuxError(null)
      try {
        const { topPairsLimit: limitRaw, topPairsAll: allPairs } = options
        const topPairsParams = new URLSearchParams()
        if (allPairs) {
          topPairsParams.set('all', 'true')
        } else {
          const limitValue = Number(limitRaw)
          if (!Number.isNaN(limitValue) && limitValue >= 0) {
            topPairsParams.set('limit', String(limitValue))
          } else {
            topPairsParams.set('limit', '500')
          }
        }
        const topPairsUrl = `/api/top-pairs?${topPairsParams.toString()}`
      const results = await Promise.allSettled([
        fetch(topPairsUrl, { cache: 'no-store' }),
        fetch('/api/signals/active', { cache: 'no-store' }),
        fetch('/api/backtests?limit=500', { cache: 'no-store' }),
        fetch('/api/signals/refresh-status', { cache: 'no-store' }),
      ])

      const errors: string[] = []
      const parseResult = async (
        label: string,
        result: PromiseSettledResult<Response>,
        setter: (rows: GenericRow[]) => void,
      ) => {
        if (result.status === 'rejected') {
          errors.push(`${label} fetch failed`)
          setter([])
          return false
        }
        if (!result.value.ok) {
          errors.push(`${label} API error: ${result.value.status}`)
          setter([])
          return false
        }
        try {
          setter(await result.value.json())
          return true
        } catch {
          errors.push(`${label} parse error`)
          setter([])
          return false
        }
      }
      const parseObjectResult = async <T,>(
        label: string,
        result: PromiseSettledResult<Response>,
        setter: (payload: T | null) => void,
      ) => {
        if (result.status === 'rejected') {
          errors.push(`${label} fetch failed`)
          setter(null)
          return false
        }
        if (!result.value.ok) {
          errors.push(`${label} API error: ${result.value.status}`)
          setter(null)
          return false
        }
        try {
          setter((await result.value.json()) as T)
          return true
        } catch {
          errors.push(`${label} parse error`)
          setter(null)
          return false
        }
      }

      const topPairsOk = await parseResult('Top pairs', results[0], setTopPairs)
      const signalsOk = await parseResult('Signals', results[1], setSignals)
      await parseResult('Backtests', results[2], setBacktests)
      await parseObjectResult<RefreshStatus>('Refresh status', results[3], setRefreshStatus)

        if (topPairsOk && signalsOk) {
          setAuxLastUpdated(new Date().toISOString())
        }
        if (errors.length) {
          setAuxError(errors.join(' | '))
        }
      } catch (err) {
        setAuxError(err instanceof Error ? err.message : 'Failed to load tables')
      } finally {
        setAuxLoading(false)
        auxFetchInFlight.current = false
      }
    },
    [],
  )

  const fetchSignalHistory = useCallback(async () => {
    setHistoryLoading(true)
    setHistoryError(null)
    const params = new URLSearchParams()
    if (historyFrom) params.set('from', historyFrom)
    if (historyTo) params.set('to', historyTo)
    if (tableStockFilter) params.set('stock', tableStockFilter)
    if (tableFutureFilter) params.set('future', tableFutureFilter)
    if (tableSignalFilter) params.set('signal_action', tableSignalFilter)
    params.set('limit', '500')
    try {
      const response = await fetch(`/api/signals/history?${params.toString()}`, {
        cache: 'no-store',
      })
      if (!response.ok) {
        let message = `History API error: ${response.status}`
        try {
          const payload = (await response.json()) as { error?: string }
          if (payload?.error) {
            message = `History API error: ${payload.error}`
          }
        } catch {
          // ignore parsing errors, keep status-based message
        }
        throw new Error(message)
      }
      const data: SignalHistoryRow[] = await response.json()
      setSignalHistory(data)
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : 'Failed to load history')
    } finally {
      setHistoryLoading(false)
    }
  }, [historyFrom, historyTo, tableFutureFilter, tableSignalFilter, tableStockFilter])

  const fetchExecutionLog = useCallback(async (pairKey: string, stock: string, future: string) => {
    setExecutionLoadingKey(pairKey)
    setExecutionError((prev) => ({ ...prev, [pairKey]: '' }))
    try {
      const params = new URLSearchParams({
        stock,
        future,
        limit: '20',
      })
      const response = await fetch(`/api/signals/executions?${params.toString()}`, {
        cache: 'no-store',
      })
      if (!response.ok) {
        throw new Error(`Executions API error: ${response.status}`)
      }
      const data: ExecutionRow[] = await response.json()
      setExecutionLogs((prev) => ({ ...prev, [pairKey]: data }))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load executions'
      setExecutionError((prev) => ({ ...prev, [pairKey]: message }))
    } finally {
      setExecutionLoadingKey(null)
    }
  }, [])

  const handleExecuteSignal = useCallback(
    async (row: GenericRow) => {
      const payload = {
        stock: row.stock,
        future: row.future,
        direction: row.signal_direction,
        action: row.signal_action,
        price: executionForm.price ? Number(executionForm.price) : null,
        quantity: executionForm.quantity ? Number(executionForm.quantity) : null,
        side: executionForm.side || null,
        status: executionForm.status || null,
        note: executionForm.note || null,
      }
      const response = await fetch('/api/signals/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!response.ok) {
        throw new Error(`Execute API error: ${response.status}`)
      }
      const pairKey = row.stock && row.future ? `${row.stock}-${row.future}` : null
      if (pairKey) {
        void fetchExecutionLog(pairKey, String(row.stock), String(row.future))
      }
      setExecutionForm({
        price: '',
        quantity: '',
        side: '',
        status: '',
        note: '',
      })
    },
    [executionForm, fetchExecutionLog],
  )

  const fetchSpreadSeries = useCallback(
    async (pairKey: string, stock: string, future: string) => {
      setSpreadLoadingKey(pairKey)
      setSpreadError((prev) => ({ ...prev, [pairKey]: '' }))
      try {
        const response = await fetch(
          `/api/spread-series?stock=${encodeURIComponent(stock)}&future=${encodeURIComponent(
            future,
          )}&full_life=true`,
          { cache: 'no-store' },
        )
        if (!response.ok) {
          throw new Error(`API error: ${response.status}`)
        }
        const data: SpreadSeriesPoint[] = await response.json()
        setSpreadSeries((prev) => ({ ...prev, [pairKey]: data }))
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to load spread series'
        setSpreadError((prev) => ({ ...prev, [pairKey]: message }))
      } finally {
        setSpreadLoadingKey(null)
      }
    },
    [],
  )

  const fetchParamSpecs = useCallback(
    async (options?: { resetValues?: boolean }) => {
      setParamSpecsLoading(true)
      setParamSpecsError(null)
      const resetValues = options?.resetValues ?? false
      try {
        const params = new URLSearchParams()
        const preset = paramPreset.trim()
        if (preset) params.set('preset', preset)
        const url = params.toString() ? `/api/params/specs?${params.toString()}` : '/api/params/specs'
        const response = await fetch(url, { cache: 'no-store' })
        if (!response.ok) {
          throw new Error(`Params API error: ${response.status}`)
        }
        const data = (await response.json()) as ParameterSpec[]
        setParamSpecs(data)
        setParamValues((prev) => {
          const defaults = buildParamDefaults(data)
          if (resetValues || Object.keys(prev).length === 0) {
            return defaults
          }
          const next: Record<string, ParamValue> = {}
          data.forEach((spec) => {
            next[spec.key] = spec.key in prev ? prev[spec.key] : defaults[spec.key]
          })
          return next
        })
      } catch (err) {
        setParamSpecsError(err instanceof Error ? err.message : 'Failed to load params')
      } finally {
        setParamSpecsLoading(false)
      }
    },
    [paramPreset],
  )

  const handleBacktestRun = useCallback(async () => {
    setBacktestRunLoading(true)
    setBacktestRunError(null)
    setBacktestRunParseError(null)
    setBacktestRunReport(null)
    try {
      const { payload, errors } = collectParamRequest(paramSpecs, paramValues)
      if (errors.length) {
        const summary = errors.slice(0, 6).join(' | ')
        setBacktestRunParseError(
          errors.length > 6 ? `${summary} | ... (${errors.length})` : summary,
        )
        return
      }
      const response = await fetch('/api/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request: payload, precompute: backtestPrecompute }),
      })
      const data = (await response.json()) as BacktestReport & { error?: string; message?: string }
      if (!response.ok) {
        throw new Error(data?.message || data?.error || `Backtest API error: ${response.status}`)
      }
      setBacktestRunReport(data)
    } catch (err) {
      setBacktestRunError(err instanceof Error ? err.message : 'Failed to run backtest')
    } finally {
      setBacktestRunLoading(false)
    }
  }, [backtestPrecompute, paramSpecs, paramValues])

  const fetchForwardStatus = useCallback(async () => {
    setForwardLoading(true)
    setForwardError(null)
    try {
      const params = new URLSearchParams()
      const runId = forwardRunId.trim()
      if (runId) params.set('run_id', runId)
      const url = params.toString()
        ? `/api/forward/status?${params.toString()}`
        : '/api/forward/status'
      const response = await fetch(url, { cache: 'no-store' })
      const data = (await response.json()) as ForwardStatus & { error?: string; message?: string }
      if (!response.ok) {
        throw new Error(data?.message || data?.error || `Forward API error: ${response.status}`)
      }
      setForwardStatus(data)
    } catch (err) {
      setForwardError(err instanceof Error ? err.message : 'Failed to load forward status')
    } finally {
      setForwardLoading(false)
    }
  }, [forwardRunId])

  const handleHpoRun = useCallback(async () => {
    setHpoLoading(true)
    setHpoError(null)
    setHpoResponse(null)
    try {
      const { payload, errors } = collectParamRequest(paramSpecs, paramValues)
      if (errors.length) {
        const summary = errors.slice(0, 6).join(' | ')
        setHpoError(errors.length > 6 ? `${summary} | ... (${errors.length})` : summary)
        return
      }
      let searchSpace: Record<string, unknown> = {}
      if (hpoSearchSpace.trim()) {
        try {
          searchSpace = JSON.parse(hpoSearchSpace)
        } catch {
          setHpoError('Search space JSON is invalid.')
          return
        }
      }
      const response = await fetch('/api/hpo/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ base: payload, search_space: searchSpace }),
      })
      const data = (await response.json()) as HpoResponse & { error?: string; message?: string }
      if (!response.ok) {
        throw new Error(data?.message || data?.error || `HPO API error: ${response.status}`)
      }
      setHpoResponse(data)
    } catch (err) {
      setHpoError(err instanceof Error ? err.message : 'Failed to run HPO')
    } finally {
      setHpoLoading(false)
    }
  }, [hpoSearchSpace, paramSpecs, paramValues])

  useEffect(() => {
    fetchDecisionView()
    fetchAuxData({ topPairsLimit, topPairsAll })
  }, [fetchDecisionView, fetchAuxData, topPairsAll, topPairsLimit])

  useEffect(() => {
    if (!autoRefresh) return
    const interval = window.setInterval(() => {
      void fetchAuxData({ topPairsLimit, topPairsAll })
    }, AUTO_REFRESH_MS)
    return () => window.clearInterval(interval)
  }, [autoRefresh, fetchAuxData, topPairsAll, topPairsLimit])

  useEffect(() => {
    if (tab !== 'backtest_v2' && tab !== 'hpo') return
    if (paramSpecsLoading || paramSpecs.length > 0) return
    void fetchParamSpecs({ resetValues: true })
  }, [fetchParamSpecs, paramSpecs.length, paramSpecsLoading, tab])

  const requestRecompute = useCallback(async (): Promise<boolean> => {
    setRecomputeLoading(true)
    setRecomputeError(null)
    try {
      const response = await fetch('/api/signals/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (!response.ok) {
        let message = `Recompute API error: ${response.status}`
        try {
          const payload = (await response.json()) as { last_error?: string }
          if (payload?.last_error) {
            message = `Recompute error: ${payload.last_error}`
          }
        } catch {
          // ignore parsing errors
        }
        throw new Error(message)
      }
      const payload = (await response.json()) as RefreshStatus
      setRefreshStatus(payload)
      return true
    } catch (err) {
      setRecomputeError(err instanceof Error ? err.message : 'Failed to recompute data')
      return false
    } finally {
      setRecomputeLoading(false)
    }
  }, [])

  const handleRefresh = useCallback(() => {
    fetchDecisionView()
    fetchAuxData({ topPairsLimit, topPairsAll })
  }, [fetchDecisionView, fetchAuxData, topPairsAll, topPairsLimit])

  const handleAuxRefresh = useCallback(async () => {
    await requestRecompute()
    await fetchAuxData({ topPairsLimit, topPairsAll })
  }, [fetchAuxData, requestRecompute, topPairsAll, topPairsLimit])

  const handleParamValueChange = useCallback((key: string, value: ParamValue) => {
    setParamValues((prev) => ({ ...prev, [key]: value }))
  }, [])

  const handleParamReset = useCallback(() => {
    if (!paramSpecs.length) return
    setParamValues(buildParamDefaults(paramSpecs))
  }, [paramSpecs])

  const submitDecisionAction = useCallback(
    async (action: 'approve' | 'reject') => {
      if (!selectedId) return
      setDecisionActionSubmitting(true)
      setDecisionActionError(null)
      try {
        const response = await fetch(`/api/decisions/${selectedId}/action`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action,
            note: decisionActionNote || undefined,
          }),
        })
        if (!response.ok) {
          throw new Error(`API error: ${response.status}`)
        }
        const data = (await response.json()) as {
          operator_action?: OperatorAction
          execution_status?: ExecutionStatus
        }
        setDecisionAction(data)
        if (data.operator_action || data.execution_status) {
          setRows((prev) =>
            prev.map((row) =>
              row.decision_id === selectedId
                ? {
                    ...row,
                    operator_action: data.operator_action ?? row.operator_action,
                    execution_status: data.execution_status ?? row.execution_status,
                  }
                : row,
            ),
          )
        }
        setDecisionActionNote('')
      } catch (err) {
        setDecisionActionError(err instanceof Error ? err.message : 'Failed to submit action')
      } finally {
        setDecisionActionSubmitting(false)
      }
    },
    [decisionActionNote, selectedId],
  )

  const strategyOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.strategy_type).filter(Boolean))).sort(),
    [rows],
  )
  const instrumentOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.primary_instrument).filter(Boolean))).sort(),
    [rows],
  )
  const riskOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.risk_state).filter(Boolean))).sort(),
    [rows],
  )
  const newsOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.news_severity).filter(Boolean))).sort(),
    [rows],
  )

  const tableRows = useMemo<GenericRow[]>(() => {
    if (tab === 'top_pairs') return topPairs
    if (tab === 'signals') return signals
    if (tab === 'backtests') return backtests
    return []
  }, [tab, topPairs, signals, backtests])

  const tableColumns = useMemo(() => getTableColumns(tableRows), [tableRows])
  const tableVisibleColumns = useMemo(() => {
    const available = new Set(tableColumns)
    const pick = (columns: string[]) => columns.filter((column) => available.has(column))
    if (tab === 'top_pairs') {
      return pick([
        'stock',
        'stock_name',
        'future',
        'expiry',
        'spread_pct',
        'rtc_pct',
        'floor_rate_annual',
        'score_floor',
        'total_score',
        'avg_trade_return_annual_recent',
        'decision',
        'signal_action',
        'signal_direction',
      ])
    }
    if (tab === 'signals') {
      return pick([
        'timestamp',
        'stock',
        'future',
        'signal_action',
        'signal_direction',
        'signal_score',
        'spread_pct',
        'floor_rate_annual',
      ])
    }
    return tableColumns
  }, [tab, tableColumns])

  const defaultSortKey = useMemo(() => {
    if (tab === 'top_pairs' && tableVisibleColumns.includes('total_score')) return 'total_score'
    if (tab === 'top_pairs' && tableVisibleColumns.includes('score_floor')) return 'score_floor'
    if (tab === 'signals' && tableVisibleColumns.includes('signal_score')) return 'signal_score'
    if (tab === 'backtests' && tableVisibleColumns.includes('cagr')) return 'cagr'
    return tableVisibleColumns[0] ?? ''
  }, [tab, tableVisibleColumns])

  useEffect(() => {
    setExpandedRowKey(null)
    setTableStockFilter('')
    setTableFutureFilter('')
    setTableSignalFilter('')
  }, [tab])

  useEffect(() => {
    if (!tableVisibleColumns.length) return
    if (!tableSortKey || !tableVisibleColumns.includes(tableSortKey)) {
      if (defaultSortKey) {
        setTableSortKey(defaultSortKey)
        setTableSortDirection('desc')
      }
    }
  }, [defaultSortKey, tableSortKey, tableVisibleColumns])

  useEffect(() => {
    setDecisionActionNote('')
  }, [selectedId])

  const filteredRows = useMemo(() => {
    const quick = quickFilter.trim().toLowerCase()
    return rows.filter((row) => {
      if (strategyFilter && row.strategy_type !== strategyFilter) return false
      if (instrumentFilter && row.primary_instrument !== instrumentFilter) return false
      if (riskFilter && row.risk_state !== riskFilter) return false
      if (newsFilter && row.news_severity !== newsFilter) return false
      if (quick) {
        const haystack = JSON.stringify(row).toLowerCase()
        if (!haystack.includes(quick)) return false
      }
      return true
    })
  }, [rows, strategyFilter, instrumentFilter, riskFilter, newsFilter, quickFilter])

  const selectedDecision = useMemo(
    () => rows.find((row) => row.decision_id === selectedId) ?? null,
    [rows, selectedId],
  )

  const signalFilterRows = useMemo<GenericRow[]>(() => {
    if (tab !== 'signals') return tableRows
    if (!signalHistory.length) return tableRows
    if (!tableRows.length) {
      return signalHistory.map((row) => row as unknown as GenericRow)
    }
    return [
      ...tableRows,
      ...signalHistory.map((row) => row as unknown as GenericRow),
    ]
  }, [signalHistory, tab, tableRows])

  const tableStockOptions = useMemo(
    () =>
      Array.from(new Set(signalFilterRows.map((row) => row.stock).filter(Boolean).map(String))).sort(),
    [signalFilterRows],
  )
  const tableFutureOptions = useMemo(
    () =>
      Array.from(new Set(signalFilterRows.map((row) => row.future).filter(Boolean).map(String))).sort(),
    [signalFilterRows],
  )
  const tableSignalOptions = useMemo(
    () =>
      Array.from(
        new Set(signalFilterRows.map((row) => row.signal_action).filter(Boolean).map(String)),
      ).sort(),
    [signalFilterRows],
  )

  const filteredParamSpecs = useMemo(() => {
    const query = paramFilter.trim().toLowerCase()
    if (!query) return paramSpecs
    return paramSpecs.filter((spec) => spec.key.toLowerCase().includes(query))
  }, [paramFilter, paramSpecs])

  const paramSections = useMemo<[string, ParameterSpec[]][]>(() => {
    const grouped = new Map<string, ParameterSpec[]>()
    filteredParamSpecs.forEach((spec) => {
      const section = spec.key.split('.')[0] || 'general'
      const list = grouped.get(section) ?? []
      list.push(spec)
      grouped.set(section, list)
    })
    return Array.from(grouped.entries())
      .map(([section, specs]) => [
        section,
        specs.sort((left, right) => left.key.localeCompare(right.key)),
      ])
      .sort(([left], [right]) => left.localeCompare(right))
  }, [filteredParamSpecs])

  const backtestSummaryEntries = useMemo(() => {
    const metrics = backtestRunReport?.summary_metrics
    if (!metrics) return []
    return Object.entries(metrics).map(([key, value]) => ({
      key,
      label: toTitleCase(key),
      value,
    }))
  }, [backtestRunReport])

  const backtestEquityRows = useMemo<GenericRow[]>(
    () => (backtestRunReport?.equity_curve ?? []) as GenericRow[],
    [backtestRunReport],
  )

  const backtestTradeRows = useMemo<GenericRow[]>(
    () => (backtestRunReport?.trades ?? []) as GenericRow[],
    [backtestRunReport],
  )

  const backtestEquityColumns = useMemo(() => {
    const columns = getTableColumns(backtestEquityRows)
    const preferred = ['date', 'equity', 'cash', 'drawdown', 'turnover', 'positions']
    const ordered = preferred.filter((column) => columns.includes(column))
    const rest = columns.filter((column) => !preferred.includes(column))
    return [...ordered, ...rest]
  }, [backtestEquityRows])

  const backtestTradeColumns = useMemo(() => {
    const columns = getTableColumns(backtestTradeRows)
    const preferred = [
      'pair_id',
      'stock_secid',
      'future_secid',
      'direction',
      'entry_date',
      'exit_date',
      'entry_price_stock',
      'entry_price_fut',
      'exit_price_stock',
      'exit_price_fut',
      'quantity_stock',
      'quantity_fut',
      'pnl',
      'hold_days',
      'exit_reason',
    ]
    const ordered = preferred.filter((column) => columns.includes(column))
    const rest = columns.filter((column) => !preferred.includes(column))
    return [...ordered, ...rest]
  }, [backtestTradeRows])

  const hpoLeaderboardRows = useMemo<HpoTrial[]>(() => {
    if (!hpoResponse) return []
    const payload = hpoResponse.result ?? hpoResponse
    const raw = payload.leaderboard ?? payload.trials ?? []
    if (!Array.isArray(raw)) return []
    const mode = payload.mode ?? 'max'
    const rows = raw.slice() as HpoTrial[]
    if (rows.length && typeof rows[0]?.objective === 'number') {
      rows.sort((left, right) => {
        const leftValue = left.objective ?? Number.NEGATIVE_INFINITY
        const rightValue = right.objective ?? Number.NEGATIVE_INFINITY
        return mode === 'min' ? leftValue - rightValue : rightValue - leftValue
      })
    }
    return rows
  }, [hpoResponse])

  const hpoLeaderboardColumns = useMemo(() => {
    const rows = hpoLeaderboardRows as GenericRow[]
    const columns = getTableColumns(rows)
    const preferred = ['objective', 'params', 'fold_objectives']
    const ordered = preferred.filter((column) => columns.includes(column))
    const rest = columns.filter((column) => !preferred.includes(column))
    return [...ordered, ...rest]
  }, [hpoLeaderboardRows])

  const decisionColumns = useMemo<GridColDef[]>(
    () => [
      {
        headerName: 'Time',
        field: 'created_at',
        valueFormatter: (params: { value?: unknown }) => formatDate(params?.value as string),
        width: 190,
      },
      {
        headerName: 'Decision',
        field: 'decision_id',
        width: 260,
        cellClassName: 'cell-mono',
      },
      { headerName: 'Strategy', field: 'strategy_type', width: 140 },
      { headerName: 'Instrument', field: 'primary_instrument', width: 140 },
      {
        headerName: 'Proposal',
        field: 'proposal_type',
        width: 140,
        valueGetter: (params: { row?: DecisionView } | undefined) =>
          params?.row?.proposal_summary?.type ?? '',
      },
      {
        headerName: 'Action',
        field: 'action',
        width: 120,
        cellClassName: (params) =>
          params.value === 'approve'
            ? 'cell-approve'
            : params.value === 'reject'
              ? 'cell-reject'
              : '',
      },
      {
        headerName: 'Risk',
        field: 'risk_state',
        width: 110,
        cellClassName: (params) =>
          params.value === 'green'
            ? 'cell-risk-green'
            : params.value === 'yellow'
              ? 'cell-risk-yellow'
              : params.value === 'red'
                ? 'cell-risk-red'
                : '',
      },
      {
        headerName: 'News',
        field: 'news_severity',
        width: 110,
        cellClassName: (params) =>
          params.value === 'high'
            ? 'cell-news-high'
            : params.value === 'critical'
              ? 'cell-news-critical'
              : '',
      },
      {
        headerName: 'Execution',
        field: 'execution_status',
        width: 140,
        valueGetter: (params: { row?: DecisionView } | undefined) =>
          params?.row?.execution_status?.status ??
          params?.row?.operator_action?.status ??
          '',
      },
      {
        headerName: 'Cost',
        field: 'cost_round_trip',
        valueFormatter: (params: { value?: unknown }) =>
          formatValue(params?.value, 'cost_round_trip'),
        width: 120,
      },
      {
        headerName: 'Max DD',
        field: 'max_drawdown',
        valueFormatter: (params: { value?: unknown }) =>
          formatValue(params?.value, 'max_drawdown'),
        width: 120,
      },
    ],
    [],
  )

  const handleRowClick = useCallback(
    (params: GridRowParams<DecisionView> | undefined) => {
      const decisionId = params?.row?.decision_id
      if (!decisionId) return
      setSelectedId(decisionId)
      fetchDecisionLog(decisionId)
      fetchDecisionAction(decisionId)
    },
    [fetchDecisionAction, fetchDecisionLog],
  )

  const handleTableSort = useCallback(
    (column: string) => {
      if (tableSortKey === column) {
        setTableSortDirection((prevDirection) => (prevDirection === 'asc' ? 'desc' : 'asc'))
      } else {
        setTableSortKey(column)
        setTableSortDirection('asc')
      }
    },
    [tableSortKey],
  )

  const handleToggleDetails = useCallback(
    (row: GenericRow) => {
      const pairKey =
        (row.stock && row.future ? `${row.stock}-${row.future}` : null) ?? String(row.id)
      if (expandedRowKey === pairKey) {
        setExpandedRowKey(null)
        return
      }
      setExpandedRowKey(pairKey)
      setDetailTab('overview')
      const stock = row.stock ? String(row.stock) : ''
      const future = row.future ? String(row.future) : ''
      if (stock && future && !spreadSeries[pairKey]) {
        void fetchSpreadSeries(pairKey, stock, future)
      }
      if (tab === 'signals' && stock && future && !executionLogs[pairKey]) {
        void fetchExecutionLog(pairKey, stock, future)
      }
    },
    [expandedRowKey, executionLogs, fetchExecutionLog, fetchSpreadSeries, spreadSeries, tab],
  )

  const isLoading = loading || auxLoading || recomputeLoading

  const decisionRows = useMemo(
    () =>
      filteredRows.map((row) => ({
        id: row.decision_id,
        ...row,
        cost_round_trip: row.cost_summary?.round_trip_cost ?? null,
        max_drawdown: row.backtest_metrics?.max_drawdown ?? null,
      })),
    [filteredRows],
  )

  const filteredTableRows = useMemo<GenericRow[]>(() => {
    const query = tableFilter.trim().toLowerCase()
    const baseRows: GenericRow[] = tableRows.map((row, index) => ({
      id:
        row.id ??
        row.decision_id ??
        (row.stock && row.future ? `${row.stock}-${row.future}` : null) ??
        row.signal_id ??
        row.instrument ??
        row.snapshot_id ??
        `${tab}-${index}`,
      ...row,
    })) as GenericRow[]
    return baseRows.filter((row) => {
      if (tab === 'top_pairs' || tab === 'signals') {
        if (tableStockFilter && String(row.stock ?? '') !== tableStockFilter) return false
        if (tableFutureFilter && String(row.future ?? '') !== tableFutureFilter) return false
        if (tableSignalFilter && String(row.signal_action ?? '') !== tableSignalFilter) return false
      }
      if (query && !JSON.stringify(row).toLowerCase().includes(query)) return false
      return true
    })
  }, [
    tableRows,
    tableFilter,
    tab,
    tableStockFilter,
    tableFutureFilter,
    tableSignalFilter,
  ])

  const sortedTableRows = useMemo<GenericRow[]>(() => {
    if (!tableSortKey) return filteredTableRows
    const sorted = [...filteredTableRows].sort((left, right) =>
      compareValues(left[tableSortKey], right[tableSortKey]),
    )
    return tableSortDirection === 'asc' ? sorted : sorted.reverse()
  }, [filteredTableRows, tableSortDirection, tableSortKey])

  const filteredSignalHistory = useMemo(() => {
    if (!signalHistory.length) return []
    const query = tableFilter.trim().toLowerCase()
    const fromTs = parseDateInput(historyFrom, 'start')
    const toTs = parseDateInput(historyTo, 'end')
    return signalHistory.filter((row) => {
      const rowTs = Date.parse(row.timestamp)
      if ((fromTs !== null || toTs !== null) && Number.isNaN(rowTs)) return false
      if (fromTs !== null && rowTs < fromTs) return false
      if (toTs !== null && rowTs > toTs) return false
      if (tableStockFilter && String(row.stock ?? '') !== tableStockFilter) return false
      if (tableFutureFilter && String(row.future ?? '') !== tableFutureFilter) return false
      if (tableSignalFilter && String(row.signal_action ?? '') !== tableSignalFilter) return false
      if (query && !JSON.stringify(row).toLowerCase().includes(query)) return false
      return true
    })
  }, [
    signalHistory,
    tableFilter,
    tableStockFilter,
    tableFutureFilter,
    tableSignalFilter,
    historyFrom,
    historyTo,
  ])

  const detailRecord = (detail as Record<string, unknown> | null) ?? null
  const detailDecision = detailRecord ? getObject<Record<string, unknown>>(detailRecord['decision']) : null
  const detailAggregation = detailRecord
    ? getObject<Record<string, unknown>>(detailRecord['aggregation'])
    : null
  const detailProposal = detailRecord ? getObject<Record<string, unknown>>(detailRecord['proposal']) : null
  const detailBasket = detailRecord
    ? getObject<Record<string, unknown>>(detailRecord['basket_allocations'])
    : null
  const detailFacts = detailRecord ? getArray<Record<string, unknown>>(detailRecord['facts']) : []
  const operatorAction =
    decisionAction?.operator_action ?? selectedDecision?.operator_action ?? undefined
  const executionStatus =
    decisionAction?.execution_status ?? selectedDecision?.execution_status ?? undefined

  const basketRows = useMemo(() => {
    const current = getArray<BasketAllocation>(detailBasket?.current)
    const target = getArray<BasketAllocation>(detailBasket?.target)
    const delta = getArray<BasketAllocation>(detailBasket?.delta)
    const buckets = new Set<string>()
    current.forEach((row) => row.basket && buckets.add(row.basket))
    target.forEach((row) => row.basket && buckets.add(row.basket))
    delta.forEach((row) => row.basket && buckets.add(row.basket))
    return Array.from(buckets).map((basket) => ({
      basket,
      current: current.find((row) => row.basket === basket)?.weight,
      target: target.find((row) => row.basket === basket)?.weight,
      delta: delta.find((row) => row.basket === basket)?.weight,
    }))
  }, [detailBasket])

  const showPairDetails = tab === 'top_pairs' || tab === 'signals'

  const snapshotFields = useMemo(
    () => [
      { key: 'stock', label: 'Stock' },
      { key: 'stock_name', label: 'Stock name' },
      { key: 'future', label: 'Future' },
      { key: 'expiry', label: 'Expiry' },
      { key: 'dte', label: 'DTE' },
      { key: 'spot', label: 'Spot' },
      { key: 'future_price', label: 'Future price' },
      { key: 'spread_mid', label: 'Spread (mid)' },
      { key: 'spread_pct', label: 'Spread %' },
      { key: 'rtc_pct', label: 'RTC %' },
      { key: 'floor_rate_annual', label: 'Floor rate' },
      { key: 'score_floor', label: 'Floor score' },
      { key: 'total_score', label: 'Total score' },
      { key: 'decision', label: 'Decision' },
      { key: 'signal_action', label: 'Signal' },
      { key: 'signal_direction', label: 'Direction' },
      { key: 'signal_score', label: 'Signal score' },
    ],
    [],
  )

  const overviewFields = useMemo(
    () => [
      { key: 'floor_pass', label: 'Floor pass' },
      { key: 'liquidity_pass', label: 'Liquidity pass' },
      { key: 'dte', label: 'DTE' },
      { key: 'r_cb_annual', label: 'CB rate' },
      { key: 'r_fund_annual', label: 'Funding rate' },
      { key: 'r_disc_annual', label: 'Discount rate' },
      { key: 'snapshot_as_of', label: 'Snapshot as of' },
    ],
    [],
  )

  const alphaFields = useMemo(
    () => [
      { key: 'avg_trade_return_annual_recent', label: 'Avg trade return (annual, last 5)' },
      { key: 'score_alpha', label: 'Alpha score' },
      { key: 'p_hit_tp', label: 'P(hit TP)' },
      { key: 'p_hit_sl', label: 'P(hit SL)' },
      { key: 'sigma_h', label: 'Spread sigma (H)' },
      { key: 'half_life', label: 'Half-life' },
    ],
    [],
  )

  const liquidityFields = useMemo(
    () => [
      { key: 'spread_bps_stock', label: 'Stock spread (bps)' },
      { key: 'spread_bps_fut', label: 'Futures spread (bps)' },
      { key: 'dollar_vol_stock', label: 'Stock $ volume' },
      { key: 'dollar_vol_fut', label: 'Futures $ volume' },
      { key: 'days_to_exit', label: 'Days to exit' },
      { key: 'open_interest', label: 'Open interest' },
    ],
    [],
  )

  const executionFields = useMemo(() => {
    const base = [
      { key: 'signal_action', label: 'Signal action' },
      { key: 'signal_direction', label: 'Signal direction' },
      { key: 'signal_score', label: 'Signal score' },
    ]
    const extra =
      tab === 'signals'
        ? [
            { key: 'signal_reasons', label: 'Signal reasons' },
            { key: 'signal_metrics', label: 'Signal metrics' },
          ]
        : [{ key: 'decision', label: 'Decision' }]
    return [...base, ...extra]
  }, [tab])

  const renderFieldGrid = (
    entries: { key: string; label: string; value: unknown }[],
  ) => (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
        gap: 1,
        mt: 1,
      }}
    >
      {entries.map((entry) => (
        <Box key={entry.key}>
          <Typography variant="caption" color="text.secondary">
            {entry.label}
          </Typography>
          <Typography variant="body2">{formatCellValue(entry.value, entry.key)}</Typography>
        </Box>
      ))}
    </Box>
  )

  const renderKeyValueGrid = (payload?: Record<string, unknown>, emptyLabel = 'No data') => {
    const entries = Object.entries(payload ?? {}).map(([key, value]) => ({
      key,
      label: toTitleCase(key),
      value,
    }))
    if (!entries.length) {
      return (
        <Typography variant="body2" color="text.secondary">
          {emptyLabel}
        </Typography>
      )
    }
    return renderFieldGrid(entries)
  }

  const renderJsonBlock = (payload: unknown) => (
    <Box
      component="pre"
      sx={{
        margin: 0,
        padding: 1.5,
        borderRadius: 1,
        backgroundColor: '#0b1020',
        color: '#e2e8f0',
        fontSize: '12px',
        overflow: 'auto',
      }}
    >
      {JSON.stringify(payload, null, 2)}
    </Box>
  )

  const renderTable = (rows: GenericRow[], columns: string[], emptyLabel: string) => {
    if (!rows.length || !columns.length) {
      return (
        <Typography variant="body2" color="text.secondary">
          {emptyLabel}
        </Typography>
      )
    }
    return (
      <TableContainer sx={{ maxHeight: '60vh' }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              {columns.map((column) => (
                <TableCell key={column}>{toTitleCase(column)}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row, index) => {
              const rowKey = row.id ?? row.pair_id ?? row.date ?? `row-${index}`
              return (
                <TableRow key={`${String(rowKey)}-${index}`}>
                  {columns.map((column) => (
                    <TableCell key={`${column}-${index}`}>
                      {isDateColumn(column)
                        ? formatDate(String(row[column] ?? ''))
                        : formatCellValue(row[column], column)}
                    </TableCell>
                  ))}
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </TableContainer>
    )
  }

  const renderParamInput = (spec: ParameterSpec) => {
    const value = paramValues[spec.key]
    const helperParts = []
    if (spec.description) helperParts.push(spec.description)
    helperParts.push(`type: ${spec.value_type}`)
    if (spec.min_value !== null && spec.min_value !== undefined) {
      helperParts.push(`min: ${spec.min_value}`)
    }
    if (spec.max_value !== null && spec.max_value !== undefined) {
      helperParts.push(`max: ${spec.max_value}`)
    }
    if (spec.default !== undefined) {
      const defaultLabel = spec.default === null ? 'null' : shortenText(compactJson(spec.default))
      helperParts.push(`default: ${defaultLabel}`)
    }
    const helperText = helperParts.filter(Boolean).join(' | ')

    if (spec.value_type === 'bool') {
      return (
        <Box key={spec.key}>
          <FormControlLabel
            control={
              <Switch
                checked={Boolean(value)}
                onChange={(event) => handleParamValueChange(spec.key, event.target.checked)}
              />
            }
            label={spec.key}
          />
          {helperText ? (
            <Typography variant="caption" color="text.secondary">
              {helperText}
            </Typography>
          ) : null}
        </Box>
      )
    }

    if (spec.options && spec.options.length) {
      const stringValue = typeof value === 'string' ? value : compactJson(value)
      return (
        <TextField
          key={spec.key}
          select
          fullWidth
          size="small"
          label={spec.key}
          value={stringValue}
          onChange={(event) => handleParamValueChange(spec.key, event.target.value)}
          helperText={helperText}
        >
          {spec.options.map((option) => (
            <MenuItem key={String(option)} value={String(option)}>
              {String(option)}
            </MenuItem>
          ))}
        </TextField>
      )
    }

    const inputValue =
      typeof value === 'string' ? value : value === undefined ? '' : String(value)
    const multiline = isJsonValueType(spec.value_type) || spec.value_type === 'union'
    const inputType =
      spec.value_type === 'int' || spec.value_type === 'float' ? 'number' : 'text'

    return (
      <TextField
        key={spec.key}
        fullWidth
        size="small"
        label={spec.key}
        value={inputValue}
        onChange={(event) => handleParamValueChange(spec.key, event.target.value)}
        helperText={helperText}
        type={inputType}
        multiline={multiline}
        minRows={multiline ? 3 : undefined}
      />
    )
  }

  return (
    <Box className="app-root">
      <Container maxWidth="xl" sx={{ py: 3 }}>
        <Stack spacing={2}>
          <Typography variant="h5" fontWeight={600}>
            Trading Advisor Decisions
          </Typography>
          <Tabs value={tab} onChange={(_, value) => setTab(value)}>
            <Tab label="Decisions" value="decisions" />
            <Tab label="Top pairs" value="top_pairs" />
            <Tab label="Signals" value="signals" />
            <Tab label="Backtests" value="backtests" />
            <Tab label="Backtest v2" value="backtest_v2" />
            <Tab label="Forward status" value="forward" />
            <Tab label="HPO" value="hpo" />
          </Tabs>
          {tab === 'decisions' ? (
            <>
              <Paper sx={{ p: 2 }}>
                <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                  <TextField
                    label="Quick search"
                    size="small"
                    value={quickFilter}
                    onChange={(event) => setQuickFilter(event.target.value)}
                    sx={{ minWidth: 240 }}
                  />
                  <FormControl size="small" sx={{ minWidth: 160 }}>
                    <InputLabel>Strategy</InputLabel>
                    <Select
                      label="Strategy"
                      value={strategyFilter}
                      onChange={(event) => setStrategyFilter(event.target.value)}
                    >
                      <MenuItem value="">All</MenuItem>
                      {strategyOptions.map((item) => (
                        <MenuItem key={item} value={item}>
                          {item}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 160 }}>
                    <InputLabel>Instrument</InputLabel>
                    <Select
                      label="Instrument"
                      value={instrumentFilter}
                      onChange={(event) => setInstrumentFilter(event.target.value)}
                    >
                      <MenuItem value="">All</MenuItem>
                      {instrumentOptions.map((item) => (
                        <MenuItem key={item} value={item}>
                          {item}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 140 }}>
                    <InputLabel>Risk</InputLabel>
                    <Select
                      label="Risk"
                      value={riskFilter}
                      onChange={(event) => setRiskFilter(event.target.value)}
                    >
                      <MenuItem value="">All</MenuItem>
                      {riskOptions.map((item) => (
                        <MenuItem key={item} value={item}>
                          {item}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 140 }}>
                    <InputLabel>News</InputLabel>
                    <Select
                      label="News"
                      value={newsFilter}
                      onChange={(event) => setNewsFilter(event.target.value)}
                    >
                      <MenuItem value="">All</MenuItem>
                      {newsOptions.map((item) => (
                        <MenuItem key={item} value={item}>
                          {item}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <Button variant="contained" onClick={handleRefresh} disabled={isLoading}>
                    Refresh
                  </Button>
                  <Typography variant="body2" color="text.secondary">
                    {isLoading ? 'Loading...' : `${filteredRows.length} rows`}
                  </Typography>
                  {error ? (
                    <Typography variant="body2" color="error">
                      {error}
                    </Typography>
                  ) : null}
                </Stack>
              </Paper>
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="stretch">
                <Paper sx={{ flex: 2, p: 2 }}>
                  <DataGrid
                    rows={decisionRows}
                    columns={decisionColumns}
                    loading={loading}
                    onRowClick={handleRowClick}
                    disableRowSelectionOnClick
                    pageSizeOptions={[10, 25, 50, 100]}
                    initialState={{
                      pagination: { paginationModel: { pageSize: 10, page: 0 } },
                    }}
                    slots={{ toolbar: GridToolbar }}
                    slotProps={{ toolbar: { showQuickFilter: false } }}
                    sx={{ height: '68vh' }}
                  />
                </Paper>
                <Paper sx={{ flex: 1, p: 2 }}>
                  <Stack spacing={1}>
                    <Typography variant="subtitle1" fontWeight={600}>
                      Decision details
                    </Typography>
                    {selectedId ? (
                      <Typography variant="body2" color="text.secondary">
                        {selectedId}
                      </Typography>
                    ) : null}
                    {detailError ? (
                      <Typography variant="body2" color="error">
                        {detailError}
                      </Typography>
                    ) : null}
                    {detail ? (
                      <Stack spacing={2}>
                        <Stack direction="row" spacing={1} flexWrap="wrap">
                          <Chip
                            label={`Action: ${
                              selectedDecision?.action ||
                              getString(detailDecision?.['action']) ||
                              'hold'
                            }`}
                            color="primary"
                            size="small"
                          />
                          <Chip
                            label={`Risk: ${
                              selectedDecision?.risk_state ||
                              getString(detailDecision?.['risk_state']) ||
                              'unknown'
                            }`}
                            size="small"
                          />
                          <Chip
                            label={`News: ${selectedDecision?.news_severity || 'n/a'}`}
                            size="small"
                          />
                          {selectedDecision?.aggregation_summary?.score !== undefined ? (
                            <Chip
                              label={`Agg score: ${formatNumber(
                                selectedDecision?.aggregation_summary?.score,
                                3,
                              )}`}
                              size="small"
                            />
                          ) : null}
                        </Stack>

                        <Divider />

                        <Box>
                          <Typography variant="subtitle2" fontWeight={600}>
                            Orchestrator proposal
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            {selectedDecision?.proposal_summary?.summary ||
                              getString(detailProposal?.['summary']) ||
                              'Proposal not available.'}
                          </Typography>
                          <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1 }}>
                            <Chip
                              label={`Type: ${
                                selectedDecision?.proposal_summary?.type ||
                                getString(detailProposal?.['type']) ||
                                'n/a'
                              }`}
                              size="small"
                            />
                            <Chip
                              label={`Cadence: ${
                                selectedDecision?.proposal_summary?.cadence ||
                                getString(detailProposal?.['cadence']) ||
                                'n/a'
                              }`}
                              size="small"
                            />
                            {selectedDecision?.proposal_summary?.effective_date ||
                            getString(detailProposal?.['effective_date']) ? (
                              <Chip
                                label={`Effective: ${
                                  selectedDecision?.proposal_summary?.effective_date ||
                                  getString(detailProposal?.['effective_date'])
                                }`}
                                size="small"
                              />
                            ) : null}
                          </Stack>
                          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2 }} flexWrap="wrap">
                            <TextField
                              label="Operator note"
                              size="small"
                              value={decisionActionNote}
                              onChange={(event) => setDecisionActionNote(event.target.value)}
                              sx={{ minWidth: 220 }}
                            />
                            <Button
                              variant="contained"
                              color="success"
                              disabled={!selectedId || decisionActionSubmitting}
                              onClick={() => submitDecisionAction('approve')}
                            >
                              Approve & execute
                            </Button>
                            <Button
                              variant="outlined"
                              color="error"
                              disabled={!selectedId || decisionActionSubmitting}
                              onClick={() => submitDecisionAction('reject')}
                            >
                              Reject & execute
                            </Button>
                          </Stack>
                          {decisionActionError ? (
                            <Typography variant="body2" color="error" sx={{ mt: 1 }}>
                              {decisionActionError}
                            </Typography>
                          ) : null}
                          {decisionActionLoading ? (
                            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                              Loading operator status...
                            </Typography>
                          ) : null}
                          {operatorAction ? (
                            <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1 }}>
                              <Chip
                                label={`Operator: ${operatorAction.action ?? 'n/a'}`}
                                size="small"
                              />
                              {operatorAction.status ? (
                                <Chip label={`Status: ${operatorAction.status}`} size="small" />
                              ) : null}
                              {operatorAction.actor ? (
                                <Chip label={`Actor: ${operatorAction.actor}`} size="small" />
                              ) : null}
                            </Stack>
                          ) : null}
                          {executionStatus ? (
                            <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1 }}>
                              {executionStatus.status ? (
                                <Chip label={`Execution: ${executionStatus.status}`} size="small" />
                              ) : null}
                              {executionStatus.requested_at ? (
                                <Chip
                                  label={`Requested: ${formatDate(executionStatus.requested_at)}`}
                                  size="small"
                                />
                              ) : null}
                              {executionStatus.executed_at ? (
                                <Chip
                                  label={`Executed: ${formatDate(executionStatus.executed_at)}`}
                                  size="small"
                                />
                              ) : null}
                            </Stack>
                          ) : null}
                        </Box>

                        <Divider />

                        <Box>
                          <Typography variant="subtitle2" fontWeight={600}>
                            Basket allocations (by strategy type)
                          </Typography>
                          {basketRows.length ? (
                            <Table size="small">
                              <TableHead>
                                <TableRow>
                                  <TableCell>Basket</TableCell>
                                  <TableCell>Current</TableCell>
                                  <TableCell>Target</TableCell>
                                  <TableCell>Delta</TableCell>
                                </TableRow>
                              </TableHead>
                              <TableBody>
                                {basketRows.map((row) => (
                                  <TableRow key={row.basket}>
                                    <TableCell>{row.basket}</TableCell>
                                    <TableCell>{formatValue(row.current)}</TableCell>
                                    <TableCell>{formatValue(row.target)}</TableCell>
                                    <TableCell>{formatValue(row.delta)}</TableCell>
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          ) : (
                            <Typography variant="body2" color="text.secondary">
                              Basket allocations not provided.
                            </Typography>
                          )}
                        </Box>

                        <Divider />

                        <Box>
                          <Typography variant="subtitle2" fontWeight={600}>
                            Evidence & rationale
                          </Typography>
                          <Stack spacing={1} sx={{ mt: 1 }}>
                            {detailFacts.length ? (
                              detailFacts.map((fact, index) => (
                                <Box key={`${getString(fact['label']) || 'fact'}-${index}`}>
                                  <Typography variant="body2">
                                    {getString(fact['label'])}: {formatValue(fact['value'])}
                                  </Typography>
                                  <Typography variant="caption" color="text.secondary">
                                    {getString(fact['category'])}
                                    {fact['source'] ? ` · ${getString(fact['source'])}` : ''}
                                    {fact['confidence'] !== undefined
                                      ? ` · conf ${formatValue(fact['confidence'], 'confidence')}`
                                      : ''}
                                  </Typography>
                                </Box>
                              ))
                            ) : (
                              <Typography variant="body2" color="text.secondary">
                                Evidence facts not provided.
                              </Typography>
                            )}
                            {detailAggregation?.['reasons'] ? (
                              <Typography variant="caption" color="text.secondary">
                                Aggregation reasons: {formatValue(detailAggregation['reasons'])}
                              </Typography>
                            ) : null}
                          </Stack>
                        </Box>

                        <Accordion>
                          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                            <Typography variant="subtitle2">Raw decision log</Typography>
                          </AccordionSummary>
                          <AccordionDetails>
                            <Box
                              component="pre"
                              sx={{
                                margin: 0,
                                padding: 1.5,
                                borderRadius: 1,
                                backgroundColor: '#0b1020',
                                color: '#e2e8f0',
                                fontSize: '12px',
                                overflow: 'auto',
                              }}
                            >
                              {JSON.stringify(detail, null, 2)}
                            </Box>
                          </AccordionDetails>
                        </Accordion>
                      </Stack>
                    ) : (
                      <Typography variant="body2" color="text.secondary">
                        Select a decision to inspect full log.
                      </Typography>
                    )}
                  </Stack>
                </Paper>
              </Stack>
            </>
          ) : null}
          {tab === 'top_pairs' || tab === 'signals' || tab === 'backtests' ? (
            <>
              <Paper sx={{ p: 2 }}>
                <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                  <TextField
                    label="Quick search"
                    size="small"
                    value={tableFilter}
                    onChange={(event) => setTableFilter(event.target.value)}
                    sx={{ minWidth: 240 }}
                  />
                  {tab === 'top_pairs' || tab === 'signals' ? (
                    <>
                      <FormControl size="small" sx={{ minWidth: 140 }}>
                        <InputLabel>Stock</InputLabel>
                        <Select
                          label="Stock"
                          value={tableStockFilter}
                          onChange={(event) => setTableStockFilter(event.target.value)}
                        >
                          <MenuItem value="">All</MenuItem>
                          {tableStockOptions.map((item) => (
                            <MenuItem key={item} value={item}>
                              {item}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <FormControl size="small" sx={{ minWidth: 140 }}>
                        <InputLabel>Future</InputLabel>
                        <Select
                          label="Future"
                          value={tableFutureFilter}
                          onChange={(event) => setTableFutureFilter(event.target.value)}
                        >
                          <MenuItem value="">All</MenuItem>
                          {tableFutureOptions.map((item) => (
                            <MenuItem key={item} value={item}>
                              {item}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <FormControl size="small" sx={{ minWidth: 140 }}>
                        <InputLabel>Signal</InputLabel>
                        <Select
                          label="Signal"
                          value={tableSignalFilter}
                          onChange={(event) => setTableSignalFilter(event.target.value)}
                        >
                          <MenuItem value="">All</MenuItem>
                          {tableSignalOptions.map((item) => (
                            <MenuItem key={item} value={item}>
                              {item}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    </>
                  ) : null}
                  {tab === 'top_pairs' ? (
                    <>
                      <TextField
                        label="Top pairs limit"
                        size="small"
                        type="number"
                        value={topPairsLimit}
                        onChange={(event) => setTopPairsLimit(event.target.value)}
                        disabled={topPairsAll}
                        sx={{ minWidth: 140 }}
                      />
                      <FormControlLabel
                        control={
                          <Switch
                            checked={topPairsAll}
                            onChange={(event) => setTopPairsAll(event.target.checked)}
                          />
                        }
                        label="All pairs"
                      />
                    </>
                  ) : null}
                  <Button
                    variant="outlined"
                    onClick={handleAuxRefresh}
                    disabled={auxLoading || recomputeLoading}
                  >
                    {recomputeLoading ? 'Recomputing...' : 'Reload'}
                  </Button>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={autoRefresh}
                        onChange={(event) => setAutoRefresh(event.target.checked)}
                      />
                    }
                    label={`Auto refresh (${AUTO_REFRESH_LABEL})`}
                  />
                  <Typography variant="body2" color="text.secondary">
                    {auxLastUpdated
                      ? `Updated ${formatDate(auxLastUpdated)}`
                      : 'Updated: n/a'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {refreshStatus?.last_success_at
                      ? `Recomputed ${formatDate(refreshStatus.last_success_at)}`
                      : 'Recomputed: n/a'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {auxLoading ? 'Loading...' : `${sortedTableRows.length} rows`}
                  </Typography>
                  {!auxLoading ? (
                    <Typography variant="body2" color="text.secondary">
                      Top pairs: {topPairs.length} · Signals: {signals.length} · Backtests: {backtests.length}
                    </Typography>
                  ) : null}
                  {auxError ? (
                    <Typography variant="body2" color="error">
                      {auxError}
                    </Typography>
                  ) : null}
                  {recomputeError ? (
                    <Typography variant="body2" color="error">
                      {recomputeError}
                    </Typography>
                  ) : null}
                </Stack>
              </Paper>
              {tab === 'signals' ? (
                <Paper sx={{ p: 2 }}>
                  <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                    <TextField
                      label="History from (YYYY-MM-DD)"
                      size="small"
                      value={historyFrom}
                      onChange={(event) => setHistoryFrom(event.target.value)}
                      sx={{ minWidth: 200 }}
                    />
                    <TextField
                      label="History to (YYYY-MM-DD)"
                      size="small"
                      value={historyTo}
                      onChange={(event) => setHistoryTo(event.target.value)}
                      sx={{ minWidth: 200 }}
                    />
                    <Button variant="outlined" onClick={fetchSignalHistory} disabled={historyLoading}>
                      Load history
                    </Button>
                    {historyLoading ? (
                      <Typography variant="body2" color="text.secondary">
                        Loading history...
                      </Typography>
                    ) : null}
                    {historyError ? (
                      <Typography variant="body2" color="error">
                        {historyError}
                      </Typography>
                    ) : null}
                  </Stack>
                </Paper>
              ) : null}
              <Paper sx={{ p: 2 }}>
                <TableContainer sx={{ maxHeight: '68vh' }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        {showPairDetails ? <TableCell /> : null}
                        {tableVisibleColumns.map((column) => (
                          <TableCell
                            key={column}
                            sortDirection={tableSortKey === column ? tableSortDirection : false}
                          >
                            <TableSortLabel
                              active={tableSortKey === column}
                              direction={tableSortKey === column ? tableSortDirection : 'asc'}
                              onClick={() => handleTableSort(column)}
                            >
                              {toTitleCase(column)}
                            </TableSortLabel>
                          </TableCell>
                        ))}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {sortedTableRows.map((row) => {
                        const pairKey =
                          (row.stock && row.future ? `${row.stock}-${row.future}` : null) ??
                          String(row.id)
                        const isExpanded = expandedRowKey === pairKey
                        const snapshotEntries = snapshotFields
                          .map((field) => ({
                            ...field,
                            value: row[field.key],
                          }))
                          .filter((field) => field.value !== null && field.value !== undefined)
                        const overviewEntries = overviewFields
                          .map((field) => ({
                            ...field,
                            value: row[field.key],
                          }))
                          .filter((field) => field.value !== null && field.value !== undefined)
                        const alphaEntries = alphaFields
                          .map((field) => ({
                            ...field,
                            value: row[field.key],
                          }))
                          .filter((field) => field.value !== null && field.value !== undefined)
                        const liquidityEntries = liquidityFields
                          .map((field) => ({
                            ...field,
                            value: row[field.key],
                          }))
                          .filter((field) => field.value !== null && field.value !== undefined)
                        const executionEntries = executionFields
                          .map((field) => ({
                            ...field,
                            value: row[field.key],
                          }))
                          .filter((field) => field.value !== null && field.value !== undefined)

                        return (
                          <Fragment key={pairKey}>
                            <TableRow>
                              {showPairDetails ? (
                                <TableCell>
                                  <Button size="small" onClick={() => handleToggleDetails(row)}>
                                    {isExpanded ? 'Hide' : 'Details'}
                                  </Button>
                                </TableCell>
                              ) : null}
                              {tableVisibleColumns.map((column) => (
                                <TableCell key={column}>
                                  {formatCellValue(row[column], column)}
                                </TableCell>
                              ))}
                            </TableRow>
                            {showPairDetails && isExpanded ? (
                              <TableRow>
                                <TableCell colSpan={tableVisibleColumns.length + 1}>
                                  <Stack spacing={2}>
                                    <Box>
                                      <Typography variant="subtitle2" fontWeight={600}>
                                        Snapshot
                                      </Typography>
                                      {renderFieldGrid(snapshotEntries)}
                                    </Box>
                                    <Box>
                                      <Tabs
                                        value={detailTab}
                                        onChange={(_, value) => setDetailTab(value)}
                                      >
                                        <Tab label="Overview" value="overview" />
                                        <Tab label="Alpha" value="alpha" />
                                        <Tab label="Liquidity" value="liquidity" />
                                        <Tab label="Execution" value="execution" />
                                      </Tabs>
                                      {detailTab === 'overview' && overviewEntries.length
                                        ? renderFieldGrid(overviewEntries)
                                        : null}
                                      {detailTab === 'alpha' && alphaEntries.length
                                        ? renderFieldGrid(alphaEntries)
                                        : null}
                                      {detailTab === 'liquidity' && liquidityEntries.length
                                        ? renderFieldGrid(liquidityEntries)
                                        : null}
                                      {detailTab === 'execution' && executionEntries.length
                                        ? renderFieldGrid(executionEntries)
                                        : null}
                                    </Box>
                                    <Box>
                                      <Typography variant="subtitle2" fontWeight={600}>
                                        Spread chart (contract life)
                                      </Typography>
                                      {spreadError[pairKey] ? (
                                        <Typography variant="body2" color="error">
                                          {spreadError[pairKey]}
                                        </Typography>
                                      ) : null}
                                      {spreadLoadingKey === pairKey ? (
                                        <Typography variant="body2" color="text.secondary">
                                          Loading spread series...
                                        </Typography>
                                      ) : (
                                        <SpreadChart data={spreadSeries[pairKey] ?? []} />
                                      )}
                                    </Box>
                                    {tab === 'signals' ? (
                                      <Box>
                                        <Typography variant="subtitle2" fontWeight={600}>
                                          Execute signal
                                        </Typography>
                                        <Stack direction="row" spacing={2} flexWrap="wrap">
                                          <TextField
                                            label="Price"
                                            size="small"
                                            value={executionForm.price}
                                            onChange={(event) =>
                                              setExecutionForm((prev) => ({
                                                ...prev,
                                                price: event.target.value,
                                              }))
                                            }
                                            sx={{ minWidth: 140 }}
                                          />
                                          <TextField
                                            label="Qty"
                                            size="small"
                                            value={executionForm.quantity}
                                            onChange={(event) =>
                                              setExecutionForm((prev) => ({
                                                ...prev,
                                                quantity: event.target.value,
                                              }))
                                            }
                                            sx={{ minWidth: 120 }}
                                          />
                                          <TextField
                                            label="Side"
                                            size="small"
                                            value={executionForm.side}
                                            onChange={(event) =>
                                              setExecutionForm((prev) => ({
                                                ...prev,
                                                side: event.target.value,
                                              }))
                                            }
                                            sx={{ minWidth: 120 }}
                                          />
                                          <TextField
                                            label="Status"
                                            size="small"
                                            value={executionForm.status}
                                            onChange={(event) =>
                                              setExecutionForm((prev) => ({
                                                ...prev,
                                                status: event.target.value,
                                              }))
                                            }
                                            sx={{ minWidth: 120 }}
                                          />
                                          <TextField
                                            label="Note"
                                            size="small"
                                            value={executionForm.note}
                                            onChange={(event) =>
                                              setExecutionForm((prev) => ({
                                                ...prev,
                                                note: event.target.value,
                                              }))
                                            }
                                            sx={{ minWidth: 240 }}
                                          />
                                          <Button
                                            variant="contained"
                                            onClick={() => handleExecuteSignal(row)}
                                          >
                                            Execute
                                          </Button>
                                        </Stack>
                                        <Box sx={{ mt: 2 }}>
                                          <Typography variant="subtitle2" fontWeight={600}>
                                            Execution history
                                          </Typography>
                                          {executionError[pairKey] ? (
                                            <Typography variant="body2" color="error">
                                              {executionError[pairKey]}
                                            </Typography>
                                          ) : null}
                                          {executionLoadingKey === pairKey ? (
                                            <Typography variant="body2" color="text.secondary">
                                              Loading executions...
                                            </Typography>
                                          ) : executionLogs[pairKey]?.length ? (
                                            <Table size="small">
                                              <TableHead>
                                                <TableRow>
                                                  {[
                                                    'timestamp',
                                                    'action',
                                                    'direction',
                                                    'price',
                                                    'quantity',
                                                    'side',
                                                    'status',
                                                    'note',
                                                  ].map((col) => (
                                                    <TableCell key={col}>{toTitleCase(col)}</TableCell>
                                                  ))}
                                                </TableRow>
                                              </TableHead>
                                              <TableBody>
                                                {executionLogs[pairKey].map((entry, index) => (
                                                  <TableRow key={`${entry.timestamp}-${index}`}>
                                                    <TableCell>{formatDate(entry.timestamp)}</TableCell>
                                                    <TableCell>{entry.action}</TableCell>
                                                    <TableCell>{entry.direction ?? ''}</TableCell>
                                                    <TableCell>
                                                      {formatValue(entry.price, 'future_price')}
                                                    </TableCell>
                                                    <TableCell>{formatValue(entry.quantity)}</TableCell>
                                                    <TableCell>{entry.side ?? ''}</TableCell>
                                                    <TableCell>{entry.status ?? ''}</TableCell>
                                                    <TableCell>{entry.note ?? ''}</TableCell>
                                                  </TableRow>
                                                ))}
                                              </TableBody>
                                            </Table>
                                          ) : (
                                            <Typography variant="body2" color="text.secondary">
                                              No executions logged yet.
                                            </Typography>
                                          )}
                                        </Box>
                                      </Box>
                                    ) : null}
                                  </Stack>
                                </TableCell>
                              </TableRow>
                            ) : null}
                          </Fragment>
                        )
                      })}
                    </TableBody>
                  </Table>
                </TableContainer>
                {!sortedTableRows.length ? (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    {tab === 'signals' && !auxLoading && signals.length === 0
                      ? 'No actionable signals yet. Open Details on an active signal row to execute.'
                      : 'No rows match the current filter.'}
                  </Typography>
                ) : null}
              </Paper>
              {tab === 'signals' && signalHistory.length ? (
                <Paper sx={{ p: 2 }}>
                  <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
                    Signal history
                  </Typography>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        {[
                          'timestamp',
                          'stock',
                          'future',
                          'signal_action',
                          'signal_direction',
                          'signal_score',
                        ].map(
                          (col) => (
                            <TableCell key={col}>{toTitleCase(col)}</TableCell>
                          ),
                        )}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {filteredSignalHistory.map((row, index) => (
                        <TableRow
                          key={`${row.run_id}-${row.timestamp}-${row.stock}-${row.future}-${row.signal_action ?? ''}-${index}`}
                        >
                          <TableCell>{formatDate(row.timestamp)}</TableCell>
                          <TableCell>{row.stock}</TableCell>
                          <TableCell>{row.future}</TableCell>
                          <TableCell>{row.signal_action}</TableCell>
                          <TableCell>{row.signal_direction ?? ''}</TableCell>
                          <TableCell>{formatValue(row.signal_score, 'signal_score')}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {!filteredSignalHistory.length ? (
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                      No history rows match the current filter.
                    </Typography>
                  ) : null}
                </Paper>
              ) : null}
            </>
          ) : null}
          {tab === 'backtest_v2' ? (
            <Stack spacing={2}>
              <Paper sx={{ p: 2 }}>
                <Stack spacing={2}>
                  <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                    <TextField
                      label="Preset (optional)"
                      size="small"
                      value={paramPreset}
                      onChange={(event) => setParamPreset(event.target.value)}
                      sx={{ minWidth: 200 }}
                    />
                    <Button
                      variant="outlined"
                      onClick={() => fetchParamSpecs({ resetValues: true })}
                      disabled={paramSpecsLoading}
                    >
                      {paramSpecsLoading ? 'Loading params...' : 'Load params'}
                    </Button>
                    <Button
                      variant="text"
                      onClick={handleParamReset}
                      disabled={!paramSpecs.length}
                    >
                      Reset defaults
                    </Button>
                    <FormControlLabel
                      control={
                        <Switch
                          checked={backtestPrecompute}
                          onChange={(event) => setBacktestPrecompute(event.target.checked)}
                        />
                      }
                      label="Precompute cache"
                    />
                    <Typography variant="body2" color="text.secondary">
                      {paramSpecs.length ? `Params: ${paramSpecs.length}` : 'Params: n/a'}
                    </Typography>
                    {paramSpecsError ? (
                      <Typography variant="body2" color="error">
                        {paramSpecsError}
                      </Typography>
                    ) : null}
                  </Stack>
                  <TextField
                    label="Filter params"
                    size="small"
                    value={paramFilter}
                    onChange={(event) => setParamFilter(event.target.value)}
                    sx={{ maxWidth: 320 }}
                  />
                  {paramSpecs.length ? (
                    paramSections.length ? (
                      paramSections.map(([section, specs], index) => (
                        <Accordion key={section} defaultExpanded={index === 0 || section === 'test'}>
                          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                            <Typography variant="subtitle2">
                              {toTitleCase(section)} ({specs.length})
                            </Typography>
                          </AccordionSummary>
                          <AccordionDetails>
                            <Box
                              sx={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                                gap: 2,
                              }}
                            >
                              {specs.map((spec) => renderParamInput(spec))}
                            </Box>
                          </AccordionDetails>
                        </Accordion>
                      ))
                    ) : (
                      <Typography variant="body2" color="text.secondary">
                        No parameters match the current filter.
                      </Typography>
                    )
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      Load params to edit the backtest request payload.
                    </Typography>
                  )}
                  <Divider />
                  <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                    <Button
                      variant="contained"
                      onClick={handleBacktestRun}
                      disabled={backtestRunLoading || !paramSpecs.length}
                    >
                      Run backtest
                    </Button>
                    {backtestRunLoading ? (
                      <Typography variant="body2" color="text.secondary">
                        Running backtest...
                      </Typography>
                    ) : null}
                    {backtestRunParseError ? (
                      <Typography variant="body2" color="error">
                        {backtestRunParseError}
                      </Typography>
                    ) : null}
                    {backtestRunError ? (
                      <Typography variant="body2" color="error">
                        {backtestRunError}
                      </Typography>
                    ) : null}
                  </Stack>
                </Stack>
              </Paper>
              {backtestRunReport ? (
                <Stack spacing={2}>
                  <Paper sx={{ p: 2 }}>
                    <Stack spacing={1}>
                      <Typography variant="subtitle1" fontWeight={600}>
                        Summary metrics
                      </Typography>
                      {backtestSummaryEntries.length
                        ? renderFieldGrid(backtestSummaryEntries)
                        : renderKeyValueGrid({}, 'Summary metrics not available yet.')}
                      {backtestRunReport.warnings && backtestRunReport.warnings.length ? (
                        <Stack direction="row" spacing={1} flexWrap="wrap">
                          {backtestRunReport.warnings.map((warning, index) => (
                            <Chip key={`${warning}-${index}`} label={`Warning: ${warning}`} size="small" />
                          ))}
                        </Stack>
                      ) : null}
                    </Stack>
                  </Paper>
                  <Paper sx={{ p: 2 }}>
                    <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1 }}>
                      Equity curve
                    </Typography>
                    {renderTable(backtestEquityRows, backtestEquityColumns, 'Equity curve is empty.')}
                  </Paper>
                  <Paper sx={{ p: 2 }}>
                    <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1 }}>
                      Trades
                    </Typography>
                    {renderTable(backtestTradeRows, backtestTradeColumns, 'Trades list is empty.')}
                  </Paper>
                  {backtestRunReport.resolved_config ? (
                    <Accordion>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography variant="subtitle2">Resolved config</Typography>
                      </AccordionSummary>
                      <AccordionDetails>{renderJsonBlock(backtestRunReport.resolved_config)}</AccordionDetails>
                    </Accordion>
                  ) : null}
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Run a backtest to see summary metrics, equity curve, and trades.
                </Typography>
              )}
            </Stack>
          ) : null}
          {tab === 'forward' ? (
            <Stack spacing={2}>
              <Paper sx={{ p: 2 }}>
                <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                  <TextField
                    label="Run id (optional)"
                    size="small"
                    value={forwardRunId}
                    onChange={(event) => setForwardRunId(event.target.value)}
                    sx={{ minWidth: 220 }}
                  />
                  <Button variant="contained" onClick={fetchForwardStatus} disabled={forwardLoading}>
                    Load status
                  </Button>
                  {forwardLoading ? (
                    <Typography variant="body2" color="text.secondary">
                      Loading status...
                    </Typography>
                  ) : null}
                  {forwardError ? (
                    <Typography variant="body2" color="error">
                      {forwardError}
                    </Typography>
                  ) : null}
                </Stack>
              </Paper>
              {forwardStatus ? (
                <Stack spacing={2}>
                  <Paper sx={{ p: 2 }}>
                    <Stack direction="row" spacing={1} flexWrap="wrap">
                      <Chip label={`Run: ${forwardStatus.run_id ?? 'n/a'}`} size="small" />
                      <Chip label={`Status: ${forwardStatus.status ?? 'n/a'}`} size="small" />
                    </Stack>
                  </Paper>
                  <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
                    <Paper sx={{ p: 2, flex: 1 }}>
                      <Typography variant="subtitle2" fontWeight={600}>
                        Last equity report
                      </Typography>
                      {renderKeyValueGrid(forwardStatus.last_equity ?? undefined, 'No equity yet.')}
                    </Paper>
                    <Paper sx={{ p: 2, flex: 1 }}>
                      <Typography variant="subtitle2" fontWeight={600}>
                        Last trade
                      </Typography>
                      {renderKeyValueGrid(forwardStatus.last_trade ?? undefined, 'No trades yet.')}
                    </Paper>
                    <Paper sx={{ p: 2, flex: 1 }}>
                      <Typography variant="subtitle2" fontWeight={600}>
                        Last alert
                      </Typography>
                      {renderKeyValueGrid(forwardStatus.last_alert ?? undefined, 'No alerts yet.')}
                    </Paper>
                  </Stack>
                  <Accordion>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Typography variant="subtitle2">State snapshot</Typography>
                    </AccordionSummary>
                    <AccordionDetails>{renderJsonBlock(forwardStatus.state ?? {})}</AccordionDetails>
                  </Accordion>
                  {forwardStatus.run_meta ? (
                    <Accordion>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography variant="subtitle2">Run metadata</Typography>
                      </AccordionSummary>
                      <AccordionDetails>{renderJsonBlock(forwardStatus.run_meta)}</AccordionDetails>
                    </Accordion>
                  ) : null}
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Load the forward status to see the latest report and alerts.
                </Typography>
              )}
            </Stack>
          ) : null}
          {tab === 'hpo' ? (
            <Stack spacing={2}>
              <Paper sx={{ p: 2 }}>
                <Stack spacing={2}>
                  <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                    <Button variant="outlined" onClick={() => fetchParamSpecs({ resetValues: false })}>
                      Load params
                    </Button>
                    <Typography variant="body2" color="text.secondary">
                      {paramSpecs.length
                        ? `Base params loaded: ${paramSpecs.length}`
                        : 'Base params not loaded (defaults will be used)'}
                    </Typography>
                  </Stack>
                  <TextField
                    label="Search space (JSON)"
                    size="small"
                    value={hpoSearchSpace}
                    onChange={(event) => setHpoSearchSpace(event.target.value)}
                    placeholder='{"strategy.z_window":{"kind":"int","min_value":20,"max_value":120}}'
                    multiline
                    minRows={6}
                  />
                  <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                    <Button variant="contained" onClick={handleHpoRun} disabled={hpoLoading}>
                      Run HPO
                    </Button>
                    {hpoLoading ? (
                      <Typography variant="body2" color="text.secondary">
                        Running HPO...
                      </Typography>
                    ) : null}
                    {hpoError ? (
                      <Typography variant="body2" color="error">
                        {hpoError}
                      </Typography>
                    ) : null}
                  </Stack>
                </Stack>
              </Paper>
              {hpoResponse ? (
                <Stack spacing={2}>
                  <Paper sx={{ p: 2 }}>
                    <Stack direction="row" spacing={1} flexWrap="wrap">
                      {hpoResponse.status ? (
                        <Chip label={`Status: ${hpoResponse.status}`} size="small" />
                      ) : null}
                      {hpoResponse.message ? (
                        <Chip label={hpoResponse.message} size="small" />
                      ) : null}
                    </Stack>
                  </Paper>
                  <Paper sx={{ p: 2 }}>
                    <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1 }}>
                      Leaderboard
                    </Typography>
                    {renderTable(
                      hpoLeaderboardRows as GenericRow[],
                      hpoLeaderboardColumns,
                      'No leaderboard entries yet.',
                    )}
                  </Paper>
                  <Accordion>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Typography variant="subtitle2">Raw HPO response</Typography>
                    </AccordionSummary>
                    <AccordionDetails>{renderJsonBlock(hpoResponse)}</AccordionDetails>
                  </Accordion>
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Run HPO to see the leaderboard.
                </Typography>
              )}
            </Stack>
          ) : null}
        </Stack>
      </Container>
    </Box>
  )
}

export default App
