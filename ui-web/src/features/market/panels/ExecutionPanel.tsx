import {
  Box,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import type { ReactNode } from 'react'
import type { ExecutionRow } from '../../../entities/decision/types'
import type { ExecutionForm } from '../useMarketTables'

const EXECUTION_SIDE_OPTIONS = [
  { value: '', label: 'Не выбрано' },
  { value: 'stock', label: 'Акция' },
  { value: 'future', label: 'Фьючерс' },
] as const

type Props = {
  title: string
  warning?: string
  executionForm: ExecutionForm
  onExecutionFormFieldChange: (field: keyof ExecutionForm, value: string) => void
  onExecute: () => void
  executionDisabled?: boolean
  executionError?: string
  executionLoading?: boolean
  executionLogs?: ExecutionRow[]
  renderFieldLabel: (column: string) => ReactNode
  formatDate: (value?: string) => string
  formatValue: (value: unknown, column?: string) => string
}

const ExecutionPanel = ({
  title,
  warning,
  executionForm,
  onExecutionFormFieldChange,
  onExecute,
  executionDisabled = false,
  executionError,
  executionLoading = false,
  executionLogs = [],
  renderFieldLabel,
  formatDate,
  formatValue,
}: Props) => (
  <Box sx={{ mt: 2 }}>
    <Typography variant="subtitle2" fontWeight={600}>
      {title}
    </Typography>
    {warning ? (
      <Typography variant="body2" color="warning.main" sx={{ mt: 0.5 }}>
        {warning}
      </Typography>
    ) : null}
    <Stack direction="row" spacing={2} flexWrap="wrap">
      <TextField
        label="Цена"
        size="small"
        value={executionForm.price}
        onChange={(event) => onExecutionFormFieldChange('price', event.target.value)}
        sx={{ minWidth: 140 }}
      />
      <TextField
        label="Кол-во"
        size="small"
        value={executionForm.quantity}
        onChange={(event) => onExecutionFormFieldChange('quantity', event.target.value)}
        sx={{ minWidth: 120 }}
      />
      <FormControl size="small" sx={{ minWidth: 160 }}>
        <InputLabel>Нога сделки</InputLabel>
        <Select
          label="Нога сделки"
          value={executionForm.side}
          onChange={(event) => onExecutionFormFieldChange('side', String(event.target.value))}
        >
          {EXECUTION_SIDE_OPTIONS.map((item) => (
            <MenuItem key={item.value || 'empty'} value={item.value}>
              {item.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <TextField
        label="Комментарий"
        size="small"
        value={executionForm.note}
        onChange={(event) => onExecutionFormFieldChange('note', event.target.value)}
        sx={{ minWidth: 240 }}
      />
      <Button variant="contained" onClick={onExecute} disabled={executionDisabled}>
        Исполнить
      </Button>
    </Stack>
    <Box sx={{ mt: 2 }}>
      <Typography variant="subtitle2" fontWeight={600}>
        История исполнений
      </Typography>
      {executionError ? (
        <Typography variant="body2" color="error">
          {executionError}
        </Typography>
      ) : null}
      {executionLoading ? (
        <Typography variant="body2" color="text.secondary">
          Загрузка исполнений...
        </Typography>
      ) : executionLogs.length ? (
        <Table size="small">
          <TableHead>
            <TableRow>
              {['timestamp', 'action', 'direction', 'price', 'quantity', 'side', 'note'].map((col) => (
                <TableCell key={col}>{renderFieldLabel(col)}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {executionLogs.map((entry, index) => (
              <TableRow key={`${entry.timestamp}-${index}`}>
                <TableCell>{formatDate(entry.timestamp)}</TableCell>
                <TableCell>{formatValue(entry.action, 'action')}</TableCell>
                <TableCell>{formatValue(entry.direction ?? '', 'direction')}</TableCell>
                <TableCell>{formatValue(entry.price, 'future_price')}</TableCell>
                <TableCell>{formatValue(entry.quantity, 'quantity')}</TableCell>
                <TableCell>{formatValue(entry.side ?? '', 'side')}</TableCell>
                <TableCell>{entry.note ?? ''}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <Typography variant="body2" color="text.secondary">
          Исполнений пока нет.
        </Typography>
      )}
    </Box>
  </Box>
)

export default ExecutionPanel
