export const formatDate = (value?: string): string => {
  if (!value) return 'вЂ”'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('ru-RU')
}

export const parseDateInput = (value: string, bound: 'start' | 'end') => {
  const trimmed = value.trim()
  if (!trimmed) return null
  if (!trimmed.includes('T') && !trimmed.includes(' ')) {
    const parts = trimmed.split('-').map((item) => Number(item))
    if (parts.length !== 3 || parts.some((item) => Number.isNaN(item))) return null
    const [year, month, day] = parts
    const date = new Date(
      year,
      month - 1,
      day,
      bound === 'end' ? 23 : 0,
      bound === 'end' ? 59 : 0,
      bound === 'end' ? 59 : 0,
      bound === 'end' ? 999 : 0,
    )
    return Number.isNaN(date.getTime()) ? null : date.getTime()
  }
  const parsed = new Date(trimmed)
  return Number.isNaN(parsed.getTime()) ? null : parsed.getTime()
}

export const formatDateInputValue = (value: Date) => value.toISOString().slice(0, 10)
