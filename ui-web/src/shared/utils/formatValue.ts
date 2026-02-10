import { fieldMeta } from '../metadata/fieldMeta'
import { formatNumber } from './format'
import { getFieldLabel, getValueLabel } from './field'

const percentColumns = new Set([
  'spread_pct',
  'rtc_pct',
  'floor_rate_annual',
  'score_floor',
  'score_alpha',
  'total_score',
  'signal_score',
  'expected_return',
  'p_hit_tp',
  'p_hit_sl',
  'r_cb_annual',
  'r_fund_annual',
  'r_disc_annual',
  'implied_rate_net',
  'required_rate',
  'tp_pct',
  'sl_pct',
  'tp_net',
  'sl_net',
  'spread_pct_entry_exec',
  'spread_pct_exit_exec',
  'pnl_spread_pct',
  'entry_spread_exec_pct',
  'entry_spread_pct_exec',
  'exit_spread_pct_exec',
  'trail_peak_spread_pct',
  'share_alpha_exits',
  'avg_trade_return_annual_recent',
  'trade_return_pct',
  'trade_return_pct_net',
  'trade_return_annual',
  'cagr',
  'hit_rate',
  'max_drawdown',
  'drawdown',
  'expected_net_irr',
  'spread_vol_pct',
  'entry_price_tolerance_pct',
  'entry_spread_pct_min',
  'entry_spread_pct_max',
  'tp_spread_pct_level',
  'sl_spread_pct_level',
  'forecast_tp_probability',
  'forecast_sl_probability',
])

const alreadyPercentColumns = new Set(['cycle_return_pct'])

const columnDigits: Record<string, number> = {
  spot: 2,
  future_price: 2,
  spread_mid: 4,
  spread_pct: 4,
  rtc_pct: 4,
  floor_rate_annual: 4,
  score_floor: 4,
  score_alpha: 4,
  total_score: 4,
  p_hit_tp: 3,
  p_hit_sl: 3,
  sigma_h: 4,
  half_life: 3,
  spread_bps_stock: 2,
  spread_bps_fut: 2,
  dollar_vol_stock: 0,
  dollar_vol_fut: 0,
  days_to_exit: 2,
  open_interest: 0,
  r_cb_annual: 2,
  r_fund_annual: 2,
  r_disc_annual: 2,
  tp_net: 4,
  sl_net: 4,
  signal_score: 4,
  signal_score_norm: 3,
  score: 4,
  turnover: 2,
  sharpe: 2,
  cost_round_trip: 2,
  entry_stock_min: 2,
  entry_stock_max: 2,
  entry_future_min_per_share: 2,
  entry_future_max_per_share: 2,
  entry_spread_min: 4,
  entry_spread_max: 4,
  tp_spread_level: 4,
  sl_spread_level: 4,
  tp_stock_level_if_fut_const: 2,
  sl_stock_level_if_fut_const: 2,
  tp_future_level_if_stock_const: 2,
  sl_future_level_if_stock_const: 2,
  forecast_exit_days: 0,
  orderbook_stock_min_depth: 0,
  orderbook_fut_min_depth: 0,
  orderbook_stock_quote_age_sec: 0,
  orderbook_fut_quote_age_sec: 0,
  orderbook_stock_imbalance: 2,
  orderbook_fut_imbalance: 2,
  stock_buy_max: 2,
  stock_sell_min: 2,
  future_buy_max_per_share: 2,
  future_sell_min_per_share: 2,
  future_buy_max_contract: 2,
  future_sell_min_contract: 2,
  spread_min: 4,
  spread_max: 4,
  qty_fut_contracts: 0,
  qty_stock_shares: 0,
  min_session_volume_stock: 0,
  min_session_volume_fut_contracts: 0,
  stock_price_hits: 0,
  fut_price_hits: 0,
  spread_hits: 0,
  sync_hits: 0,
  stock_volume_hits: 0,
  fut_volume_hits: 0,
  snapshots: 0,
  required: 0,
}

export const toNumeric = (value: unknown) => {
  if (typeof value === 'number') return value
  if (typeof value !== 'string') return Number.NaN
  const cleaned = value.replace('%', '').replace(',', '.').trim()
  const parsed = Number(cleaned)
  return Number.isNaN(parsed) ? Number.NaN : parsed
}

export const compareValues = (left: unknown, right: unknown) => {
  if (left === null || left === undefined) return right === null || right === undefined ? 0 : 1
  if (right === null || right === undefined) return -1
  const leftNum = toNumeric(left)
  const rightNum = toNumeric(right)
  if (!Number.isNaN(leftNum) && !Number.isNaN(rightNum)) {
    return leftNum - rightNum
  }
  return String(left).localeCompare(String(right))
}

export const formatValue = (value: unknown, column?: string): string => {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) {
    return value.map((item) => formatValue(item, column)).join(', ')
  }
  if (typeof value === 'boolean') {
    return value ? 'Да' : 'Нет'
  }
  if (column === 'status') {
    if (typeof value === 'string') {
      const mapped = getValueLabel(column, value)
      return mapped ?? value
    }
    if (typeof value === 'number') return String(value)
  }
  if (typeof value === 'string') {
    const mapped = getValueLabel(column, value)
    if (mapped) return mapped
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (!entries.length) return '—'
    return entries
      .map(([key, item]) => `${getFieldLabel(key)}: ${formatValue(item, key)}`)
      .join(', ')
  }
  const numeric = toNumeric(value)
  const meta = column ? fieldMeta[column] : undefined
  if (!Number.isNaN(numeric)) {
    if (meta?.format === 'percent' || (column && percentColumns.has(column))) {
      const scaled = column && alreadyPercentColumns.has(column) ? numeric : numeric * 100
      return `${formatNumber(scaled, meta?.digits ?? 2)}%`
    }
    if (meta?.format === 'bps') {
      return `${formatNumber(numeric, meta?.digits ?? 2)} б.п.`
    }
    if (meta?.format === 'currency') {
      return `${formatNumber(numeric, meta?.digits ?? 2)} ?`
    }
    if (meta?.format === 'days') {
      return `${formatNumber(numeric, meta?.digits ?? 0)} дн.`
    }
  }
  if (!Number.isNaN(numeric)) {
    const digits = meta?.digits ?? (column && column in columnDigits ? columnDigits[column] : 4)
    return formatNumber(numeric, digits)
  }
  return String(value)
}

export const formatCellValue = (value: unknown, column?: string): string => formatValue(value, column)
