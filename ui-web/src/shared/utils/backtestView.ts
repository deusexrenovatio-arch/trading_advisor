import type { GenericRow, HpoResponse, HpoTrial, ParameterSpec } from '../../entities/decision/types'
import { getParamLabel, paramSectionOrder } from './params'
import { getTableColumns } from './tables'

export const filterParamSpecs = (specs: ParameterSpec[], query: string) => {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return specs
  return specs.filter((spec) => {
    const label = getParamLabel(spec).toLowerCase()
    return spec.key.toLowerCase().includes(normalized) || label.includes(normalized)
  })
}

export const buildParamSections = (
  specs: ParameterSpec[],
  order: string[] = paramSectionOrder,
): [string, ParameterSpec[]][] => {
  const grouped = new Map<string, ParameterSpec[]>()
  specs.forEach((spec) => {
    const section = spec.key.split('.')[0] || 'general'
    const list = grouped.get(section) ?? []
    list.push(spec)
    grouped.set(section, list)
  })
  const orderIndex = new Map(order.map((section, index) => [section, index]))
  const sections = Array.from(grouped.entries()).map(
    ([section, sectionSpecs]): [string, ParameterSpec[]] => [
      section,
      sectionSpecs.sort((left, right) => left.key.localeCompare(right.key)),
    ],
  )
  return sections.sort(([left], [right]) => {
    const leftRank = orderIndex.get(left) ?? Number.MAX_SAFE_INTEGER
    const rightRank = orderIndex.get(right) ?? Number.MAX_SAFE_INTEGER
    if (leftRank !== rightRank) return leftRank - rightRank
    return left.localeCompare(right)
  })
}

export const buildBacktestEquityColumns = (rows: GenericRow[]) => {
  const columns = getTableColumns(rows)
  const preferred = ['date', 'equity', 'cash', 'drawdown', 'turnover', 'positions']
  const ordered = preferred.filter((column) => columns.includes(column))
  const rest = columns.filter((column) => !preferred.includes(column))
  return [...ordered, ...rest]
}

export const buildBacktestTradeColumns = (rows: GenericRow[]) => {
  const columns = getTableColumns(rows)
  const preferred = [
    'pair_id',
    'stock_secid',
    'future_secid',
    'direction',
    'entry_date',
    'exit_date',
    'entry_price_stock',
    'entry_price_fut',
    'exit_price_stock',
    'exit_price_fut',
    'quantity_stock',
    'quantity_fut',
    'pnl',
    'hold_days',
    'exit_reason',
  ]
  const ordered = preferred.filter((column) => columns.includes(column))
  const rest = columns.filter((column) => !preferred.includes(column))
  return [...ordered, ...rest]
}

export const buildHpoLeaderboardRows = (response: HpoResponse | null): HpoTrial[] => {
  if (!response) return []
  const payload = response.result ?? response
  const raw = payload.leaderboard ?? payload.trials ?? []
  if (!Array.isArray(raw)) return []
  const mode = payload.mode ?? 'max'
  const rows = raw.slice() as HpoTrial[]
  if (rows.length && typeof rows[0]?.objective === 'number') {
    rows.sort((left, right) => {
      const leftValue = left.objective ?? Number.NEGATIVE_INFINITY
      const rightValue = right.objective ?? Number.NEGATIVE_INFINITY
      return mode === 'min' ? leftValue - rightValue : rightValue - leftValue
    })
  }
  return rows
}

export const buildHpoLeaderboardColumns = (rows: HpoTrial[]) => {
  const columns = getTableColumns(rows as GenericRow[])
  const preferred = ['objective', 'params', 'fold_objectives']
  const ordered = preferred.filter((column) => columns.includes(column))
  const rest = columns.filter((column) => !preferred.includes(column))
  return [...ordered, ...rest]
}
