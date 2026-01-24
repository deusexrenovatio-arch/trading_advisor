import { Box, Typography } from '@mui/material'
import { LineChart } from '@mui/x-charts/LineChart'

type SpreadPoint = {
  date: string
  spread_mid?: number | null
  spread_pct?: number | null
  spread?: number | null
  entry_flag?: boolean | null
  exit_flag?: boolean | null
  trade_cycle?: number | null
  trade_return_pct?: number | null
}

type SpreadChartProps = {
  data: SpreadPoint[]
}

export default function SpreadChart({ data }: SpreadChartProps) {
  if (!data.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        No spread data available.
      </Typography>
    )
  }

  const dates = data.map((point) => new Date(point.date))
  const spreadValues = data.map(
    (point) => (point.spread_mid ?? point.spread ?? null) as number | null,
  )
  const spreadPctValues = data.map((point) => (point.spread_pct ?? null) as number | null)
  const entryValues = spreadValues.map((value, index) =>
    data[index]?.entry_flag ? value : null,
  )
  const exitValues = spreadValues.map((value, index) =>
    data[index]?.exit_flag ? value : null,
  )

  const cycleSummary = (() => {
    const map = new Map<number, { entry?: string; exit?: string; returnPct?: number | null }>()
    data.forEach((point) => {
      if (point.trade_cycle == null) return
      const entry = map.get(point.trade_cycle) ?? {}
      if (point.entry_flag) {
        entry.entry = point.date
      }
      if (point.exit_flag) {
        entry.exit = point.date
        if (typeof point.trade_return_pct === 'number') {
          entry.returnPct = point.trade_return_pct
        }
      }
      map.set(point.trade_cycle, entry)
    })
    return Array.from(map.entries())
      .map(([cycle, value]) => ({ cycle, ...value }))
      .sort((a, b) => a.cycle - b.cycle)
  })()

  return (
    <Box sx={{ width: '100%', minHeight: 320 }}>
      <LineChart
        xAxis={[
          {
            data: dates,
            scaleType: 'time',
            valueFormatter: (value) => value.toLocaleDateString(),
          },
        ]}
        yAxis={[
          { id: 'spread_mid', label: 'Spread (mid)', position: 'left' },
          { id: 'spread_pct', label: 'Spread %', position: 'right' },
        ]}
        series={[
          {
            data: spreadValues,
            label: 'Spread (mid)',
            showMark: false,
            color: '#1976d2',
            yAxisId: 'spread_mid',
          },
          {
            data: entryValues,
            label: 'Entry',
            showMark: true,
            color: '#16a34a',
            yAxisId: 'spread_mid',
          },
          {
            data: exitValues,
            label: 'Exit',
            showMark: true,
            color: '#dc2626',
            yAxisId: 'spread_mid',
          },
          {
            data: spreadPctValues,
            label: 'Spread %',
            showMark: false,
            color: '#0f766e',
            yAxisId: 'spread_pct',
            valueFormatter: (value: number | null) =>
              value == null ? '' : `${(value * 100).toFixed(2)}%`,
          },
        ]}
        height={300}
      />
      {cycleSummary.length ? (
        <Box sx={{ mt: 1 }}>
          <Typography variant="caption" color="text.secondary">
            Trades
          </Typography>
          {cycleSummary.map((item) => (
            <Typography key={item.cycle} variant="caption" display="block">
              #{item.cycle}: entry {item.entry ?? '—'} · exit {item.exit ?? '—'} · return{' '}
              {typeof item.returnPct === 'number' ? `${(item.returnPct * 100).toFixed(2)}%` : '—'}
            </Typography>
          ))}
        </Box>
      ) : null}
    </Box>
  )
}
