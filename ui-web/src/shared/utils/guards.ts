export const getObject = <T,>(value: unknown): T | null => {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as T
  }
  return null
}

export const getArray = <T,>(value: unknown): T[] => {
  if (Array.isArray(value)) {
    return value as T[]
  }
  return []
}

export const getString = (value: unknown) => (typeof value === 'string' ? value : '')
