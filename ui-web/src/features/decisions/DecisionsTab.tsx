import {
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import type { GridColDef, GridRowParams } from '@mui/x-data-grid'
import type {
  DecisionLog,
  DecisionView,
  ExecutionStatus,
  OperatorAction,
} from '../../entities/decision/types'
import DecisionDetail from './DecisionDetail'
import DecisionTable from './DecisionTable'

export type BasketRow = {
  basket?: string
  current?: number
  target?: number
  delta?: number
}

type Props = {
  quickFilter: string
  onQuickFilterChange: (value: string) => void
  strategyFilter: string
  instrumentFilter: string
  riskFilter: string
  newsFilter: string
  strategyOptions: string[]
  instrumentOptions: string[]
  riskOptions: string[]
  newsOptions: string[]
  onStrategyFilterChange: (value: string) => void
  onInstrumentFilterChange: (value: string) => void
  onRiskFilterChange: (value: string) => void
  onNewsFilterChange: (value: string) => void
  createdFrom: string
  createdTo: string
  onCreatedFromChange: (value: string) => void
  onCreatedToChange: (value: string) => void
  onRefresh: () => void
  isLoading: boolean
  filteredCount: number
  error?: string | null
  decisionRows: DecisionView[]
  decisionColumns: GridColDef[]
  loading: boolean
  onRowClick: (params: GridRowParams) => void
  selectedId?: string | null
  detail?: DecisionLog | null
  detailError?: string | null
  selectedDecision?: DecisionView | null
  detailDecision?: Record<string, unknown> | null
  detailProposal?: Record<string, unknown> | null
  detailAggregation?: Record<string, unknown> | null
  detailFacts: Record<string, unknown>[]
  basketRows: BasketRow[]
  decisionActionNote: string
  onDecisionActionNoteChange: (value: string) => void
  decisionActionSubmitting: boolean
  onSubmitDecisionAction: (action: 'approve' | 'reject') => void
  decisionActionError?: string | null
  decisionActionLoading: boolean
  operatorAction?: OperatorAction
  executionStatus?: ExecutionStatus
  formatValue: (value: unknown, column?: string) => string
  formatNumber: (value?: number, digits?: number) => string
  formatDate: (value?: string) => string
  getString: (value: unknown) => string
}

const DecisionsTab = ({
  quickFilter,
  onQuickFilterChange,
  strategyFilter,
  instrumentFilter,
  riskFilter,
  newsFilter,
  strategyOptions,
  instrumentOptions,
  riskOptions,
  newsOptions,
  onStrategyFilterChange,
  onInstrumentFilterChange,
  onRiskFilterChange,
  onNewsFilterChange,
  createdFrom,
  createdTo,
  onCreatedFromChange,
  onCreatedToChange,
  onRefresh,
  isLoading,
  filteredCount,
  error,
  decisionRows,
  decisionColumns,
  loading,
  onRowClick,
  selectedId,
  detail,
  detailError,
  selectedDecision,
  detailDecision,
  detailProposal,
  detailAggregation,
  detailFacts,
  basketRows,
  decisionActionNote,
  onDecisionActionNoteChange,
  decisionActionSubmitting,
  onSubmitDecisionAction,
  decisionActionError,
  decisionActionLoading,
  operatorAction,
  executionStatus,
  formatValue,
  formatNumber,
  formatDate,
  getString,
}: Props) => (
  <>
    <Paper sx={{ p: 2 }}>
      <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
        <TextField
          label="Быстрый поиск"
          size="small"
          value={quickFilter}
          onChange={(event) => onQuickFilterChange(event.target.value)}
          sx={{ minWidth: 240 }}
        />
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Стратегия</InputLabel>
          <Select
            label="Стратегия"
            value={strategyFilter}
            onChange={(event) => onStrategyFilterChange(event.target.value)}
          >
            <MenuItem value="">Все</MenuItem>
            {strategyOptions.map((item) => (
              <MenuItem key={item} value={item}>
                {formatValue(item, 'strategy_type')}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Инструмент</InputLabel>
          <Select
            label="Инструмент"
            value={instrumentFilter}
            onChange={(event) => onInstrumentFilterChange(event.target.value)}
          >
            <MenuItem value="">Все</MenuItem>
            {instrumentOptions.map((item) => (
              <MenuItem key={item} value={item}>
                {item}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Риск</InputLabel>
          <Select
            label="Риск"
            value={riskFilter}
            onChange={(event) => onRiskFilterChange(event.target.value)}
          >
            <MenuItem value="">Все</MenuItem>
            {riskOptions.map((item) => (
              <MenuItem key={item} value={item}>
                {formatValue(item, 'risk_state')}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Новости</InputLabel>
          <Select
            label="Новости"
            value={newsFilter}
            onChange={(event) => onNewsFilterChange(event.target.value)}
          >
            <MenuItem value="">Все</MenuItem>
            {newsOptions.map((item) => (
              <MenuItem key={item} value={item}>
                {formatValue(item, 'news_severity')}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <TextField
          label="Дата с"
          size="small"
          type="date"
          value={createdFrom}
          onChange={(event) => onCreatedFromChange(event.target.value)}
          InputLabelProps={{ shrink: true }}
          sx={{ minWidth: 160 }}
        />
        <TextField
          label="Дата по"
          size="small"
          type="date"
          value={createdTo}
          onChange={(event) => onCreatedToChange(event.target.value)}
          InputLabelProps={{ shrink: true }}
          sx={{ minWidth: 160 }}
        />
        <Button variant="contained" onClick={onRefresh} disabled={isLoading}>
          Обновить
        </Button>
        <Typography variant="body2" color="text.secondary">
          {isLoading ? 'Загрузка...' : `${filteredCount} строк`}
        </Typography>
        {error ? (
          <Typography variant="body2" color="error">
            {error}
          </Typography>
        ) : null}
      </Stack>
    </Paper>
    <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="stretch">
      <DecisionTable
        decisionRows={decisionRows}
        decisionColumns={decisionColumns}
        loading={loading}
        onRowClick={onRowClick}
      />
      <DecisionDetail
        selectedId={selectedId}
        detail={detail}
        detailError={detailError}
        selectedDecision={selectedDecision}
        detailDecision={detailDecision}
        detailProposal={detailProposal}
        detailAggregation={detailAggregation}
        detailFacts={detailFacts}
        basketRows={basketRows}
        decisionActionNote={decisionActionNote}
        onDecisionActionNoteChange={onDecisionActionNoteChange}
        decisionActionSubmitting={decisionActionSubmitting}
        onSubmitDecisionAction={onSubmitDecisionAction}
        decisionActionError={decisionActionError}
        decisionActionLoading={decisionActionLoading}
        operatorAction={operatorAction}
        executionStatus={executionStatus}
        formatValue={formatValue}
        formatNumber={formatNumber}
        formatDate={formatDate}
        getString={getString}
      />
    </Stack>
  </>
)

export default DecisionsTab
