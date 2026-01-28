import { useCallback, useEffect, useState } from 'react'
import type {
  BacktestReport,
  ForwardStatus,
  HpoResponse,
  ParameterSpec,
  ParamValue,
} from '../../entities/decision/types'
import {
  fetchForwardStatus as fetchForwardStatusApi,
  fetchHpoStatus as fetchHpoStatusApi,
  fetchParamSpecs as fetchParamSpecsApi,
  runBacktest as runBacktestApi,
  runHpo as runHpoApi,
} from '../../shared/api/decisionApi'
import type { AppTab } from '../market/useMarketTables'

type ParamRequestBuilder = (
  specs: ParameterSpec[],
  values: Record<string, ParamValue>,
) => {
  payload: Record<string, unknown>
  errors: string[]
}

type Params = {
  tab: AppTab
  buildParamDefaults: (specs: ParameterSpec[]) => Record<string, ParamValue>
  collectParamRequest: ParamRequestBuilder
}

export const useBacktestForwardHpo = ({
  tab,
  buildParamDefaults,
  collectParamRequest,
}: Params) => {
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
  const [hpoRunId, setHpoRunId] = useState('')

  const fetchParamSpecs = useCallback(
    async (options?: { resetValues?: boolean }) => {
      setParamSpecsLoading(true)
      setParamSpecsError(null)
      const resetValues = options?.resetValues ?? false
      try {
        const preset = paramPreset.trim()
        const data = await fetchParamSpecsApi(preset || undefined)
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
        setParamSpecsError(err instanceof Error ? err.message : 'Не удалось загрузить параметры')
      } finally {
        setParamSpecsLoading(false)
      }
    },
    [buildParamDefaults, paramPreset],
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
      const data = await runBacktestApi({ request: payload, precompute: backtestPrecompute })
      setBacktestRunReport(data)
    } catch (err) {
      setBacktestRunError(err instanceof Error ? err.message : 'Не удалось запустить бэктест')
    } finally {
      setBacktestRunLoading(false)
    }
  }, [backtestPrecompute, collectParamRequest, paramSpecs, paramValues])

  const fetchForwardStatus = useCallback(async () => {
    setForwardLoading(true)
    setForwardError(null)
    try {
      const runId = forwardRunId.trim()
      const data = await fetchForwardStatusApi(runId || undefined)
      setForwardStatus(data)
    } catch (err) {
      setForwardError(err instanceof Error ? err.message : 'Не удалось загрузить статус форварда')
    } finally {
      setForwardLoading(false)
    }
  }, [forwardRunId])

  const handleHpoRun = useCallback(async () => {
    setHpoLoading(true)
    setHpoError(null)
    setHpoResponse(null)
    setHpoRunId('')
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
          setHpoError('Неверный JSON пространства поиска.')
          return
        }
      }
      const data = await runHpoApi({ base: payload, search_space: searchSpace })
      setHpoResponse(data)
      if (data?.run_id) {
        setHpoRunId(data.run_id)
      }
    } catch (err) {
      setHpoError(err instanceof Error ? err.message : 'Не удалось запустить HPO')
    } finally {
      setHpoLoading(false)
    }
  }, [collectParamRequest, hpoSearchSpace, paramSpecs, paramValues])

  const handleParamValueChange = useCallback((key: string, value: ParamValue) => {
    setParamValues((prev) => ({ ...prev, [key]: value }))
  }, [])

  const handleParamReset = useCallback(() => {
    if (!paramSpecs.length) return
    setParamValues(buildParamDefaults(paramSpecs))
  }, [buildParamDefaults, paramSpecs])

  useEffect(() => {
    if (tab !== 'backtest_v2' && tab !== 'hpo') return
    if (paramSpecsLoading || paramSpecs.length > 0) return
    void fetchParamSpecs({ resetValues: true })
  }, [fetchParamSpecs, paramSpecs.length, paramSpecsLoading, tab])

  useEffect(() => {
    if (!hpoRunId) return undefined
    if (!hpoResponse || hpoResponse.status !== 'running') return undefined
    let cancelled = false
    const interval = window.setInterval(async () => {
      try {
        const data = await fetchHpoStatusApi(hpoRunId)
        if (!cancelled) {
          setHpoResponse(data)
          if (data?.status && data.status !== 'running') {
            setHpoRunId('')
          }
        }
      } catch (err) {
        if (!cancelled) {
          setHpoError(
            err instanceof Error ? err.message : 'РќРµ СѓРґР°Р»РѕСЃСЊ РїСЂРѕРІРµСЂРёС‚СЊ СЃС‚Р°С‚СѓСЃ HPO',
          )
        }
      }
    }, 5000)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [hpoRunId, hpoResponse, fetchHpoStatusApi])

  return {
    paramSpecs,
    paramValues,
    paramFilter,
    paramPreset,
    paramSpecsLoading,
    paramSpecsError,
    backtestPrecompute,
    backtestRunReport,
    backtestRunLoading,
    backtestRunError,
    backtestRunParseError,
    forwardRunId,
    forwardStatus,
    forwardLoading,
    forwardError,
    hpoSearchSpace,
    hpoResponse,
    hpoLoading,
    hpoError,
    hpoRunId,
    setParamFilter,
    setParamPreset,
    setBacktestPrecompute,
    setForwardRunId,
    setHpoSearchSpace,
    fetchParamSpecs,
    handleParamValueChange,
    handleParamReset,
    handleBacktestRun,
    fetchForwardStatus,
    handleHpoRun,
  }
}
