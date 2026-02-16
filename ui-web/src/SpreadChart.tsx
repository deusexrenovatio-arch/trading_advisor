import CloseFullscreenIcon from '@mui/icons-material/CloseFullscreen'
import OpenInFullIcon from '@mui/icons-material/OpenInFull'
import {
  Box,
  Dialog,
  DialogContent,
  IconButton,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material'
import { useEffect, useMemo, useRef, useState } from 'react'

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

type MarkerPoint = {
  ts: number
  spread: number
}

type Candle = {
  ts: number
  open: number
  high: number
  low: number
  close: number
  hasEntry: boolean
  hasExit: boolean
  entryMarkers: MarkerPoint[]
  exitMarkers: MarkerPoint[]
}

const DEFAULT_CHART_HEIGHT = 440
const FULLSCREEN_CHART_HEIGHT = 720
const CHART_MIN_WIDTH = 760
const CHART_MAX_WIDTH = 18000
const PAD_TOP = 16
const PAD_RIGHT = 16
const PAD_BOTTOM = 32
const PAD_LEFT = 56
const CANDLE_LIMIT = 4000
const TOOLTIP_WIDTH = 250
const TOOLTIP_HEIGHT = 110
const NORMAL_VIEWPORT_HORIZONTAL_GUTTER = 80
const INTERVAL_MIN_CANDLE_WIDTH: Record<CandleInterval, number> = {
  '1D': 14,
  '1H': 7,
  '5m': 4,
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

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
    const markerTs = row.ts.getTime()
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
        entryMarkers: row.hasEntry ? [{ ts: markerTs, spread: row.spread }] : [],
        exitMarkers: row.hasExit ? [{ ts: markerTs, spread: row.spread }] : [],
      })
      continue
    }
    if (row.spread > last.high) last.high = row.spread
    if (row.spread < last.low) last.low = row.spread
    last.close = row.spread
    last.hasEntry = last.hasEntry || row.hasEntry
    last.hasExit = last.hasExit || row.hasExit
    if (row.hasEntry) last.entryMarkers.push({ ts: markerTs, spread: row.spread })
    if (row.hasExit) last.exitMarkers.push({ ts: markerTs, spread: row.spread })
  }

  if (candles.length <= CANDLE_LIMIT) return candles
  return candles.slice(candles.length - CANDLE_LIMIT)
}

const useContainerWidth = (active = true) => {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const element = containerRef.current
    if (!element || !active) return undefined
    const update = () => {
      const next = Math.floor(element.clientWidth)
      if (next > 0) setWidth(next)
    }
    update()
    const observer = new ResizeObserver(() => update())
    observer.observe(element)
    return () => observer.disconnect()
  }, [active])

  return { containerRef, width }
}

type ChartCanvasProps = {
  candles: Candle[]
  interval: CandleInterval
  chartHeight: number
  chartWidth: number
  svgWidth: number | string
}

