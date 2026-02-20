import type { ParameterSpec, ParamPrimitive, ParamValue } from '../../entities/decision/types'
import { paramMeta, paramSectionOrder, valueTypeLabels } from '../metadata/paramMeta'
import { valueLabels } from '../metadata/valueLabels'
import { formatNumber, humanizeKey } from './format'
import { getObject } from './guards'
import { getFieldLabel, getFieldTooltip } from './field'

export { paramSectionOrder, valueTypeLabels }

export const normalizeParamKey = (value: string) =>
  value.replace(/[A-Z]/g, (match) => match.toLowerCase())

const getParamLeaf = (key: string) => {
  const parts = key.split('.')
  return parts[parts.length - 1] || key
}

export const getParamLabel = (spec: ParameterSpec) => {
  const meta = paramMeta[spec.key] ?? paramMeta[normalizeParamKey(spec.key)]
  if (meta?.label) return meta.label
  const leaf = getParamLeaf(spec.key)
  const normalized = normalizeParamKey(leaf)
  return (
    getFieldLabel(leaf) ||
    getFieldLabel(normalized) ||
    humanizeKey(normalized)
  )
}

export const getParamTooltip = (spec: ParameterSpec) => {
  const meta = paramMeta[spec.key] ?? paramMeta[normalizeParamKey(spec.key)]
  if (meta?.tooltip) return meta.tooltip
  const leaf = getParamLeaf(spec.key)
  const normalized = normalizeParamKey(leaf)
  return getFieldTooltip(leaf) || getFieldTooltip(normalized) || spec.description || ''
}

export const getParamOptionLabel = (spec: ParameterSpec, option: unknown) => {
  const raw = String(option)
  const leaf = getParamLeaf(spec.key)
  const normalized = normalizeParamKey(leaf)
  const metaLabels =
    paramMeta[spec.key]?.valueLabels ??
    paramMeta[normalizeParamKey(spec.key)]?.valueLabels ??
    valueLabels[spec.key] ??
    valueLabels[leaf] ??
    valueLabels[normalized]
  return metaLabels?.[raw] ?? raw
}

const shortenText = (value: string, limit = 120) =>
  value.length > limit ? `${value.slice(0, limit)}...` : value

export const compactJson = (value: unknown): string => {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

export const formatParamDefault = (spec: ParameterSpec) => {
  if (spec.default === undefined) return ''
  if (spec.default === null) return '—'
  if (spec.value_type === 'bool') {
    return spec.default ? 'Да' : 'Нет'
  }
  if (spec.value_type === 'dict') {
    let raw: Record<string, unknown> | null
    if (typeof spec.default === 'string') {
      try {
        raw = getObject<Record<string, unknown>>(JSON.parse(spec.default))
      } catch {
        raw = null
      }
    } else {
      raw = getObject<Record<string, unknown>>(spec.default)
    }
    if (!raw) return '—'
    const meta = paramMeta[spec.key] ?? paramMeta[normalizeParamKey(spec.key)]
    const labels = meta?.valueLabels
    const entries = Object.entries(raw)
    if (!entries.length) return '—'
    return entries
      .map(([key, value]) => {
        if (value === undefined) return null
        const label = labels?.[key] ?? humanizeKey(key)
        if (typeof value === 'number') {
          const digits = Number.isInteger(value) ? 0 : 3
          return `${label}: ${formatNumber(value, digits)}`
        }
        return `${label}: ${String(value)}`
      })
      .filter(Boolean)
      .join(', ')
  }
  if (Array.isArray(spec.default)) {
    return spec.default.map((item) => String(item)).join(', ')
  }
  return shortenText(compactJson(spec.default))
}

export const buildParamHelperText = (spec: ParameterSpec) => {
  const parts: string[] = []
  const typeLabel = valueTypeLabels[spec.value_type] ?? spec.value_type
  if (typeLabel) parts.push(`Тип: ${typeLabel}`)
  if (spec.min_value !== null && spec.min_value !== undefined) {
    parts.push(`Мин: ${spec.min_value}`)
  }
  if (spec.max_value !== null && spec.max_value !== undefined) {
    parts.push(`Макс: ${spec.max_value}`)
  }
  const defaultLabel = formatParamDefault(spec)
  if (defaultLabel) parts.push(`По умолчанию: ${defaultLabel}`)
  return parts.filter(Boolean).join(' | ')
}

export const isJsonValueType = (valueType: string) =>
  ['list', 'dict', 'tuple', 'set'].includes(valueType)

export const parseParamDictValue = (raw: ParamValue | undefined): Record<string, unknown> => {
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    return raw as Record<string, unknown>
  }
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      return {}
    }
  }
  return {}
}

const normalizeDictPayload = (payload: Record<string, unknown>) => {
  const next: Record<string, unknown> = {}
  Object.entries(payload).forEach(([key, value]) => {
    if (value === undefined) return
    if (value === null) {
      next[key] = null
      return
    }
    if (typeof value === 'string') {
      const trimmed = value.trim()
      if (!trimmed) {
        next[key] = null
        return
      }
      const numeric = Number(trimmed.replace(',', '.'))
      next[key] = Number.isNaN(numeric) ? trimmed : numeric
      return
    }
    next[key] = value
  })
  return next
}

