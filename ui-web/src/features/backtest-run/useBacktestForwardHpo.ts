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
import { getObject } from '../../shared/utils/guards'
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
  const [hpoRequestJson, setHpoRequestJson] = useState('')
  const [hpoRequestJsonError, setHpoRequestJsonError] = useState<string | null>(
    null,
  )
  const [hpoSearchSpace, setHpoSearchSpace] = useState('')
  const [hpoResponse, setHpoResponse] = useState<HpoResponse | null>(null)
  const [hpoLoading, setHpoLoading] = useState(false)
  const [hpoError, setHpoError] = useState<string | null>(null)
  const [hpoRunId, setHpoRunId] = useState('')

  const normalizeHpoPayload = useCallback((raw: unknown) => {
    const obj = getObject<Record<string, unknown>>(raw)
    if (!obj) return null
    const hasTopLevel =
      'base' in obj || 'cv' in obj || 'optimization' in obj || 'search_space' in obj
    return hasTopLevel ? obj : { base: obj }
  }, [])

  const mergeDefaults = useCallback(
    (defaults: Record<string, unknown>, overrides: Record<string, unknown>) => {
      const result: Record<string, unknown> = { ...defaults }
      Object.entries(overrides).forEach(([key, value]) => {
        if (value === undefined) return
        const prev = result[key]
        const isPlainObject =
          value && typeof value === 'object' && !Array.isArray(value)
        const prevIsPlain =
          prev && typeof prev === 'object' && !Array.isArray(prev)
        if (isPlainObject && prevIsPlain) {
          result[key] = mergeDefaults(
            prev as Record<string, unknown>,
            value as Record<string, unknown>,
          )
        } else {
          result[key] = value
        }
      })
      return result
    },
    [],
  )

  const stripEmptyPayload = useCallback((value: unknown): unknown => {
    if (value === null || value === undefined) return undefined
    if (typeof value === 'string') {
      return value.trim().length ? value : undefined
    }
    if (Array.isArray(value)) {
      return value
    }
    if (typeof value === 'object') {
      const obj = value as Record<string, unknown>
      const next: Record<string, unknown> = {}
      Object.entries(obj).forEach(([key, inner]) => {
        const cleaned = stripEmptyPayload(inner)
        if (cleaned !== undefined) {
          next[key] = cleaned
        }
      })
      return Object.keys(next).length ? next : undefined
    }
    return value
  }, [])

  const parseSearchSpace = useCallback(() => {
    if (!hpoSearchSpace.trim()) return { searchSpace: {}, error: null }
    try {
      const parsed = JSON.parse(hpoSearchSpace)
      const searchSpace = getObject<Record<string, unknown>>(parsed)
      if (!searchSpace) {
        return { searchSpace: {}, error: 'Invalid search space JSON.' }
      }
      return { searchSpace, error: null }
    } catch {
      return { searchSpace: {}, error: 'Invalid search space JSON.' }
    }
  }, [hpoSearchSpace])

  const validateDateRange = useCallback((payload: Record<string, unknown>) => {
    const base = getObject<Record<string, unknown>>(payload.base)
    const test = base ? getObject<Record<string, unknown>>(base.test) : null
    const start = test?.start_date
    const end = test?.end_date
    if (!start || !end) {
      return 'Provide test.start_date and test.end_date in form or JSON request.'
    }
    return null
  }, [])

  const handleHpoRequestJsonChange = useCallback(
    (value: string) => {
      setHpoRequestJson(value)
      if (!value.trim()) {
        setHpoRequestJsonError(null)
        return
      }
      try {
        const parsed = JSON.parse(value)
        const normalized = normalizeHpoPayload(parsed)
        if (!normalized) {
          setHpoRequestJsonError('Invalid HPO request JSON.')
          return
        }
        setHpoRequestJsonError(null)
      } catch {
        setHpoRequestJsonError('Invalid HPO request JSON.')
      }
    },
    [normalizeHpoPayload],
  )

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
      const { searchSpace, error: searchSpaceError } = parseSearchSpace()
      if (searchSpaceError) {
        setHpoError(searchSpaceError)
        return
      }
      let requestPayload: Record<string, unknown> = {
        base: payload,
        search_space: searchSpace,
      }
      if (hpoRequestJson.trim()) {
        try {
          const parsed = JSON.parse(hpoRequestJson)
          const normalized = normalizeHpoPayload(parsed)
          if (!normalized) {
            setHpoError('Invalid HPO request JSON.')
            return
          }
          const stripped = stripEmptyPayload(payload)
          const defaults = getObject<Record<string, unknown>>(stripped) ?? {}
          requestPayload = mergeDefaults(
            {
              base: defaults,
              search_space: searchSpace,
            },
            normalized,
          )
        } catch {
          setHpoError('Invalid HPO request JSON.')
          return
        }
      }
      const dateError = validateDateRange(requestPayload)
      if (dateError) {
        setHpoError(dateError)
        return
      }
      const data = await runHpoApi(requestPayload)
      setHpoResponse(data)
      if (data?.run_id) {
        setHpoRunId(data.run_id)
      }
    } catch (err) {
      setHpoError(err instanceof Error ? err.message : 'Failed to start HPO')
    } finally {
      setHpoLoading(false)
    }
  }, [collectParamRequest, hpoRequestJson, normalizeHpoPayload, parseSearchSpace, paramSpecs, paramValues, stripEmptyPayload, mergeDefaults, validateDateRange])

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
  }, [hpoRunId, hpoResponse])

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
    hpoRequestJson,
    hpoRequestJsonError,
    hpoSearchSpace,
    hpoResponse,
    hpoLoading,
    hpoError,
    hpoRunId,
    setParamFilter,
    setParamPreset,
    setBacktestPrecompute,
    setForwardRunId,
    handleHpoRequestJsonChange,
    setHpoSearchSpace,
    fetchParamSpecs,
    handleParamValueChange,
    handleParamReset,
    handleBacktestRun,
    fetchForwardStatus,
    handleHpoRun,
  }
}
