import type { GenericRow } from '../../entities/decision/types'

export const getTableColumns = (rows: GenericRow[]): string[] => {
  if (!rows.length) return []
  return Object.keys(rows[0]).filter((key) => key !== 'id')
}

export const isDateColumn = (column: string) =>
  column === 'date' ||
  column.endsWith('_date') ||
  column.endsWith('_at') ||
  column.includes('timestamp')
