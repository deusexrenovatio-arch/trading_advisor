import { useCallback, useEffect, useState } from 'react'
import type { NewsEventV2 } from '../../entities/decision/types'
import { fetchNewsFeedV2 } from '../../shared/api/decisionApi'

export const SEVERITIES = ['', 'low', 'medium', 'high', 'critical']

export const useNewsIntelligence = () => {
  const [severity, setSeverity] = useState('')
  const [ticker, setTicker] = useState('')
  const [rows, setRows] = useState<NewsEventV2[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchNewsFeedV2({
        severity: severity || undefined,
        ticker: ticker || undefined,
        limit: 100,
      })
      setRows(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load news feed')
    } finally {
      setLoading(false)
    }
  }, [severity, ticker])

  useEffect(() => {
    void load()
  }, [load])

  return {
    severity,
    setSeverity,
    ticker,
    setTicker,
    rows,
    loading,
    error,
    load,
  }
}
