import type { GridColDef } from '@mui/x-data-grid'
import type { DecisionView } from '../../entities/decision/types'

type Params = {
  getFieldLabel: (key: string) => string
  getFieldTooltip: (key: string) => string
  formatDate: (value?: string) => string
  formatValue: (value: unknown, column?: string) => string
}

export const createDecisionColumns = ({
  getFieldLabel,
  getFieldTooltip,
  formatDate,
  formatValue,
}: Params): GridColDef[] => [
  {
    headerName: getFieldLabel('created_at'),
    description: getFieldTooltip('created_at'),
    field: 'created_at',
    valueFormatter: (params: { value?: unknown }) => formatDate(params?.value as string),
    width: 190,
  },
  {
    headerName: getFieldLabel('decision_id'),
    description: getFieldTooltip('decision_id'),
    field: 'decision_id',
    width: 260,
    cellClassName: 'cell-mono',
  },
  {
    headerName: getFieldLabel('strategy_type'),
    description: getFieldTooltip('strategy_type'),
    field: 'strategy_type',
    width: 160,
    valueFormatter: (params: { value?: unknown }) => formatValue(params?.value, 'strategy_type'),
  },
  {
    headerName: getFieldLabel('primary_instrument'),
    description: getFieldTooltip('primary_instrument'),
    field: 'primary_instrument',
    width: 140,
  },
  {
    headerName: getFieldLabel('proposal_type'),
    description: getFieldTooltip('proposal_type'),
    field: 'proposal_type',
    width: 140,
    valueGetter: (params: { row?: DecisionView } | undefined) =>
      params?.row?.proposal_summary?.type ?? '',
    valueFormatter: (params: { value?: unknown }) => formatValue(params?.value, 'proposal_type'),
  },
  {
    headerName: getFieldLabel('action'),
    description: getFieldTooltip('action'),
    field: 'action',
    width: 120,
    cellClassName: (params) =>
      params.value === 'approve' ? 'cell-approve' : params.value === 'reject' ? 'cell-reject' : '',
    valueFormatter: (params: { value?: unknown }) => formatValue(params?.value, 'action'),
  },
  {
    headerName: getFieldLabel('risk_state'),
    description: getFieldTooltip('risk_state'),
    field: 'risk_state',
    width: 110,
    cellClassName: (params) =>
      params.value === 'green'
        ? 'cell-risk-green'
        : params.value === 'yellow'
          ? 'cell-risk-yellow'
          : params.value === 'red'
            ? 'cell-risk-red'
            : '',
    valueFormatter: (params: { value?: unknown }) => formatValue(params?.value, 'risk_state'),
  },
  {
    headerName: getFieldLabel('news_severity'),
    description: getFieldTooltip('news_severity'),
    field: 'news_severity',
    width: 110,
    cellClassName: (params) =>
      params.value === 'high'
        ? 'cell-news-high'
        : params.value === 'critical'
          ? 'cell-news-critical'
          : '',
    valueFormatter: (params: { value?: unknown }) => formatValue(params?.value, 'news_severity'),
  },
  {
    headerName: getFieldLabel('execution_status'),
    description: getFieldTooltip('execution_status'),
    field: 'execution_status',
    width: 140,
    valueGetter: (params: { row?: DecisionView } | undefined) =>
      params?.row?.execution_ref?.status ??
      params?.row?.decision_ref?.latest_status ??
      params?.row?.execution_status?.status ??
      params?.row?.operator_action?.status ??
      '',
    valueFormatter: (params: { value?: unknown }) => formatValue(params?.value, 'status'),
  },
  {
    headerName: getFieldLabel('cost_round_trip'),
    description: getFieldTooltip('cost_round_trip'),
    field: 'cost_round_trip',
    valueFormatter: (params: { value?: unknown }) => formatValue(params?.value, 'cost_round_trip'),
    width: 120,
  },
  {
    headerName: getFieldLabel('max_drawdown'),
    description: getFieldTooltip('max_drawdown'),
    field: 'max_drawdown',
    valueFormatter: (params: { value?: unknown }) => formatValue(params?.value, 'max_drawdown'),
    width: 120,
  },
]