const ChartCanvas = ({ candles, interval, chartHeight, chartWidth, svgWidth }: ChartCanvasProps) => {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const plotWidth = Math.max(chartWidth - PAD_LEFT - PAD_RIGHT, 1)
  const plotHeight = Math.max(chartHeight - PAD_TOP - PAD_BOTTOM, 1)
  const candleStep = candles.length > 0 ? plotWidth / candles.length : plotWidth
  const bodyWidth = Math.max(Math.min(candleStep * 0.68, 11), 1)

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
  const priceSpan = Math.max(priceRange.max - priceRange.min, 1e-9)
  const toY = (value: number) => PAD_TOP + ((priceRange.max - value) / priceSpan) * plotHeight

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

  const hoveredCandle = hoverIndex != null ? candles[hoverIndex] : null
  const hoverCenterX = hoverIndex != null ? PAD_LEFT + (hoverIndex + 0.5) * candleStep : null
  const hoverCloseY = hoveredCandle ? toY(hoveredCandle.close) : null
  const tooltipX =
    hoverCenterX == null
      ? PAD_LEFT + 8
      : clamp(hoverCenterX + 12, PAD_LEFT + 8, chartWidth - TOOLTIP_WIDTH - 8)
  const tooltipY =
    hoverCloseY == null
      ? PAD_TOP + 8
      : clamp(hoverCloseY - TOOLTIP_HEIGHT * 0.6, PAD_TOP + 8, chartHeight - PAD_BOTTOM - TOOLTIP_HEIGHT - 8)

  const formatPrice = (value: number) => value.toFixed(4)
  const minLabel = formatPrice(priceRange.min)
  const midLabel = formatPrice((priceRange.max + priceRange.min) / 2)
  const maxLabel = formatPrice(priceRange.max)

  const handleMouseMove = (event: React.MouseEvent<SVGRectElement>) => {
    if (!candles.length) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const widthRatio = bounds.width > 0 ? plotWidth / bounds.width : 1
    const localX = (event.clientX - bounds.left) * widthRatio
    const clampedX = clamp(localX, 0, plotWidth - 1)
    const relative = clampedX / plotWidth
    const index = clamp(Math.floor(relative * candles.length), 0, candles.length - 1)
    setHoverIndex(index)
  }

  return (
    <svg
      width={svgWidth}
      height={chartHeight}
      viewBox={`0 0 ${chartWidth} ${chartHeight}`}
      role="img"
      aria-label="Spread candlestick chart"
    >
      <line
        x1={PAD_LEFT}
        y1={PAD_TOP}
        x2={PAD_LEFT}
        y2={chartHeight - PAD_BOTTOM}
        stroke="#9ca3af"
        strokeWidth={1}
      />
      <line
        x1={PAD_LEFT}
        y1={chartHeight - PAD_BOTTOM}
        x2={chartWidth - PAD_RIGHT}
        y2={chartHeight - PAD_BOTTOM}
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
        y1={chartHeight - PAD_BOTTOM}
        x2={chartWidth - PAD_RIGHT}
        y2={chartHeight - PAD_BOTTOM}
        stroke="#e5e7eb"
        strokeWidth={1}
      />
      <text x={6} y={PAD_TOP + 4} fontSize={11} fill="#6b7280">
        {maxLabel}
      </text>
      <text x={6} y={PAD_TOP + plotHeight / 2 + 4} fontSize={11} fill="#6b7280">
        {midLabel}
      </text>
      <text x={6} y={chartHeight - PAD_BOTTOM + 4} fontSize={11} fill="#6b7280">
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

            {candle.entryMarkers.slice(0, 3).map((marker, markerIdx) => {
              const y = toY(marker.spread) - 7 - markerIdx * 6
              const points = `${centerX},${y} ${centerX - 4},${y + 7} ${centerX + 4},${y + 7}`
              return <polygon key={`entry-${marker.ts}-${markerIdx}`} points={points} fill="#0f766e" />
            })}

            {candle.exitMarkers.slice(0, 3).map((marker, markerIdx) => {
              const y = toY(marker.spread) + 7 + markerIdx * 6
              const points = `${centerX},${y} ${centerX - 4},${y - 7} ${centerX + 4},${y - 7}`
              return <polygon key={`exit-${marker.ts}-${markerIdx}`} points={points} fill="#7c2d12" />
            })}
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
              y1={chartHeight - PAD_BOTTOM}
              x2={x}
              y2={chartHeight - PAD_BOTTOM + 4}
              stroke="#9ca3af"
              strokeWidth={1}
            />
            <text x={x} y={chartHeight - 8} textAnchor="middle" fontSize={10} fill="#6b7280">
              {formatCandleTs(candle.ts, interval)}
            </text>
          </g>
        )
      })}

      {hoveredCandle && hoverCenterX != null && hoverCloseY != null ? (
        <g>
          <line
            x1={hoverCenterX}
            y1={PAD_TOP}
            x2={hoverCenterX}
            y2={chartHeight - PAD_BOTTOM}
            stroke="#334155"
            strokeWidth={1}
            strokeDasharray="4 3"
          />
          <circle cx={hoverCenterX} cy={hoverCloseY} r={3.2} fill="#1d4ed8" />
          <rect
            x={tooltipX}
            y={tooltipY}
            rx={6}
            ry={6}
            width={TOOLTIP_WIDTH}
            height={TOOLTIP_HEIGHT}
            fill="#111827"
            fillOpacity={0.92}
          />
          <text x={tooltipX + 8} y={tooltipY + 18} fontSize={11} fill="#f8fafc">
            {formatCandleTs(hoveredCandle.ts, interval)}
          </text>
          <text x={tooltipX + 8} y={tooltipY + 36} fontSize={11} fill="#f8fafc">
            O {formatPrice(hoveredCandle.open)}  H {formatPrice(hoveredCandle.high)}
          </text>
          <text x={tooltipX + 8} y={tooltipY + 52} fontSize={11} fill="#f8fafc">
            L {formatPrice(hoveredCandle.low)}  C {formatPrice(hoveredCandle.close)}
          </text>
          <text x={tooltipX + 8} y={tooltipY + 68} fontSize={11} fill="#93c5fd">
            Buy points: {hoveredCandle.entryMarkers.length}
          </text>
          <text x={tooltipX + 8} y={tooltipY + 84} fontSize={11} fill="#fdba74">
            Sell points: {hoveredCandle.exitMarkers.length}
          </text>
        </g>
      ) : null}

      <rect
        x={PAD_LEFT}
        y={PAD_TOP}
        width={plotWidth}
        height={plotHeight}
        fill="transparent"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIndex(null)}
      />
    </svg>
  )
}

