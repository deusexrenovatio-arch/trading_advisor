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
import type { GenericRow, HpoResponse } from '../../entities/decision/types'
import GenericTable from '../../shared/ui/GenericTable'
import JsonBlock from '../../shared/ui/JsonBlock'

type Props = {
  onFetchParamSpecs: () => void
  paramSpecsCount: number
  hpoRequestJson: string
  hpoRequestJsonError?: string | null
  onHpoRequestJsonChange: (value: string) => void
  hpoSearchSpace: string
  onHpoSearchSpaceChange: (value: string) => void
  onHpoRun: () => void
  hpoLoading: boolean
  hpoError?: string | null
  hpoResponse: HpoResponse | null
  formatValue: (value: unknown, column?: string) => string
  hpoLeaderboardRows: GenericRow[]
  hpoLeaderboardColumns: string[]
  renderFieldLabel: (key: string) => ReactNode
  formatCellValue: (value: unknown, column?: string) => string
  formatDate: (value?: string) => string
  isDateColumn: (column: string) => boolean
}

const HpoTab = ({
  onFetchParamSpecs,
  paramSpecsCount,
  hpoRequestJson,
  hpoRequestJsonError,
  onHpoRequestJsonChange,
  hpoSearchSpace,
  onHpoSearchSpaceChange,
  onHpoRun,
  hpoLoading,
  hpoError,
  hpoResponse,
  formatValue,
  hpoLeaderboardRows,
  hpoLeaderboardColumns,
  renderFieldLabel,
  formatCellValue,
  formatDate,
  isDateColumn,
}: Props) => (
  <Stack spacing={2}>
    <Paper sx={{ p: 2 }}>
      <Stack spacing={2}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <Button variant="outlined" onClick={onFetchParamSpecs}>
            Загрузить параметры
          </Button>
          <Typography variant="body2" color="text.secondary">
            {paramSpecsCount
              ? `Базовые параметры загружены: ${paramSpecsCount}`
              : 'Базовые параметры не загружены (будут использованы значения по умолчанию)'}
          </Typography>
        </Stack>
        <TextField
          label="HPO запрос (JSON)"
          size="small"
          value={hpoRequestJson}
          onChange={(event) => onHpoRequestJsonChange(event.target.value)}
          placeholder='{"base":{"test":{"start_date":"2025-10-01","end_date":"2026-01-28"}},"cv":{"test_size":0.2}}'
          multiline
          minRows={6}
          error={Boolean(hpoRequestJsonError)}
          helperText={
            hpoRequestJsonError ||
            'Если заполнено, JSON используется целиком; недостающие поля дополняются из формы.'
          }
        />
        <TextField
          label="Пространство поиска (JSON)"
          size="small"
          value={hpoSearchSpace}
          onChange={(event) => onHpoSearchSpaceChange(event.target.value)}
          placeholder='{"strategy.z_window":{"kind":"int","min_value":20,"max_value":120}}'
          multiline
          minRows={6}
        />
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <Button
            variant="contained"
            onClick={onHpoRun}
            disabled={hpoLoading || hpoResponse?.status === 'running'}
          >
            Запустить HPO
          </Button>
          {hpoLoading ? (
            <Typography variant="body2" color="text.secondary">
              Запуск HPO...
            </Typography>
          ) : null}
          {hpoError ? (
            <Typography variant="body2" color="error">
              {hpoError}
            </Typography>
          ) : null}
        </Stack>
      </Stack>
    </Paper>
    {hpoResponse ? (
      <Stack spacing={2}>
        <Paper sx={{ p: 2 }}>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            {hpoResponse.run_id ? (
              <Chip label={`Run: ${formatValue(hpoResponse.run_id, 'run_id')}`} size="small" />
            ) : null}
            {hpoResponse.status ? (
              <Chip label={`Статус: ${formatValue(hpoResponse.status, 'status')}`} size="small" />
            ) : null}
            {hpoResponse.progress ? (
              <Chip
                label={`Прогресс: ${hpoResponse.progress.completed ?? 0}/${
                  hpoResponse.progress.total ?? 0
                }`}
                size="small"
              />
            ) : null}
            {hpoResponse.message ? <Chip label={hpoResponse.message} size="small" /> : null}
          </Stack>
        </Paper>
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1 }}>
            Лидерборд
          </Typography>
          <GenericTable
            rows={hpoLeaderboardRows as GenericRow[]}
            columns={hpoLeaderboardColumns}
            emptyLabel="Пока нет записей в лидерборде."
            renderHeader={renderFieldLabel}
            renderCell={(row, column) =>
              isDateColumn(column)
                ? formatDate(String(row[column] ?? ''))
                : formatCellValue(row[column], column)
            }
          />
        </Paper>
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="subtitle2">Сырой ответ HPO</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <JsonBlock payload={hpoResponse} />
          </AccordionDetails>
        </Accordion>
      </Stack>
    ) : (
      <Typography variant="body2" color="text.secondary">
        Запустите HPO, чтобы увидеть лидерборд.
      </Typography>
    )}
  </Stack>
)

export default HpoTab
