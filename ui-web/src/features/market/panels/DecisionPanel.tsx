import { Box, Chip, Stack, Typography } from '@mui/material'
import type { ReactNode } from 'react'
import KeyValueGrid from '../../../shared/ui/KeyValueGrid'

type Entry = {
  key: string
  value: unknown
}

const PRETRADE_GATE_CHIPS = [
  { key: 'quote_pass', label: 'Котировки' },
  { key: 'stock_price_pass', label: 'Акция' },
  { key: 'fut_price_pass', label: 'Фьючерс' },
  { key: 'spread_pass', label: 'Спред' },
  { key: 'sync_pass', label: 'Синхронность' },
  { key: 'stock_volume_pass', label: 'Объём акции' },
  { key: 'fut_volume_pass', label: 'Объём фьючерса' },
] as const

const gateChipColor = (value: unknown): 'success' | 'error' | 'default' => {
  if (value === true) return 'success'
  if (value === false) return 'error'
  return 'default'
}

const gateChipStatus = (value: unknown) => {
  if (value === true) return 'OK'
  if (value === false) return 'FAIL'
  return 'N/A'
}

type Props = {
  title: string
  effectiveSignalEntries: Entry[]
  isOpenPosition: boolean
  isEntrySignal: boolean
  primaryGateEntries: Entry[]
  pretradeGateMap: Map<string, unknown>
  renderFieldLabel: (column: string) => ReactNode
  formatCellValue: (value: unknown, column?: string) => string
  formatDate: (value?: string) => string
}

const DecisionPanel = ({
  title,
  effectiveSignalEntries,
  isOpenPosition,
  isEntrySignal,
  primaryGateEntries,
  pretradeGateMap,
  renderFieldLabel,
  formatCellValue,
  formatDate,
}: Props) => (
  <Box>
    <Typography variant="subtitle2" fontWeight={600}>
      {title}
    </Typography>
    <KeyValueGrid
      entries={effectiveSignalEntries}
      renderLabel={renderFieldLabel}
      renderValue={(value, key) =>
        key === 'pretrade_checked_at'
          ? formatDate(typeof value === 'string' ? value : undefined)
          : formatCellValue(value, key)
      }
    />
    {isOpenPosition ? (
      <Chip size="small" color="warning" variant="outlined" label="Позиция открыта" sx={{ mt: 1 }} />
    ) : null}
    {isEntrySignal ? (
      primaryGateEntries.length ? (
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
          {PRETRADE_GATE_CHIPS.map((chip) => (
            <Chip
              key={chip.key}
              size="small"
              variant="outlined"
              color={gateChipColor(pretradeGateMap.get(chip.key))}
              label={`${chip.label}: ${gateChipStatus(pretradeGateMap.get(chip.key))}`}
            />
          ))}
        </Stack>
      ) : (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Выполните pre-trade проверку, чтобы подтвердить исполнимость входа.
        </Typography>
      )
    ) : null}
  </Box>
)

export default DecisionPanel
