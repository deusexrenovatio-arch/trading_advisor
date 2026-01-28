export const formatNumber = (value?: number, digits = 2): string => {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return ''
  }
  return Number(value).toFixed(digits)
}

export const humanizeKey = (value: string) =>
  value.replaceAll('_', ' ').replace(/\b\w/g, (match) => match.toUpperCase())
