import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  ExecutionRow,
  GenericRow,
  PretradeCheckResult,
  RefreshStatus,
  SignalActiveV2,
  SignalHistoryRow,
  SpreadSeriesPoint,
} from '../../entities/decision/types'
import {
  fetchBacktests as fetchBacktestsApi,
  fetchPretradeCheck as fetchPretradeCheckApi,
  fetchRefreshStatus as fetchRefreshStatusApi,
  fetchSignalExecutions as fetchSignalExecutionsApi,
  fetchSignalHistory as fetchSignalHistoryApi,
  fetchSignalsActiveV2 as fetchSignalsActiveV2Api,
  fetchSpreadSeries as fetchSpreadSeriesApi,
  fetchTopPairs as fetchTopPairsApi,
  refreshSignals as refreshSignalsApi,
  submitSignalActionV2 as submitSignalActionV2Api,
} from '../../shared/api/decisionApi'
import { ApiError } from '../../shared/api/http'
import { formatDateInputValue, parseDateInput } from '../../shared/utils/date'
import { getTableColumns } from '../../shared/utils/tables'
import {
  PRETRADE_PREFETCH_LIMIT,
  SIGNAL_ACTION_HOLD_OPEN_VALUE,
  isEntrySignal,
  mapSignalV2Row,
  normalizeExecutionAction,
  normalizeExecutionLeg,
  resolveEffectiveSignalAction,
  resolveSignalDirection,
  toHistorySignalAction,
  toSignalFilterAction,
} from './signalViewModel'

const AUTO_REFRESH_MS = 60_000
const PRETRADE_SNAPSHOTS = 4
const PRETRADE_MIN_HITS = 2
const PRETRADE_POLL_SEC = 0
const EXECUTION_LEG_STOCK = 'stock'
const EXECUTION_LEG_FUTURE = 'future'

export type MarketTab = 'top_pairs' | 'signals' | 'backtests'
export type AppTab = MarketTab | 'decisions' | 'backtest_v2' | 'forward' | 'hpo'

export type ExecutionForm = {
  price: string
  quantity: string
  side: string
  note: string
}

type PendingExecutionOrder = {
  orderId: string
  legs: Set<string>
}

const createExecutionOrderId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  const randomPart = Math.random().toString(36).slice(2, 10)
  return `exec-${Date.now()}-${randomPart}`
}

type Params = {
  tab: AppTab
  compareValues: (left: unknown, right: unknown) => number
  onOperatorAction?: () => void
}

const formatExecutionActionError = (err: unknown) => {
  if (err instanceof ApiError) {
    const payload = err.payload
    if (payload) {
      const reasonCode = String(payload.reason_code ?? '').trim()
      const reasonText = String(payload.message ?? err.message ?? '').trim()
      const failClosedRaw = payload.fail_closed
      const failClosed =
        failClosedRaw && typeof failClosedRaw === 'object' && !Array.isArray(failClosedRaw)
          ? (failClosedRaw as Record<string, unknown>)
          : null
      const failClosedCode = failClosed ? String(failClosed.reason_code ?? '').trim() : ''
      const detailParts = [reasonCode, failClosedCode].filter(Boolean)
      if (reasonText) {
        return detailParts.length ? `${reasonText} (${detailParts.join(', ')})` : reasonText
      }
      if (detailParts.length) {
        return detailParts.join(', ')
      }
    }
    return err.message || `HTTP ${err.status}`
  }
  if (err instanceof Error) return err.message
  return 'Не удалось выполнить действие по сигналу'
}

