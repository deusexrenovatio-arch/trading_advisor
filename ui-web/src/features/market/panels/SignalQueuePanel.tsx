import { Chip, Paper, Stack, Typography } from '@mui/material'
import type { GenericRow } from '../../../entities/decision/types'

type Props = {
  openSignalRows: GenericRow[]
  formatValue: (value: unknown, column?: string) => string
}

const SignalQueuePanel = ({ openSignalRows, formatValue }: Props) => {
  if (!openSignalRows.length) return null

  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="subtitle2" fontWeight={600}>
        Открытые позиции ({openSignalRows.length})
      </Typography>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
        {openSignalRows.map((row) => {
          const stock = row.stock ? String(row.stock) : ''
          const future = row.future ? String(row.future) : ''
          const pairLabel = stock && future ? `${stock}/${future}` : 'Пара'
          const action = String(
            row.signal_action_effective ?? row.signal_action ?? 'hold_open',
          ).toLowerCase()
          return (
            <Chip
              key={`${stock}-${future}-${String(row.timestamp ?? '')}`}
              color="warning"
              variant="outlined"
              label={`${pairLabel}: ${formatValue(action, 'signal_action_effective')}`}
            />
          )
        })}
      </Stack>
    </Paper>
  )
}

export default SignalQueuePanel
