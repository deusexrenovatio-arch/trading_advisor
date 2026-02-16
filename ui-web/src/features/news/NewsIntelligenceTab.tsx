import {
  Alert,
  Box,
  Button,
  MenuItem,
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
import { SEVERITIES, useNewsIntelligence } from './useNewsIntelligence'
import { formatDate } from '../../shared/utils/date'
import { formatValue } from '../../shared/utils/formatValue'

function NewsIntelligenceTab() {
  const {
    severity,
    setSeverity,
    ticker,
    setTicker,
    rows,
    loading,
    error,
    load,
  } = useNewsIntelligence()

  return (
    <Stack spacing={2}>
      <Typography variant="h6">Лента новостей (News Intelligence)</Typography>
      <Typography variant="body2" color="text.secondary">
        Фильтруйте события по значимости и тикеру, чтобы быстро понять влияние новостей на решения.
      </Typography>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
        <TextField
          select
          label="Значимость"
          size="small"
          value={severity}
          onChange={(event) => setSeverity(event.target.value)}
          sx={{ minWidth: 180 }}
        >
          {SEVERITIES.map((value) => (
            <MenuItem key={value || 'all'} value={value}>
              {value ? formatValue(value, 'news_severity') : 'Все'}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Тикер"
          size="small"
          value={ticker}
          onChange={(event) => setTicker(event.target.value.trim().toUpperCase())}
          sx={{ minWidth: 180 }}
        />
        <Button variant="outlined" onClick={() => void load()} disabled={loading}>
          {loading ? 'Загрузка...' : 'Обновить ленту'}
        </Button>
      </Stack>
      {error ? <Alert severity="error">{error}</Alert> : null}
      <Paper variant="outlined">
        <Box sx={{ px: 2, pt: 1.5 }}>
          <Typography variant="body2" color="text.secondary">
            Событий в выборке: {rows.length}
          </Typography>
        </Box>
        <Box sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Время</TableCell>
                <TableCell>Значимость</TableCell>
                <TableCell>Заголовок</TableCell>
                <TableCell>Тикер</TableCell>
                <TableCell>Решение</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.news_event_id}>
                  <TableCell>{formatDate(row.published_at)}</TableCell>
                  <TableCell>{formatValue(row.severity, 'news_severity')}</TableCell>
                  <TableCell>{row.headline}</TableCell>
                  <TableCell>{row.entity_links?.[0]?.ticker || '-'}</TableCell>
                  <TableCell>{row.decision_ref?.decision_id || '-'}</TableCell>
                </TableRow>
              ))}
              {!rows.length ? (
                <TableRow>
                  <TableCell colSpan={5}>Событий не найдено по текущим фильтрам.</TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </Box>
      </Paper>
    </Stack>
  )
}

export default NewsIntelligenceTab
