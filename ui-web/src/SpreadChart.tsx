import { useMemo, useState } from 'react'
import { Box, Stack, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'

type SpreadPoint = {
  date: string
  exec_ts?: string | null
  spread_mid?: number | null
  spread_pct?: number | null
  spread?: number | null
  entry_flag?: boolean | null
  exit_flag?: boolean | null
  trade_cycle?: number | null
  trade_return_pct?: number | null
  trade_pnl_cash?: number | null
  trade_return_pct_net?: number | null
  trade_return_annual?: number | null
  trade_return_annual_fill_to_fill?: number | null
  trade_return_annual_operational?: number | null
  annual_target_threshold?: number | null
  annual_target_pass?: boolean | null
  trade_hold_days?: number | null
}

type SpreadChartProps = {
  data: SpreadPoint[]
}

type CandleInterval = '1D' | '1H' | '5m'

type Candle = {
  ts: number
  open: number
  high: number
  low: number
  close: number
  hasEntry: boolean
  hasExit: boolean
}

const CHART_HEIGHT = 440
const CHART_BASE_WIDTH = 1200
const CHART_MAX_WIDTH = 18000
const PAD_TOP = 16
const PAD_RIGHT = 16
const PAD_BOTTOM = 30
const PAD_LEFT = 56
const CANDLE_LIMIT = 4000
const INTERVAL_MIN_CANDLE_WIDTH: Record<CandleInterval, number> = {
  '1D': 14,
  '1H': 7,
  '5m': 4,
}

const parseTs = (value?: string | null): Date | null => {
  if (!value) return null
  const normalized = value.includes('T') ? value : value.replace(' ', 'T')
  const parsed = new Date(normalized)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

const toBucketTs = (ts: Date, interval: CandleInterval): number => {
  const bucket = new Date(ts)
  if (interval === '1D') {
    bucket.setHours(0, 0, 0, 0)
    return bucket.getTime()
  }
  if (interval === '1H') {
    bucket.setMinutes(0, 0, 0)
    return bucket.getTime()
  }
  bucket.setMinutes(Math.floor(bucket.getMinutes() / 5) * 5, 0, 0)
  return bucket.getTime()
}

const intervalLabel = (interval: CandleInterval) => {
  if (interval === '1D') return '1 день'
  if (interval === '1H') return '1 час'
  return '5 минут'
}

const formatCandleTs = (ts: number, interval: CandleInterval) => {
  const date = new Date(ts)
  if (interval === '1D') return date.toLocaleDateString('ru-RU')
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const aggregateCandles = (data: SpreadPoint[], interval: CandleInterval): Candle[] => {
  const rows = data
    .map((point) => {
      const ts = parseTs(point.exec_ts ?? point.date)
      const spreadRaw = point.spread_mid ?? point.spread
      const spread = typeof spreadRaw === 'number' ? spreadRaw : null
      if (!ts || spread == null || Number.isNaN(spread)) return null
      return {
        ts,
        spread,
        hasEntry: Boolean(point.entry_flag),
        hasExit: Boolean(point.exit_flag),
      }
    })
    .filter(
      (
        row,
      ): row is { ts: Date; spread: number; hasEntry: boolean; hasExit: boolean } => row !== null,
    )
    .sort((left, right) => left.ts.getTime() - right.ts.getTime())

  const candles: Candle[] = []
  for (const row of rows) {
    const bucketTs = toBucketTs(row.ts, interval)
    const last = candles[candles.length - 1]
    if (!last || last.ts !== bucketTs) {
      candles.push({
        ts: bucketTs,
        open: row.spread,
        high: row.spread,
        low: row.spread,
        close: row.spread,
        hasEntry: row.hasEntry,
        hasExit: row.hasExit,
      })
      continue
    }
    if (row.spread > last.high) last.high = row.spread
    if (row.spread < last.low) last.low = row.spread
    last.close = row.spread
    last.hasEntry = last.hasEntry || row.hasEntry
    last.hasExit = last.hasExit || row.hasExit
  }

  if (candles.length <= CANDLE_LIMIT) return candles
  return candles.slice(candles.length - CANDLE_LIMIT)
}

export default function SpreadChart({ data }: SpreadChartProps) {
  const [interval, setInterval] = useState<CandleInterval>('1H')

  const candles = useMemo(() => aggregateCandles(data, interval), [data, interval])

  const priceRange = useMemo(() => {
    if (!candles.length) return { min: 0, max: 1 }
    const min = Math.min(...candles.map((item) => item.low))
    const max = Math.max(...candles.map((item) => item.high))
    if (min === max) {
      const delta = Math.abs(min) > 0 ? Math.abs(min) * 0.02 : 1
      return { min: min - delta, max: max + delta }
    }
    const pad = (max - min) * 0.06
    return { min: min - pad, max: max + pad }
  }, [candles])

  const formatPrice = (value: number) => value.toFixed(4)

  const chartWidth = Math.min(
    Math.max(CHART_BASE_WIDTH, PAD_LEFT + PAD_RIGHT + candles.length * INTERVAL_MIN_CANDLE_WIDTH[interval]),
    CHART_MAX_WIDTH,
  )
  const plotWidth = chartWidth - PAD_LEFT - PAD_RIGHT
  const plotHeight = CHART_HEIGHT - PAD_TOP - PAD_BOTTOM
  const candleStep = candles.length > 0 ? plotWidth / candles.length : plotWidth
  const bodyWidth = Math.max(Math.min(candleStep * 0.68, 11), 1)
  const priceSpan = priceRange.max - priceRange.min
  const toY = (value: number) => PAD_TOP + ((priceRange.max - value) / priceSpan) * plotHeight

  const cycleSummary = (() => {
    const map = new Map<
      number,
      {
        entry?: string
        exit?: string
        returnPct?: number | null
        pnlCash?: number | null
        returnNet?: number | null
        returnAnn?: number | null
        returnAnnOperational?: number | null
        annualTarget?: number | null
        annualTargetPass?: boolean | null
        holdDays?: number | null
      }
    >()
    data.forEach((point) => {
      const pointTs = point.exec_ts ?? point.date
      if (point.trade_cycle == null) return
      const entry = map.get(point.trade_cycle) ?? {}
      if (point.entry_flag) entry.entry = pointTs
      if (point.exit_flag) {
        entry.exit = pointTs
        if (typeof point.trade_return_pct === 'number') entry.returnPct = point.trade_return_pct
        if (typeof point.trade_pnl_cash === 'number') entry.pnlCash = point.trade_pnl_cash
        if (typeof point.trade_return_pct_net === 'number') entry.returnNet = point.trade_return_pct_net
        if (typeof point.trade_return_annual === 'number') entry.returnAnn = point.trade_return_annual
        if (typeof point.trade_return_annual_operational === 'number') {
          entry.returnAnnOperational = point.trade_return_annual_operational
        }
        if (typeof point.annual_target_threshold === 'number') {
          entry.annualTarget = point.annual_target_threshold
        }
        if (typeof point.annual_target_pass === 'boolean') entry.annualTargetPass = point.annual_target_pass
        if (typeof point.trade_hold_days === 'number') entry.holdDays = point.trade_hold_days
      }
      map.set(point.trade_cycle, entry)
    })
    return Array.from(map.entries())
      .map(([cycle, value]) => ({ cycle, ...value }))
      .sort((a, b) => a.cycle - b.cycle)
  })()

  const formatPct = (value?: number | null) => (value == null ? '--' : `${(value * 100).toFixed(2)}%`)
  const formatCash = (value?: number | null) => (value == null ? '--' : Number(value).toFixed(2))

  const tickIndices = useMemo(() => {
    if (!candles.length) return []
    if (candles.length <= 8) return candles.map((_, index) => index)
    const count = 8
    const indexes: number[] = []
    for (let i = 0; i < count; i += 1) {
      indexes.push(Math.round((i * (candles.length - 1)) / (count - 1)))
    }
    return Array.from(new Set(indexes))
  }, [candles])

  const minLabel = formatPrice(priceRange.min)
  const midLabel = formatPrice((priceRange.max + priceRange.min) / 2)
  const maxLabel = formatPrice(priceRange.max)

  if (!data.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        Нет данных по спреду.
      </Typography>
    )
  }

  return (
    <Box sx={{ width: '100%', minHeight: CHART_HEIGHT }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <Typography variant="caption" color="text.secondary">
          Таймфрейм
        </Typography>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={interval}
          onChange={(_, value) => {
            if (value) setInterval(value)
          }}
          aria-label="Таймфрейм свечей"
        >
          <ToggleButton value="1D">1 день</ToggleButton>
          <ToggleButton value="1H">1 час</ToggleButton>
          <ToggleButton value="5m">5 минут</ToggleButton>
        </ToggleButtonGroup>
        <Typography variant="caption" color="text.secondary">
          {candles.length} свечей ({intervalLabel(interval)})
        </Typography>
      </Stack>
      {!candles.length ? (
        <Typography variant="body2" color="text.secondary">
          Нет данных для построения свечей.
        </Typography>
      ) : (
        <Box
          sx={{
            width: '100%',
            overflowX: 'auto',
            border: '1px solid',
            borderColor: 'divider',
            borderRadius: 1,
          }}
        >
          <svg width={chartWidth} height={CHART_HEIGHT} role="img" aria-label="Свечной график спреда">
            <line
              x1={PAD_LEFT}
              y1={PAD_TOP}
              x2={PAD_LEFT}
              y2={CHART_HEIGHT - PAD_BOTTOM}
              stroke="#9ca3af"
              strokeWidth={1}
            />
            <line
              x1={PAD_LEFT}
              y1={CHART_HEIGHT - PAD_BOTTOM}
              x2={chartWidth - PAD_RIGHT}
              y2={CHART_HEIGHT - PAD_BOTTOM}
              stroke="#9ca3af"
              strokeWidth={1}
            />
            <line
              x1={PAD_LEFT}
              y1={PAD_TOP}
              x2={chartWidth - PAD_RIGHT}
              y2={PAD_TOP}
              stroke="#e5e7eb"
              strokeWidth={1}
            />
            <line
              x1={PAD_LEFT}
              y1={PAD_TOP + plotHeight / 2}
              x2={chartWidth - PAD_RIGHT}
              y2={PAD_TOP + plotHeight / 2}
              stroke="#e5e7eb"
              strokeWidth={1}
            />
            <line
              x1={PAD_LEFT}
              y1={CHART_HEIGHT - PAD_BOTTOM}
              x2={chartWidth - PAD_RIGHT}
              y2={CHART_HEIGHT - PAD_BOTTOM}
              stroke="#e5e7eb"
              strokeWidth={1}
            />
            <text x={6} y={PAD_TOP + 4} fontSize={11} fill="#6b7280">
              {maxLabel}
            </text>
            <text x={6} y={PAD_TOP + plotHeight / 2 + 4} fontSize={11} fill="#6b7280">
              {midLabel}
            </text>
            <text x={6} y={CHART_HEIGHT - PAD_BOTTOM + 4} fontSize={11} fill="#6b7280">
              {minLabel}
            </text>
            {candles.map((candle, index) => {
              const centerX = PAD_LEFT + (index + 0.5) * candleStep
              const yOpen = toY(candle.open)
              const yClose = toY(candle.close)
              const yHigh = toY(candle.high)
              const yLow = toY(candle.low)
              const bullish = candle.close >= candle.open
              const bodyY = Math.min(yOpen, yClose)
              const bodyH = Math.max(Math.abs(yClose - yOpen), 1.5)
              const color = bullish ? '#16a34a' : '#dc2626'
              return (
                <g key={`${candle.ts}-${index}`}>
                  <line x1={centerX} y1={yHigh} x2={centerX} y2={yLow} stroke={color} strokeWidth={1} />
                  <rect
                    x={centerX - bodyWidth / 2}
                    y={bodyY}
                    width={bodyWidth}
                    height={bodyH}
                    fill={bullish ? '#16a34a66' : '#dc262666'}
                    stroke={color}
                    strokeWidth={1}
                  />
                  {candle.hasEntry ? (
                    <circle cx={centerX} cy={Math.max(yClose - 6, PAD_TOP + 5)} r={2.4} fill="#0f766e" />
                  ) : null}
                  {candle.hasExit ? (
                    <circle
                      cx={centerX}
                      cy={Math.min(yClose + 6, CHART_HEIGHT - PAD_BOTTOM - 5)}
                      r={2.4}
                      fill="#7c2d12"
                    />
                  ) : null}
                </g>
              )
            })}
            {tickIndices.map((index) => {
              const candle = candles[index]
              const x = PAD_LEFT + (index + 0.5) * candleStep
              return (
                <g key={`tick-${candle.ts}`}>
                  <line
                    x1={x}
                    y1={CHART_HEIGHT - PAD_BOTTOM}
                    x2={x}
                    y2={CHART_HEIGHT - PAD_BOTTOM + 4}
                    stroke="#9ca3af"
                    strokeWidth={1}
                  />
                  <text x={x} y={CHART_HEIGHT - 8} textAnchor="middle" fontSize={10} fill="#6b7280">
                    {formatCandleTs(candle.ts, interval)}
                  </text>
                </g>
              )
            })}
          </svg>
        </Box>
      )}
      {cycleSummary.length ? (
        <Box sx={{ mt: 1 }}>
          <Typography variant="caption" color="text.secondary">
            Сделки
          </Typography>
          {cycleSummary.map((item) => (
            <Typography key={item.cycle} variant="caption" display="block">
              #{item.cycle}: вход {item.entry ?? '--'} | выход {item.exit ?? '--'} | PnL {formatCash(item.pnlCash)} |
              net {formatPct(item.returnNet)} | год. {formatPct(item.returnAnn)} | год. опер.{' '}
              {formatPct(item.returnAnnOperational)} | target {formatPct(item.annualTarget)} | pass{' '}
              {item.annualTargetPass == null ? '--' : item.annualTargetPass ? 'Yes' : 'No'} | держал{' '}
              {item.holdDays ?? '--'} дн.
            </Typography>
          ))}
        </Box>
      ) : null}
    </Box>
  )
}
