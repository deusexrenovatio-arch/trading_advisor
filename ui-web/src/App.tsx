import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
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
  spread?: number | null
  spot?: number | null
  future_price?: number | null
  fair_value?: number | null
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
  implied_rate_net: 'Implied rate',
  required_rate: 'Required rate',
  expected_net_irr: 'Expected IRR',
  spot: 'Spot',
  future_price: 'Future price',
  fair_value: 'Fair value',
  max_drawdown: 'Max drawdown',
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
  'implied_rate_net',
  'required_rate',
  'expected_net_irr',
  'spread_vol_pct',
  'cagr',
  'hit_rate',
  'max_drawdown',
  'cycle_return_pct',
])

const columnDigits: Record<string, number> = {
  spot: 2,
  future_price: 2,
  fair_value: 2,
  spread: 4,
  zscore: 3,
  zscore_raw: 3,
  spread_vol: 4,
  spread_trend_pos: 4,
  spread_trend_slope: 6,
  spread_trend_z: 3,
  implied_rate_net: 2,
  required_rate: 2,
  expected_net_irr: 2,
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

function App() {
  const [rows, setRows] = useState<DecisionView[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [auxLoading, setAuxLoading] = useState(false)
  const [auxError, setAuxError] = useState<string | null>(null)
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
  const [tab, setTab] = useState<'decisions' | 'top_pairs' | 'signals' | 'backtests'>('decisions')
  const [topPairs, setTopPairs] = useState<GenericRow[]>([])
  const [signals, setSignals] = useState<GenericRow[]>([])
  const [backtests, setBacktests] = useState<GenericRow[]>([])
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
          return
        }
        if (!result.value.ok) {
          errors.push(`${label} API error: ${result.value.status}`)
          setter([])
          return
        }
        try {
          setter(await result.value.json())
        } catch (err) {
          errors.push(`${label} parse error`)
          setter([])
        }
      }

      await parseResult('Top pairs', results[0], setTopPairs)
      await parseResult('Signals', results[1], setSignals)
      await parseResult('Backtests', results[2], setBacktests)

      if (errors.length) {
        setAuxError(errors.join(' | '))
      }
    } catch (err) {
      setAuxError(err instanceof Error ? err.message : 'Failed to load tables')
    } finally {
      setAuxLoading(false)
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
          )}&window_days=60`,
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

  useEffect(() => {
    fetchDecisionView()
    fetchAuxData({ topPairsLimit, topPairsAll })
  }, [fetchDecisionView, fetchAuxData])

  const handleRefresh = useCallback(() => {
    fetchDecisionView()
    fetchAuxData({ topPairsLimit, topPairsAll })
  }, [fetchDecisionView, fetchAuxData, topPairsAll, topPairsLimit])

  const handleAuxRefresh = useCallback(() => {
    fetchAuxData({ topPairsLimit, topPairsAll })
  }, [fetchAuxData, topPairsAll, topPairsLimit])

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
        'stock_name',
        'future',
        'spot',
        'future_price',
        'implied_rate_net',
        'required_rate',
        'expected_net_irr',
        'signal_action',
        'signal_direction',
        'score',
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
      ])
    }
    return tableColumns
  }, [tab, tableColumns])

  const defaultSortKey = useMemo(() => {
    if (tab === 'top_pairs' && tableVisibleColumns.includes('score')) return 'score'
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

  const isLoading = loading || auxLoading

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
      { key: 'timestamp', label: 'Timestamp' },
      { key: 'spot', label: 'Spot' },
      { key: 'future_price', label: 'Future price' },
      { key: 'implied_rate_net', label: 'Implied rate' },
      { key: 'required_rate', label: 'Required rate' },
      { key: 'expected_net_irr', label: 'Expected IRR' },
      { key: 'signal_action', label: 'Signal' },
      { key: 'signal_direction', label: 'Direction' },
      { key: 'signal_score', label: 'Signal score' },
    ],
    [],
  )

  const detailFields = useMemo(() => {
    const base = [
      { key: 'signal_score_norm', label: 'Signal score (norm)' },
      { key: 'spread', label: 'Spread' },
      { key: 'zscore', label: 'Z-score' },
      { key: 'spread_vol', label: 'Spread vol' },
      { key: 'spread_vol_pct', label: 'Spread vol %' },
      { key: 'spread_trend_pos', label: 'Trend pos' },
      { key: 'spread_trend_slope', label: 'Trend slope' },
      { key: 'spread_trend_z', label: 'Trend Z' },
    ]
    const signalDetails =
      tab === 'signals'
        ? [
            { key: 'signal_reasons', label: 'Signal reasons' },
            { key: 'signal_metrics', label: 'Signal metrics' },
          ]
        : []
    return [
      ...base,
      ...signalDetails,
      { key: 'score', label: 'Score' },
      { key: 'snapshot_as_of', label: 'Snapshot as of' },
    ]
  }, [tab])

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
          ) : (
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
                  <Button variant="outlined" onClick={handleAuxRefresh} disabled={auxLoading}>
                    Reload
                  </Button>
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
                        const detailEntries = detailFields
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
                                      <Box
                                        sx={{
                                          display: 'grid',
                                          gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                                          gap: 1,
                                          mt: 1,
                                        }}
                                      >
                                        {snapshotEntries.map((entry) => (
                                          <Box key={entry.key}>
                                            <Typography variant="caption" color="text.secondary">
                                              {entry.label}
                                            </Typography>
                                            <Typography variant="body2">
                                              {formatCellValue(entry.value, entry.key)}
                                            </Typography>
                                          </Box>
                                        ))}
                                      </Box>
                                    </Box>
                                    {detailEntries.length ? (
                                      <Box>
                                        <Typography variant="subtitle2" fontWeight={600}>
                                          Details
                                        </Typography>
                                        <Box
                                          sx={{
                                            display: 'grid',
                                            gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                                            gap: 1,
                                            mt: 1,
                                          }}
                                        >
                                          {detailEntries.map((entry) => (
                                            <Box key={entry.key}>
                                              <Typography variant="caption" color="text.secondary">
                                                {entry.label}
                                              </Typography>
                                              <Typography variant="body2">
                                              {formatCellValue(entry.value, entry.key)}
                                              </Typography>
                                            </Box>
                                          ))}
                                        </Box>
                                      </Box>
                                    ) : null}
                                    <Box>
                                      <Typography variant="subtitle2" fontWeight={600}>
                                        Spread chart (60d)
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
          )}
        </Stack>
      </Container>
    </Box>
  )
}

export default App
