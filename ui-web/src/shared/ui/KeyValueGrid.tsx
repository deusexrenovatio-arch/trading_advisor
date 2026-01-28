import { Box, Typography } from '@mui/material'
import type { ReactNode } from 'react'

export type KeyValueEntry = { key: string; value: unknown }

type Props = {
  entries?: KeyValueEntry[]
  payload?: Record<string, unknown>
  emptyLabel?: string
  renderLabel: (key: string) => ReactNode
  renderValue: (value: unknown, key?: string) => ReactNode
  minColumnWidth?: number
}

const KeyValueGrid = ({
  entries,
  payload,
  emptyLabel = 'Нет данных',
  renderLabel,
  renderValue,
  minColumnWidth = 160,
}: Props) => {
  const resolvedEntries =
    entries ?? Object.entries(payload ?? {}).map(([key, value]) => ({ key, value }))

  if (!resolvedEntries.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        {emptyLabel}
      </Typography>
    )
  }

  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: `repeat(auto-fit, minmax(${minColumnWidth}px, 1fr))`,
        gap: 1,
        mt: 1,
      }}
    >
      {resolvedEntries.map((entry) => (
        <Box key={entry.key}>
          <Typography variant="caption" color="text.secondary">
            {renderLabel(entry.key)}
          </Typography>
          <Typography variant="body2">{renderValue(entry.value, entry.key)}</Typography>
        </Box>
      ))}
    </Box>
  )
}

export default KeyValueGrid
