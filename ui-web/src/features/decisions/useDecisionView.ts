import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  BasketAllocation,
  DecisionLog,
  DecisionView,
  ExecutionStatus,
  OperatorAction,
} from '../../entities/decision/types'
import {
  fetchDecisionAction as fetchDecisionActionApi,
  fetchDecisionLog as fetchDecisionLogApi,
  fetchDecisionView as fetchDecisionViewApi,
  submitDecisionAction as submitDecisionActionApi,
} from '../../shared/api/decisionApi'
import { getArray, getObject } from '../../shared/utils/guards'

export type DecisionActionState = {
  operator_action?: OperatorAction
  execution_status?: ExecutionStatus
}

const isNonEmptyString = (value: unknown): value is string =>
  typeof value === 'string' && value.length > 0

export const useDecisionView = () => {
  const [rows, setRows] = useState<DecisionView[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<DecisionLog | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [decisionAction, setDecisionAction] = useState<DecisionActionState | null>(null)
  const [decisionActionError, setDecisionActionError] = useState<string | null>(null)
  const [decisionActionLoading, setDecisionActionLoading] = useState(false)
  const [decisionActionSubmitting, setDecisionActionSubmitting] = useState(false)
  const [decisionActionNote, setDecisionActionNote] = useState('')
  const [quickFilter, setQuickFilter] = useState('')
  const [strategyFilter, setStrategyFilter] = useState('')
  const [instrumentFilter, setInstrumentFilter] = useState('')
  const [riskFilter, setRiskFilter] = useState('')
  const [newsFilter, setNewsFilter] = useState('')
  const [createdFrom, setCreatedFrom] = useState('')
  const [createdTo, setCreatedTo] = useState('')

  const fetchDecisionView = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchDecisionViewApi({
        limit: 500,
        strategy_type: strategyFilter || undefined,
        primary_instrument: instrumentFilter || undefined,
        risk_state: riskFilter || undefined,
        news_severity: newsFilter || undefined,
        created_from: createdFrom || undefined,
        created_to: createdTo || undefined,
      })
      setRows(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить данные')
    } finally {
      setLoading(false)
    }
  }, [createdFrom, createdTo, instrumentFilter, newsFilter, riskFilter, strategyFilter])

  const fetchDecisionLog = useCallback(async (decisionId: string) => {
    setDetail(null)
    setDetailError(null)
    try {
      const data = await fetchDecisionLogApi(decisionId)
      setDetail(data)
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : 'Не удалось загрузить лог решения')
    }
  }, [])

  const fetchDecisionAction = useCallback(async (decisionId: string) => {
    setDecisionAction(null)
    setDecisionActionError(null)
    setDecisionActionLoading(true)
    try {
      const data = await fetchDecisionActionApi(decisionId)
      setDecisionAction(data)
    } catch (err) {
      setDecisionActionError(
        err instanceof Error ? err.message : 'Не удалось загрузить действие решения',
      )
    } finally {
      setDecisionActionLoading(false)
    }
  }, [])

  const selectDecision = useCallback(
    (decisionId: string) => {
      setSelectedId(decisionId)
      void fetchDecisionLog(decisionId)
      void fetchDecisionAction(decisionId)
    },
    [fetchDecisionAction, fetchDecisionLog],
  )

  const submitDecisionAction = useCallback(
    async (action: 'approve' | 'reject') => {
      if (!selectedId) return
      setDecisionActionSubmitting(true)
      setDecisionActionError(null)
      try {
        const data = await submitDecisionActionApi(selectedId, {
          action,
          note: decisionActionNote || undefined,
        })
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
        setDecisionActionError(err instanceof Error ? err.message : 'Не удалось отправить действие')
      } finally {
        setDecisionActionSubmitting(false)
      }
    },
    [decisionActionNote, selectedId],
  )

  const filteredRows = useMemo(() => {
    const quick = quickFilter.trim().toLowerCase()
    if (!quick) return rows
    return rows.filter((row) => JSON.stringify(row).toLowerCase().includes(quick))
  }, [rows, quickFilter])

  const strategyOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.strategy_type).filter(isNonEmptyString))).sort(),
    [rows],
  )
  const instrumentOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.primary_instrument).filter(isNonEmptyString))).sort(),
    [rows],
  )
  const riskOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.risk_state).filter(isNonEmptyString))).sort(),
    [rows],
  )
  const newsOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.news_severity).filter(isNonEmptyString))).sort(),
    [rows],
  )

  const selectedDecision = useMemo(
    () => rows.find((row) => row.decision_id === selectedId) ?? null,
    [rows, selectedId],
  )

  const detailRecord = (detail as Record<string, unknown> | null) ?? null
  const detailDecision = detailRecord
    ? getObject<Record<string, unknown>>(detailRecord['decision'])
    : null
  const detailAggregation = detailRecord
    ? getObject<Record<string, unknown>>(detailRecord['aggregation'])
    : null
  const detailProposal = detailRecord
    ? getObject<Record<string, unknown>>(detailRecord['proposal'])
    : null
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

  useEffect(() => {
    void fetchDecisionView()
  }, [fetchDecisionView])

  useEffect(() => {
    setDecisionActionNote('')
  }, [selectedId])

  return {
    rows,
    loading,
    error,
    fetchDecisionView,
    selectedId,
    selectDecision,
    detail,
    detailError,
    decisionAction,
    decisionActionLoading,
    decisionActionError,
    decisionActionSubmitting,
    decisionActionNote,
    setDecisionActionNote,
    quickFilter,
    setQuickFilter,
    strategyFilter,
    setStrategyFilter,
    instrumentFilter,
    setInstrumentFilter,
    riskFilter,
    setRiskFilter,
    newsFilter,
    setNewsFilter,
    createdFrom,
    setCreatedFrom,
    createdTo,
    setCreatedTo,
    filteredRows,
    strategyOptions,
    instrumentOptions,
    riskOptions,
    newsOptions,
    selectedDecision,
    detailDecision,
    detailAggregation,
    detailProposal,
    detailFacts,
    basketRows,
    operatorAction,
    executionStatus,
    submitDecisionAction,
  }
}
