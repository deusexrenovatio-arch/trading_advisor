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
      <Typography variant="h6">News Intelligence</Typography>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
        <TextField
          select
          label="Severity"
          size="small"
          value={severity}
          onChange={(event) => setSeverity(event.target.value)}
          sx={{ minWidth: 180 }}
        >
          {SEVERITIES.map((value) => (
            <MenuItem key={value || 'all'} value={value}>
              {value || 'all'}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Ticker"
          size="small"
          value={ticker}
          onChange={(event) => setTicker(event.target.value.trim().toUpperCase())}
          sx={{ minWidth: 180 }}
        />
        <Button variant="outlined" onClick={() => void load()} disabled={loading}>
          {loading ? 'Loading...' : 'Reload'}
        </Button>
      </Stack>
      {error ? <Alert severity="error">{error}</Alert> : null}
      <Paper variant="outlined">
        <Box sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Time</TableCell>
                <TableCell>Severity</TableCell>
                <TableCell>Headline</TableCell>
                <TableCell>Ticker</TableCell>
                <TableCell>Decision</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.news_event_id}>
                  <TableCell>{row.published_at}</TableCell>
                  <TableCell>{row.severity}</TableCell>
                  <TableCell>{row.headline}</TableCell>
                  <TableCell>{row.entity_links?.[0]?.ticker || '-'}</TableCell>
                  <TableCell>{row.decision_ref?.decision_id || '-'}</TableCell>
                </TableRow>
              ))}
              {!rows.length ? (
                <TableRow>
                  <TableCell colSpan={5}>No events</TableCell>
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
