import { useCallback, useEffect, useMemo, useState } from 'react'
import type { RebalancePreviewV2 } from '../../entities/decision/types'
import { commitRebalanceV2, fetchRebalancePreviewV2 } from '../../shared/api/decisionApi'

export const usePortfolioControl = () => {
  const [preview, setPreview] = useState<RebalancePreviewV2 | null>(null)
  const [limit, setLimit] = useState('12')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [commitStatus, setCommitStatus] = useState<string | null>(null)

  const loadPreview = useCallback(async () => {
    setLoading(true)
    setError(null)
    setCommitStatus(null)
    try {
      const parsedLimit = Number(limit)
      const normalizedLimit = Number.isFinite(parsedLimit) && parsedLimit > 0 ? parsedLimit : 12
      const data = await fetchRebalancePreviewV2(normalizedLimit)
      setPreview(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить предпросмотр ребаланса')
    } finally {
      setLoading(false)
    }
  }, [limit])

  const handleCommit = useCallback(async () => {
    if (!preview) return
    setLoading(true)
    setError(null)
    setCommitStatus(null)
    try {
      const response = await commitRebalanceV2({
        rebalance_plan_id: preview.rebalance_plan_id,
        actor_id: 'ui-operator',
        positions: preview.positions as Array<Record<string, unknown>>,
      })
      setCommitStatus(`Ребаланс применён: ${response.positions_committed} позиций (commit ${response.commit_id})`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось применить план ребаланса')
    } finally {
      setLoading(false)
    }
  }, [preview])

  useEffect(() => {
    void loadPreview()
  }, [loadPreview])

  const riskRows = useMemo(() => preview?.risk_checks ?? [], [preview])

  return {
    preview,
    limit,
    setLimit,
    loading,
    error,
    commitStatus,
    loadPreview,
    handleCommit,
    riskRows,
  }
}
