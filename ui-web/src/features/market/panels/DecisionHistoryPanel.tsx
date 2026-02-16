import { Paper, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material'
import type { ReactNode } from 'react'
import type { SignalHistoryRow } from '../../../entities/decision/types'

type Props = {
  rows: SignalHistoryRow[]
  renderFieldLabel: (column: string) => ReactNode
  formatDate: (value?: string) => string
  formatValue: (value: unknown, column?: string) => string
}

const DecisionHistoryPanel = ({ rows, renderFieldLabel, formatDate, formatValue }: Props) => (
  <Paper sx={{ p: 2 }}>
    <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
      История сигналов
    </Typography>
    <Table size="small" stickyHeader>
      <TableHead>
        <TableRow>
          {['timestamp', 'stock', 'future', 'signal_action', 'signal_direction', 'signal_score'].map(
            (column) => (
              <TableCell key={column}>{renderFieldLabel(column)}</TableCell>
            ),
          )}
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map((row, index) => (
          <TableRow
            key={`${row.run_id}-${row.timestamp}-${row.stock}-${row.future}-${row.signal_action ?? ''}-${index}`}
          >
            <TableCell>{formatDate(row.timestamp)}</TableCell>
            <TableCell>{row.stock}</TableCell>
            <TableCell>{row.future}</TableCell>
            <TableCell>{formatValue(row.signal_action, 'signal_action')}</TableCell>
            <TableCell>{formatValue(row.signal_direction ?? '', 'signal_direction')}</TableCell>
            <TableCell>{formatValue(row.signal_score, 'signal_score')}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
    {!rows.length ? (
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
        Нет строк истории по текущему фильтру.
      </Typography>
    ) : null}
  </Paper>
)

export default DecisionHistoryPanel
