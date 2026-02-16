import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { usePortfolioControl } from './usePortfolioControl'
import { formatValue } from '../../shared/utils/formatValue'

function PortfolioControlTab() {
  const {
    preview,
    limit,
    setLimit,
    loading,
    error,
    commitStatus,
    loadPreview,
    handleCommit,
    riskRows,
  } = usePortfolioControl()

  const failedRiskChecks = riskRows.filter((row) => row.passed === false)

  return (
    <Stack spacing={2}>
      <Typography variant="h6">Управление портфелем (Portfolio Control)</Typography>
      <Typography variant="body2" color="text.secondary">
        Предпросмотр формирует целевые веса по активным сигналам и сразу показывает риск-ограничения перед коммитом.
      </Typography>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
        <TextField
          label="Лимит позиций"
          size="small"
          value={limit}
          onChange={(event) => setLimit(event.target.value)}
          sx={{ width: 140 }}
        />
        <Button variant="outlined" onClick={() => void loadPreview()} disabled={loading}>
          {loading ? 'Загрузка...' : 'Обновить предпросмотр'}
        </Button>
        <Button
          variant="contained"
          onClick={() => void handleCommit()}
          disabled={loading || !preview || !preview.positions.length}
        >
          Применить ребаланс
        </Button>
      </Stack>
      {error ? <Alert severity="error">{error}</Alert> : null}
      {commitStatus ? <Alert severity="success">{commitStatus}</Alert> : null}
      {preview ? (
        <Paper variant="outlined" sx={{ p: 1.25 }}>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
            <Chip label={`План: ${preview.rebalance_plan_id}`} size="small" />
            <Chip label={`Позиции: ${preview.positions.length}`} size="small" />
            <Chip label={`Проверки риска: ${riskRows.length}`} size="small" />
          </Stack>
        </Paper>
      ) : null}
      <Paper variant="outlined">
        <Box sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Пара</TableCell>
                <TableCell>Целевой вес</TableCell>
                <TableCell>Состояние</TableCell>
                <TableCell>Действие сигнала</TableCell>
                <TableCell>Скор</TableCell>
                <TableCell>Причины</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(preview?.positions ?? []).map((row) => (
                <TableRow key={row.signal_id || row.entity_ref.entity_id}>
                  <TableCell>{row.entity_ref.ticker || row.entity_ref.entity_id}</TableCell>
                  <TableCell>{`${((row.target_weight ?? 0) * 100).toFixed(2)}%`}</TableCell>
                  <TableCell>{formatValue(row.lifecycle_state ?? '-', 'lifecycle_state')}</TableCell>
                  <TableCell>{formatValue(row.signal_action ?? '-', 'signal_action')}</TableCell>
                  <TableCell>{formatValue(row.signal_score ?? '-', 'signal_score')}</TableCell>
                  <TableCell>{formatValue(row.reasons ?? [])}</TableCell>
                </TableRow>
              ))}
              {!preview?.positions?.length ? (
                <TableRow>
                  <TableCell colSpan={6}>Данных для предпросмотра пока нет.</TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </Box>
      </Paper>
      <Paper variant="outlined" sx={{ p: 1.5 }}>
        <Stack spacing={1}>
          <Typography variant="subtitle2">Проверки риска</Typography>
          {failedRiskChecks.length ? (
            <Alert severity="warning">
              Обнаружены ограничения риска: {failedRiskChecks.length}. Перед коммитом проверьте блокирующие проверки.
            </Alert>
          ) : null}
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Проверка</TableCell>
                  <TableCell>Статус</TableCell>
                  <TableCell>Лимит</TableCell>
                  <TableCell>Факт</TableCell>
                  <TableCell>Комментарий</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {riskRows.map((row, index) => {
                  const key = String(row.check ?? row.id ?? `risk-check-${index}`)
                  const passed = row.passed === true ? true : row.passed === false ? false : null
                  const statusLabel = passed === true ? 'Пройдено' : passed === false ? 'Не пройдено' : 'Нет данных'
                  const color = passed === true ? 'success' : passed === false ? 'error' : 'default'
                  return (
                    <TableRow key={key}>
                      <TableCell>{formatValue(row.check ?? row.id ?? '-')}</TableCell>
                      <TableCell>
                        <Chip size="small" color={color} label={statusLabel} />
                      </TableCell>
                      <TableCell>{formatValue(row.limit ?? '-')}</TableCell>
                      <TableCell>{formatValue(row.value ?? '-')}</TableCell>
                      <TableCell>{formatValue(row.description ?? row.action ?? '-')}</TableCell>
                    </TableRow>
                  )
                })}
                {!riskRows.length ? (
                  <TableRow>
                    <TableCell colSpan={5}>Проверки риска отсутствуют.</TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </Box>
        </Stack>
      </Paper>
    </Stack>
  )
}

export default PortfolioControlTab
