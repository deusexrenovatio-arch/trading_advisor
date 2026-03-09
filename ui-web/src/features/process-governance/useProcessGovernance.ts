import { startTransition, useCallback, useEffect, useMemo, useState } from 'react'
import { fetchProcessImprovementReport } from '../../shared/api/processApi'
import type { ProcessImprovementReport, WeeklyReport } from '../../entities/governance/types'

const DEFAULT_WEEKS = 8
const DEFAULT_WINDOW_SIZE = 20

export const useProcessGovernance = () => {
  const [weeks, setWeeks] = useState(DEFAULT_WEEKS)
  const [windowSize, setWindowSize] = useState(DEFAULT_WINDOW_SIZE)
  const [report, setReport] = useState<ProcessImprovementReport | null>(null)
  const [selectedWeekStart, setSelectedWeekStart] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextReport = await fetchProcessImprovementReport({
        weeks,
        windowSize,
      })
      setReport(nextReport)
      setSelectedWeekStart((current) => {
        if (current && nextReport.weekly_reports.some((item) => item.week_start === current)) {
          return current
        }
        return nextReport.weekly_reports[0]?.week_start ?? null
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить отчёт по говернансу процесса')
    } finally {
      setLoading(false)
    }
  }, [weeks, windowSize])

  useEffect(() => {
    void load()
  }, [load])

  const weeklyReports = useMemo(() => report?.weekly_reports ?? [], [report])
  const weeklyTrend = useMemo(() => report?.weekly_trend ?? [], [report])

  const selectedWeek = useMemo<WeeklyReport | null>(() => {
    if (!weeklyReports.length) return null
    return weeklyReports.find((item) => item.week_start === selectedWeekStart) ?? weeklyReports[0]
  }, [selectedWeekStart, weeklyReports])

  const selectWeek = useCallback((weekStart: string) => {
    startTransition(() => {
      setSelectedWeekStart(weekStart)
    })
  }, [])

  return {
    weeks,
    setWeeks,
    windowSize,
    setWindowSize,
    report,
    weeklyReports,
    weeklyTrend,
    selectedWeek,
    selectedWeekStart,
    selectWeek,
    loading,
    error,
    load,
  }
}
