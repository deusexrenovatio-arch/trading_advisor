import { Box, Button, Chip, Divider, Paper, Stack, TextField, Typography } from '@mui/material'
import JsonBlock from '../../shared/ui/JsonBlock'
import type {
  DecisionLog,
  DecisionView,
  ExecutionStatus,
  OperatorAction,
} from '../../entities/decision/types'
import type { BasketRow } from './DecisionsTab'

type Props = {
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

const DecisionDetail = ({
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
  <Paper sx={{ flex: 1, p: 2 }}>
    <Stack spacing={1}>
      <Typography variant="subtitle1" fontWeight={600}>
        Детали решения
      </Typography>
      {selectedId ? (
        <Typography variant="body2" color="text.secondary">
          {selectedId}
        </Typography>
      ) : null}
      {detailError ? (
        <Typography variant="body2" color="error">
          {detailError}
        </Typography>
      ) : null}
      {detail ? (
        <Stack spacing={2}>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            <Chip
              label={`Действие: ${formatValue(
                selectedDecision?.action || getString(detailDecision?.['action']) || 'hold',
                'action',
              )}`}
              color="primary"
              size="small"
            />
            <Chip
              label={`Риск: ${formatValue(
                selectedDecision?.risk_state || getString(detailDecision?.['risk_state']) || 'н/д',
                'risk_state',
              )}`}
              size="small"
            />
            <Chip
              label={`Новости: ${formatValue(
                selectedDecision?.news_severity || 'н/д',
                'news_severity',
              )}`}
              size="small"
            />
            {selectedDecision?.aggregation_summary?.score !== undefined ? (
              <Chip
                label={`Скор агрегации: ${formatNumber(
                  selectedDecision?.aggregation_summary?.score,
                  3,
                )}`}
                size="small"
              />
            ) : null}
          </Stack>

          <Divider />

          <Box>
            <Typography variant="subtitle2" fontWeight={600}>
              Предложение оркестратора
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {selectedDecision?.proposal_summary?.summary ||
                getString(detailProposal?.['summary']) ||
                'Предложение недоступно.'}
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1 }}>
              <Chip
                label={`Тип: ${formatValue(
                  selectedDecision?.proposal_summary?.type ||
                    getString(detailProposal?.['type']) ||
                    'н/д',
                  'proposal_type',
                )}`}
                size="small"
              />
              <Chip
                label={`Периодичность: ${
                  selectedDecision?.proposal_summary?.cadence ||
                  getString(detailProposal?.['cadence']) ||
                  'н/д'
                }`}
                size="small"
              />
              {selectedDecision?.proposal_summary?.effective_date ||
              getString(detailProposal?.['effective_date']) ? (
                <Chip
                  label={`Вступает в силу: ${formatDate(
                    selectedDecision?.proposal_summary?.effective_date ||
                      getString(detailProposal?.['effective_date']),
                  )}`}
                  size="small"
                />
              ) : null}
            </Stack>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2 }} flexWrap="wrap">
              <TextField
                label="Комментарий оператора"
                size="small"
                value={decisionActionNote}
                onChange={(event) => onDecisionActionNoteChange(event.target.value)}
                sx={{ minWidth: 220 }}
              />
              <Button
                variant="contained"
                color="success"
                disabled={!selectedId || decisionActionSubmitting}
                onClick={() => onSubmitDecisionAction('approve')}
              >
                Одобрить и исполнить
              </Button>
              <Button
                variant="outlined"
                color="error"
                disabled={!selectedId || decisionActionSubmitting}
                onClick={() => onSubmitDecisionAction('reject')}
              >
                Отклонить
              </Button>
            </Stack>
            {decisionActionError ? (
              <Typography variant="body2" color="error" sx={{ mt: 1 }}>
                {decisionActionError}
              </Typography>
            ) : null}
            {decisionActionLoading ? (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                Загрузка статуса оператора...
              </Typography>
            ) : null}
            {operatorAction ? (
              <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1 }}>
                <Chip
                  label={`Оператор: ${formatValue(operatorAction.action ?? 'н/д', 'action')}`}
                  size="small"
                />
                {operatorAction.status ? (
                  <Chip
                    label={`Статус: ${formatValue(operatorAction.status, 'status')}`}
                    size="small"
                  />
                ) : null}
                {operatorAction.actor ? (
                  <Chip label={`Исполнитель: ${operatorAction.actor}`} size="small" />
                ) : null}
              </Stack>
            ) : null}
            {executionStatus ? (
              <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1 }}>
                {executionStatus.status ? (
                  <Chip
                    label={`Исполнение: ${formatValue(executionStatus.status, 'status')}`}
                    size="small"
                  />
                ) : null}
                {executionStatus.requested_at ? (
                  <Chip
                    label={`Запрос: ${formatDate(executionStatus.requested_at)}`}
                    size="small"
                  />
                ) : null}
                {executionStatus.executed_at ? (
                  <Chip
                    label={`Исполнено: ${formatDate(executionStatus.executed_at)}`}
                    size="small"
                  />
                ) : null}
              </Stack>
            ) : null}
          </Box>

          <Divider />

          <Box>
            <Typography variant="subtitle2" fontWeight={600}>
              Распределение корзин (по типу стратегии)
            </Typography>
            {basketRows.length ? (
              <Box component="table" sx={{ width: '100%', mt: 1, borderCollapse: 'collapse' }}>
                <Box component="thead">
                  <Box component="tr">
                    <Box component="th" sx={{ textAlign: 'left', fontWeight: 600, pb: 1 }}>
                      Корзина
                    </Box>
                    <Box component="th" sx={{ textAlign: 'left', fontWeight: 600, pb: 1 }}>
                      Текущее
                    </Box>
                    <Box component="th" sx={{ textAlign: 'left', fontWeight: 600, pb: 1 }}>
                      Целевое
                    </Box>
                    <Box component="th" sx={{ textAlign: 'left', fontWeight: 600, pb: 1 }}>
                      Дельта
                    </Box>
                  </Box>
                </Box>
                <Box component="tbody">
                  {basketRows.map((row) => (
                    <Box component="tr" key={row.basket}>
                      <Box component="td" sx={{ py: 0.5 }}>
                        {formatValue(row.basket, 'basket')}
                      </Box>
                      <Box component="td" sx={{ py: 0.5 }}>
                        {formatValue(row.current, 'basket_weight')}
                      </Box>
                      <Box component="td" sx={{ py: 0.5 }}>
                        {formatValue(row.target, 'basket_weight')}
                      </Box>
                      <Box component="td" sx={{ py: 0.5 }}>
                        {formatValue(row.delta, 'basket_weight')}
                      </Box>
                    </Box>
                  ))}
                </Box>
              </Box>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Данные по корзинам не переданы.
              </Typography>
            )}
          </Box>

          <Divider />

          <Box>
            <Typography variant="subtitle2" fontWeight={600}>
              Доказательства и обоснование
            </Typography>
            <Stack spacing={1} sx={{ mt: 1 }}>
              {detailFacts.length ? (
                detailFacts.map((fact, index) => (
                  <Box key={`${getString(fact['label']) || 'fact'}-${index}`}>
                    <Typography variant="body2">
                      {getString(fact['label'])}: {formatValue(fact['value'])}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {getString(fact['category'])}
                      {fact['source'] ? ` · ${getString(fact['source'])}` : ''}
                      {fact['confidence'] !== undefined
                        ? ` · дост. ${formatValue(fact['confidence'], 'confidence')}`
                        : ''}
                    </Typography>
                  </Box>
                ))
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Факты не предоставлены.
                </Typography>
              )}
              {detailAggregation?.['reasons'] ? (
                <Typography variant="caption" color="text.secondary">
                  Причины агрегации: {formatValue(detailAggregation['reasons'])}
                </Typography>
              ) : null}
            </Stack>
          </Box>

          <Box>
            <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
              Сырой лог решения
            </Typography>
            <JsonBlock payload={detail} />
          </Box>
        </Stack>
      ) : (
        <Typography variant="body2" color="text.secondary">
          Выберите решение, чтобы просмотреть полный лог.
        </Typography>
      )}
    </Stack>
  </Paper>
)

export default DecisionDetail