export const getParamDictEntries = (spec: ParameterSpec, raw: Record<string, unknown>) => {
  const meta = paramMeta[spec.key] ?? paramMeta[normalizeParamKey(spec.key)]
  const labels = meta?.valueLabels
  const keys = new Set<string>([
    ...Object.keys(raw ?? {}),
    ...Object.keys(labels ?? {}),
  ])
  const ordered = Array.from(keys)
  if (meta?.order?.length) {
    const orderIndex = new Map(meta.order.map((key, index) => [key, index]))
    ordered.sort((left, right) => {
      const leftRank = orderIndex.get(left) ?? Number.MAX_SAFE_INTEGER
      const rightRank = orderIndex.get(right) ?? Number.MAX_SAFE_INTEGER
      if (leftRank !== rightRank) return leftRank - rightRank
      return left.localeCompare(right)
    })
  } else {
    ordered.sort((left, right) => left.localeCompare(right))
  }
  return ordered.map((key) => ({
    key,
    label: labels?.[key] ?? getFieldLabel(key),
    value: raw?.[key],
  }))
}

const normalizeParamDefault = (spec: ParameterSpec): ParamValue => {
  if (spec.value_type === 'bool') {
    return Boolean(spec.default)
  }
  if (spec.default === null || spec.default === undefined) {
    return ''
  }
  if (spec.value_type === 'dict') {
    if (typeof spec.default === 'string') {
      try {
        const parsed = JSON.parse(spec.default)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          return parsed as Record<string, ParamPrimitive | unknown>
        }
      } catch {
        return ''
      }
    }
    if (typeof spec.default === 'object' && !Array.isArray(spec.default)) {
      return spec.default as Record<string, ParamPrimitive | unknown>
    }
    return ''
  }
  if (isJsonValueType(spec.value_type) || typeof spec.default === 'object') {
    return compactJson(spec.default)
  }
  return String(spec.default)
}

export const buildParamDefaults = (specs: ParameterSpec[]): Record<string, ParamValue> => {
  const next: Record<string, ParamValue> = {}
  specs.forEach((spec) => {
    next[spec.key] = normalizeParamDefault(spec)
  })
  return next
}

const setNestedValue = (target: Record<string, unknown>, path: string, value: unknown) => {
  const parts = path.split('.')
  let cursor: Record<string, unknown> = target
  parts.forEach((part, index) => {
    if (index === parts.length - 1) {
      cursor[part] = value
      return
    }
    const existing = cursor[part]
    if (!existing || typeof existing !== 'object' || Array.isArray(existing)) {
      cursor[part] = {}
    }
    cursor = cursor[part] as Record<string, unknown>
  })
}

export const parseParamValue = (raw: ParamValue | undefined, spec: ParameterSpec) => {
  const empty =
    raw === undefined ||
    raw === null ||
    (typeof raw === 'string' && raw.trim().length === 0)
  if (empty) {
    return { value: spec.default ?? null }
  }
  const valueType = spec.value_type
  const label = getParamLabel(spec)
  if (valueType === 'bool') {
    if (typeof raw === 'boolean') {
      return { value: raw }
    }
    const normalized = String(raw).toLowerCase()
    if (normalized === 'true' || normalized === 'false') {
      return { value: normalized === 'true' }
    }
    return { value: null, error: `${label}: неверное значение (да/нет)` }
  }
  if (valueType === 'int') {
    const parsed = Number.parseInt(String(raw), 10)
    if (Number.isNaN(parsed)) {
      return { value: null, error: `${label}: неверное целое` }
    }
    return { value: parsed }
  }
  if (valueType === 'float') {
    const parsed = Number.parseFloat(String(raw))
    if (Number.isNaN(parsed)) {
      return { value: null, error: `${label}: неверное число` }
    }
    return { value: parsed }
  }
  if (valueType === 'str') {
    return { value: String(raw) }
  }
  if (valueType === 'dict') {
    if (typeof raw === 'string') {
      try {
        const parsed = JSON.parse(raw)
        const payload = getObject<Record<string, unknown>>(parsed)
        if (!payload) {
          return { value: null, error: `${label}: неверный JSON` }
        }
        return { value: normalizeDictPayload(payload) }
      } catch {
        return { value: null, error: `${label}: неверный JSON` }
      }
    }
    const payload = getObject<Record<string, unknown>>(raw) ?? {}
    return { value: normalizeDictPayload(payload) }
  }
  if (isJsonValueType(valueType) || valueType === 'union') {
    if (typeof raw !== 'string') {
      return { value: raw }
    }
    try {
      return { value: JSON.parse(raw) }
    } catch {
      return { value: null, error: `${label}: неверный JSON` }
    }
  }
  if (typeof raw === 'string') {
    const trimmed = raw.trim()
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try {
        return { value: JSON.parse(trimmed) }
      } catch {
        return { value: null, error: `${label}: неверный JSON` }
      }
    }
  }
  return { value: raw }
}

export const collectParamRequest = (
  specs: ParameterSpec[],
  values: Record<string, ParamValue>,
) => {
  const payload: Record<string, unknown> = {}
  const errors: string[] = []
  specs.forEach((spec) => {
    const parsed = parseParamValue(values[spec.key], spec)
    if (parsed.error) {
      errors.push(parsed.error)
      return
    }
    setNestedValue(payload, spec.key, parsed.value)
  })
  return { payload, errors }
}
