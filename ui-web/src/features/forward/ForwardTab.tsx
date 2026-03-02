import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Button,
  Chip,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import type { ReactNode } from 'react'
import type { ForwardStatus } from '../../entities/decision/types'
import JsonBlock from '../../shared/ui/JsonBlock'
import KeyValueGrid from '../../shared/ui/KeyValueGrid'

type Props = {
  forwardRunId: string
  onForwardRunIdChange: (value: string) => void
  forwardRequestJson: string
  onForwardRequestJsonChange: (value: string) => void
  onStartForwardRun: () => void
  onFetchForwardStatus: () => void
  forwardLoading: boolean
  forwardStartLoading: boolean
  forwardError?: string | null
  forwardRequestJsonError?: string | null
  forwardStartError?: string | null
  forwardStartMessage?: string | null
  forwardStatus: ForwardStatus | null
  formatValue: (value: unknown, column?: string) => string
  renderFieldLabel: (key: string) => ReactNode
  formatCellValue: (value: unknown, column?: string) => string
}

const ForwardTab = ({
  forwardRunId,
  onForwardRunIdChange,
  forwardRequestJson,
  onForwardRequestJsonChange,
  onStartForwardRun,
  onFetchForwardStatus,
  forwardLoading,
  forwardStartLoading,
  forwardError,
  forwardRequestJsonError,
  forwardStartError,
  forwardStartMessage,
  forwardStatus,
  formatValue,
  renderFieldLabel,
  formatCellValue,
}: Props) => (
  <Stack spacing={2}>
    <Paper sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <TextField
            label="ID прогона (опционально)"
            size="small"
            value={forwardRunId}
            onChange={(event) => onForwardRunIdChange(event.target.value)}
            sx={{ minWidth: 220 }}
          />
          <Button variant="contained" onClick={onStartForwardRun} disabled={forwardStartLoading}>
            Запустить forward
          </Button>
          <Button variant="outlined" onClick={onFetchForwardStatus} disabled={forwardLoading}>
            Загрузить статус
          </Button>
          {forwardStartLoading ? (
            <Typography variant="body2" color="text.secondary">
              Запуск...
            </Typography>
          ) : null}
          {forwardLoading ? (
            <Typography variant="body2" color="text.secondary">
              Загрузка статуса...
            </Typography>
          ) : null}
        </Stack>
        <TextField
          label="Forward request JSON (опционально)"
          size="small"
          value={forwardRequestJson}
          onChange={(event) => onForwardRequestJsonChange(event.target.value)}
          multiline
          minRows={3}
        />
        {forwardRequestJsonError ? (
          <Typography variant="body2" color="error">
            {forwardRequestJsonError}
          </Typography>
        ) : null}
        {forwardStartError ? (
          <Typography variant="body2" color="error">
            {forwardStartError}
          </Typography>
        ) : null}
        {forwardError ? (
          <Typography variant="body2" color="error">
            {forwardError}
          </Typography>
        ) : null}
        {forwardStartMessage ? (
          <Typography variant="body2" color="success.main">
            {forwardStartMessage}
          </Typography>
        ) : null}
      </Stack>
    </Paper>
    {forwardStatus ? (
      <Stack spacing={2}>
        <Paper sx={{ p: 2 }}>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            <Chip label={`Прогон: ${forwardStatus.run_id ?? 'н/д'}`} size="small" />
            <Chip
              label={`Статус: ${formatValue(forwardStatus.status ?? 'н/д', 'status')}`}
              size="small"
            />
          </Stack>
        </Paper>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
          <Paper sx={{ p: 2, flex: 1 }}>
            <Typography variant="subtitle2" fontWeight={600}>
              Последний отчёт по эквити
            </Typography>
            <KeyValueGrid
              payload={forwardStatus.last_equity ?? undefined}
              emptyLabel="Отчёта по эквити пока нет."
              renderLabel={renderFieldLabel}
              renderValue={(value, key) => formatCellValue(value, key)}
            />
          </Paper>
          <Paper sx={{ p: 2, flex: 1 }}>
            <Typography variant="subtitle2" fontWeight={600}>
              Последняя сделка
            </Typography>
            <KeyValueGrid
              payload={forwardStatus.last_trade ?? undefined}
              emptyLabel="Сделок пока нет."
              renderLabel={renderFieldLabel}
              renderValue={(value, key) => formatCellValue(value, key)}
            />
          </Paper>
          <Paper sx={{ p: 2, flex: 1 }}>
            <Typography variant="subtitle2" fontWeight={600}>
              Последнее уведомление
            </Typography>
            <KeyValueGrid
              payload={forwardStatus.last_alert ?? undefined}
              emptyLabel="Уведомлений пока нет."
              renderLabel={renderFieldLabel}
              renderValue={(value, key) => formatCellValue(value, key)}
            />
          </Paper>
        </Stack>
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="subtitle2">Снимок состояния</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <JsonBlock payload={forwardStatus.state ?? {}} />
          </AccordionDetails>
        </Accordion>
        {forwardStatus.run_meta ? (
          <Accordion>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">Метаданные прогона</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <JsonBlock payload={forwardStatus.run_meta} />
            </AccordionDetails>
          </Accordion>
        ) : null}
      </Stack>
    ) : (
      <Typography variant="body2" color="text.secondary">
        Загрузите статус форварда, чтобы увидеть отчёты и уведомления.
      </Typography>
    )}
  </Stack>
)

export default ForwardTab