export default function SpreadChart({ data }: SpreadChartProps) {
  const [interval, setInterval] = useState<CandleInterval>('1H')
  const [isFullscreen, setIsFullscreen] = useState(false)
  const { containerRef, width: containerWidth } = useContainerWidth(true)

  const candles = useMemo(() => aggregateCandles(data, interval), [data, interval])
  const latestClose = candles.length ? candles[candles.length - 1].close : null

  const cycleSummary = useMemo(() => {
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
  }, [data])

  const formatPct = (value?: number | null) => (value == null ? '--' : `${(value * 100).toFixed(2)}%`)
  const formatCash = (value?: number | null) => (value == null ? '--' : Number(value).toFixed(2))
  const formatPrice = (value: number) => value.toFixed(4)

  const renderChart = (fullscreenMode: boolean) => {
    const chartHeight = fullscreenMode ? FULLSCREEN_CHART_HEIGHT : DEFAULT_CHART_HEIGHT
    const minCandleWidth = INTERVAL_MIN_CANDLE_WIDTH[interval]
    const intrinsicWidth = PAD_LEFT + PAD_RIGHT + candles.length * minCandleWidth
    const viewportInnerWidth =
      typeof window !== 'undefined' ? Math.max(window.innerWidth, 320) : CHART_MIN_WIDTH
    const fullscreenWidth = Math.max(viewportInnerWidth - 64, CHART_MIN_WIDTH)
    const normalViewportCap = Math.max(viewportInnerWidth - NORMAL_VIEWPORT_HORIZONTAL_GUTTER, 320)
    const resolvedContainerWidth = containerWidth > 0 ? containerWidth : normalViewportCap
    const viewportWidth = fullscreenMode
      ? fullscreenWidth
      : Math.min(resolvedContainerWidth, normalViewportCap)
    const chartWidth = fullscreenMode
      ? clamp(Math.max(intrinsicWidth, viewportWidth), CHART_MIN_WIDTH, CHART_MAX_WIDTH)
      : Math.max(viewportWidth, 320)
    const svgWidth: number | string = fullscreenMode ? chartWidth : '100%'

    if (!candles.length) {
      return (
        <Typography variant="body2" color="text.secondary">
          Нет данных для построения свечей.
        </Typography>
      )
    }

    return (
      <Box
        sx={{
          width: '100%',
          maxWidth: '100%',
          minWidth: 0,
          overflow: 'hidden',
          overflowX: fullscreenMode ? 'auto' : 'hidden',
          border: '1px solid',
          borderColor: 'divider',
          borderRadius: 1,
        }}
      >
        <ChartCanvas
          candles={candles}
          interval={interval}
          chartHeight={chartHeight}
          chartWidth={chartWidth}
          svgWidth={svgWidth}
        />
      </Box>
    )
  }

  if (!data.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        Нет данных по спреду.
      </Typography>
    )
  }

  return (
    <Box ref={containerRef} sx={{ width: '100%', maxWidth: '100%', minWidth: 0 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }} useFlexGap flexWrap="wrap">
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
          aria-label="Candle timeframe"
        >
          <ToggleButton value="1D" aria-label="Candle interval 1D">
            1 день
          </ToggleButton>
          <ToggleButton value="1H" aria-label="Candle interval 1H">
            1 час
          </ToggleButton>
          <ToggleButton value="5m" aria-label="Candle interval 5m">
            5 минут
          </ToggleButton>
        </ToggleButtonGroup>
        <Typography variant="caption" color="text.secondary">
          {candles.length} свечей ({intervalLabel(interval)})
        </Typography>
        {latestClose != null ? (
          <Typography variant="caption" color="text.secondary">
            Текущее значение: {formatPrice(latestClose)}
          </Typography>
        ) : null}
        <Tooltip title="Fullscreen">
          <IconButton size="small" onClick={() => setIsFullscreen(true)} aria-label="Fullscreen spread chart">
            <OpenInFullIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      {renderChart(false)}

      <Dialog fullScreen open={isFullscreen} onClose={() => setIsFullscreen(false)}>
        <DialogContent sx={{ p: 2 }}>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }} useFlexGap flexWrap="wrap">
            <Typography variant="subtitle1" fontWeight={600}>
              Spread chart (fullscreen)
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {candles.length} candles ({intervalLabel(interval)})
            </Typography>
            <Box sx={{ flexGrow: 1 }} />
            <Tooltip title="Close fullscreen">
              <IconButton size="small" onClick={() => setIsFullscreen(false)} aria-label="Close fullscreen">
                <CloseFullscreenIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
          {renderChart(true)}
        </DialogContent>
      </Dialog>

      {cycleSummary.length ? (
        <Box sx={{ mt: 1 }}>
          <Typography variant="caption" color="text.secondary">
            Сделки
          </Typography>
          {cycleSummary.map((item) => (
            <Typography key={item.cycle} variant="caption" display="block" sx={{ whiteSpace: 'normal' }}>
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
