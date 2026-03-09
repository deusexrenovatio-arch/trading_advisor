import { requestJson } from './http'
import type { ProcessImprovementReport } from '../../entities/governance/types'

export const fetchProcessImprovementReport = (options: {
  weeks?: number
  windowSize?: number
}) => {
  const params = new URLSearchParams()
  if (options.weeks) params.set('weeks', String(options.weeks))
  if (options.windowSize) params.set('window_size', String(options.windowSize))
  const query = params.toString()
  const url = query ? `/api/v2/ops/process-improvement?${query}` : '/api/v2/ops/process-improvement'
  return requestJson<ProcessImprovementReport>(url, { cache: 'no-store' })
}
