const normalizeIdempotencyPart = (
  value: string | number | null | undefined,
): string | null => {
  if (value === null || value === undefined) return null
  const normalized = String(value)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  if (!normalized) return null
  return normalized.slice(0, 24)
}

const randomIdempotencySuffix = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().replace(/-/g, '')
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
}

export const buildIdempotencyKey = (
  scope: string,
  parts: Array<string | number | null | undefined> = [],
) => {
  const normalizedScope = normalizeIdempotencyPart(scope) ?? 'req'
  const normalizedParts = parts
    .map((part) => normalizeIdempotencyPart(part))
    .filter((part): part is string => Boolean(part))
    .slice(0, 3)
  return [normalizedScope, ...normalizedParts, randomIdempotencySuffix()].join(':')
}