export const useMarketTables = ({ tab, compareValues, onOperatorAction }: Params) => {
  const [auxLoading, setAuxLoading] = useState(false)
  const [auxError, setAuxError] = useState<string | null>(null)
  const [auxLastUpdated, setAuxLastUpdated] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [refreshStatus, setRefreshStatus] = useState<RefreshStatus | null>(null)
  const [recomputeLoading, setRecomputeLoading] = useState(false)
  const [recomputeError, setRecomputeError] = useState<string | null>(null)
  const [topPairs, setTopPairs] = useState<GenericRow[]>([])
  const [signals, setSignals] = useState<GenericRow[]>([])
  const [backtests, setBacktests] = useState<GenericRow[]>([])
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
  const [pretradeChecks, setPretradeChecks] = useState<Record<string, PretradeCheckResult>>({})
  const [pretradeLoadingKey, setPretradeLoadingKey] = useState<string | null>(null)
  const [pretradeError, setPretradeError] = useState<Record<string, string>>({})
  const [pretradeCheckedAt, setPretradeCheckedAt] = useState<Record<string, string>>({})
  const [topPairsLimit, setTopPairsLimit] = useState('25')
  const [topPairsAll, setTopPairsAll] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyFrom, setHistoryFrom] = useState(() => {
    const date = new Date()
    date.setDate(date.getDate() - 7)
    return formatDateInputValue(date)
  })
  const [historyTo, setHistoryTo] = useState(() => formatDateInputValue(new Date()))
  const [signalHistory, setSignalHistory] = useState<SignalHistoryRow[]>([])
  const [executionForm, setExecutionForm] = useState<ExecutionForm>({
    price: '',
    quantity: '',
    side: '',
    note: '',
  })
  const pendingExecutionOrdersRef = useRef<Record<string, PendingExecutionOrder>>({})
  const auxFetchInFlight = useRef(false)
  const mergeSignalMetrics = useCallback((rows: GenericRow[]) => {
    return rows.map((row) => {
      const metrics = row.signal_metrics
      if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) return row
      return {
        ...(metrics as Record<string, unknown>),
        ...row,
      }
    })
  }, [])

  const toEffectiveSignalAction = useCallback(
    (row: GenericRow) => toSignalFilterAction(row, tab === 'signals'),
    [tab],
  )

  const toHistoryAction = toHistorySignalAction

  const fetchAuxData = useCallback(async () => {
    if (auxFetchInFlight.current) return
    auxFetchInFlight.current = true
    setAuxLoading(true)
    setAuxError(null)
    try {
      const limitValue = Number(topPairsLimit)
      const resolvedLimit = !Number.isNaN(limitValue) && limitValue >= 0 ? limitValue : 500
      const results = await Promise.allSettled([
        fetchTopPairsApi(resolvedLimit, topPairsAll),
        fetchSignalsActiveV2Api(),
        fetchBacktestsApi(500),
        fetchRefreshStatusApi(),
      ])

      const errors: string[] = []
      const parseRows = (
        label: string,
        result: PromiseSettledResult<GenericRow[]>,
        setter: (rows: GenericRow[]) => void,
        transform?: (rows: GenericRow[]) => GenericRow[],
      ) => {
        if (result.status === 'rejected') {
          const message = result.reason instanceof Error ? result.reason.message : 'ошибка загрузки'
          errors.push(`${label}: ${message}`)
          setter([])
          return false
        }
        setter(transform ? transform(result.value) : result.value)
        return true
      }
      const parseStatus = (
        label: string,
        result: PromiseSettledResult<RefreshStatus>,
        setter: (payload: RefreshStatus | null) => void,
      ) => {
        if (result.status === 'rejected') {
          const message = result.reason instanceof Error ? result.reason.message : 'ошибка загрузки'
          errors.push(`${label}: ${message}`)
          setter(null)
          return false
        }
        setter(result.value)
        return true
      }

      const topPairsOk = parseRows(
        'Топ пар',
        results[0] as PromiseSettledResult<GenericRow[]>,
        setTopPairs,
      )
      const signalsResult = results[1] as PromiseSettledResult<SignalActiveV2[]>
      let signalsOk = false
      if (signalsResult.status === 'rejected') {
        const message =
          signalsResult.reason instanceof Error
            ? signalsResult.reason.message
            : 'ошибка загрузки'
        errors.push(`Сигналы: ${message}`)
        setSignals([])
      } else {
        setSignals(mergeSignalMetrics(signalsResult.value.map(mapSignalV2Row)))
        signalsOk = true
      }
      parseRows('Бэктесты', results[2] as PromiseSettledResult<GenericRow[]>, setBacktests)
      parseStatus(
        'Статус обновления',
        results[3] as PromiseSettledResult<RefreshStatus>,
        setRefreshStatus,
      )

      if (topPairsOk && signalsOk) {
        setAuxLastUpdated(new Date().toISOString())
      }
      if (errors.length) {
        setAuxError(errors.join(' | '))
      }
    } catch (err) {
      setAuxError(err instanceof Error ? err.message : 'Не удалось загрузить таблицы')
    } finally {
      setAuxLoading(false)
      auxFetchInFlight.current = false
    }
  }, [mergeSignalMetrics, topPairsAll, topPairsLimit])

  const requestRecompute = useCallback(async (): Promise<boolean> => {
    setRecomputeLoading(true)
    setRecomputeError(null)
    try {
      const payload = await refreshSignalsApi()
      setRefreshStatus(payload)
      return true
    } catch (err) {
      setRecomputeError(err instanceof Error ? err.message : 'Не удалось пересчитать данные')
      return false
    } finally {
      setRecomputeLoading(false)
    }
  }, [])

  const refreshAuxData = useCallback(async () => {
    await requestRecompute()
    await fetchAuxData()
  }, [fetchAuxData, requestRecompute])

  const fetchSignalHistory = useCallback(async () => {
    setHistoryLoading(true)
    setHistoryError(null)
    try {
      const historyActionFilter = toHistoryAction(tableSignalFilter || '')
      const data = await fetchSignalHistoryApi(
        historyFrom || undefined,
        historyTo || undefined,
        500,
        tableStockFilter || undefined,
        tableFutureFilter || undefined,
        historyActionFilter,
      )
      setSignalHistory(data)
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : 'Не удалось загрузить историю')
    } finally {
      setHistoryLoading(false)
    }
  }, [
    historyFrom,
    historyTo,
    tableFutureFilter,
    tableSignalFilter,
    tableStockFilter,
    toHistoryAction,
  ])

  const fetchExecutionLog = useCallback(async (pairKey: string, stock: string, future: string) => {
    setExecutionLoadingKey(pairKey)
    setExecutionError((prev) => ({ ...prev, [pairKey]: '' }))
    try {
      const data = await fetchSignalExecutionsApi(stock, future, 20)
      setExecutionLogs((prev) => ({ ...prev, [pairKey]: data }))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Не удалось загрузить исполнения'
      setExecutionError((prev) => ({ ...prev, [pairKey]: message }))
    } finally {
      setExecutionLoadingKey(null)
    }
  }, [])

  const fetchPretradeCheck = useCallback(
    async (
      pairKey: string,
      stock: string,
      future: string,
      direction: 'cash_and_carry' | 'reverse',
      force = false,
    ) => {
      if (!force && pretradeChecks[pairKey]) return
      setPretradeLoadingKey(pairKey)
      setPretradeError((prev) => ({ ...prev, [pairKey]: '' }))
      try {
        const data = await fetchPretradeCheckApi(stock, future, {
          direction,
          snapshots: PRETRADE_SNAPSHOTS,
          minHits: PRETRADE_MIN_HITS,
          pollSec: PRETRADE_POLL_SEC,
        })
        setPretradeChecks((prev) => ({ ...prev, [pairKey]: data }))
        setPretradeCheckedAt((prev) => ({ ...prev, [pairKey]: new Date().toISOString() }))
      } catch (err) {
        let message = err instanceof Error ? err.message : 'Не удалось загрузить pre-trade check'
        if (err instanceof Error && err.message.includes('404')) {
          message =
            'Pre-trade endpoint недоступен (404). Перезапустите backend из актуального main с --config configs/default.yaml.'
        }
        setPretradeError((prev) => ({ ...prev, [pairKey]: message }))
      } finally {
        setPretradeLoadingKey(null)
      }
    },
    [pretradeChecks],
  )

  const handleRefreshPretrade = useCallback(
    (row: GenericRow) => {
      const stock = row.stock ? String(row.stock) : ''
      const future = row.future ? String(row.future) : ''
      if (!stock || !future || !isEntrySignal(row)) return
      const pairKey = `${stock}-${future}`
      const directionValue = resolveSignalDirection(row.signal_direction)
      void fetchPretradeCheck(pairKey, stock, future, directionValue, true)
    },
    [fetchPretradeCheck],
  )

  const handleExecuteSignal = useCallback(
    async (row: GenericRow) => {
      onOperatorAction?.()
      const signalId = row.signal_id ? String(row.signal_id) : ''
      if (!signalId) {
        throw new Error('signal_id is required for /api/v2/signals/{signal_id}/actions')
      }
      const stock = row.stock ? String(row.stock) : ''
      const future = row.future ? String(row.future) : ''
      const pairKey = stock && future ? `${stock}-${future}` : null
      const actionKey = normalizeExecutionAction(row.signal_action)
      const pendingKey = pairKey ? `${pairKey}:${actionKey}` : null
      if (pairKey) {
        setExecutionError((prev) => ({ ...prev, [pairKey]: '' }))
      }
      const normalizedLeg = normalizeExecutionLeg(executionForm.side)
      const isTwoLegCandidate =
        Boolean(stock) &&
        Boolean(future) &&
        (normalizedLeg === EXECUTION_LEG_STOCK || normalizedLeg === EXECUTION_LEG_FUTURE)

      let orderId: string | null = null
      let pendingOrderAfterExecute: PendingExecutionOrder | null = null
      if (isTwoLegCandidate && pendingKey) {
        const pendingMap = pendingExecutionOrdersRef.current
        const current = pendingMap[pendingKey]
        const shouldStartNewOrder =
          !current || current.legs.has(normalizedLeg) || current.legs.size >= 2
        const nextOrder: PendingExecutionOrder = shouldStartNewOrder
          ? { orderId: createExecutionOrderId(), legs: new Set<string>() }
          : { orderId: current.orderId, legs: new Set(current.legs) }
        nextOrder.legs.add(normalizedLeg)
        orderId = nextOrder.orderId
        pendingOrderAfterExecute = nextOrder
      }

      const payload = {
        action: actionKey,
        stock: row.stock,
        future: row.future,
        direction: row.signal_direction,
        source: 'ui',
        actor_id: 'operator',
        price: executionForm.price ? Number(executionForm.price) : null,
        quantity: executionForm.quantity ? Number(executionForm.quantity) : null,
        side: normalizedLeg || executionForm.side || null,
        order_id: orderId,
        note: executionForm.note || null,
      }
      try {
        await submitSignalActionV2Api(signalId, payload)
      } catch (err) {
        if (pairKey) {
          setExecutionError((prev) => ({
            ...prev,
            [pairKey]: formatExecutionActionError(err),
          }))
        }
        return
      }
      if (pendingKey && normalizedLeg && pendingOrderAfterExecute) {
        const isLinkedTwoLegOrder =
          pendingOrderAfterExecute.legs.has(EXECUTION_LEG_STOCK) &&
          pendingOrderAfterExecute.legs.has(EXECUTION_LEG_FUTURE)
        if (isLinkedTwoLegOrder) {
          delete pendingExecutionOrdersRef.current[pendingKey]
        } else {
          pendingExecutionOrdersRef.current[pendingKey] = pendingOrderAfterExecute
        }
      }
      if (pairKey) {
        void fetchExecutionLog(pairKey, String(row.stock), String(row.future))
      }
      setExecutionForm({
        price: '',
        quantity: '',
        side: '',
        note: '',
      })
    },
    [executionForm, fetchExecutionLog, onOperatorAction],
  )

  const fetchSpreadSeries = useCallback(
    async (pairKey: string, stock: string, future: string) => {
      setSpreadLoadingKey(pairKey)
      setSpreadError((prev) => ({ ...prev, [pairKey]: '' }))
      try {
        const data = await fetchSpreadSeriesApi(stock, future, 60, true)
        setSpreadSeries((prev) => ({ ...prev, [pairKey]: data }))
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Не удалось загрузить серию спреда'
        setSpreadError((prev) => ({ ...prev, [pairKey]: message }))
      } finally {
        setSpreadLoadingKey(null)
      }
    },
    [],
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
      setDetailTab(tab === 'signals' ? 'execution' : 'overview')
      const stock = row.stock ? String(row.stock) : ''
      const future = row.future ? String(row.future) : ''
      if (stock && future && !spreadSeries[pairKey]) {
        void fetchSpreadSeries(pairKey, stock, future)
      }
      if (tab === 'signals' && stock && future && !executionLogs[pairKey]) {
        void fetchExecutionLog(pairKey, stock, future)
      }
      if (tab === 'signals' && stock && future && isEntrySignal(row) && !pretradeChecks[pairKey]) {
        const directionValue = resolveSignalDirection(row.signal_direction)
        void fetchPretradeCheck(pairKey, stock, future, directionValue)
      }
    },
    [
      expandedRowKey,
      executionLogs,
      fetchExecutionLog,
      fetchPretradeCheck,
      fetchSpreadSeries,
      pretradeChecks,
      spreadSeries,
      tab,
    ],
  )

  const onExecutionFormFieldChange = useCallback((field: keyof ExecutionForm, value: string) => {
    setExecutionForm((prev) => ({ ...prev, [field]: value }))
  }, [])

  const tableRows = useMemo<GenericRow[]>(() => {
    if (tab === 'top_pairs') return topPairs
    if (tab === 'signals') {
      return signals.map((row) => ({
        ...row,
        signal_action_effective: resolveEffectiveSignalAction(row),
      }))
    }
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
        'signal_action_effective',
        'signal_direction',
        'signal_score',
        'entry_stock_min',
        'entry_stock_max',
        'entry_future_min_per_share',
        'entry_future_max_per_share',
        'tp_spread_pct_level',
        'sl_spread_pct_level',
        'forecast_exit_days',
      ])
    }
    return tableColumns
  }, [tab, tableColumns])
  const tableVisibleSet = useMemo(() => new Set(tableVisibleColumns), [tableVisibleColumns])
  const stripDuplicates = useCallback(
    (entries: { key: string; value: unknown }[]) => {
      const filtered = entries.filter((entry) => !tableVisibleSet.has(entry.key))
      return filtered.length ? filtered : entries
    },
    [tableVisibleSet],
  )

  const defaultSortKey = useMemo(() => {
    if (tab === 'top_pairs' && tableVisibleColumns.includes('total_score')) return 'total_score'
    if (tab === 'top_pairs' && tableVisibleColumns.includes('score_floor')) return 'score_floor'
    if (tab === 'signals' && tableVisibleColumns.includes('signal_score')) return 'signal_score'
    if (tab === 'backtests' && tableVisibleColumns.includes('cagr')) return 'cagr'
    return tableVisibleColumns[0] ?? ''
  }, [tab, tableVisibleColumns])

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
        if (tableSignalFilter && toEffectiveSignalAction(row) !== tableSignalFilter) return false
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
    toEffectiveSignalAction,
  ])

  const sortedTableRows = useMemo<GenericRow[]>(() => {
    if (!tableSortKey) return filteredTableRows
    const sorted = [...filteredTableRows].sort((left, right) =>
      compareValues(left[tableSortKey], right[tableSortKey]),
    )
    return tableSortDirection === 'asc' ? sorted : sorted.reverse()
  }, [compareValues, filteredTableRows, tableSortDirection, tableSortKey])

  useEffect(() => {
    if (tab !== 'signals') return
    if (pretradeLoadingKey) return

    const candidate = sortedTableRows.slice(0, PRETRADE_PREFETCH_LIMIT).find((row) => {
      if (!isEntrySignal(row)) return false
      const stock = row.stock ? String(row.stock) : ''
      const future = row.future ? String(row.future) : ''
      if (!stock || !future) return false
      const pairKey = `${stock}-${future}`
      if (pretradeChecks[pairKey]) return false
      if (pretradeError[pairKey]) return false
      return true
    })

    if (!candidate) return

    const stock = String(candidate.stock ?? '')
    const future = String(candidate.future ?? '')
    if (!stock || !future) return
    const pairKey = `${stock}-${future}`
    const directionValue = resolveSignalDirection(candidate.signal_direction)
    void fetchPretradeCheck(pairKey, stock, future, directionValue)
  }, [
    fetchPretradeCheck,
    pretradeChecks,
    pretradeError,
    pretradeLoadingKey,
    sortedTableRows,
    tab,
  ])

  const filteredSignalHistory = useMemo(() => {
    if (!signalHistory.length) return []
    const query = tableFilter.trim().toLowerCase()
    const fromTs = parseDateInput(historyFrom, 'start')
    const toTs = parseDateInput(historyTo, 'end')
    const historyActionFilter = toHistoryAction(tableSignalFilter || '')
    return signalHistory.filter((row) => {
      const rowTs = Date.parse(row.timestamp)
      if ((fromTs !== null || toTs !== null) && Number.isNaN(rowTs)) return false
      if (fromTs !== null && rowTs < fromTs) return false
      if (toTs !== null && rowTs > toTs) return false
      if (tableStockFilter && String(row.stock ?? '') !== tableStockFilter) return false
      if (tableFutureFilter && String(row.future ?? '') !== tableFutureFilter) return false
      if (historyActionFilter && String(row.signal_action ?? '') !== historyActionFilter) return false
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
    toHistoryAction,
  ])

  const openSignalRows = useMemo<GenericRow[]>(() => {
    if (tab !== 'signals') return []
    const isOpenRow = (row: GenericRow) => {
      if (row.position_open === true) return true
      if (String(row.position_state ?? '').toLowerCase() === 'open') return true
      return toEffectiveSignalAction(row) === SIGNAL_ACTION_HOLD_OPEN_VALUE
    }

    const latestByPair = new Map<string, GenericRow>()
    for (const row of tableRows) {
      if (!isOpenRow(row)) continue
      const stock = row.stock ? String(row.stock) : ''
      const future = row.future ? String(row.future) : ''
      if (!stock || !future) continue
      const key = `${stock}-${future}`
      const previous = latestByPair.get(key)
      if (!previous || String(previous.timestamp ?? '') < String(row.timestamp ?? '')) {
        latestByPair.set(key, row)
      }
    }
    return Array.from(latestByPair.values()).sort((left, right) =>
      String(right.timestamp ?? '').localeCompare(String(left.timestamp ?? '')),
    )
  }, [tab, tableRows, toEffectiveSignalAction])

  const showPairDetails = tab === 'top_pairs' || tab === 'signals'

  const snapshotFields = useMemo(
    () => [
      'stock',
      'stock_name',
      'future',
      'expiry',
      'spot',
      'future_price',
      'spread_mid',
      'spread_pct',
      'rtc_pct',
      'total_score',
    ],
    [],
  )

  const overviewFields = useMemo(
    () => [
      'floor_pass',
      'liquidity_pass',
      'dte',
      'floor_rate_annual',
      'score_floor',
      'r_cb_annual',
      'r_fund_annual',
      'r_disc_annual',
      'snapshot_as_of',
    ],
    [],
  )

  const alphaFields = useMemo(
    () => [
      'avg_trade_return_annual_recent',
      'score_alpha',
      'p_hit_tp',
      'p_hit_sl',
      'sigma_h',
      'half_life',
    ],
    [],
  )

  const liquidityFields = useMemo(
    () => [
      'spread_bps_stock',
      'spread_bps_fut',
      'dollar_vol_stock',
      'dollar_vol_fut',
      'days_to_exit',
      'open_interest',
    ],
    [],
  )

  const signalContextFields = useMemo(
    () => ['signal_action', 'signal_direction', 'signal_score', 'decision', 'signal_reasons'],
    [],
  )

  const signalEntryFields = useMemo(
    () => [
      'entry_price_tolerance_pct',
      'entry_stock_min',
      'entry_stock_max',
      'entry_future_min_per_share',
      'entry_future_max_per_share',
      'entry_spread_min',
      'entry_spread_max',
      'entry_spread_pct_min',
      'entry_spread_pct_max',
    ],
    [],
  )

  const signalRiskFields = useMemo(
    () => [
      'tp_net',
      'sl_net',
      'tp_spread_pct_level',
      'sl_spread_pct_level',
      'tp_spread_level',
      'sl_spread_level',
      'tp_stock_level_if_fut_const',
      'sl_stock_level_if_fut_const',
      'tp_future_level_if_stock_const',
      'sl_future_level_if_stock_const',
    ],
    [],
  )

  const signalForecastFields = useMemo(
    () => [
      'forecast_exit_days',
      'forecast_exit_date',
      'forecast_model',
      'forecast_tp_probability',
      'forecast_sl_probability',
    ],
    [],
  )

  const signalModelFields = useMemo(
    () => [
      'orderbook_pass',
      'orderbook_stock_quote_available',
      'orderbook_fut_quote_available',
      'orderbook_stock_depth_available',
      'orderbook_fut_depth_available',
      'orderbook_data_warnings',
      'orderbook_stock_min_depth',
      'orderbook_fut_min_depth',
      'orderbook_stock_quote_age_sec',
      'orderbook_fut_quote_age_sec',
      'orderbook_stock_imbalance',
      'orderbook_fut_imbalance',
      'floor_rate_annual',
      'rtc_pct',
      'spread_pct',
      'score_floor',
      'score_alpha',
      'total_score',
    ],
    [],
  )

  const executionFields = useMemo(() => {
    if (tab !== 'signals') {
      return ['signal_action', 'signal_direction', 'signal_score', 'decision']
    }
    return signalContextFields
  }, [signalContextFields, tab])

  const signalFilterRows = useMemo<GenericRow[]>(() => {
    if (tab !== 'signals') return tableRows
    if (!signalHistory.length) return tableRows
    if (!tableRows.length) {
      return signalHistory.map((row) => row as unknown as GenericRow)
    }
    return [...tableRows, ...signalHistory.map((row) => row as unknown as GenericRow)]
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
        new Set(signalFilterRows.map((row) => toEffectiveSignalAction(row)).filter(Boolean).map(String)),
      ).sort(),
    [signalFilterRows, toEffectiveSignalAction],
  )

  useEffect(() => {
    setExpandedRowKey(null)
    setDetailTab(tab === 'signals' ? 'execution' : 'overview')
    setTableStockFilter('')
    setTableFutureFilter('')
    setTableSignalFilter('')
    pendingExecutionOrdersRef.current = {}
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
    void fetchAuxData()
  }, [fetchAuxData])

  useEffect(() => {
    if (!autoRefresh) return
    const interval = window.setInterval(() => {
      void fetchAuxData()
    }, AUTO_REFRESH_MS)
    return () => window.clearInterval(interval)
  }, [autoRefresh, fetchAuxData])

  return {
    auxLoading,
    auxError,
    auxLastUpdated,
    autoRefresh,
    setAutoRefresh,
    refreshStatus,
    recomputeLoading,
    recomputeError,
    topPairs,
    signals,
    backtests,
    topPairsLimit,
    setTopPairsLimit,
    topPairsAll,
    setTopPairsAll,
    tableFilter,
    setTableFilter,
    tableStockFilter,
    setTableStockFilter,
    tableFutureFilter,
    setTableFutureFilter,
    tableSignalFilter,
    setTableSignalFilter,
    tableStockOptions,
    tableFutureOptions,
    tableSignalOptions,
    tableVisibleColumns,
    tableSortKey,
    tableSortDirection,
    handleTableSort,
    showPairDetails,
    expandedRowKey,
    handleToggleDetails,
    detailTab,
    setDetailTab,
    snapshotFields,
    overviewFields,
    alphaFields,
    liquidityFields,
    signalContextFields,
    signalEntryFields,
    signalRiskFields,
    signalForecastFields,
    signalModelFields,
    executionFields,
    spreadError,
    spreadLoadingKey,
    spreadSeries,
    executionForm,
    onExecutionFormFieldChange,
    handleExecuteSignal,
    isEntrySignal,
    executionError,
    executionLogs,
    executionLoadingKey,
    pretradeChecks,
    pretradeLoadingKey,
    pretradeError,
    pretradeCheckedAt,
    handleRefreshPretrade,
    fetchAuxData,
    refreshAuxData,
    historyFrom,
    historyTo,
    setHistoryFrom,
    setHistoryTo,
    fetchSignalHistory,
    historyLoading,
    historyError,
    signalHistory,
    filteredSignalHistory,
    openSignalRows,
    sortedTableRows,
    stripDuplicates,
  }
}

export type MarketTablesState = ReturnType<typeof useMarketTables>
