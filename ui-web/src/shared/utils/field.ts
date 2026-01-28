import { fieldMeta } from '../metadata/fieldMeta'
import { valueLabels } from '../metadata/valueLabels'
import { humanizeKey } from './format'

export const getFieldLabel = (key: string) => fieldMeta[key]?.label ?? humanizeKey(key)
export const getFieldTooltip = (key: string) => fieldMeta[key]?.tooltip ?? ''

export const getValueLabel = (column: string | undefined, value: string) => {
  if (!column) return null
  const map = valueLabels[column]
  return map?.[value] ?? null
}

export const toTitleCase = (value: string) => getFieldLabel(value)
