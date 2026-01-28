import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  Divider,
  FormControlLabel,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import type { ReactNode } from 'react'
import type { BacktestReport, GenericRow, ParameterSpec } from '../../entities/decision/types'
import GenericTable from '../../shared/ui/GenericTable'
import JsonBlock from '../../shared/ui/JsonBlock'
import KeyValueGrid from '../../shared/ui/KeyValueGrid'

type ParamSection = [string, ParameterSpec[]]

type Props = {
  paramPreset: string
  onParamPresetChange: (value: string) => void
  onFetchParamSpecs: (opts: { resetValues: boolean }) => void
  paramSpecsLoading: boolean
  onParamReset: () => void
  paramSpecs: ParameterSpec[]
  backtestPrecompute: boolean
  onBacktestPrecomputeChange: (value: boolean) => void
  paramSpecsError?: string | null
  paramFilter: string
  onParamFilterChange: (value: string) => void
  paramSections: ParamSection[]
  renderParamInput: (spec: ParameterSpec) => ReactNode
  onBacktestRun: () => void
  backtestRunLoading: boolean
  backtestRunError?: string | null
  backtestRunParseError?: string | null
  backtestRunReport: BacktestReport | null
  backtestSummaryEntries: { key: string; value: unknown }[]
  backtestEquityRows: GenericRow[]
  backtestEquityColumns: string[]
  backtestTradeRows: GenericRow[]
  backtestTradeColumns: string[]
  toTitleCase: (value: string) => string
  renderFieldLabel: (key: string) => string
  formatCellValue: (value: unknown, column?: string) => string
  formatDate: (value?: string) => string
  isDateColumn: (column: string) => boolean
}

