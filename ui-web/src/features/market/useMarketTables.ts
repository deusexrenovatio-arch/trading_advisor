import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  ExecutionRow,
  GenericRow,
  PretradeCheckResult,
  RefreshStatus,
  SignalHistoryRow,
  SpreadSeriesPoint,
} from '../../entities/decision/types'
import {
  executeSignal as executeSignalApi,
  fetchBacktests as fetchBacktestsApi,
  fetchPretradeCheck as fetchPretradeCheckApi,
  fetchRefreshStatus as fetchRefreshStatusApi,
  fetchSignalExecutions as fetchSignalExecutionsApi,
  fetchSignalHistory as fetchSignalHistoryApi,
  fetchSignalsActive as fetchSignalsActiveApi,
  fetchSpreadSeries as fetchSpreadSeriesApi,
  fetchTopPairs as fetchTopPairsApi,
  refreshSignals as refreshSignalsApi,
} from '../../shared/api/decisionApi'
import { formatDateInputValue, parseDateInput } from '../../shared/utils/date'
import { getTableColumns } from '../../shared/utils/tables'

const AUTO_REFRESH_MS = 60_000
const PRETRADE_SNAPSHOTS = 4
const PRETRADE_MIN_HITS = 2
const PRETRADE_POLL_SEC = 0

export type MarketTab = 'top_pairs' | 'signals' | 'backtests'
export type AppTab = MarketTab | 'decisions' | 'backtest_v2' | 'forward' | 'hpo'

export type ExecutionForm = {
  price: string
  quantity: string
  side: string
  status: string
  note: string
}

type Params = {
  tab: AppTab
  compareValues: (left: unknown, right: unknown) => number
}

export const useMarketTables = ({ tab, compareValues }: Params) => {
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
    status: '',
    note: '',
  })
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
        fetchSignalsActiveApi(),
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
      const signalsOk = parseRows(
        'Сигналы',
        results[1] as PromiseSettledResult<GenericRow[]>,
        setSignals,
        mergeSignalMetrics,
      )
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
      const data = await fetchSignalHistoryApi(
        historyFrom || undefined,
        historyTo || undefined,
        500,
        tableStockFilter || undefined,
        tableFutureFilter || undefined,
        tableSignalFilter || undefined,
      )
      setSignalHistory(data)
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : 'Не удалось загрузить историю')
    } finally {
      setHistoryLoading(false)
    }
  }, [historyFrom, historyTo, tableFutureFilter, tableSignalFilter, tableStockFilter])

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

  const isEntrySignal = useCallback((row: GenericRow) => {
    return String(row.signal_action ?? '').toLowerCase() === 'enter'
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
      const directionValue =
        String(row.signal_direction ?? '').toLowerCase() === 'reverse'
          ? 'reverse'
          : 'cash_and_carry'
      void fetchPretradeCheck(pairKey, stock, future, directionValue, true)
    },
    [fetchPretradeCheck, isEntrySignal],
  )

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
      await executeSignalApi(payload)
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
      setDetailTab('overview')
      const stock = row.stock ? String(row.stock) : ''
      const future = row.future ? String(row.future) : ''
      if (stock && future && !spreadSeries[pairKey]) {
        void fetchSpreadSeries(pairKey, stock, future)
      }
      if (tab === 'signals' && stock && future && !executionLogs[pairKey]) {
        void fetchExecutionLog(pairKey, stock, future)
      }
      if (tab === 'signals' && stock && future && isEntrySignal(row) && !pretradeChecks[pairKey]) {
        const directionValue =
          String(row.signal_direction ?? '').toLowerCase() === 'reverse'
            ? 'reverse'
            : 'cash_and_carry'
        void fetchPretradeCheck(pairKey, stock, future, directionValue)
      }
    },
    [
      expandedRowKey,
      executionLogs,
      fetchExecutionLog,
      fetchPretradeCheck,
      fetchSpreadSeries,
      isEntrySignal,
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
        'entry_spread_pct_min',
        'entry_spread_pct_max',
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
  }, [compareValues, filteredTableRows, tableSortDirection, tableSortKey])

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

  const executionFields = useMemo(() => {
    if (tab !== 'signals') {
      return ['signal_action', 'signal_direction', 'signal_score', 'decision']
    }
    return [
      'signal_action',
      'signal_direction',
      'signal_score',
      'entry_price_tolerance_pct',
      'entry_stock_min',
      'entry_stock_max',
      'entry_future_min_per_share',
      'entry_future_max_per_share',
      'entry_spread_min',
      'entry_spread_max',
      'entry_spread_pct_min',
      'entry_spread_pct_max',
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
      'forecast_exit_days',
      'forecast_exit_date',
      'forecast_model',
      'forecast_tp_probability',
      'forecast_sl_probability',
      'signal_reasons',
      'signal_metrics',
    ]
  }, [tab])

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
        new Set(signalFilterRows.map((row) => row.signal_action).filter(Boolean).map(String)),
      ).sort(),
    [signalFilterRows],
  )

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
    sortedTableRows,
    stripDuplicates,
  }
}

export type MarketTablesState = ReturnType<typeof useMarketTables>
