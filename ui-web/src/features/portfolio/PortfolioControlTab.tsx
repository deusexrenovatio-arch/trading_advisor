import {
  Alert,
  Box,
  Button,
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

  return (
    <Stack spacing={2}>
      <Typography variant="h6">Portfolio Control</Typography>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
        <TextField
          label="Preview limit"
          size="small"
          value={limit}
          onChange={(event) => setLimit(event.target.value)}
          sx={{ width: 140 }}
        />
        <Button variant="outlined" onClick={() => void loadPreview()} disabled={loading}>
          {loading ? 'Loading...' : 'Refresh Preview'}
        </Button>
        <Button
          variant="contained"
          onClick={() => void handleCommit()}
          disabled={loading || !preview || !preview.positions.length}
        >
          Commit Rebalance
        </Button>
      </Stack>
      {error ? <Alert severity="error">{error}</Alert> : null}
      {commitStatus ? <Alert severity="success">{commitStatus}</Alert> : null}
      <Paper variant="outlined">
        <Box sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Pair</TableCell>
                <TableCell>Target weight</TableCell>
                <TableCell>Lifecycle</TableCell>
                <TableCell>Signal action</TableCell>
                <TableCell>Score</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(preview?.positions ?? []).map((row) => (
                <TableRow key={row.signal_id || row.entity_ref.entity_id}>
                  <TableCell>{row.entity_ref.entity_id}</TableCell>
                  <TableCell>{row.target_weight?.toFixed(4)}</TableCell>
                  <TableCell>{row.lifecycle_state || '-'}</TableCell>
                  <TableCell>{row.signal_action || '-'}</TableCell>
                  <TableCell>{row.signal_score ?? '-'}</TableCell>
                </TableRow>
              ))}
              {!preview?.positions?.length ? (
                <TableRow>
                  <TableCell colSpan={5}>No preview rows</TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </Box>
      </Paper>
      <Paper variant="outlined" sx={{ p: 1.5 }}>
        <Typography variant="subtitle2" gutterBottom>
          Risk checks
        </Typography>
        <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{JSON.stringify(riskRows, null, 2)}</pre>
      </Paper>
    </Stack>
  )
}

export default PortfolioControlTab
