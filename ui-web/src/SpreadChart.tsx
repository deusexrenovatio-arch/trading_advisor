import { Box, Typography } from '@mui/material'
import { LineChart } from '@mui/x-charts/LineChart'

type SpreadPoint = {
  date: string
  spread?: number | null
  zscore?: number | null
  z_entry?: number | null
  z_exit?: number | null
  entry_flag?: boolean | null
  exit_flag?: boolean | null
  entry_cycle?: number | null
  exit_cycle?: number | null
  cycle_return_pct?: number | null
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
  const spreadValues = data.map((point) => (point.spread ?? null) as number | null)
  const zValues = data.map((point) => (point.zscore ?? null) as number | null)
  const zEntry =
    data.find((point) => typeof point.z_entry === 'number')?.z_entry ?? null
  const zExit = data.find((point) => typeof point.z_exit === 'number')?.z_exit ?? null
  const entryLine =
    zEntry == null ? [] : new Array(data.length).fill(zEntry) as number[]
  const entryLineNeg =
    zEntry == null ? [] : new Array(data.length).fill(-zEntry) as number[]
  const exitLine =
    zExit == null ? [] : new Array(data.length).fill(zExit) as number[]
  const exitLineNeg =
    zExit == null ? [] : new Array(data.length).fill(-zExit) as number[]
  const entryValues = spreadValues.map((value, index) =>
    data[index]?.entry_flag ? value : null,
  )
  const exitValues = spreadValues.map((value, index) =>
    data[index]?.exit_flag ? value : null,
  )
  const entryCycles = data.map((point) => point.entry_cycle ?? null)
  const exitCycles = data.map((point) => point.exit_cycle ?? null)
  const cycleSummary = (() => {
    const map = new Map<number, { entry?: string; exit?: string; returnPct?: number | null }>()
    data.forEach((point) => {
      if (point.entry_cycle) {
        const entry = map.get(point.entry_cycle) ?? {}
        entry.entry = point.date
        map.set(point.entry_cycle, entry)
      }
      if (point.exit_cycle) {
        const exit = map.get(point.exit_cycle) ?? {}
        exit.exit = point.date
        if (typeof point.cycle_return_pct === 'number') {
          exit.returnPct = point.cycle_return_pct
        }
        map.set(point.exit_cycle, exit)
      }
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
          { id: 'spread', label: 'Spread', position: 'left' },
          { id: 'zscore', label: 'Z-score', position: 'right' },
        ]}
        series={[
          {
            data: spreadValues,
            label: 'Spread',
            showMark: false,
            color: '#1976d2',
            yAxisId: 'spread',
          },
          {
            data: entryValues,
            label: 'Entry',
            showMark: true,
            color: '#16a34a',
            yAxisId: 'spread',
            valueFormatter: (value: number | null, context) => {
              const idx = context.dataIndex
              const cycle = entryCycles[idx]
              if (value == null) return ''
              return cycle ? `#${cycle} (${value.toFixed(4)})` : value.toFixed(4)
            },
          },
          {
            data: exitValues,
            label: 'Exit',
            showMark: true,
            color: '#dc2626',
            yAxisId: 'spread',
            valueFormatter: (value: number | null, context) => {
              const idx = context.dataIndex
              const cycle = exitCycles[idx]
              const returnPct = data[idx]?.cycle_return_pct
              if (value == null) return ''
              if (cycle && typeof returnPct === 'number') {
                return `#${cycle} (${value.toFixed(4)} · ${returnPct.toFixed(2)}%)`
              }
              return cycle ? `#${cycle} (${value.toFixed(4)})` : value.toFixed(4)
            },
          },
          {
            data: zValues,
            label: 'Z-score',
            showMark: false,
            color: '#7c3aed',
            yAxisId: 'zscore',
          },
          ...(zEntry == null
            ? []
            : [
                {
                  data: entryLine,
                  label: 'Entry +',
                  showMark: false,
                  color: '#ef4444',
                  yAxisId: 'zscore',
                },
                {
                  data: entryLineNeg,
                  label: 'Entry -',
                  showMark: false,
                  color: '#ef4444',
                  yAxisId: 'zscore',
                },
              ]),
          ...(zExit == null
            ? []
            : [
                {
                  data: exitLine,
                  label: 'Exit +',
                  showMark: false,
                  color: '#f59e0b',
                  yAxisId: 'zscore',
                },
                {
                  data: exitLineNeg,
                  label: 'Exit -',
                  showMark: false,
                  color: '#f59e0b',
                  yAxisId: 'zscore',
                },
              ]),
        ]}
        height={300}
      />
      {cycleSummary.length ? (
        <Box sx={{ mt: 1 }}>
          <Typography variant="caption" color="text.secondary">
            Cycles
          </Typography>
          {cycleSummary.map((item) => (
            <Typography key={item.cycle} variant="caption" display="block">
              #{item.cycle}: entry {item.entry ?? '—'} · exit {item.exit ?? '—'} · return{' '}
              {typeof item.returnPct === 'number' ? `${item.returnPct.toFixed(2)}%` : '—'}
            </Typography>
          ))}
        </Box>
      ) : null}
    </Box>
  )
}