const BacktestV2Tab = ({
  paramPreset,
  onParamPresetChange,
  onFetchParamSpecs,
  paramSpecsLoading,
  onParamReset,
  paramSpecs,
  backtestPrecompute,
  onBacktestPrecomputeChange,
  paramSpecsError,
  paramFilter,
  onParamFilterChange,
  paramSections,
  renderParamInput,
  onBacktestRun,
  backtestRunLoading,
  backtestRunError,
  backtestRunParseError,
  backtestRunReport,
  backtestSummaryEntries,
  backtestEquityRows,
  backtestEquityColumns,
  backtestTradeRows,
  backtestTradeColumns,
  toTitleCase,
  renderFieldLabel,
  formatCellValue,
  formatDate,
  isDateColumn,
}: Props) => (
  <Stack spacing={2}>
    <Paper sx={{ p: 2 }}>
      <Stack spacing={2}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <TextField
            label="Пресет (опционально)"
            size="small"
            value={paramPreset}
            onChange={(event) => onParamPresetChange(event.target.value)}
            sx={{ minWidth: 200 }}
          />
          <Button
            variant="outlined"
            onClick={() => onFetchParamSpecs({ resetValues: true })}
            disabled={paramSpecsLoading}
          >
            {paramSpecsLoading ? 'Загрузка параметров...' : 'Загрузить параметры'}
          </Button>
          <Button variant="text" onClick={onParamReset} disabled={!paramSpecs.length}>
            Сбросить по умолчанию
          </Button>
          <FormControlLabel
            control={
              <Switch
                checked={backtestPrecompute}
                onChange={(event) => onBacktestPrecomputeChange(event.target.checked)}
              />
            }
            label="Предрасчёт кэша"
          />
          <Typography variant="body2" color="text.secondary">
            {paramSpecs.length ? `Параметров: ${paramSpecs.length}` : 'Параметров: н/д'}
          </Typography>
          {paramSpecsError ? (
            <Typography variant="body2" color="error">
              {paramSpecsError}
            </Typography>
          ) : null}
        </Stack>
        <TextField
          label="Фильтр параметров"
          size="small"
          value={paramFilter}
          onChange={(event) => onParamFilterChange(event.target.value)}
          sx={{ maxWidth: 320 }}
        />
        {paramSpecs.length ? (
          paramSections.length ? (
            paramSections.map(([section, specs], index) => (
              <Accordion key={section} defaultExpanded={index === 0 || section === 'test'}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography variant="subtitle2">
                    {toTitleCase(section)} ({specs.length})
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <Box
                    sx={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                      gap: 2,
                    }}
                  >
                    {specs.map((spec) => renderParamInput(spec))}
                  </Box>
                </AccordionDetails>
              </Accordion>
            ))
          ) : (
            <Typography variant="body2" color="text.secondary">
              Нет параметров, подходящих под фильтр.
            </Typography>
          )
        ) : (
          <Typography variant="body2" color="text.secondary">
            Загрузите параметры, чтобы редактировать запрос бэктеста.
          </Typography>
        )}
        <Divider />
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <Button variant="contained" onClick={onBacktestRun} disabled={backtestRunLoading || !paramSpecs.length}>
            Запустить бэктест
          </Button>
          {backtestRunLoading ? (
            <Typography variant="body2" color="text.secondary">
              Запуск бэктеста...
            </Typography>
          ) : null}
          {backtestRunParseError ? (
            <Typography variant="body2" color="error">
              {backtestRunParseError}
            </Typography>
          ) : null}
          {backtestRunError ? (
            <Typography variant="body2" color="error">
              {backtestRunError}
            </Typography>
          ) : null}
        </Stack>
      </Stack>
    </Paper>
    {backtestRunReport ? (
      <Stack spacing={2}>
        <Paper sx={{ p: 2 }}>
          <Stack spacing={1}>
            <Typography variant="subtitle1" fontWeight={600}>
              Итоговые метрики
            </Typography>
            {backtestSummaryEntries.length ? (
              <KeyValueGrid
                entries={backtestSummaryEntries}
                renderLabel={renderFieldLabel}
                renderValue={(value, key) => formatCellValue(value, key)}
              />
            ) : (
              <KeyValueGrid
                payload={{}}
                emptyLabel="Итоговые метрики пока недоступны."
                renderLabel={renderFieldLabel}
                renderValue={(value, key) => formatCellValue(value, key)}
              />
            )}
            {backtestRunReport.warnings && backtestRunReport.warnings.length ? (
              <Stack direction="row" spacing={1} flexWrap="wrap">
                {backtestRunReport.warnings.map((warning, index) => (
                  <Chip key={`${warning}-${index}`} label={`Предупреждение: ${warning}`} size="small" />
                ))}
              </Stack>
            ) : null}
          </Stack>
        </Paper>
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1 }}>
            Кривая эквити
          </Typography>
          <GenericTable
            rows={backtestEquityRows}
            columns={backtestEquityColumns}
            emptyLabel="Кривая эквити пуста."
            renderHeader={renderFieldLabel}
            renderCell={(row, column) =>
              isDateColumn(column)
                ? formatDate(String(row[column] ?? ''))
                : formatCellValue(row[column], column)
            }
          />
        </Paper>
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1 }}>
            Сделки
          </Typography>
          <GenericTable
            rows={backtestTradeRows}
            columns={backtestTradeColumns}
            emptyLabel="Список сделок пуст."
            renderHeader={renderFieldLabel}
            renderCell={(row, column) =>
              isDateColumn(column)
                ? formatDate(String(row[column] ?? ''))
                : formatCellValue(row[column], column)
            }
          />
        </Paper>
        {backtestRunReport.resolved_config ? (
          <Accordion>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">Развёрнутый конфиг</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <JsonBlock payload={backtestRunReport.resolved_config} />
            </AccordionDetails>
          </Accordion>
        ) : null}
      </Stack>
    ) : (
      <Typography variant="body2" color="text.secondary">
        Запустите бэктест, чтобы увидеть метрики, кривую эквити и сделки.
      </Typography>
    )}
  </Stack>
)

export default BacktestV2Tab
