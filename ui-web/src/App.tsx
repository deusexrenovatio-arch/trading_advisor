import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  Container,
  Divider,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import {
  DataGrid,
  type GridColDef,
  type GridRowParams,
  GridToolbar,
} from '@mui/x-data-grid'
import { ruRU } from '@mui/x-data-grid/locales'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import SpreadChart from './SpreadChart'
import './App.css'

type AggregationSummary = {
  action?: string
  score?: number
  strategies?: string[]
  blocked_strategies?: string[]
}
type ProposalSummary = {
  type?: string
  cadence?: string
  effective_date?: string
  summary?: string
}
type BasketAllocation = {
  basket?: string
  weight?: number
}
type BasketSummary = {
  current?: BasketAllocation[]
  target?: BasketAllocation[]
  delta?: BasketAllocation[]
}
type OperatorAction = {
  action?: string
  status?: string
  actor?: string
  note?: string
  created_at?: string
}
type ExecutionStatus = {
  status?: string
  requested_at?: string
  executed_at?: string
}

type DecisionView = {
  decision_id: string
  decision_view_id?: string
  created_at?: string
  strategy_type?: string
  primary_instrument?: string
  action?: string
  risk_state?: string
  news_severity?: string
  cost_summary?: {
    round_trip_cost?: number
  }
  backtest_metrics?: {
    max_drawdown?: number
  }
  aggregation_summary?: AggregationSummary
  proposal_summary?: ProposalSummary
  basket_summary?: BasketSummary
  operator_action?: OperatorAction
  execution_status?: ExecutionStatus
}

type DecisionLog = Record<string, unknown>
type GenericRow = Record<string, unknown>
type SpreadSeriesPoint = {
  date: string
  spread_mid?: number | null
  spread_pct?: number | null
  spread?: number | null
  spot_mid?: number | null
  future_mid?: number | null
  pv_div?: number | null
  div_sum?: number | null
  rtc_pct?: number | null
  tp_net?: number | null
  sl_net?: number | null
  floor_rate_annual?: number | null
  floor_pass?: boolean | null
  liquidity_pass?: boolean | null
  entry_flag?: boolean | null
  exit_flag?: boolean | null
  trade_cycle?: number | null
  trade_return_pct?: number | null
  trade_pnl_cash?: number | null
  trade_return_pct_net?: number | null
  trade_return_annual?: number | null
  trade_hold_days?: number | null
  zscore?: number | null
}
type SignalHistoryRow = {
  run_id: string
  timestamp: string
  stock: string
  future: string
  signal_action: string
  signal_direction?: string | null
  signal_score: number
  signal_reasons?: string[]
  signal_metrics?: Record<string, unknown>
}
type ExecutionRow = {
  timestamp: string
  stock: string
  future: string
  direction?: string | null
  action: string
  price?: number | null
  quantity?: number | null
  side?: string | null
  status?: string | null
  note?: string | null
}
type RefreshStatus = {
  enabled?: boolean
  interval_sec?: number
  status?: string
  last_started_at?: string | null
  last_success_at?: string | null
  last_error?: string | null
  next_run_at?: string | null
}

type ParameterSpec = {
  key: string
  value_type: string
  default?: unknown
  min_value?: number | null
  max_value?: number | null
  options?: unknown[] | null
  description?: string | null
}

type ParamPrimitive = string | number | boolean | null
type ParamValue = ParamPrimitive | ParamPrimitive[] | Record<string, ParamPrimitive | unknown>

type BacktestEquityPoint = {
  date: string
  equity?: number | null
  cash?: number | null
  drawdown?: number | null
  turnover?: number | null
  positions?: number | null
}

type BacktestTrade = {
  pair_id: string
  stock_secid?: string | null
  future_secid?: string | null
  direction?: string | null
  entry_date?: string | null
  exit_date?: string | null
  entry_price_stock?: number | null
  entry_price_fut?: number | null
  exit_price_stock?: number | null
  exit_price_fut?: number | null
  quantity_stock?: number | null
  quantity_fut?: number | null
  pnl?: number | null
  hold_days?: number | null
  exit_reason?: string | null
}

type BacktestReport = {
  summary_metrics?: Record<string, unknown>
  equity_curve?: BacktestEquityPoint[]
  trades?: BacktestTrade[]
  resolved_config?: Record<string, unknown>
  warnings?: string[]
}

type ForwardStatus = {
  run_id?: string
  status?: string
  state?: Record<string, unknown>
  last_trade?: Record<string, unknown> | null
  last_equity?: Record<string, unknown> | null
  last_alert?: Record<string, unknown> | null
  run_meta?: Record<string, unknown>
}

type HpoTrial = {
  objective?: number
  params?: Record<string, unknown>
  fold_objectives?: number[]
  fold_results?: unknown[]
}

type HpoResponse = {
  status?: string
  message?: string
  mode?: string
  leaderboard?: HpoTrial[]
  trials?: HpoTrial[]
  result?: {
    mode?: string
    leaderboard?: HpoTrial[]
    trials?: HpoTrial[]
  }
}

const AUTO_REFRESH_MS = 60_000
const AUTO_REFRESH_LABEL = '60 с'

const formatNumber = (value?: number, digits = 2): string => {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return ''
  }
  return Number(value).toFixed(digits)
}

const formatDate = (value?: string): string => {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('ru-RU')
}

const parseDateInput = (value: string, bound: 'start' | 'end') => {
  const trimmed = value.trim()
  if (!trimmed) return null
  if (!trimmed.includes('T') && !trimmed.includes(' ')) {
    const parts = trimmed.split('-').map((item) => Number(item))
    if (parts.length !== 3 || parts.some((item) => Number.isNaN(item))) return null
    const [year, month, day] = parts
    const date = new Date(
      year,
      month - 1,
      day,
      bound === 'end' ? 23 : 0,
      bound === 'end' ? 59 : 0,
      bound === 'end' ? 59 : 0,
      bound === 'end' ? 999 : 0,
    )
    return Number.isNaN(date.getTime()) ? null : date.getTime()
  }
  const parsed = new Date(trimmed)
  return Number.isNaN(parsed.getTime()) ? null : parsed.getTime()
}

type FieldFormat = 'percent' | 'bps' | 'currency' | 'days'
type FieldMeta = {
  label: string
  tooltip?: string
  format?: FieldFormat
  digits?: number
}

const formatDateInputValue = (value: Date) => value.toISOString().slice(0, 10)

const humanizeKey = (value: string) =>
  value.replaceAll('_', ' ').replace(/\b\w/g, (match) => match.toUpperCase())

const fieldMeta: Record<string, FieldMeta> = {
  created_at: {
    label: 'Время',
    tooltip: 'Дата и время создания записи.',
  },
  decision_id: {
    label: 'ID решения',
    tooltip: 'Уникальный идентификатор решения.',
  },
  decision_view_id: {
    label: 'ID витрины',
    tooltip: 'Идентификатор записи decision_view.',
  },
  strategy_type: {
    label: 'Стратегия',
    tooltip: 'Тип стратегии, сформировавшей решение.',
  },
  primary_instrument: {
    label: 'Инструмент',
    tooltip: 'Основной инструмент решения.',
  },
  proposal_type: {
    label: 'Тип предложения',
    tooltip: 'Тип предложения оркестратора.',
  },
  action: {
    label: 'Действие',
    tooltip: 'Операционное решение (approve/reject/hold).',
  },
  risk_state: {
    label: 'Риск',
    tooltip: 'Оценка риска: зелёный/жёлтый/красный.',
  },
  news_severity: {
    label: 'Новости',
    tooltip: 'Сила новостного риска.',
  },
  execution_status: {
    label: 'Исполнение',
    tooltip: 'Текущий статус исполнения.',
  },
  cost_round_trip: {
    label: 'Стоимость round-trip',
    tooltip:
      'Формула: (buy_stock - sell_stock) + (buy_fut - sell_fut) + fees_rt. ' +
      'Полные издержки вход-выход.',
    digits: 2,
    format: 'currency',
  },
  basket: {
    label: 'Корзина',
    tooltip: 'Категория корзины стратегии.',
  },
  basket_weight: {
    label: 'Вес корзины, %',
    tooltip:
      'Формула: weight. ' +
      'Интерпретация: доля корзины в портфеле.',
    format: 'percent',
    digits: 2,
  },
  break_even_ticks: {
    label: 'Безубыток, тиков',
    tooltip:
      'Формула: break_even_ticks = round_trip_cost / tick_value. ' +
      'Интерпретация: сколько тиков нужно пройти, чтобы покрыть издержки.',
    digits: 2,
  },
  break_even_points: {
    label: 'Безубыток, пунктов',
    tooltip:
      'Формула: break_even_points = break_even_ticks * price_step. ' +
      'Интерпретация: требуемое движение цены в пунктах.',
    digits: 2,
  },
  max_drawdown: {
    label: 'Макс. просадка',
    tooltip:
      'Формула: min(equity / rolling_max - 1). ' +
      'Интерпретация: максимальная просадка капитала.',
    format: 'percent',
    digits: 2,
  },
  stock: {
    label: 'Акция',
    tooltip: 'Тикер акции.',
  },
  stock_name: {
    label: 'Название акции',
    tooltip: 'Краткое название эмитента.',
  },
  future: {
    label: 'Фьючерс',
    tooltip: 'Тикер фьючерсного контракта.',
  },
  expiry: {
    label: 'Экспирация',
    tooltip: 'Дата экспирации фьючерса.',
  },
  dte: {
    label: 'DTE (дней до экспирации)',
    tooltip: 'Количество дней до экспирации.',
    format: 'days',
    digits: 0,
  },
  spot: {
    label: 'Спот',
    tooltip: 'Текущая цена спота.',
    digits: 2,
  },
  future_price: {
    label: 'Цена фьючерса',
    tooltip: 'Текущая цена фьючерса.',
    digits: 2,
  },
  spread_mid: {
    label: 'Спред (mid)',
    tooltip:
      'Формула: (Spot_mid - PV(div) - Futures_mid). ' +
      'Интерпретация: абсолютный спред между спотом и фьючерсом.',
    digits: 4,
  },
  spread_pct: {
    label: 'Спред, %',
    tooltip:
      'Формула: spread_mid / spot_mid. ' +
      'Интерпретация: доля спреда относительно цены спота.',
    format: 'percent',
    digits: 2,
  },
  rtc_pct: {
    label: 'Издержки RT, %',
    tooltip:
      'Формула: rtc / spot_mid, где rtc = (buy_stock - sell_stock) + ' +
      '(buy_fut - sell_fut) + fees_rt. ' +
      'Интерпретация: доля round-trip издержек в цене спота.',
    format: 'percent',
    digits: 2,
  },
  floor_rate_annual: {
    label: 'Floor-ставка, % год.',
    tooltip:
      'Формула: (floor_pnl / capital_base) * 365 / DTE. ' +
      'Интерпретация: годовая carry-доходность при удержании до экспирации.',
    format: 'percent',
    digits: 2,
  },
  floor_pnl: {
    label: 'Floor PnL, ₽',
    tooltip:
      'Формула: (fut_sell - spot_buy) + div_sum - costs_hold. ' +
      'Интерпретация: ожидаемая прибыль floor-удержания до экспирации.',
    format: 'currency',
    digits: 2,
  },
  capital_base: {
    label: 'База капитала, ₽',
    tooltip:
      'Формула: FULL_CASH -> spot_buy; MARGIN_AWARE -> margin_stock + margin_fut + var_buffer. ' +
      'Интерпретация: капитал, на который нормируется floor_rate_annual.',
    format: 'currency',
    digits: 2,
  },
  costs_hold: {
    label: 'Издержки удержания, ₽',
    tooltip:
      'Формула: fees_rt + funding_cost + riskbuffer_floor. ' +
      'Интерпретация: ожидаемые издержки на удержание до экспирации.',
    format: 'currency',
    digits: 2,
  },
  score_floor: {
    label: 'Floor-скор',
    tooltip:
      'Формула: floor_rate_annual - r_cb_annual. ' +
      'Интерпретация: превышение над бенчмарком.',
    format: 'percent',
    digits: 2,
  },
  implied_rate_net: {
    label: 'Имплайд-ставка (net), % год.',
    tooltip:
      'Формула: (future_price + pv_div - spot) / (spot * tau). ' +
      'Интерпретация: implied ставка, скорректированная на дивиденды/издержки.',
    format: 'percent',
    digits: 2,
  },
  required_rate: {
    label: 'Требуемая ставка, % год.',
    tooltip:
      'Формула: required_rate (бенчмарк/ставка из настроек). ' +
      'Интерпретация: порог для сравнения с implied_rate_net.',
    format: 'percent',
    digits: 2,
  },
  score_alpha: {
    label: 'Alpha-скор',
    tooltip:
      'Формула: p_hit_tp * tp_net - p_hit_sl * sl_pct - rtc_pct. ' +
      'Интерпретация: ожидаемая alpha-доходность с учетом TP/SL и издержек.',
    format: 'percent',
    digits: 2,
  },
  total_score: {
    label: 'Итоговый скор',
    tooltip:
      'Формула: w1*score_floor + w2*score_alpha - w3*penalty_liq - w4*penalty_event. ' +
      'Интерпретация: итоговый скор пары (выше лучше).',
    digits: 4,
  },
  signal_score: {
    label: 'Скор сигнала',
    tooltip:
      'Формула: total_score. ' +
      'Интерпретация: скор сигнала для ранжирования.',
    digits: 4,
  },
  signal_score_norm: {
    label: 'Норм. скор сигнала',
    tooltip:
      'Формула: 0.5 * (|zscore| / z_entry + |implied_rate_net - required_rate| / implied_rate_buffer). ' +
      'Интерпретация: нормированная сила сигнала (выше = сильнее).',
    digits: 3,
  },
  signal_action: {
    label: 'Сигнал',
    tooltip: 'Действие по паре: вход/выход/держать.',
  },
  signal_direction: {
    label: 'Направление',
    tooltip: 'Тип позиции: cash-and-carry или reverse.',
  },
  signal_reasons: {
    label: 'Причины сигнала',
    tooltip: 'Список причин решения по сигналу.',
  },
  signal_metrics: {
    label: 'Метрики сигнала',
    tooltip: 'Метрики, использованные при расчёте сигнала.',
  },
  decision: {
    label: 'Решение',
    tooltip: 'Техническое решение: ENTER_OK / SKIP_*.',
  },
  floor_pass: {
    label: 'Floor-проход',
    tooltip: 'Истина, если floor_rate_annual ≥ r_cb_annual − floor_tolerance.',
  },
  liquidity_pass: {
    label: 'Ликвидность пройдена',
    tooltip: 'Истина, если пройдены пороги ликвидности (спреды, объёмы, OI, days_to_exit).',
  },
  r_cb_annual: {
    label: 'Ключевая ставка, % год.',
    tooltip: 'Ключевая ставка (r_cb).',
    format: 'percent',
    digits: 2,
  },
  r_fund_annual: {
    label: 'Ставка фондирования, % год.',
    tooltip: 'Ставка фондирования позиции.',
    format: 'percent',
    digits: 2,
  },
  r_disc_annual: {
    label: 'Ставка дисконт., % год.',
    tooltip: 'Ставка дисконтирования дивидендов.',
    format: 'percent',
    digits: 2,
  },
  expected_return: {
    label: 'Ожидаемая доходность, % год.',
    tooltip:
      'Формула: expected_return = floor_rate_annual. ' +
      'Интерпретация: ожидаемая годовая carry-доходность.',
    format: 'percent',
    digits: 2,
  },
  risk_estimate: {
    label: 'Оценка риска',
    tooltip:
      'Формула: risk_estimate = sigma_h (волатильность spread_pct на горизонте H). ' +
      'Интерпретация: риск-оценка стратегии.',
    digits: 4,
  },
  liquidity_score: {
    label: 'Ликвидность, скор',
    tooltip:
      'Формула: liquidity_score (0..1). ' +
      'Интерпретация: 0 - низкая, 1 - высокая ликвидность.',
    format: 'percent',
    digits: 1,
  },
  snapshot_as_of: {
    label: 'Снимок на',
    tooltip: 'Дата/время расчёта снимка.',
  },
  avg_trade_return_annual_recent: {
    label: 'Средн. годовая доходность (посл. 5)',
    tooltip:
      'Формула: mean(trade_return_annual последних 5 сделок). ' +
      'Интерпретация: средняя годовая доходность по последним выходам.',
    format: 'percent',
    digits: 2,
  },
  share_alpha_exits: {
    label: 'Доля alpha-выходов',
    tooltip:
      'Формула: alpha_exit_count / total_trades. ' +
      'Интерпретация: доля выходов по alpha-триггерам.',
    format: 'percent',
    digits: 2,
  },
  avg_hold_days: {
    label: 'Средн. дни удержания',
    tooltip:
      'Формула: mean(hold_days). ' +
      'Интерпретация: средняя длительность удержания позиции.',
    format: 'days',
    digits: 1,
  },
  p_hit_tp: {
    label: 'P(достиж. TP)',
    tooltip:
      'Формула: mean(1{MFE ≥ TP}) по окну H. ' +
      'Интерпретация: вероятность достижения take-profit.',
    format: 'percent',
    digits: 2,
  },
  p_hit_sl: {
    label: 'P(достиж. SL)',
    tooltip:
      'Формула: mean(1{MAE ≤ −SL}) по окну H. ' +
      'Интерпретация: вероятность достижения stop-loss.',
    format: 'percent',
    digits: 2,
  },
  sigma_h: {
    label: 'Сигма спреда (H)',
    tooltip:
      'Формула: σ(Δspread_pct) на горизонте H. ' +
      'Интерпретация: волатильность спреда на окне H.',
    digits: 4,
  },
  half_life: {
    label: 'Период полураспада',
    tooltip:
      'Формула: ln(2)/-ln(phi), где phi — коэффициент AR(1) spread_pct. ' +
      'Интерпретация: скорость возврата к среднему.',
    digits: 2,
  },
  mfe_q50: {
    label: 'MFE q50, %',
    tooltip:
      'Формула: медиана(max(spread_pct_window - entry)). ' +
      'Интерпретация: типичное благоприятное движение.',
    format: 'percent',
    digits: 2,
  },
  mfe_q75: {
    label: 'MFE q75, %',
    tooltip:
      'Формула: 75-й процентиль max(spread_pct_window - entry). ' +
      'Интерпретация: сильное благоприятное движение.',
    format: 'percent',
    digits: 2,
  },
  mfe_q90: {
    label: 'MFE q90, %',
    tooltip:
      'Формула: 90-й процентиль max(spread_pct_window - entry). ' +
      'Интерпретация: экстремальное благоприятное движение.',
    format: 'percent',
    digits: 2,
  },
  mae_q50: {
    label: 'MAE q50, %',
    tooltip:
      'Формула: медиана(min(spread_pct_window - entry)). ' +
      'Интерпретация: типичное неблагоприятное движение.',
    format: 'percent',
    digits: 2,
  },
  mae_q75: {
    label: 'MAE q75, %',
    tooltip:
      'Формула: 75-й процентиль min(spread_pct_window - entry). ' +
      'Интерпретация: сильное неблагоприятное движение.',
    format: 'percent',
    digits: 2,
  },
  mae_q90: {
    label: 'MAE q90, %',
    tooltip:
      'Формула: 90-й процентиль min(spread_pct_window - entry). ' +
      'Интерпретация: экстремальное неблагоприятное движение.',
    format: 'percent',
    digits: 2,
  },
  spread_bps_stock: {
    label: 'Спред акции, б.п.',
    tooltip:
      'Формула: (ask - bid) / mid * 10 000. ' +
      'Интерпретация: относительная ширина спреда акции.',
    format: 'bps',
    digits: 2,
  },
  spread_bps_fut: {
    label: 'Спред фьючерса, б.п.',
    tooltip:
      'Формула: (ask - bid) / mid * 10 000. ' +
      'Интерпретация: относительная ширина спреда фьючерса.',
    format: 'bps',
    digits: 2,
  },
  dollar_vol_stock: {
    label: 'Денежный объём акций',
    tooltip:
      'Формула: price * volume. ' +
      'Интерпретация: денежный оборот акций.',
    digits: 0,
  },
  dollar_vol_fut: {
    label: 'Денежный объём фьючерса',
    tooltip:
      'Формула: price * volume * multiplier. ' +
      'Интерпретация: денежный оборот фьючерса.',
    digits: 0,
  },
  days_to_exit: {
    label: 'Дней до выхода',
    tooltip:
      'Формула: position_notional / (avg_dollar_vol * participation_rate). ' +
      'Интерпретация: оценка времени выхода из позиции.',
    format: 'days',
    digits: 1,
  },
  open_interest: {
    label: 'Открытый интерес',
    tooltip: 'Количество открытых контрактов.',
    digits: 0,
  },
  tp_pct: {
    label: 'TP, %',
    tooltip:
      'Формула: TP_pct (параметр стратегии). ' +
      'Интерпретация: целевой профит по spread_pct.',
    format: 'percent',
    digits: 2,
  },
  sl_pct: {
    label: 'SL, %',
    tooltip:
      'Формула: SL_pct (параметр стратегии). ' +
      'Интерпретация: стоп-уровень по spread_pct.',
    format: 'percent',
    digits: 2,
  },
  tp_net: {
    label: 'TP net, %',
    tooltip:
      'Формула: TP_pct + rtc_pct. ' +
      'Интерпретация: TP с учётом издержек.',
    format: 'percent',
    digits: 2,
  },
  sl_net: {
    label: 'SL net, %',
    tooltip:
      'Формула: SL_pct + rtc_pct. ' +
      'Интерпретация: SL с учётом издержек.',
    format: 'percent',
    digits: 2,
  },
  spread_entry_exec: {
    label: 'Спред входа (exec)',
    tooltip:
      'Формула: stock_buy - pv_div - fut_sell. ' +
      'Интерпретация: спред по ценам исполнения на входе.',
    digits: 4,
  },
  spread_exit_exec: {
    label: 'Спред выхода (exec)',
    tooltip:
      'Формула: stock_sell - pv_div - fut_buy. ' +
      'Интерпретация: спред по ценам исполнения на выходе.',
    digits: 4,
  },
  spread_pct_entry_exec: {
    label: 'Спред входа, %',
    tooltip:
      'Формула: spread_entry_exec / spot_mid. ' +
      'Интерпретация: спред входа в процентах от спота.',
    format: 'percent',
    digits: 2,
  },
  spread_pct_exit_exec: {
    label: 'Спред выхода, %',
    tooltip:
      'Формула: spread_exit_exec / spot_mid. ' +
      'Интерпретация: спред выхода в процентах от спота.',
    format: 'percent',
    digits: 2,
  },
  entry_spread_pct_exec: {
    label: 'Entry spread, % (exec)',
    tooltip:
      'Формула: spread_entry_exec / spot_mid. ' +
      'Интерпретация: спред входа (серия спредов).',
    format: 'percent',
    digits: 2,
  },
  exit_spread_pct_exec: {
    label: 'Exit spread, % (exec)',
    tooltip:
      'Формула: spread_exit_exec / spot_mid. ' +
      'Интерпретация: спред выхода (серия спредов).',
    format: 'percent',
    digits: 2,
  },
  pnl_spread_pct: {
    label: 'PnL по спреду, %',
    tooltip:
      'Формула: spread_pct_exit_exec - spread_pct_entry_exec. ' +
      'Интерпретация: прибыль/убыток по спреду.',
    format: 'percent',
    digits: 2,
  },
  entry_spread_exec_pct: {
    label: 'Entry spread (exec), %',
    tooltip:
      'Формула: spread_entry_exec / spot_mid. ' +
      'Интерпретация: зафиксированный спред входа.',
    format: 'percent',
    digits: 2,
  },
  trail_peak_spread_pct: {
    label: 'Пик трейла, %',
    tooltip:
      'Формула: max(exit_spread_pct - entry_spread_pct). ' +
      'Интерпретация: лучшая достигнутая доходность по трейлу.',
    format: 'percent',
    digits: 2,
  },
  cycle_return_pct: {
    label: 'Доходность цикла, %',
    tooltip:
      'Формула: cash_and_carry => (entry_spread - spread) / entry_spot * 100; ' +
      'reverse => (spread - entry_spread) / entry_spot * 100. ' +
      'Интерпретация: результат завершённого цикла.',
    format: 'percent',
    digits: 2,
  },
  trade_return_pct: {
    label: 'Доходность спреда, %',
    tooltip:
      'Формула: spread_pct_exit_exec - spread_pct_entry_exec. ' +
      'Интерпретация: изменение спреда между входом и выходом.',
    format: 'percent',
    digits: 2,
  },
  trade_pnl_cash: {
    label: 'P&L, руб.',
    tooltip:
      'Формула: (sell_stock - buy_stock) - (buy_fut - sell_fut) + дивиденды - фондирование - комиссии. ' +
      'Интерпретация: денежный результат сделки.',
    format: 'currency',
    digits: 2,
  },
  trade_return_pct_net: {
    label: 'Доходность (net), %',
    tooltip:
      'Формула: trade_pnl_cash / entry_spot_exec. ' +
      'Интерпретация: net-доходность относительно спота на входе.',
    format: 'percent',
    digits: 2,
  },
  trade_return_annual: {
    label: 'Годовая доходность (net), %',
    tooltip:
      'Формула: trade_return_net / hold_tau. ' +
      'Интерпретация: годовая net-доходность сделки.',
    format: 'percent',
    digits: 2,
  },
  trade_hold_days: {
    label: 'Дней в сделке',
    tooltip:
      'Формула: exit_date - entry_date. ' +
      'Интерпретация: длительность удержания сделки.',
    format: 'days',
    digits: 0,
  },
  pnl: {
    label: 'P&L',
    tooltip: 'Прибыль/убыток по сделке.',
    digits: 2,
  },
  entry_price_stock: {
    label: 'Цена входа (акция)',
    tooltip: 'Цена входа по акции.',
    digits: 2,
  },
  entry_price_fut: {
    label: 'Цена входа (фьючерс)',
    tooltip: 'Цена входа по фьючерсу.',
    digits: 2,
  },
  exit_price_stock: {
    label: 'Цена выхода (акция)',
    tooltip: 'Цена выхода по акции.',
    digits: 2,
  },
  exit_price_fut: {
    label: 'Цена выхода (фьючерс)',
    tooltip: 'Цена выхода по фьючерсу.',
    digits: 2,
  },
  quantity_stock: {
    label: 'Кол-во (акция)',
    tooltip: 'Количество акций.',
    digits: 0,
  },
  quantity_fut: {
    label: 'Кол-во (фьючерс)',
    tooltip: 'Количество фьючерсов.',
    digits: 0,
  },
  hold_days: {
    label: 'Дней в позиции',
    tooltip: 'Длительность сделки в днях.',
    format: 'days',
    digits: 0,
  },
  exit_reason: {
    label: 'Причина выхода',
    tooltip: 'Причина закрытия позиции.',
  },
  equity: {
    label: 'Эквити',
    tooltip: 'Размер капитала в моменте.',
    digits: 0,
  },
  cash: {
    label: 'Кэш',
    tooltip: 'Свободные денежные средства.',
    digits: 0,
  },
  drawdown: {
    label: 'Просадка',
    tooltip:
      'Формула: equity / rolling_max - 1. ' +
      'Интерпретация: текущая просадка капитала.',
    format: 'percent',
    digits: 2,
  },
  turnover: {
    label: 'Оборачиваемость',
    tooltip:
      'Формула: v1 -> #trades / years; v2 -> turnover_notional / equity. ' +
      'Интерпретация: частота/доля оборота.',
    digits: 2,
  },
  positions: {
    label: 'Позиции',
    tooltip: 'Количество открытых позиций.',
    digits: 0,
  },
  cagr: {
    label: 'CAGR, % год.',
    tooltip:
      'Формула: equity_last^(1/years) - 1. ' +
      'Интерпретация: среднегодовой темп роста капитала.',
    format: 'percent',
    digits: 2,
  },
  sharpe: {
    label: 'Sharpe',
    tooltip:
      'Формула: mean(ret)/std(ret) * sqrt(252). ' +
      'Интерпретация: доходность на единицу риска.',
    digits: 2,
  },
  hit_rate: {
    label: 'Доля прибыльных',
    tooltip:
      'Формула: #profit / #trades. ' +
      'Интерпретация: доля прибыльных сделок.',
    format: 'percent',
    digits: 2,
  },
  objective: {
    label: 'Целевая метрика',
    tooltip:
      'Формула: excess_ann - penalty_dd - penalty_to (с ограничениями по dd/turnover). ' +
      'Интерпретация: итоговая цель для HPO.',
    digits: 4,
  },
  params: {
    label: 'Параметры',
    tooltip: 'Набор параметров эксперимента.',
  },
  fold_objectives: {
    label: 'Метрики фолдов',
    tooltip: 'Значения метрики по фолдам.',
  },
  run_id: {
    label: 'ID прогона',
    tooltip: 'Идентификатор прогона.',
  },
  status: {
    label: 'Статус',
    tooltip: 'Статус процесса.',
  },
  message: {
    label: 'Сообщение',
    tooltip: 'Текстовое сообщение.',
  },
  code: {
    label: 'Код',
    tooltip: 'Код события/ошибки.',
  },
  confidence: {
    label: 'Достоверность',
    tooltip: 'Доля уверенности (0–1).',
    format: 'percent',
    digits: 2,
  },
  timestamp: {
    label: 'Время',
    tooltip: 'Дата и время события.',
  },
  date: {
    label: 'Дата',
    tooltip: 'Дата записи.',
  },
  action_note: {
    label: 'Комментарий',
  },
  pair_id: {
    label: 'Пара',
    tooltip: 'Код пары акция-фьючерс.',
  },
  stock_secid: {
    label: 'Акция',
    tooltip: 'Код акции.',
  },
  future_secid: {
    label: 'Фьючерс',
    tooltip: 'Код фьючерса.',
  },
  direction: {
    label: 'Направление',
    tooltip: 'Тип позиции.',
  },
  entry_date: {
    label: 'Дата входа',
    tooltip: 'Дата открытия позиции.',
  },
  exit_date: {
    label: 'Дата выхода',
    tooltip: 'Дата закрытия позиции.',
  },
  price: {
    label: 'Цена',
    tooltip: 'Цена исполнения.',
    digits: 2,
  },
  quantity: {
    label: 'Количество',
    tooltip: 'Количество контрактов/акций.',
    digits: 0,
  },
  side: {
    label: 'Сторона',
    tooltip: 'Buy/Sell сторона сделки.',
  },
  note: {
    label: 'Комментарий',
    tooltip: 'Комментарий оператора/системы.',
  },
  trade_cycle: {
    label: 'Цикл сделки',
    tooltip: 'Идентификатор торгового цикла.',
    digits: 0,
  },
  entry_cycle: {
    label: 'Цикл входа',
    tooltip: 'Идентификатор цикла при входе.',
    digits: 0,
  },
  exit_cycle: {
    label: 'Цикл выхода',
    tooltip: 'Идентификатор цикла при выходе.',
    digits: 0,
  },
  cycle_id: {
    label: 'Активный цикл',
    tooltip: 'Номер текущего цикла, если позиция открыта.',
    digits: 0,
  },
  entry_flag: {
    label: 'Вход',
    tooltip: 'Маркер события входа.',
  },
  exit_flag: {
    label: 'Выход',
    tooltip: 'Маркер события выхода.',
  },
  zscore: {
    label: 'Z-score',
    tooltip:
      'Формула: (last - mean) / std на окне z_window. ' +
      'Интерпретация: насколько спред отклонился от среднего.',
    digits: 2,
  },
  z_entry: {
    label: 'Z-entry',
    tooltip:
      'Формула: порог входа по z-score. ' +
      'Интерпретация: значение z-score для входа.',
    digits: 2,
  },
  z_exit: {
    label: 'Z-exit',
    tooltip:
      'Формула: порог выхода по z-score. ' +
      'Интерпретация: значение z-score для выхода.',
    digits: 2,
  },
  zscore_raw: {
    label: 'Z-score (raw)',
    tooltip:
      'Формула: (last - mean) / std на окне window. ' +
      'Интерпретация: базовый z-score без тренд-коррекции.',
    digits: 2,
  },
  window: {
    label: 'Окно',
    tooltip:
      'Формула: размер окна расчёта статистики. ' +
      'Интерпретация: длина истории в точках.',
    digits: 0,
  },
  mean: {
    label: 'Среднее',
    tooltip:
      'Формула: mean(series) на окне window. ' +
      'Интерпретация: средний уровень ряда.',
    digits: 4,
  },
  std: {
    label: 'Стандартное отклонение',
    tooltip:
      'Формула: std(series) на окне window. ' +
      'Интерпретация: разброс значений ряда.',
    digits: 4,
  },
  trend: {
    label: 'Тренд',
    tooltip:
      'Формула: значение трендовой линии в последней точке. ' +
      'Интерпретация: ожидаемый уровень по тренду.',
    digits: 4,
  },
  spread_vol: {
    label: 'Волатильность спреда',
    tooltip:
      'Формула: std(spread_series) на окне window. ' +
      'Интерпретация: разброс значений спреда.',
    digits: 4,
  },
  spread_vol_pct: {
    label: 'Волатильность спреда, %',
    tooltip:
      'Формула: std(spread_pct) на окне window. ' +
      'Интерпретация: разброс спреда в процентах.',
    format: 'percent',
    digits: 2,
  },
  trend_pos: {
    label: 'Отклонение от тренда',
    tooltip:
      'Формула: last - trend_last. ' +
      'Интерпретация: позиция относительно тренда.',
    digits: 4,
  },
  trend_slope: {
    label: 'Наклон тренда',
    tooltip:
      'Формула: slope линейной регрессии spread_pct. ' +
      'Интерпретация: направление тренда.',
    digits: 4,
  },
  trend_zscore: {
    label: 'Z-score тренда',
    tooltip:
      'Формула: residual / std(residual) на окне window. ' +
      'Интерпретация: насколько текущая точка отклоняется от тренда.',
    digits: 2,
  },
  spread_trend_z: {
    label: 'Z-score тренда (abs)',
    tooltip:
      'Формула: |trend_zscore|. ' +
      'Интерпретация: сила трендового отклонения.',
    digits: 2,
  },
  expected_net_irr: {
    label: 'Ожид. net IRR',
    tooltip:
      'Формула: expected_net_irr (из модели carry/alpha). ' +
      'Интерпретация: ожидаемая годовая доходность.',
    format: 'percent',
    digits: 2,
  },
  mae: {
    label: 'MAE',
    tooltip:
      'Формула: min(spread_pct_window - entry). ' +
      'Интерпретация: максимальное неблагоприятное отклонение.',
    digits: 4,
  },
  model_breaks: {
    label: 'Сбои модели',
    tooltip:
      'Формула: счётчик нарушений модели. ' +
      'Интерпретация: количество флагов качества данных.',
    digits: 0,
  },
  universe: {
    label: 'Вселенная',
  },
  execution: {
    label: 'Исполнение',
  },
  rates: {
    label: 'Ставки',
  },
  costs: {
    label: 'Издержки',
  },
  portfolio: {
    label: 'Портфель',
  },
  rebalance: {
    label: 'Ребалансировка',
  },
  general: {
    label: 'Общие',
  },
  test: {
    label: 'Тест',
  },
  strategy: {
    label: 'Стратегия',
  },
  allocation: {
    label: 'Аллокация',
  },
  liquidity: {
    label: 'Ликвидность',
  },
}

const valueLabels: Record<string, Record<string, string>> = {
  strategy_type: {
    arbitrage: 'Арбитраж',
    fundamental: 'Фундаментальная',
    speculative: 'Спекулятивная',
    mixed: 'Смешанная',
    carry: 'Кэрри',
    stat: 'Стат',
  },
  basket: {
    fundamental: 'Фундаментальная',
    speculative: 'Спекулятивная',
    arbitrage: 'Арбитраж',
  },
  price_mode: {
    BIDASK: 'Bid/Ask',
    OHLC: 'OHLC',
    AUTO: 'Авто',
    bidask: 'Bid/Ask',
    ohlc: 'OHLC',
    auto: 'Авто',
  },
  capital_base_mode: {
    FULL_CASH: 'Полный кэш',
    MARGIN_AWARE: 'С учётом маржи',
    full_cash: 'Полный кэш',
    margin_aware: 'С учётом маржи',
  },
  cadence: {
    daily: 'Ежедневно',
    weekly: 'Еженедельно',
    monthly: 'Ежемесячно',
    none: 'Нет',
    DAILY: 'Ежедневно',
    WEEKLY: 'Еженедельно',
    MONTHLY: 'Ежемесячно',
    NONE: 'Нет',
  },
  day_count: {
    'ACT/365': 'ACT/365',
    'ACT/360': 'ACT/360',
  },
  action: {
    approve: 'Одобрить',
    reject: 'Отклонить',
    hold: 'Удержать',
    enter: 'Вход',
    exit: 'Выход',
  },
  risk_state: {
    green: 'Зелёный',
    yellow: 'Жёлтый',
    red: 'Красный',
  },
  news_severity: {
    low: 'Низкая',
    medium: 'Средняя',
    high: 'Высокая',
    critical: 'Критическая',
  },
  signal_action: {
    enter: 'Вход',
    exit: 'Выход',
    hold: 'Держать',
  },
  signal_direction: {
    cash_and_carry: 'Кэш-энд-кэрри',
    reverse: 'Реверс',
    neutral: 'Нейтрально',
  },
  signal_reasons: {
    enter_ok: 'Вход разрешён',
    skip_floor: 'Пропуск: floor',
    skip_liquidity: 'Пропуск: ликвидность',
    skip_score: 'Пропуск: скор',
    floor_fail: 'Floor не пройден',
    liquidity_fail: 'Ликвидность не пройдена',
    entry_filter_fail: 'Фильтр входа не пройден',
    dte_too_low: 'Слишком мало дней до экспирации',
    hold: 'Держать',
    tp: 'TP',
    sl: 'SL',
    time: 'Таймстоп',
    expiry: 'Близко к экспирации',
    implied_rate_above_required: 'Имплайд ставка выше требуемой',
    implied_rate_below_required: 'Имплайд ставка ниже требуемой',
    implied_rate_neutral: 'Имплайд ставка нейтральна',
    insufficient_history: 'Недостаточно истории',
    zscore_high: 'Z-score высокий',
    zscore_low: 'Z-score низкий',
    zscore_revert: 'Z-score вернулся',
    zscore_mid: 'Z-score в зоне ожидания',
    event_filter_blocked: 'Заблокировано фильтром событий',
    direction_conflict: 'Конфликт направлений',
    stat_not_confirmed: 'Стат-сигнал не подтверждён',
    carry_not_confirmed: 'Carry-сигнал не подтверждён',
  },
  direction: {
    cash_and_carry: 'Кэш-энд-кэрри',
    reverse: 'Реверс',
    neutral: 'Нейтрально',
  },
  decision: {
    ENTER_OK: 'Вход разрешён',
    SKIP_FLOOR: 'Пропуск: floor',
    SKIP_LIQUIDITY: 'Пропуск: ликвидность',
    SKIP_SCORE: 'Пропуск: скор',
    enter_ok: 'Вход разрешён',
    skip_floor: 'Пропуск: floor',
    skip_liquidity: 'Пропуск: ликвидность',
    skip_score: 'Пропуск: скор',
  },
  proposal_type: {
    rebalance: 'Ребалансировка',
    confirm: 'Подтверждение',
  },
  side: {
    buy: 'Покупка',
    sell: 'Продажа',
  },
  exit_reason: {
    TP: 'TP',
    SL: 'SL',
    TRAIL: 'Трейлинг',
  },
  status: {
    ok: 'ок',
    queued: 'в очереди',
    ready: 'готово',
    recorded: 'записано',
    filled: 'исполнено',
    failed: 'ошибка',
    cancelled: 'отменено',
    pending: 'ожидание',
    running: 'в работе',
    stub: 'заглушка',
  },
}

type ParamMeta = {
  label: string
  tooltip?: string
  valueLabels?: Record<string, string>
  order?: string[]
}

const paramMeta: Record<string, ParamMeta> = {
  'test.start_date': {
    label: 'Дата начала',
    tooltip:
      'Формула: start_date. ' +
      'Интерпретация: дата начала исторического периода.',
  },
  'test.end_date': {
    label: 'Дата окончания',
    tooltip:
      'Формула: end_date. ' +
      'Интерпретация: дата окончания исторического периода.',
  },
  'test.timezone': {
    label: 'Часовой пояс',
    tooltip:
      'Формула: timezone. ' +
      'Интерпретация: таймзона для приведения дат/времени.',
  },
  'test.cost_stress_mult': {
    label: 'Множитель издержек',
    tooltip:
      'Формула: costs *= cost_stress_mult. ' +
      'Интерпретация: стресс-множитель издержек.',
  },
  'test.seed': {
    label: 'Сид генератора',
    tooltip:
      'Формула: seed. ' +
      'Интерпретация: фиксирует случайность для повторяемости.',
  },
  'universe.pair_ids': {
    label: 'Список пар',
    tooltip:
      'Формула: использовать только pair_ids. ' +
      'Интерпретация: ручной список пар.',
  },
  'universe.include_stocks': {
    label: 'Тикеры акций',
    tooltip:
      'Формула: фильтр по акциям. ' +
      'Интерпретация: разрешённые тикеры акций.',
  },
  'universe.include_futures': {
    label: 'Тикеры фьючерсов',
    tooltip:
      'Формула: фильтр по фьючерсам. ' +
      'Интерпретация: разрешённые тикеры фьючерсов.',
  },
  'universe.max_pairs': {
    label: 'Лимит пар',
    tooltip:
      'Формула: limit = max_pairs. ' +
      'Интерпретация: максимальное число пар в расчёте.',
  },
  'universe.allowed_expiry_months': {
    label: 'Месяцы экспирации',
    tooltip:
      'Формула: expiry_month ∈ allowed_expiry_months. ' +
      'Интерпретация: допустимые месяцы экспирации.',
  },
  'universe.allowed_expiry_years': {
    label: 'Годы экспирации',
    tooltip:
      'Формула: expiry_year ∈ allowed_expiry_years. ' +
      'Интерпретация: допустимые годы экспирации.',
  },
  'execution.price_mode': {
    label: 'Режим цены',
    tooltip:
      'Формула: mode = price_mode (BIDASK/OHLC/AUTO). ' +
      'Интерпретация: источник цены исполнения.',
  },
  'execution.half_spread_bps': {
    label: 'Половина спреда, б.п.',
    tooltip:
      'Формула: price ± half_spread_bps. ' +
      'Интерпретация: половина спреда в б.п.',
  },
  'execution.slip_stock_bps': {
    label: 'Проскальзывание акций, б.п.',
    tooltip:
      'Формула: slip_stock_bps. ' +
      'Интерпретация: проскальзывание по акциям в б.п.',
  },
  'execution.slip_fut_bps': {
    label: 'Проскальзывание фьючерса, б.п.',
    tooltip:
      'Формула: slip_fut_bps. ' +
      'Интерпретация: проскальзывание по фьючерсу в б.п.',
  },
  'execution.slip_fut_ticks': {
    label: 'Проскальзывание фьючерса, тиков',
    tooltip:
      'Формула: slip_fut_ticks × tick_size_fut. ' +
      'Интерпретация: проскальзывание в тиках.',
  },
  'execution.tick_size_fut': {
    label: 'Шаг цены фьючерса',
    tooltip:
      'Формула: tick_size_fut. ' +
      'Интерпретация: шаг цены фьючерса для пересчёта тиков.',
  },
  'rates.day_count': {
    label: 'База дней',
    tooltip:
      'Формула: tau = days / day_count. ' +
      'Интерпретация: база дней для годовых ставок.',
  },
  'rates.use_trading_days': {
    label: 'Торговые дни',
    tooltip:
      'Формула: использовать торговые дни вместо календарных. ' +
      'Интерпретация: пересчёт tau и ставок.',
  },
  'costs.stock_commission_bps': {
    label: 'Комиссия акций, б.п.',
    tooltip:
      'Формула: комиссия = notional × stock_commission_bps. ' +
      'Интерпретация: комиссия по акциям в б.п.',
  },
  'costs.futures_commission_bps': {
    label: 'Комиссия фьючерсов, б.п.',
    tooltip:
      'Формула: комиссия = notional × futures_commission_bps. ' +
      'Интерпретация: комиссия по фьючерсам в б.п.',
  },
  'costs.exchange_fee_bps': {
    label: 'Биржевой сбор, б.п.',
    tooltip:
      'Формула: сбор = notional × exchange_fee_bps. ' +
      'Интерпретация: биржевой сбор в б.п.',
  },
  'costs.fee_stock_per_share': {
    label: 'Комиссия за акцию, ₽',
    tooltip:
      'Формула: fee_stock_per_share × qty. ' +
      'Интерпретация: фиксированная комиссия за акцию.',
  },
  'costs.fee_stock_bps': {
    label: 'Доп. комиссия акций, б.п.',
    tooltip:
      'Формула: fee_stock_bps. ' +
      'Интерпретация: дополнительная комиссия по акциям.',
  },
  'costs.fee_fut_per_contract': {
    label: 'Комиссия за контракт, ₽',
    tooltip:
      'Формула: fee_fut_per_contract × contracts. ' +
      'Интерпретация: фиксированная комиссия за контракт.',
  },
  'liquidity.max_spread_bps_stock': {
    label: 'Макс. спред акций, б.п.',
    tooltip:
      'Формула: spread_bps_stock ≤ max_spread_bps_stock. ' +
      'Интерпретация: фильтр по спреду акций.',
  },
  'liquidity.max_spread_bps_fut': {
    label: 'Макс. спред фьючерса, б.п.',
    tooltip:
      'Формула: spread_bps_fut ≤ max_spread_bps_fut. ' +
      'Интерпретация: фильтр по спреду фьючерса.',
  },
  'liquidity.min_avg_dollarvol_stock': {
    label: 'Мин. оборот акций, ₽',
    tooltip:
      'Формула: avg_dollarvol_stock ≥ min_avg_dollarvol_stock. ' +
      'Интерпретация: минимум оборота по акциям.',
  },
  'liquidity.min_avg_dollarvol_fut': {
    label: 'Мин. оборот фьючерса, ₽',
    tooltip:
      'Формула: avg_dollarvol_fut ≥ min_avg_dollarvol_fut. ' +
      'Интерпретация: минимум оборота по фьючерсу.',
  },
  'liquidity.min_open_interest': {
    label: 'Мин. открытый интерес',
    tooltip:
      'Формула: open_interest ≥ min_open_interest. ' +
      'Интерпретация: минимум открытого интереса.',
  },
  'liquidity.participation_rate': {
    label: 'Доля участия',
    tooltip:
      'Формула: days_to_exit(position, avg_dollar, participation_rate). ' +
      'Интерпретация: доля участия в дневном объёме.',
  },
  'liquidity.max_days_to_exit': {
    label: 'Макс. дней на выход',
    tooltip:
      'Формула: days_to_exit ≤ max_days_to_exit. ' +
      'Интерпретация: ограничение по сроку выхода.',
  },
  'liquidity.use_adv': {
    label: 'Использовать ADV',
    tooltip:
      'Формула: use_adv. ' +
      'Интерпретация: использовать среднедневной оборот (ADV) в фильтрах ликвидности.',
  },
  'strategy.floor_tolerance': {
    label: 'Допуск floor',
    tooltip:
      'Формула: floor_pass = floor_rate_annual ≥ r_cb_annual - floor_tolerance. ' +
      'Интерпретация: допуск к ключевой ставке.',
  },
  'strategy.riskbuffer_floor': {
    label: 'Риск-буфер floor',
    tooltip:
      'Формула: costs_hold += riskbuffer_floor. ' +
      'Интерпретация: дополнительный буфер издержек удержания.',
  },
  'strategy.capital_base_mode': {
    label: 'База капитала',
    tooltip:
      'Формула: FULL_CASH → spot_buy; MARGIN_AWARE → margin_stock + margin_fut + var_buffer. ' +
      'Интерпретация: база капитала для floor_rate.',
  },
  'strategy.margin_stock_pct': {
    label: 'Маржа акций, доля',
    tooltip:
      'Формула: margin_stock = spot × margin_stock_pct. ' +
      'Интерпретация: доля маржи по акциям.',
  },
  'strategy.margin_fut_pct': {
    label: 'Маржа фьючерса, доля',
    tooltip:
      'Формула: margin_fut = fut × margin_fut_pct. ' +
      'Интерпретация: доля маржи по фьючерсу.',
  },
  'strategy.var_margin_buffer_pct': {
    label: 'Буфер вариационки, доля',
    tooltip:
      'Формула: var_buffer = margin_fut × var_margin_buffer_pct. ' +
      'Интерпретация: буфер вариационной маржи.',
  },
  'strategy.min_dte_entry': {
    label: 'Мин. DTE для входа',
    tooltip:
      'Формула: DTE ≥ min_DTE_entry. ' +
      'Интерпретация: минимум дней до экспирации для входа.',
  },
  'strategy.close_buffer_days': {
    label: 'Буфер до экспирации, дней',
    tooltip:
      'Формула: выход за close_buffer_days до экспирации. ' +
      'Интерпретация: временной буфер закрытия.',
  },
  'strategy.roll_trigger_days': {
    label: 'Триггер ролловера, дней',
    tooltip:
      'Формула: DTE ≤ roll_trigger_days. ' +
      'Интерпретация: порог для ролловера.',
  },
  'strategy.h_max_days': {
    label: 'Горизонт H, дней',
    tooltip:
      'Формула: горизонт расчёта alpha-метрик. ' +
      'Интерпретация: число дней вперёд для TP/SL.',
  },
  'strategy.spread_history_days': {
    label: 'История спреда, дней',
    tooltip:
      'Формула: использовать последние spread_history_days. ' +
      'Интерпретация: глубина истории спреда.',
  },
  'strategy.tp_pct': {
    label: 'TP-порог',
    tooltip:
      'Формула: выход по TP при spread_pct ≥ TP_pct. ' +
      'Интерпретация: порог фиксации прибыли (доля, 0.01 = 1%).',
  },
  'strategy.sl_pct': {
    label: 'SL-порог',
    tooltip:
      'Формула: выход по SL при spread_pct ≤ -SL_pct. ' +
      'Интерпретация: порог стоп-лосса (доля, 0.01 = 1%).',
  },
  'strategy.z_window': {
    label: 'Окно Z-score',
    tooltip:
      'Формула: zscore = (last - mean) / std на окне z_window. ' +
      'Интерпретация: длина окна расчёта.',
  },
  'strategy.z_entry_threshold': {
    label: 'Порог входа Z-score',
    tooltip:
      'Формула: |zscore| ≥ z_entry_threshold. ' +
      'Интерпретация: порог стат-входа.',
  },
  'strategy.min_floor_score': {
    label: 'Мин. floor-скор',
    tooltip:
      'Формула: score_floor ≥ min_floor_score. ' +
      'Интерпретация: минимум floor-скора для входа.',
  },
  'strategy.min_alpha_score': {
    label: 'Мин. alpha-скор',
    tooltip:
      'Формула: score_alpha ≥ min_alpha_score. ' +
      'Интерпретация: минимум alpha-скора для входа.',
  },
  'strategy.min_total_score': {
    label: 'Мин. итоговый скор',
    tooltip:
      'Формула: total_score ≥ min_total_score. ' +
      'Интерпретация: минимум итогового скора.',
  },
  'strategy.w_floor': {
    label: 'Вес floor-скора',
    tooltip:
      'Формула: total_score = w_floor*score_floor + ... ' +
      'Интерпретация: вес floor-скора.',
  },
  'strategy.w_alpha': {
    label: 'Вес alpha-скора',
    tooltip:
      'Формула: total_score = ... + w_alpha*score_alpha + ... ' +
      'Интерпретация: вес alpha-скора.',
  },
  'strategy.w_liq': {
    label: 'Вес штрафа ликвидности',
    tooltip:
      'Формула: total_score -= w_liq*penalty_liq. ' +
      'Интерпретация: вес штрафа ликвидности.',
  },
  'strategy.w_event': {
    label: 'Вес событийного штрафа',
    tooltip:
      'Формула: total_score -= w_event*penalty_event. ' +
      'Интерпретация: вес событийного штрафа.',
  },
  'strategy.k_event': {
    label: 'Коэф. событийного штрафа',
    tooltip:
      'Формула: penalty_event = k_event * event_score. ' +
      'Интерпретация: коэффициент событийного штрафа.',
  },
  'portfolio.account_equity': {
    label: 'Капитал счёта, ₽',
    tooltip:
      'Формула: account_equity. ' +
      'Интерпретация: размер капитала для расчётов.',
  },
  'portfolio.account_currency': {
    label: 'Валюта счёта',
    tooltip:
      'Формула: account_currency. ' +
      'Интерпретация: валюта портфеля.',
  },
  'portfolio.max_gross_notional': {
    label: 'Лимит общей позиции, ₽',
    tooltip:
      'Формула: gross_notional ≤ max_gross_notional. ' +
      'Интерпретация: лимит по общей позиции.',
  },
  'portfolio.max_contracts_per_pair': {
    label: 'Лимит контрактов на пару',
    tooltip:
      'Формула: contracts ≤ max_contracts_per_pair. ' +
      'Интерпретация: ограничение контрактов на пару.',
  },
  'portfolio.capital_allocated_per_trade': {
    label: 'Капитал на сделку, ₽',
    tooltip:
      'Формула: capital_allocated_per_trade. ' +
      'Интерпретация: капитал на одну сделку.',
  },
  'portfolio.margin_proxy': {
    label: 'Множитель маржи',
    tooltip:
      'Формула: margin = notional × margin_proxy. ' +
      'Интерпретация: множитель маржи.',
  },
  'allocation.weights': {
    label: 'Вес корзин',
    tooltip:
      'Формула: target_weight[basket]. ' +
      'Интерпретация: распределение веса по корзинам (сумма обычно = 1).',
    valueLabels: valueLabels.basket,
    order: ['fundamental', 'speculative', 'arbitrage'],
  },
  'allocation.min_confidence': {
    label: 'Мин. уверенность',
    tooltip:
      'Формула: confidence ≥ min_confidence. ' +
      'Интерпретация: минимальная уверенность пары.',
  },
  'allocation.max_signals': {
    label: 'Макс. сигналов',
    tooltip:
      'Формула: top N ≤ max_signals. ' +
      'Интерпретация: ограничение числа сигналов.',
  },
  'allocation.max_turnover_pct': {
    label: 'Лимит оборота',
    tooltip:
      'Формула: turnover ≤ max_turnover_pct. ' +
      'Интерпретация: ограничение оборота (доля, 0.1 = 10%).',
  },
  'allocation.min_trade_weight': {
    label: 'Мин. вес сделки',
    tooltip:
      'Формула: trade_weight ≥ min_trade_weight. ' +
      'Интерпретация: минимальный вес сделки.',
  },
  'rebalance.cadence': {
    label: 'Частота ребаланса',
    tooltip:
      'Формула: cadence (daily/weekly). ' +
      'Интерпретация: периодичность ребалансировки.',
  },
  'rebalance.threshold_pct': {
    label: 'Порог ребаланса',
    tooltip:
      'Формула: |target - current| ≥ threshold_pct. ' +
      'Интерпретация: порог для ребалансировки.',
  },
  'rebalance.cooldown_days': {
    label: 'Пауза ребаланса, дней',
    tooltip:
      'Формула: cooldown_days между ребалансами. ' +
      'Интерпретация: пауза после ребаланса.',
  },
}

const paramSectionOrder = [
  'test',
  'universe',
  'execution',
  'rates',
  'costs',
  'liquidity',
  'strategy',
  'portfolio',
  'allocation',
  'rebalance',
  'general',
]

const valueTypeLabels: Record<string, string> = {
  bool: 'да/нет',
  int: 'целое',
  float: 'число',
  str: 'текст',
  dict: 'словарь',
  list: 'список',
  tuple: 'список',
  set: 'набор',
  union: 'смешанный',
  date: 'дата',
  datetime: 'дата/время',
}

const getFieldLabel = (key: string) => fieldMeta[key]?.label ?? humanizeKey(key)
const getFieldTooltip = (key: string) => fieldMeta[key]?.tooltip ?? ''
const getValueLabel = (column: string | undefined, value: string) => {
  if (!column) return null
  const map = valueLabels[column]
  return map?.[value] ?? null
}

const normalizeParamKey = (value: string) =>
  value.replace(/[A-Z]/g, (match) => match.toLowerCase())

const getParamLeaf = (key: string) => {
  const parts = key.split('.')
  return parts[parts.length - 1] || key
}

const getParamLabel = (spec: ParameterSpec) => {
  const meta = paramMeta[spec.key] ?? paramMeta[normalizeParamKey(spec.key)]
  if (meta?.label) return meta.label
  const leaf = getParamLeaf(spec.key)
  const normalized = normalizeParamKey(leaf)
  return (
    fieldMeta[leaf]?.label ??
    fieldMeta[normalized]?.label ??
    humanizeKey(normalized)
  )
}

const getParamTooltip = (spec: ParameterSpec) => {
  const meta = paramMeta[spec.key] ?? paramMeta[normalizeParamKey(spec.key)]
  if (meta?.tooltip) return meta.tooltip
  const leaf = getParamLeaf(spec.key)
  const normalized = normalizeParamKey(leaf)
  return fieldMeta[leaf]?.tooltip ?? fieldMeta[normalized]?.tooltip ?? spec.description ?? ''
}

const getParamOptionLabel = (spec: ParameterSpec, option: unknown) => {
  const raw = String(option)
  const leaf = getParamLeaf(spec.key)
  const normalized = normalizeParamKey(leaf)
  const metaLabels =
    paramMeta[spec.key]?.valueLabels ??
    paramMeta[normalizeParamKey(spec.key)]?.valueLabels ??
    valueLabels[spec.key] ??
    valueLabels[leaf] ??
    valueLabels[normalized]
  return metaLabels?.[raw] ?? raw
}

const formatParamDefault = (spec: ParameterSpec) => {
  if (spec.default === undefined) return ''
  if (spec.default === null) return '—'
  if (spec.value_type === 'bool') {
    return spec.default ? 'Да' : 'Нет'
  }
  if (spec.value_type === 'dict') {
    let raw: Record<string, unknown> | null = null
    if (typeof spec.default === 'string') {
      try {
        raw = getObject<Record<string, unknown>>(JSON.parse(spec.default))
      } catch {
        raw = null
      }
    } else {
      raw = getObject<Record<string, unknown>>(spec.default)
    }
    if (!raw) return '—'
    const meta = paramMeta[spec.key] ?? paramMeta[normalizeParamKey(spec.key)]
    const labels = meta?.valueLabels
    const entries = Object.entries(raw)
    if (!entries.length) return '—'
    return entries
      .map(([key, value]) => {
        if (value === undefined) return null
        const label = labels?.[key] ?? humanizeKey(key)
        if (typeof value === 'number') {
          const digits = Number.isInteger(value) ? 0 : 3
          return `${label}: ${formatNumber(value, digits)}`
        }
        return `${label}: ${String(value)}`
      })
      .filter(Boolean)
      .join(', ')
  }
  if (Array.isArray(spec.default)) {
    return spec.default.map((item) => String(item)).join(', ')
  }
  return shortenText(compactJson(spec.default))
}

const buildParamHelperText = (spec: ParameterSpec) => {
  const parts: string[] = []
  const typeLabel = valueTypeLabels[spec.value_type] ?? spec.value_type
  if (typeLabel) parts.push(`Тип: ${typeLabel}`)
  if (spec.min_value !== null && spec.min_value !== undefined) {
    parts.push(`Мин: ${spec.min_value}`)
  }
  if (spec.max_value !== null && spec.max_value !== undefined) {
    parts.push(`Макс: ${spec.max_value}`)
  }
  const defaultLabel = formatParamDefault(spec)
  if (defaultLabel) parts.push(`По умолчанию: ${defaultLabel}`)
  return parts.filter(Boolean).join(' | ')
}

const ParamLabel = ({ label, tooltip }: { label: string; tooltip?: string }) => (
  <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
    <span>{label}</span>
    {tooltip ? (
      <Tooltip title={tooltip} arrow placement="top">
        <InfoOutlinedIcon fontSize="inherit" sx={{ color: 'text.secondary' }} />
      </Tooltip>
    ) : null}
  </Box>
)

const toTitleCase = (value: string) => getFieldLabel(value)

const toNumeric = (value: unknown) => {
  if (typeof value === 'number') return value
  if (typeof value !== 'string') return Number.NaN
  const cleaned = value.replace('%', '').replace(',', '.').trim()
  const parsed = Number(cleaned)
  return Number.isNaN(parsed) ? Number.NaN : parsed
}

const compareValues = (left: unknown, right: unknown) => {
  if (left === null || left === undefined) return right === null || right === undefined ? 0 : 1
  if (right === null || right === undefined) return -1
  const leftNum = toNumeric(left)
  const rightNum = toNumeric(right)
  if (!Number.isNaN(leftNum) && !Number.isNaN(rightNum)) {
    return leftNum - rightNum
  }
  return String(left).localeCompare(String(right))
}

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
}

const formatValue = (value: unknown, column?: string): string => {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) {
    return value.map((item) => formatValue(item, column)).join(', ')
  }
  if (typeof value === 'boolean') {
    return value ? 'Да' : 'Нет'
  }
  if (typeof value === 'string') {
    const mapped = getValueLabel(column, value)
    if (mapped) return mapped
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (!entries.length) return '—'
    return entries
      .map(([key, item]) => `${toTitleCase(key)}: ${formatValue(item, key)}`)
      .join(', ')
  }
  const numeric = toNumeric(value)
  const meta = column ? fieldMeta[column] : undefined
  if (!Number.isNaN(numeric)) {
    if (meta?.format === 'percent' || (column && percentColumns.has(column))) {
      const scaled =
        column && alreadyPercentColumns.has(column) ? numeric : numeric * 100
      return `${formatNumber(scaled, meta?.digits ?? 2)}%`
    }
    if (meta?.format === 'bps') {
      return `${formatNumber(numeric, meta?.digits ?? 2)} б.п.`
    }
    if (meta?.format === 'currency') {
      return `${formatNumber(numeric, meta?.digits ?? 2)} ₽`
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

const getObject = <T,>(value: unknown): T | null => {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as T
  }
  return null
}

const getArray = <T,>(value: unknown): T[] => {
  if (Array.isArray(value)) {
    return value as T[]
  }
  return []
}

const getString = (value: unknown) => (typeof value === 'string' ? value : '')

const getTableColumns = (rows: GenericRow[]): string[] => {
  if (!rows.length) return []
  return Object.keys(rows[0]).filter((key) => key !== 'id')
}

const formatCellValue = (value: unknown, column?: string): string => formatValue(value, column)

const renderFieldLabel = (key: string, labelOverride?: string) => {
  const label = labelOverride ?? getFieldLabel(key)
  const tooltip = getFieldTooltip(key)
  if (!tooltip) return label
  return (
    <Tooltip title={tooltip} arrow placement="top">
      <span>{label}</span>
    </Tooltip>
  )
}

const isJsonValueType = (valueType: string) =>
  ['list', 'dict', 'tuple', 'set'].includes(valueType)

const shortenText = (value: string, limit = 120) =>
  value.length > limit ? `${value.slice(0, limit)}...` : value

const compactJson = (value: unknown): string => {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

const parseParamDictValue = (raw: ParamValue | undefined): Record<string, unknown> => {
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    return raw as Record<string, unknown>
  }
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      return {}
    }
  }
  return {}
}

const normalizeDictPayload = (payload: Record<string, unknown>) => {
  const next: Record<string, unknown> = {}
  Object.entries(payload).forEach(([key, value]) => {
    if (value === undefined) return
    if (value === null) {
      next[key] = null
      return
    }
    if (typeof value === 'string') {
      const trimmed = value.trim()
      if (!trimmed) {
        next[key] = null
        return
      }
      const numeric = Number(trimmed.replace(',', '.'))
      next[key] = Number.isNaN(numeric) ? trimmed : numeric
      return
    }
    next[key] = value
  })
  return next
}

const getParamDictEntries = (spec: ParameterSpec, raw: Record<string, unknown>) => {
  const meta = paramMeta[spec.key] ?? paramMeta[normalizeParamKey(spec.key)]
  const labels = meta?.valueLabels
  const keys = new Set<string>([
    ...Object.keys(raw ?? {}),
    ...Object.keys(labels ?? {}),
  ])
  const ordered = Array.from(keys)
  if (meta?.order?.length) {
    const orderIndex = new Map(meta.order.map((key, index) => [key, index]))
    ordered.sort((left, right) => {
      const leftRank = orderIndex.get(left) ?? Number.MAX_SAFE_INTEGER
      const rightRank = orderIndex.get(right) ?? Number.MAX_SAFE_INTEGER
      if (leftRank !== rightRank) return leftRank - rightRank
      return left.localeCompare(right)
    })
  } else {
    ordered.sort((left, right) => left.localeCompare(right))
  }
  return ordered.map((key) => ({
    key,
    label: labels?.[key] ?? getFieldLabel(key),
    value: raw?.[key],
  }))
}

const normalizeParamDefault = (spec: ParameterSpec): ParamValue => {
  if (spec.value_type === 'bool') {
    return Boolean(spec.default)
  }
  if (spec.default === null || spec.default === undefined) {
    return ''
  }
  if (spec.value_type === 'dict') {
    if (typeof spec.default === 'string') {
      try {
        const parsed = JSON.parse(spec.default)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          return parsed as Record<string, ParamPrimitive | unknown>
        }
      } catch {
        return ''
      }
    }
    if (typeof spec.default === 'object' && !Array.isArray(spec.default)) {
      return spec.default as Record<string, ParamPrimitive | unknown>
    }
    return ''
  }
  if (isJsonValueType(spec.value_type) || typeof spec.default === 'object') {
    return compactJson(spec.default)
  }
  return String(spec.default)
}

const buildParamDefaults = (specs: ParameterSpec[]): Record<string, ParamValue> => {
  const next: Record<string, ParamValue> = {}
  specs.forEach((spec) => {
    next[spec.key] = normalizeParamDefault(spec)
  })
  return next
}

const setNestedValue = (target: Record<string, unknown>, path: string, value: unknown) => {
  const parts = path.split('.')
  let cursor: Record<string, unknown> = target
  parts.forEach((part, index) => {
    if (index === parts.length - 1) {
      cursor[part] = value
      return
    }
    const existing = cursor[part]
    if (!existing || typeof existing !== 'object' || Array.isArray(existing)) {
      cursor[part] = {}
    }
    cursor = cursor[part] as Record<string, unknown>
  })
}

const parseParamValue = (raw: ParamValue | undefined, spec: ParameterSpec) => {
  const empty =
    raw === undefined ||
    raw === null ||
    (typeof raw === 'string' && raw.trim().length === 0)
  if (empty) {
    return { value: spec.default ?? null }
  }
  const valueType = spec.value_type
  const label = getParamLabel(spec)
  if (valueType === 'bool') {
    if (typeof raw === 'boolean') {
      return { value: raw }
    }
    const normalized = String(raw).toLowerCase()
    if (normalized === 'true' || normalized === 'false') {
      return { value: normalized === 'true' }
    }
    return { value: null, error: `${label}: неверное значение (да/нет)` }
  }
  if (valueType === 'int') {
    const parsed = Number.parseInt(String(raw), 10)
    if (Number.isNaN(parsed)) {
      return { value: null, error: `${label}: неверное целое` }
    }
    return { value: parsed }
  }
  if (valueType === 'float') {
    const parsed = Number.parseFloat(String(raw))
    if (Number.isNaN(parsed)) {
      return { value: null, error: `${label}: неверное число` }
    }
    return { value: parsed }
  }
  if (valueType === 'str') {
    return { value: String(raw) }
  }
  if (valueType === 'dict') {
    if (typeof raw === 'string') {
      try {
        const parsed = JSON.parse(raw)
        const payload = getObject<Record<string, unknown>>(parsed)
        if (!payload) {
          return { value: null, error: `${label}: неверный JSON` }
        }
        return { value: normalizeDictPayload(payload) }
      } catch {
        return { value: null, error: `${label}: неверный JSON` }
      }
    }
    const payload = getObject<Record<string, unknown>>(raw) ?? {}
    return { value: normalizeDictPayload(payload) }
  }
  if (isJsonValueType(valueType) || valueType === 'union') {
    if (typeof raw !== 'string') {
      return { value: raw }
    }
    try {
      return { value: JSON.parse(raw) }
    } catch {
      return { value: null, error: `${label}: неверный JSON` }
    }
  }
  if (typeof raw === 'string') {
    const trimmed = raw.trim()
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try {
        return { value: JSON.parse(trimmed) }
      } catch {
        return { value: null, error: `${label}: неверный JSON` }
      }
    }
  }
  return { value: raw }
}

const collectParamRequest = (
  specs: ParameterSpec[],
  values: Record<string, ParamValue>,
) => {
  const payload: Record<string, unknown> = {}
  const errors: string[] = []
  specs.forEach((spec) => {
    const parsed = parseParamValue(values[spec.key], spec)
    if (parsed.error) {
      errors.push(parsed.error)
      return
    }
    setNestedValue(payload, spec.key, parsed.value)
  })
  return { payload, errors }
}

const isDateColumn = (column: string) =>
  column === 'date' ||
  column.endsWith('_date') ||
  column.endsWith('_at') ||
  column.includes('timestamp')

function App() {
  const [rows, setRows] = useState<DecisionView[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [auxLoading, setAuxLoading] = useState(false)
  const [auxError, setAuxError] = useState<string | null>(null)
  const [auxLastUpdated, setAuxLastUpdated] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [refreshStatus, setRefreshStatus] = useState<RefreshStatus | null>(null)
  const [recomputeLoading, setRecomputeLoading] = useState(false)
  const [recomputeError, setRecomputeError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<DecisionLog | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [decisionAction, setDecisionAction] = useState<{
    operator_action?: OperatorAction
    execution_status?: ExecutionStatus
  } | null>(null)
  const [decisionActionError, setDecisionActionError] = useState<string | null>(null)
  const [decisionActionLoading, setDecisionActionLoading] = useState(false)
  const [decisionActionSubmitting, setDecisionActionSubmitting] = useState(false)
  const [decisionActionNote, setDecisionActionNote] = useState('')
  const [tab, setTab] = useState<
    'decisions' | 'top_pairs' | 'signals' | 'backtests' | 'backtest_v2' | 'forward' | 'hpo'
  >('decisions')
  const [topPairs, setTopPairs] = useState<GenericRow[]>([])
  const [signals, setSignals] = useState<GenericRow[]>([])
  const [backtests, setBacktests] = useState<GenericRow[]>([])
  const [paramSpecs, setParamSpecs] = useState<ParameterSpec[]>([])
  const [paramValues, setParamValues] = useState<Record<string, ParamValue>>({})
  const [paramFilter, setParamFilter] = useState('')
  const [paramPreset, setParamPreset] = useState('')
  const [paramSpecsLoading, setParamSpecsLoading] = useState(false)
  const [paramSpecsError, setParamSpecsError] = useState<string | null>(null)
  const [backtestPrecompute, setBacktestPrecompute] = useState(true)
  const [backtestRunReport, setBacktestRunReport] = useState<BacktestReport | null>(null)
  const [backtestRunLoading, setBacktestRunLoading] = useState(false)
  const [backtestRunError, setBacktestRunError] = useState<string | null>(null)
  const [backtestRunParseError, setBacktestRunParseError] = useState<string | null>(null)
  const [forwardRunId, setForwardRunId] = useState('')
  const [forwardStatus, setForwardStatus] = useState<ForwardStatus | null>(null)
  const [forwardLoading, setForwardLoading] = useState(false)
  const [forwardError, setForwardError] = useState<string | null>(null)
  const [hpoSearchSpace, setHpoSearchSpace] = useState('')
  const [hpoResponse, setHpoResponse] = useState<HpoResponse | null>(null)
  const [hpoLoading, setHpoLoading] = useState(false)
  const [hpoError, setHpoError] = useState<string | null>(null)
  const [signalHistory, setSignalHistory] = useState<SignalHistoryRow[]>([])
  const [quickFilter, setQuickFilter] = useState('')
  const [strategyFilter, setStrategyFilter] = useState('')
  const [instrumentFilter, setInstrumentFilter] = useState('')
  const [riskFilter, setRiskFilter] = useState('')
  const [newsFilter, setNewsFilter] = useState('')
  const [tableFilter, setTableFilter] = useState('')
  const [tableStockFilter, setTableStockFilter] = useState('')
  const [tableFutureFilter, setTableFutureFilter] = useState('')
  const [tableSignalFilter, setTableSignalFilter] = useState('')
  const [tableSortKey, setTableSortKey] = useState('')
  const [tableSortDirection, setTableSortDirection] = useState<'asc' | 'desc'>('desc')
  const [expandedRowKey, setExpandedRowKey] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState<'overview' | 'alpha' | 'liquidity' | 'execution'>(
    'overview',
  )
  const [spreadSeries, setSpreadSeries] = useState<Record<string, SpreadSeriesPoint[]>>({})
  const [spreadLoadingKey, setSpreadLoadingKey] = useState<string | null>(null)
  const [spreadError, setSpreadError] = useState<Record<string, string>>({})
  const [executionLogs, setExecutionLogs] = useState<Record<string, ExecutionRow[]>>({})
  const [executionLoadingKey, setExecutionLoadingKey] = useState<string | null>(null)
  const [executionError, setExecutionError] = useState<Record<string, string>>({})
  const [topPairsLimit, setTopPairsLimit] = useState('25')
  const [topPairsAll, setTopPairsAll] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyFrom, setHistoryFrom] = useState(() => {
    const date = new Date()
    date.setDate(date.getDate() - 7)
    return formatDateInputValue(date)
  })
  const [historyTo, setHistoryTo] = useState(() => formatDateInputValue(new Date()))
  const [executionForm, setExecutionForm] = useState({
    price: '',
    quantity: '',
    side: '',
    status: '',
    note: '',
  })
  const auxFetchInFlight = useRef(false)

  const fetchDecisionView = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch('/api/decision-view?limit=500', { cache: 'no-store' })
      if (!response.ok) {
        throw new Error(`Ошибка API: ${response.status}`)
      }
      const data: DecisionView[] = await response.json()
      setRows(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить данные')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchDecisionLog = useCallback(async (decisionId: string) => {
    setDetail(null)
    setDetailError(null)
    try {
      const response = await fetch(`/api/decision-log/${decisionId}`)
      if (!response.ok) {
        throw new Error(`Ошибка API: ${response.status}`)
      }
      const data: DecisionLog = await response.json()
      setDetail(data)
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : 'Не удалось загрузить лог решения')
    }
  }, [])

  const fetchDecisionAction = useCallback(async (decisionId: string) => {
    setDecisionAction(null)
    setDecisionActionError(null)
    setDecisionActionLoading(true)
    try {
      const response = await fetch(`/api/decisions/${decisionId}/action`, { cache: 'no-store' })
      if (!response.ok) {
        throw new Error(`Ошибка API: ${response.status}`)
      }
      const data = (await response.json()) as {
        operator_action?: OperatorAction
        execution_status?: ExecutionStatus
      }
      setDecisionAction(data)
    } catch (err) {
      setDecisionActionError(err instanceof Error ? err.message : 'Не удалось загрузить действие решения')
    } finally {
      setDecisionActionLoading(false)
    }
  }, [])

  const fetchAuxData = useCallback(
    async (options: { topPairsLimit: string; topPairsAll: boolean }) => {
      if (auxFetchInFlight.current) return
      auxFetchInFlight.current = true
      setAuxLoading(true)
      setAuxError(null)
      try {
        const { topPairsLimit: limitRaw, topPairsAll: allPairs } = options
        const topPairsParams = new URLSearchParams()
        if (allPairs) {
          topPairsParams.set('all', 'true')
        } else {
          const limitValue = Number(limitRaw)
          if (!Number.isNaN(limitValue) && limitValue >= 0) {
            topPairsParams.set('limit', String(limitValue))
          } else {
            topPairsParams.set('limit', '500')
          }
        }
        const topPairsUrl = `/api/top-pairs?${topPairsParams.toString()}`
      const results = await Promise.allSettled([
        fetch(topPairsUrl, { cache: 'no-store' }),
        fetch('/api/signals/active', { cache: 'no-store' }),
        fetch('/api/backtests?limit=500', { cache: 'no-store' }),
        fetch('/api/signals/refresh-status', { cache: 'no-store' }),
      ])

      const errors: string[] = []
      const parseResult = async (
        label: string,
        result: PromiseSettledResult<Response>,
        setter: (rows: GenericRow[]) => void,
      ) => {
        if (result.status === 'rejected') {
          errors.push(`${label}: ошибка загрузки`)
          setter([])
          return false
        }
        if (!result.value.ok) {
          errors.push(`${label}: ошибка API ${result.value.status}`)
          setter([])
          return false
        }
        try {
          setter(await result.value.json())
          return true
        } catch {
          errors.push(`${label}: ошибка разбора`)
          setter([])
          return false
        }
      }
      const parseObjectResult = async <T,>(
        label: string,
        result: PromiseSettledResult<Response>,
        setter: (payload: T | null) => void,
      ) => {
        if (result.status === 'rejected') {
          errors.push(`${label}: ошибка загрузки`)
          setter(null)
          return false
        }
        if (!result.value.ok) {
          errors.push(`${label}: ошибка API ${result.value.status}`)
          setter(null)
          return false
        }
        try {
          setter((await result.value.json()) as T)
          return true
        } catch {
          errors.push(`${label}: ошибка разбора`)
          setter(null)
          return false
        }
      }

      const topPairsOk = await parseResult('Топ пар', results[0], setTopPairs)
      const signalsOk = await parseResult('Сигналы', results[1], setSignals)
      await parseResult('Бэктесты', results[2], setBacktests)
      await parseObjectResult<RefreshStatus>('Статус обновления', results[3], setRefreshStatus)

        if (topPairsOk && signalsOk) {
          setAuxLastUpdated(new Date().toISOString())
        }
        if (errors.length) {
          setAuxError(errors.join(' | '))
        }
      } catch (err) {
        setAuxError(err instanceof Error ? err.message : 'Не удалось загрузить таблицы')
      } finally {
        setAuxLoading(false)
        auxFetchInFlight.current = false
      }
    },
    [],
  )

  const fetchSignalHistory = useCallback(async () => {
    setHistoryLoading(true)
    setHistoryError(null)
    const params = new URLSearchParams()
    if (historyFrom) params.set('from', historyFrom)
    if (historyTo) params.set('to', historyTo)
    if (tableStockFilter) params.set('stock', tableStockFilter)
    if (tableFutureFilter) params.set('future', tableFutureFilter)
    if (tableSignalFilter) params.set('signal_action', tableSignalFilter)
    params.set('limit', '500')
    try {
      const response = await fetch(`/api/signals/history?${params.toString()}`, {
        cache: 'no-store',
      })
      if (!response.ok) {
        let message = `Ошибка API истории: ${response.status}`
        try {
          const payload = (await response.json()) as { error?: string }
          if (payload?.error) {
            message = `Ошибка API истории: ${payload.error}`
          }
        } catch {
          // ignore parsing errors, keep status-based message
        }
        throw new Error(message)
      }
      const data: SignalHistoryRow[] = await response.json()
      setSignalHistory(data)
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : 'Не удалось загрузить историю')
    } finally {
      setHistoryLoading(false)
    }
  }, [historyFrom, historyTo, tableFutureFilter, tableSignalFilter, tableStockFilter])

  const fetchExecutionLog = useCallback(async (pairKey: string, stock: string, future: string) => {
    setExecutionLoadingKey(pairKey)
    setExecutionError((prev) => ({ ...prev, [pairKey]: '' }))
    try {
      const params = new URLSearchParams({
        stock,
        future,
        limit: '20',
      })
      const response = await fetch(`/api/signals/executions?${params.toString()}`, {
        cache: 'no-store',
      })
      if (!response.ok) {
        throw new Error(`Ошибка API исполнений: ${response.status}`)
      }
      const data: ExecutionRow[] = await response.json()
      setExecutionLogs((prev) => ({ ...prev, [pairKey]: data }))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Не удалось загрузить исполнения'
      setExecutionError((prev) => ({ ...prev, [pairKey]: message }))
    } finally {
      setExecutionLoadingKey(null)
    }
  }, [])

  const handleExecuteSignal = useCallback(
    async (row: GenericRow) => {
      const payload = {
        stock: row.stock,
        future: row.future,
        direction: row.signal_direction,
        action: row.signal_action,
        price: executionForm.price ? Number(executionForm.price) : null,
        quantity: executionForm.quantity ? Number(executionForm.quantity) : null,
        side: executionForm.side || null,
        status: executionForm.status || null,
        note: executionForm.note || null,
      }
      const response = await fetch('/api/signals/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!response.ok) {
        throw new Error(`Ошибка API исполнения: ${response.status}`)
      }
      const pairKey = row.stock && row.future ? `${row.stock}-${row.future}` : null
      if (pairKey) {
        void fetchExecutionLog(pairKey, String(row.stock), String(row.future))
      }
      setExecutionForm({
        price: '',
        quantity: '',
        side: '',
        status: '',
        note: '',
      })
    },
    [executionForm, fetchExecutionLog],
  )

  const fetchSpreadSeries = useCallback(
    async (pairKey: string, stock: string, future: string) => {
      setSpreadLoadingKey(pairKey)
      setSpreadError((prev) => ({ ...prev, [pairKey]: '' }))
      try {
        const response = await fetch(
          `/api/spread-series?stock=${encodeURIComponent(stock)}&future=${encodeURIComponent(
            future,
          )}&full_life=true`,
          { cache: 'no-store' },
        )
        if (!response.ok) {
          throw new Error(`Ошибка API: ${response.status}`)
        }
        const data: SpreadSeriesPoint[] = await response.json()
        setSpreadSeries((prev) => ({ ...prev, [pairKey]: data }))
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Не удалось загрузить серию спреда'
        setSpreadError((prev) => ({ ...prev, [pairKey]: message }))
      } finally {
        setSpreadLoadingKey(null)
      }
    },
    [],
  )

  const fetchParamSpecs = useCallback(
    async (options?: { resetValues?: boolean }) => {
      setParamSpecsLoading(true)
      setParamSpecsError(null)
      const resetValues = options?.resetValues ?? false
      try {
        const params = new URLSearchParams()
        const preset = paramPreset.trim()
        if (preset) params.set('preset', preset)
        const url = params.toString() ? `/api/params/specs?${params.toString()}` : '/api/params/specs'
        const response = await fetch(url, { cache: 'no-store' })
        if (!response.ok) {
          throw new Error(`Ошибка API параметров: ${response.status}`)
        }
        const data = (await response.json()) as ParameterSpec[]
        setParamSpecs(data)
        setParamValues((prev) => {
          const defaults = buildParamDefaults(data)
          if (resetValues || Object.keys(prev).length === 0) {
            return defaults
          }
          const next: Record<string, ParamValue> = {}
          data.forEach((spec) => {
            next[spec.key] = spec.key in prev ? prev[spec.key] : defaults[spec.key]
          })
          return next
        })
      } catch (err) {
        setParamSpecsError(err instanceof Error ? err.message : 'Не удалось загрузить параметры')
      } finally {
        setParamSpecsLoading(false)
      }
    },
    [paramPreset],
  )

  const handleBacktestRun = useCallback(async () => {
    setBacktestRunLoading(true)
    setBacktestRunError(null)
    setBacktestRunParseError(null)
    setBacktestRunReport(null)
    try {
      const { payload, errors } = collectParamRequest(paramSpecs, paramValues)
      if (errors.length) {
        const summary = errors.slice(0, 6).join(' | ')
        setBacktestRunParseError(
          errors.length > 6 ? `${summary} | ... (${errors.length})` : summary,
        )
        return
      }
      const response = await fetch('/api/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request: payload, precompute: backtestPrecompute }),
      })
      const data = (await response.json()) as BacktestReport & { error?: string; message?: string }
      if (!response.ok) {
        throw new Error(data?.message || data?.error || `Ошибка API бэктеста: ${response.status}`)
      }
      setBacktestRunReport(data)
    } catch (err) {
      setBacktestRunError(err instanceof Error ? err.message : 'Не удалось запустить бэктест')
    } finally {
      setBacktestRunLoading(false)
    }
  }, [backtestPrecompute, paramSpecs, paramValues])

  const fetchForwardStatus = useCallback(async () => {
    setForwardLoading(true)
    setForwardError(null)
    try {
      const params = new URLSearchParams()
      const runId = forwardRunId.trim()
      if (runId) params.set('run_id', runId)
      const url = params.toString()
        ? `/api/forward/status?${params.toString()}`
        : '/api/forward/status'
      const response = await fetch(url, { cache: 'no-store' })
      const data = (await response.json()) as ForwardStatus & { error?: string; message?: string }
      if (!response.ok) {
        throw new Error(data?.message || data?.error || `Ошибка API форварда: ${response.status}`)
      }
      setForwardStatus(data)
    } catch (err) {
      setForwardError(err instanceof Error ? err.message : 'Не удалось загрузить статус форварда')
    } finally {
      setForwardLoading(false)
    }
  }, [forwardRunId])

  const handleHpoRun = useCallback(async () => {
    setHpoLoading(true)
    setHpoError(null)
    setHpoResponse(null)
    try {
      const { payload, errors } = collectParamRequest(paramSpecs, paramValues)
      if (errors.length) {
        const summary = errors.slice(0, 6).join(' | ')
        setHpoError(errors.length > 6 ? `${summary} | ... (${errors.length})` : summary)
        return
      }
      let searchSpace: Record<string, unknown> = {}
      if (hpoSearchSpace.trim()) {
        try {
          searchSpace = JSON.parse(hpoSearchSpace)
        } catch {
          setHpoError('Неверный JSON пространства поиска.')
          return
        }
      }
      const response = await fetch('/api/hpo/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ base: payload, search_space: searchSpace }),
      })
      const data = (await response.json()) as HpoResponse & { error?: string; message?: string }
      if (!response.ok) {
        throw new Error(data?.message || data?.error || `Ошибка API HPO: ${response.status}`)
      }
      setHpoResponse(data)
    } catch (err) {
      setHpoError(err instanceof Error ? err.message : 'Не удалось запустить HPO')
    } finally {
      setHpoLoading(false)
    }
  }, [hpoSearchSpace, paramSpecs, paramValues])

  useEffect(() => {
    fetchDecisionView()
    fetchAuxData({ topPairsLimit, topPairsAll })
  }, [fetchDecisionView, fetchAuxData, topPairsAll, topPairsLimit])

  useEffect(() => {
    if (!autoRefresh) return
    const interval = window.setInterval(() => {
      void fetchAuxData({ topPairsLimit, topPairsAll })
    }, AUTO_REFRESH_MS)
    return () => window.clearInterval(interval)
  }, [autoRefresh, fetchAuxData, topPairsAll, topPairsLimit])

  useEffect(() => {
    if (tab !== 'backtest_v2' && tab !== 'hpo') return
    if (paramSpecsLoading || paramSpecs.length > 0) return
    void fetchParamSpecs({ resetValues: true })
  }, [fetchParamSpecs, paramSpecs.length, paramSpecsLoading, tab])

  const requestRecompute = useCallback(async (): Promise<boolean> => {
    setRecomputeLoading(true)
    setRecomputeError(null)
    try {
      const response = await fetch('/api/signals/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (!response.ok) {
        let message = `Ошибка API пересчёта: ${response.status}`
        try {
          const payload = (await response.json()) as { last_error?: string }
          if (payload?.last_error) {
            message = `Recompute error: ${payload.last_error}`
          }
        } catch {
          // ignore parsing errors
        }
        throw new Error(message)
      }
      const payload = (await response.json()) as RefreshStatus
      setRefreshStatus(payload)
      return true
    } catch (err) {
      setRecomputeError(err instanceof Error ? err.message : 'Не удалось пересчитать данные')
      return false
    } finally {
      setRecomputeLoading(false)
    }
  }, [])

  const handleRefresh = useCallback(() => {
    fetchDecisionView()
    fetchAuxData({ topPairsLimit, topPairsAll })
  }, [fetchDecisionView, fetchAuxData, topPairsAll, topPairsLimit])

  const handleAuxRefresh = useCallback(async () => {
    await requestRecompute()
    await fetchAuxData({ topPairsLimit, topPairsAll })
  }, [fetchAuxData, requestRecompute, topPairsAll, topPairsLimit])

  const handleParamValueChange = useCallback((key: string, value: ParamValue) => {
    setParamValues((prev) => ({ ...prev, [key]: value }))
  }, [])

  const handleParamReset = useCallback(() => {
    if (!paramSpecs.length) return
    setParamValues(buildParamDefaults(paramSpecs))
  }, [paramSpecs])

  const submitDecisionAction = useCallback(
    async (action: 'approve' | 'reject') => {
      if (!selectedId) return
      setDecisionActionSubmitting(true)
      setDecisionActionError(null)
      try {
        const response = await fetch(`/api/decisions/${selectedId}/action`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action,
            note: decisionActionNote || undefined,
          }),
        })
        if (!response.ok) {
          throw new Error(`Ошибка API: ${response.status}`)
        }
        const data = (await response.json()) as {
          operator_action?: OperatorAction
          execution_status?: ExecutionStatus
        }
        setDecisionAction(data)
        if (data.operator_action || data.execution_status) {
          setRows((prev) =>
            prev.map((row) =>
              row.decision_id === selectedId
                ? {
                    ...row,
                    operator_action: data.operator_action ?? row.operator_action,
                    execution_status: data.execution_status ?? row.execution_status,
                  }
                : row,
            ),
          )
        }
        setDecisionActionNote('')
      } catch (err) {
        setDecisionActionError(err instanceof Error ? err.message : 'Не удалось отправить действие')
      } finally {
        setDecisionActionSubmitting(false)
      }
    },
    [decisionActionNote, selectedId],
  )

  const strategyOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.strategy_type).filter(Boolean))).sort(),
    [rows],
  )
  const instrumentOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.primary_instrument).filter(Boolean))).sort(),
    [rows],
  )
  const riskOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.risk_state).filter(Boolean))).sort(),
    [rows],
  )
  const newsOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.news_severity).filter(Boolean))).sort(),
    [rows],
  )

  const tableRows = useMemo<GenericRow[]>(() => {
    if (tab === 'top_pairs') return topPairs
    if (tab === 'signals') return signals
    if (tab === 'backtests') return backtests
    return []
  }, [tab, topPairs, signals, backtests])

  const tableColumns = useMemo(() => getTableColumns(tableRows), [tableRows])
  const tableVisibleColumns = useMemo(() => {
    const available = new Set(tableColumns)
    const pick = (columns: string[]) => columns.filter((column) => available.has(column))
    if (tab === 'top_pairs') {
      return pick([
        'stock',
        'stock_name',
        'future',
        'expiry',
        'spread_pct',
        'rtc_pct',
        'floor_rate_annual',
        'score_floor',
        'total_score',
        'avg_trade_return_annual_recent',
        'decision',
        'signal_action',
        'signal_direction',
      ])
    }
    if (tab === 'signals') {
      return pick([
        'timestamp',
        'stock',
        'future',
        'signal_action',
        'signal_direction',
        'signal_score',
        'spread_pct',
        'floor_rate_annual',
      ])
    }
    return tableColumns
  }, [tab, tableColumns])
  const tableVisibleSet = useMemo(() => new Set(tableVisibleColumns), [tableVisibleColumns])
  const stripDuplicates = useCallback(
    (entries: { key: string; value: unknown }[]) => {
      const filtered = entries.filter((entry) => !tableVisibleSet.has(entry.key))
      return filtered.length ? filtered : entries
    },
    [tableVisibleSet],
  )

  const defaultSortKey = useMemo(() => {
    if (tab === 'top_pairs' && tableVisibleColumns.includes('total_score')) return 'total_score'
    if (tab === 'top_pairs' && tableVisibleColumns.includes('score_floor')) return 'score_floor'
    if (tab === 'signals' && tableVisibleColumns.includes('signal_score')) return 'signal_score'
    if (tab === 'backtests' && tableVisibleColumns.includes('cagr')) return 'cagr'
    return tableVisibleColumns[0] ?? ''
  }, [tab, tableVisibleColumns])

  useEffect(() => {
    setExpandedRowKey(null)
    setTableStockFilter('')
    setTableFutureFilter('')
    setTableSignalFilter('')
  }, [tab])

  useEffect(() => {
    if (!tableVisibleColumns.length) return
    if (!tableSortKey || !tableVisibleColumns.includes(tableSortKey)) {
      if (defaultSortKey) {
        setTableSortKey(defaultSortKey)
        setTableSortDirection('desc')
      }
    }
  }, [defaultSortKey, tableSortKey, tableVisibleColumns])

  useEffect(() => {
    setDecisionActionNote('')
  }, [selectedId])

  const filteredRows = useMemo(() => {
    const quick = quickFilter.trim().toLowerCase()
    return rows.filter((row) => {
      if (strategyFilter && row.strategy_type !== strategyFilter) return false
      if (instrumentFilter && row.primary_instrument !== instrumentFilter) return false
      if (riskFilter && row.risk_state !== riskFilter) return false
      if (newsFilter && row.news_severity !== newsFilter) return false
      if (quick) {
        const haystack = JSON.stringify(row).toLowerCase()
        if (!haystack.includes(quick)) return false
      }
      return true
    })
  }, [rows, strategyFilter, instrumentFilter, riskFilter, newsFilter, quickFilter])

  const selectedDecision = useMemo(
    () => rows.find((row) => row.decision_id === selectedId) ?? null,
    [rows, selectedId],
  )

  const signalFilterRows = useMemo<GenericRow[]>(() => {
    if (tab !== 'signals') return tableRows
    if (!signalHistory.length) return tableRows
    if (!tableRows.length) {
      return signalHistory.map((row) => row as unknown as GenericRow)
    }
    return [
      ...tableRows,
      ...signalHistory.map((row) => row as unknown as GenericRow),
    ]
  }, [signalHistory, tab, tableRows])

  const tableStockOptions = useMemo(
    () =>
      Array.from(new Set(signalFilterRows.map((row) => row.stock).filter(Boolean).map(String))).sort(),
    [signalFilterRows],
  )
  const tableFutureOptions = useMemo(
    () =>
      Array.from(new Set(signalFilterRows.map((row) => row.future).filter(Boolean).map(String))).sort(),
    [signalFilterRows],
  )
  const tableSignalOptions = useMemo(
    () =>
      Array.from(
        new Set(signalFilterRows.map((row) => row.signal_action).filter(Boolean).map(String)),
      ).sort(),
    [signalFilterRows],
  )

  const filteredParamSpecs = useMemo(() => {
    const query = paramFilter.trim().toLowerCase()
    if (!query) return paramSpecs
    return paramSpecs.filter((spec) => {
      const label = getParamLabel(spec).toLowerCase()
      return spec.key.toLowerCase().includes(query) || label.includes(query)
    })
  }, [paramFilter, paramSpecs])

  const paramSections = useMemo<[string, ParameterSpec[]][]>(() => {
    const grouped = new Map<string, ParameterSpec[]>()
    filteredParamSpecs.forEach((spec) => {
      const section = spec.key.split('.')[0] || 'general'
      const list = grouped.get(section) ?? []
      list.push(spec)
      grouped.set(section, list)
    })
    const orderIndex = new Map(paramSectionOrder.map((section, index) => [section, index]))
    return Array.from(grouped.entries())
      .map(([section, specs]) => [
        section,
        specs.sort((left, right) => left.key.localeCompare(right.key)),
      ])
      .sort(([left], [right]) => {
        const leftRank = orderIndex.get(left) ?? Number.MAX_SAFE_INTEGER
        const rightRank = orderIndex.get(right) ?? Number.MAX_SAFE_INTEGER
        if (leftRank !== rightRank) return leftRank - rightRank
        return left.localeCompare(right)
      })
  }, [filteredParamSpecs])

  const backtestSummaryEntries = useMemo(() => {
    const metrics = backtestRunReport?.summary_metrics
    if (!metrics) return []
    return Object.entries(metrics).map(([key, value]) => ({ key, value }))
  }, [backtestRunReport])

  const backtestEquityRows = useMemo<GenericRow[]>(
    () => (backtestRunReport?.equity_curve ?? []) as GenericRow[],
    [backtestRunReport],
  )

  const backtestTradeRows = useMemo<GenericRow[]>(
    () => (backtestRunReport?.trades ?? []) as GenericRow[],
    [backtestRunReport],
  )

  const backtestEquityColumns = useMemo(() => {
    const columns = getTableColumns(backtestEquityRows)
    const preferred = ['date', 'equity', 'cash', 'drawdown', 'turnover', 'positions']
    const ordered = preferred.filter((column) => columns.includes(column))
    const rest = columns.filter((column) => !preferred.includes(column))
    return [...ordered, ...rest]
  }, [backtestEquityRows])

  const backtestTradeColumns = useMemo(() => {
    const columns = getTableColumns(backtestTradeRows)
    const preferred = [
      'pair_id',
      'stock_secid',
      'future_secid',
      'direction',
      'entry_date',
      'exit_date',
      'entry_price_stock',
      'entry_price_fut',
      'exit_price_stock',
      'exit_price_fut',
      'quantity_stock',
      'quantity_fut',
      'pnl',
      'hold_days',
      'exit_reason',
    ]
    const ordered = preferred.filter((column) => columns.includes(column))
    const rest = columns.filter((column) => !preferred.includes(column))
    return [...ordered, ...rest]
  }, [backtestTradeRows])

  const hpoLeaderboardRows = useMemo<HpoTrial[]>(() => {
    if (!hpoResponse) return []
    const payload = hpoResponse.result ?? hpoResponse
    const raw = payload.leaderboard ?? payload.trials ?? []
    if (!Array.isArray(raw)) return []
    const mode = payload.mode ?? 'max'
    const rows = raw.slice() as HpoTrial[]
    if (rows.length && typeof rows[0]?.objective === 'number') {
      rows.sort((left, right) => {
        const leftValue = left.objective ?? Number.NEGATIVE_INFINITY
        const rightValue = right.objective ?? Number.NEGATIVE_INFINITY
        return mode === 'min' ? leftValue - rightValue : rightValue - leftValue
      })
    }
    return rows
  }, [hpoResponse])

  const hpoLeaderboardColumns = useMemo(() => {
    const rows = hpoLeaderboardRows as GenericRow[]
    const columns = getTableColumns(rows)
    const preferred = ['objective', 'params', 'fold_objectives']
    const ordered = preferred.filter((column) => columns.includes(column))
    const rest = columns.filter((column) => !preferred.includes(column))
    return [...ordered, ...rest]
  }, [hpoLeaderboardRows])

  const decisionColumns = useMemo<GridColDef[]>(
    () => [
      {
        headerName: getFieldLabel('created_at'),
        description: getFieldTooltip('created_at'),
        field: 'created_at',
        valueFormatter: (params: { value?: unknown }) => formatDate(params?.value as string),
        width: 190,
      },
      {
        headerName: getFieldLabel('decision_id'),
        description: getFieldTooltip('decision_id'),
        field: 'decision_id',
        width: 260,
        cellClassName: 'cell-mono',
      },
      {
        headerName: getFieldLabel('strategy_type'),
        description: getFieldTooltip('strategy_type'),
        field: 'strategy_type',
        width: 160,
        valueFormatter: (params: { value?: unknown }) =>
          formatValue(params?.value, 'strategy_type'),
      },
      {
        headerName: getFieldLabel('primary_instrument'),
        description: getFieldTooltip('primary_instrument'),
        field: 'primary_instrument',
        width: 140,
      },
      {
        headerName: getFieldLabel('proposal_type'),
        description: getFieldTooltip('proposal_type'),
        field: 'proposal_type',
        width: 140,
        valueGetter: (params: { row?: DecisionView } | undefined) =>
          params?.row?.proposal_summary?.type ?? '',
        valueFormatter: (params: { value?: unknown }) =>
          formatValue(params?.value, 'proposal_type'),
      },
      {
        headerName: getFieldLabel('action'),
        description: getFieldTooltip('action'),
        field: 'action',
        width: 120,
        cellClassName: (params) =>
          params.value === 'approve'
            ? 'cell-approve'
            : params.value === 'reject'
              ? 'cell-reject'
              : '',
        valueFormatter: (params: { value?: unknown }) => formatValue(params?.value, 'action'),
      },
      {
        headerName: getFieldLabel('risk_state'),
        description: getFieldTooltip('risk_state'),
        field: 'risk_state',
        width: 110,
        cellClassName: (params) =>
          params.value === 'green'
            ? 'cell-risk-green'
            : params.value === 'yellow'
              ? 'cell-risk-yellow'
              : params.value === 'red'
                ? 'cell-risk-red'
                : '',
        valueFormatter: (params: { value?: unknown }) => formatValue(params?.value, 'risk_state'),
      },
      {
        headerName: getFieldLabel('news_severity'),
        description: getFieldTooltip('news_severity'),
        field: 'news_severity',
        width: 110,
        cellClassName: (params) =>
          params.value === 'high'
            ? 'cell-news-high'
            : params.value === 'critical'
              ? 'cell-news-critical'
              : '',
        valueFormatter: (params: { value?: unknown }) =>
          formatValue(params?.value, 'news_severity'),
      },
      {
        headerName: getFieldLabel('execution_status'),
        description: getFieldTooltip('execution_status'),
        field: 'execution_status',
        width: 140,
        valueGetter: (params: { row?: DecisionView } | undefined) =>
          params?.row?.execution_status?.status ??
          params?.row?.operator_action?.status ??
          '',
        valueFormatter: (params: { value?: unknown }) => formatValue(params?.value, 'status'),
      },
      {
        headerName: getFieldLabel('cost_round_trip'),
        description: getFieldTooltip('cost_round_trip'),
        field: 'cost_round_trip',
        valueFormatter: (params: { value?: unknown }) =>
          formatValue(params?.value, 'cost_round_trip'),
        width: 120,
      },
      {
        headerName: getFieldLabel('max_drawdown'),
        description: getFieldTooltip('max_drawdown'),
        field: 'max_drawdown',
        valueFormatter: (params: { value?: unknown }) =>
          formatValue(params?.value, 'max_drawdown'),
        width: 120,
      },
    ],
    [],
  )

  const handleRowClick = useCallback(
    (params: GridRowParams<DecisionView> | undefined) => {
      const decisionId = params?.row?.decision_id
      if (!decisionId) return
      setSelectedId(decisionId)
      fetchDecisionLog(decisionId)
      fetchDecisionAction(decisionId)
    },
    [fetchDecisionAction, fetchDecisionLog],
  )

  const handleTableSort = useCallback(
    (column: string) => {
      if (tableSortKey === column) {
        setTableSortDirection((prevDirection) => (prevDirection === 'asc' ? 'desc' : 'asc'))
      } else {
        setTableSortKey(column)
        setTableSortDirection('asc')
      }
    },
    [tableSortKey],
  )

  const handleToggleDetails = useCallback(
    (row: GenericRow) => {
      const pairKey =
        (row.stock && row.future ? `${row.stock}-${row.future}` : null) ?? String(row.id)
      if (expandedRowKey === pairKey) {
        setExpandedRowKey(null)
        return
      }
      setExpandedRowKey(pairKey)
      setDetailTab('overview')
      const stock = row.stock ? String(row.stock) : ''
      const future = row.future ? String(row.future) : ''
      if (stock && future && !spreadSeries[pairKey]) {
        void fetchSpreadSeries(pairKey, stock, future)
      }
      if (tab === 'signals' && stock && future && !executionLogs[pairKey]) {
        void fetchExecutionLog(pairKey, stock, future)
      }
    },
    [expandedRowKey, executionLogs, fetchExecutionLog, fetchSpreadSeries, spreadSeries, tab],
  )

  const isLoading = loading || auxLoading || recomputeLoading

  const decisionRows = useMemo(
    () =>
      filteredRows.map((row) => ({
        id: row.decision_id,
        ...row,
        cost_round_trip: row.cost_summary?.round_trip_cost ?? null,
        max_drawdown: row.backtest_metrics?.max_drawdown ?? null,
      })),
    [filteredRows],
  )

  const filteredTableRows = useMemo<GenericRow[]>(() => {
    const query = tableFilter.trim().toLowerCase()
    const baseRows: GenericRow[] = tableRows.map((row, index) => ({
      id:
        row.id ??
        row.decision_id ??
        (row.stock && row.future ? `${row.stock}-${row.future}` : null) ??
        row.signal_id ??
        row.instrument ??
        row.snapshot_id ??
        `${tab}-${index}`,
      ...row,
    })) as GenericRow[]
    return baseRows.filter((row) => {
      if (tab === 'top_pairs' || tab === 'signals') {
        if (tableStockFilter && String(row.stock ?? '') !== tableStockFilter) return false
        if (tableFutureFilter && String(row.future ?? '') !== tableFutureFilter) return false
        if (tableSignalFilter && String(row.signal_action ?? '') !== tableSignalFilter) return false
      }
      if (query && !JSON.stringify(row).toLowerCase().includes(query)) return false
      return true
    })
  }, [
    tableRows,
    tableFilter,
    tab,
    tableStockFilter,
    tableFutureFilter,
    tableSignalFilter,
  ])

  const sortedTableRows = useMemo<GenericRow[]>(() => {
    if (!tableSortKey) return filteredTableRows
    const sorted = [...filteredTableRows].sort((left, right) =>
      compareValues(left[tableSortKey], right[tableSortKey]),
    )
    return tableSortDirection === 'asc' ? sorted : sorted.reverse()
  }, [filteredTableRows, tableSortDirection, tableSortKey])

  const filteredSignalHistory = useMemo(() => {
    if (!signalHistory.length) return []
    const query = tableFilter.trim().toLowerCase()
    const fromTs = parseDateInput(historyFrom, 'start')
    const toTs = parseDateInput(historyTo, 'end')
    return signalHistory.filter((row) => {
      const rowTs = Date.parse(row.timestamp)
      if ((fromTs !== null || toTs !== null) && Number.isNaN(rowTs)) return false
      if (fromTs !== null && rowTs < fromTs) return false
      if (toTs !== null && rowTs > toTs) return false
      if (tableStockFilter && String(row.stock ?? '') !== tableStockFilter) return false
      if (tableFutureFilter && String(row.future ?? '') !== tableFutureFilter) return false
      if (tableSignalFilter && String(row.signal_action ?? '') !== tableSignalFilter) return false
      if (query && !JSON.stringify(row).toLowerCase().includes(query)) return false
      return true
    })
  }, [
    signalHistory,
    tableFilter,
    tableStockFilter,
    tableFutureFilter,
    tableSignalFilter,
    historyFrom,
    historyTo,
  ])

  const detailRecord = (detail as Record<string, unknown> | null) ?? null
  const detailDecision = detailRecord ? getObject<Record<string, unknown>>(detailRecord['decision']) : null
  const detailAggregation = detailRecord
    ? getObject<Record<string, unknown>>(detailRecord['aggregation'])
    : null
  const detailProposal = detailRecord ? getObject<Record<string, unknown>>(detailRecord['proposal']) : null
  const detailBasket = detailRecord
    ? getObject<Record<string, unknown>>(detailRecord['basket_allocations'])
    : null
  const detailFacts = detailRecord ? getArray<Record<string, unknown>>(detailRecord['facts']) : []
  const operatorAction =
    decisionAction?.operator_action ?? selectedDecision?.operator_action ?? undefined
  const executionStatus =
    decisionAction?.execution_status ?? selectedDecision?.execution_status ?? undefined

  const basketRows = useMemo(() => {
    const current = getArray<BasketAllocation>(detailBasket?.current)
    const target = getArray<BasketAllocation>(detailBasket?.target)
    const delta = getArray<BasketAllocation>(detailBasket?.delta)
    const buckets = new Set<string>()
    current.forEach((row) => row.basket && buckets.add(row.basket))
    target.forEach((row) => row.basket && buckets.add(row.basket))
    delta.forEach((row) => row.basket && buckets.add(row.basket))
    return Array.from(buckets).map((basket) => ({
      basket,
      current: current.find((row) => row.basket === basket)?.weight,
      target: target.find((row) => row.basket === basket)?.weight,
      delta: delta.find((row) => row.basket === basket)?.weight,
    }))
  }, [detailBasket])

  const showPairDetails = tab === 'top_pairs' || tab === 'signals'

  const snapshotFields = useMemo(
    () => [
      'stock',
      'stock_name',
      'future',
      'expiry',
      'spot',
      'future_price',
      'spread_mid',
      'spread_pct',
      'rtc_pct',
      'total_score',
    ],
    [],
  )

  const overviewFields = useMemo(
    () => [
      'floor_pass',
      'liquidity_pass',
      'dte',
      'floor_rate_annual',
      'score_floor',
      'r_cb_annual',
      'r_fund_annual',
      'r_disc_annual',
      'snapshot_as_of',
    ],
    [],
  )

  const alphaFields = useMemo(
    () => [
      'avg_trade_return_annual_recent',
      'score_alpha',
      'p_hit_tp',
      'p_hit_sl',
      'sigma_h',
      'half_life',
    ],
    [],
  )

  const liquidityFields = useMemo(
    () => [
      'spread_bps_stock',
      'spread_bps_fut',
      'dollar_vol_stock',
      'dollar_vol_fut',
      'days_to_exit',
      'open_interest',
    ],
    [],
  )

  const executionFields = useMemo(() => {
    const base = ['signal_action', 'signal_direction', 'signal_score']
    const extra =
      tab === 'signals' ? ['signal_reasons', 'signal_metrics'] : ['decision']
    return [...base, ...extra]
  }, [tab])

  const renderFieldGrid = (entries: { key: string; value: unknown }[]) => (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
        gap: 1,
        mt: 1,
      }}
    >
      {entries.map((entry) => (
        <Box key={entry.key}>
          <Typography variant="caption" color="text.secondary">
            {renderFieldLabel(entry.key)}
          </Typography>
          <Typography variant="body2">{formatCellValue(entry.value, entry.key)}</Typography>
        </Box>
      ))}
    </Box>
  )

  const renderKeyValueGrid = (payload?: Record<string, unknown>, emptyLabel = 'Нет данных') => {
    const entries = Object.entries(payload ?? {}).map(([key, value]) => ({ key, value }))
    if (!entries.length) {
      return (
        <Typography variant="body2" color="text.secondary">
          {emptyLabel}
        </Typography>
      )
    }
    return renderFieldGrid(entries)
  }

  const renderJsonBlock = (payload: unknown) => (
    <Box
      component="pre"
      sx={{
        margin: 0,
        padding: 1.5,
        borderRadius: 1,
        backgroundColor: '#0b1020',
        color: '#e2e8f0',
        fontSize: '12px',
        overflow: 'auto',
      }}
    >
      {JSON.stringify(payload, null, 2)}
    </Box>
  )

  const renderTable = (rows: GenericRow[], columns: string[], emptyLabel: string) => {
    if (!rows.length || !columns.length) {
      return (
        <Typography variant="body2" color="text.secondary">
          {emptyLabel}
        </Typography>
      )
    }
    return (
      <TableContainer sx={{ maxHeight: '60vh' }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              {columns.map((column) => (
                <TableCell key={column}>{renderFieldLabel(column)}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row, index) => {
              const rowKey = row.id ?? row.pair_id ?? row.date ?? `row-${index}`
              return (
                <TableRow key={`${String(rowKey)}-${index}`}>
                  {columns.map((column) => (
                    <TableCell key={`${column}-${index}`}>
                      {isDateColumn(column)
                        ? formatDate(String(row[column] ?? ''))
                        : formatCellValue(row[column], column)}
                    </TableCell>
                  ))}
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </TableContainer>
    )
  }

  const renderParamInput = (spec: ParameterSpec) => {
    const value = paramValues[spec.key]
    const label = getParamLabel(spec)
    const tooltip = getParamTooltip(spec)
    const helperText = buildParamHelperText(spec)
    const labelNode = <ParamLabel label={label} tooltip={tooltip} />
    const inputLabelProps = { sx: { pointerEvents: 'auto' } }

    if (spec.value_type === 'dict') {
      const dictValue = parseParamDictValue(value)
      const entries = getParamDictEntries(spec, dictValue)
      return (
        <Box key={spec.key} sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Typography variant="caption" fontWeight={600}>
            {labelNode}
          </Typography>
          {entries.length ? (
            <Stack spacing={1}>
              {entries.map((entry) => (
                <Stack key={entry.key} direction="row" spacing={1} alignItems="center">
                  <Typography variant="body2" sx={{ minWidth: 160 }}>
                    {entry.label}
                  </Typography>
                  <TextField
                    size="small"
                    type="number"
                    value={
                      entry.value === null || entry.value === undefined
                        ? ''
                        : String(entry.value)
                    }
                    onChange={(event) => {
                      const nextValue = event.target.value
                      const next = { ...dictValue, [entry.key]: nextValue }
                      handleParamValueChange(spec.key, next)
                    }}
                    inputProps={{ step: 'any' }}
                    sx={{ flex: 1 }}
                  />
                </Stack>
              ))}
            </Stack>
          ) : (
            <Typography variant="body2" color="text.secondary">
              Нет значений.
            </Typography>
          )}
          {helperText ? (
            <Typography variant="caption" color="text.secondary">
              {helperText}
            </Typography>
          ) : null}
        </Box>
      )
    }

    if (spec.value_type === 'bool') {
      return (
        <Box key={spec.key}>
          <FormControlLabel
            control={
              <Switch
                checked={Boolean(value)}
                onChange={(event) => handleParamValueChange(spec.key, event.target.checked)}
              />
            }
            label={labelNode}
          />
          {helperText ? (
            <Typography variant="caption" color="text.secondary">
              {helperText}
            </Typography>
          ) : null}
        </Box>
      )
    }

    if (spec.options && spec.options.length) {
      const stringValue = typeof value === 'string' ? value : compactJson(value)
      return (
        <TextField
          key={spec.key}
          select
          fullWidth
          size="small"
          label={labelNode}
          InputLabelProps={inputLabelProps}
          value={stringValue}
          onChange={(event) => handleParamValueChange(spec.key, event.target.value)}
          helperText={helperText}
        >
          {spec.options.map((option) => (
            <MenuItem key={String(option)} value={String(option)}>
              {getParamOptionLabel(spec, option)}
            </MenuItem>
          ))}
        </TextField>
      )
    }

    const inputValue =
      typeof value === 'string' || typeof value === 'number'
        ? String(value)
        : value === undefined || value === null
          ? ''
          : compactJson(value)
    const multiline = isJsonValueType(spec.value_type) || spec.value_type === 'union'
    const inputType =
      spec.value_type === 'int' || spec.value_type === 'float' ? 'number' : 'text'
    const step = spec.value_type === 'int' ? '1' : 'any'

    return (
      <TextField
        key={spec.key}
        fullWidth
        size="small"
        label={labelNode}
        InputLabelProps={inputLabelProps}
        value={inputValue}
        onChange={(event) => handleParamValueChange(spec.key, event.target.value)}
        helperText={helperText}
        type={inputType}
        multiline={multiline}
        minRows={multiline ? 3 : undefined}
        inputProps={inputType === 'number' ? { step } : undefined}
      />
    )
  }

  return (
    <Box className="app-root">
      <Container maxWidth="xl" sx={{ py: 3 }}>
        <Stack spacing={2}>
          <Typography variant="h5" fontWeight={600}>
            Решения торгового советника
          </Typography>
          <Tabs value={tab} onChange={(_, value) => setTab(value)}>
            <Tab label="Решения" value="decisions" />
            <Tab label="Топ пар" value="top_pairs" />
            <Tab label="Сигналы" value="signals" />
            <Tab label="Бэктесты" value="backtests" />
            <Tab label="Бэктест v2" value="backtest_v2" />
            <Tab label="Статус форварда" value="forward" />
            <Tab label="HPO" value="hpo" />
          </Tabs>
          {tab === 'decisions' ? (
            <>
              <Paper sx={{ p: 2 }}>
                <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                  <TextField
                    label="Быстрый поиск"
                    size="small"
                    value={quickFilter}
                    onChange={(event) => setQuickFilter(event.target.value)}
                    sx={{ minWidth: 240 }}
                  />
                  <FormControl size="small" sx={{ minWidth: 160 }}>
                    <InputLabel>Стратегия</InputLabel>
                    <Select
                      label="Стратегия"
                      value={strategyFilter}
                      onChange={(event) => setStrategyFilter(event.target.value)}
                    >
                      <MenuItem value="">Все</MenuItem>
                      {strategyOptions.map((item) => (
                        <MenuItem key={item} value={item}>
                          {formatValue(item, 'strategy_type')}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 160 }}>
                    <InputLabel>Инструмент</InputLabel>
                    <Select
                      label="Инструмент"
                      value={instrumentFilter}
                      onChange={(event) => setInstrumentFilter(event.target.value)}
                    >
                      <MenuItem value="">Все</MenuItem>
                      {instrumentOptions.map((item) => (
                        <MenuItem key={item} value={item}>
                          {item}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 140 }}>
                    <InputLabel>Риск</InputLabel>
                    <Select
                      label="Риск"
                      value={riskFilter}
                      onChange={(event) => setRiskFilter(event.target.value)}
                    >
                      <MenuItem value="">Все</MenuItem>
                      {riskOptions.map((item) => (
                        <MenuItem key={item} value={item}>
                          {formatValue(item, 'risk_state')}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 140 }}>
                    <InputLabel>Новости</InputLabel>
                    <Select
                      label="Новости"
                      value={newsFilter}
                      onChange={(event) => setNewsFilter(event.target.value)}
                    >
                      <MenuItem value="">Все</MenuItem>
                      {newsOptions.map((item) => (
                        <MenuItem key={item} value={item}>
                          {formatValue(item, 'news_severity')}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <Button variant="contained" onClick={handleRefresh} disabled={isLoading}>
                    Обновить
                  </Button>
                  <Typography variant="body2" color="text.secondary">
                    {isLoading ? 'Загрузка...' : `${filteredRows.length} строк`}
                  </Typography>
                  {error ? (
                    <Typography variant="body2" color="error">
                      {error}
                    </Typography>
                  ) : null}
                </Stack>
              </Paper>
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="stretch">
                <Paper sx={{ flex: 2, p: 2 }}>
                  <DataGrid
                    rows={decisionRows}
                    columns={decisionColumns}
                    loading={loading}
                    onRowClick={handleRowClick}
                    disableRowSelectionOnClick
                    pageSizeOptions={[10, 25, 50, 100]}
                    initialState={{
                      pagination: { paginationModel: { pageSize: 10, page: 0 } },
                    }}
                    slots={{ toolbar: GridToolbar }}
                    slotProps={{ toolbar: { showQuickFilter: false } }}
                    localeText={ruRU.components.MuiDataGrid.defaultProps.localeText}
                    sx={{ height: '68vh' }}
                  />
                </Paper>
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
                              selectedDecision?.action ||
                                getString(detailDecision?.['action']) ||
                                'hold',
                              'action',
                            )}`}
                            color="primary"
                            size="small"
                          />
                          <Chip
                            label={`Риск: ${formatValue(
                              selectedDecision?.risk_state ||
                                getString(detailDecision?.['risk_state']) ||
                                'н/д',
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
                              onChange={(event) => setDecisionActionNote(event.target.value)}
                              sx={{ minWidth: 220 }}
                            />
                            <Button
                              variant="contained"
                              color="success"
                              disabled={!selectedId || decisionActionSubmitting}
                              onClick={() => submitDecisionAction('approve')}
                            >
                              Одобрить и исполнить
                            </Button>
                            <Button
                              variant="outlined"
                              color="error"
                              disabled={!selectedId || decisionActionSubmitting}
                              onClick={() => submitDecisionAction('reject')}
                            >
                              Отклонить и исполнить
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
                                label={`Оператор: ${formatValue(
                                  operatorAction.action ?? 'н/д',
                                  'action',
                                )}`}
                                size="small"
                              />
                              {operatorAction.status ? (
                                <Chip
                                  label={`Статус: ${formatValue(
                                    operatorAction.status,
                                    'status',
                                  )}`}
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
                                  label={`Исполнение: ${formatValue(
                                    executionStatus.status,
                                    'status',
                                  )}`}
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
                            <Table size="small">
                              <TableHead>
                                <TableRow>
                                  <TableCell>Корзина</TableCell>
                                  <TableCell>Текущее</TableCell>
                                  <TableCell>Целевое</TableCell>
                                  <TableCell>Дельта</TableCell>
                                </TableRow>
                              </TableHead>
                              <TableBody>
                                {basketRows.map((row) => (
                                  <TableRow key={row.basket}>
                                    <TableCell>{formatValue(row.basket, 'basket')}</TableCell>
                                    <TableCell>{formatValue(row.current, 'basket_weight')}</TableCell>
                                    <TableCell>{formatValue(row.target, 'basket_weight')}</TableCell>
                                    <TableCell>{formatValue(row.delta, 'basket_weight')}</TableCell>
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
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

                        <Accordion>
                          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                            <Typography variant="subtitle2">Сырой лог решения</Typography>
                          </AccordionSummary>
                          <AccordionDetails>
                            <Box
                              component="pre"
                              sx={{
                                margin: 0,
                                padding: 1.5,
                                borderRadius: 1,
                                backgroundColor: '#0b1020',
                                color: '#e2e8f0',
                                fontSize: '12px',
                                overflow: 'auto',
                              }}
                            >
                              {JSON.stringify(detail, null, 2)}
                            </Box>
                          </AccordionDetails>
                        </Accordion>
                      </Stack>
                    ) : (
                      <Typography variant="body2" color="text.secondary">
                        Выберите решение, чтобы просмотреть полный лог.
                      </Typography>
                    )}
                  </Stack>
                </Paper>
              </Stack>
            </>
          ) : null}
          {tab === 'top_pairs' || tab === 'signals' || tab === 'backtests' ? (
            <>
              <Paper sx={{ p: 2 }}>
                <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                  <TextField
                    label="Быстрый поиск"
                    size="small"
                    value={tableFilter}
                    onChange={(event) => setTableFilter(event.target.value)}
                    sx={{ minWidth: 240 }}
                  />
                  {tab === 'top_pairs' || tab === 'signals' ? (
                    <>
                      <FormControl size="small" sx={{ minWidth: 140 }}>
                        <InputLabel>Акция</InputLabel>
                        <Select
                          label="Акция"
                          value={tableStockFilter}
                          onChange={(event) => setTableStockFilter(event.target.value)}
                        >
                          <MenuItem value="">Все</MenuItem>
                          {tableStockOptions.map((item) => (
                            <MenuItem key={item} value={item}>
                              {item}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <FormControl size="small" sx={{ minWidth: 140 }}>
                        <InputLabel>Фьючерс</InputLabel>
                        <Select
                          label="Фьючерс"
                          value={tableFutureFilter}
                          onChange={(event) => setTableFutureFilter(event.target.value)}
                        >
                          <MenuItem value="">Все</MenuItem>
                          {tableFutureOptions.map((item) => (
                            <MenuItem key={item} value={item}>
                              {item}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <FormControl size="small" sx={{ minWidth: 140 }}>
                        <InputLabel>Сигнал</InputLabel>
                        <Select
                          label="Сигнал"
                          value={tableSignalFilter}
                          onChange={(event) => setTableSignalFilter(event.target.value)}
                        >
                          <MenuItem value="">Все</MenuItem>
                          {tableSignalOptions.map((item) => (
                            <MenuItem key={item} value={item}>
                              {formatValue(item, 'signal_action')}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    </>
                  ) : null}
                    {tab === 'top_pairs' ? (
                    <>
                      <TextField
                        label="Лимит топ-пар"
                        size="small"
                        type="number"
                        value={topPairsLimit}
                        onChange={(event) => setTopPairsLimit(event.target.value)}
                        disabled={topPairsAll}
                        sx={{ minWidth: 140 }}
                      />
                      <FormControlLabel
                        control={
                          <Switch
                            checked={topPairsAll}
                            onChange={(event) => setTopPairsAll(event.target.checked)}
                          />
                        }
                        label="Все пары"
                      />
                    </>
                  ) : null}
                  <Button
                    variant="outlined"
                    onClick={handleAuxRefresh}
                    disabled={auxLoading || recomputeLoading}
                  >
                    {recomputeLoading ? 'Пересчёт...' : 'Обновить'}
                  </Button>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={autoRefresh}
                        onChange={(event) => setAutoRefresh(event.target.checked)}
                      />
                    }
                    label={`Автообновление (${AUTO_REFRESH_LABEL})`}
                  />
                  <Typography variant="body2" color="text.secondary">
                    {auxLastUpdated
                      ? `Обновлено ${formatDate(auxLastUpdated)}`
                      : 'Обновлено: н/д'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {refreshStatus?.last_success_at
                      ? `Пересчитано ${formatDate(refreshStatus.last_success_at)}`
                      : 'Пересчитано: н/д'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {auxLoading ? 'Загрузка...' : `${sortedTableRows.length} строк`}
                  </Typography>
                  {!auxLoading ? (
                    <Typography variant="body2" color="text.secondary">
                      Топ пар: {topPairs.length} · Сигналы: {signals.length} · Бэктесты:{' '}
                      {backtests.length}
                    </Typography>
                  ) : null}
                  {auxError ? (
                    <Typography variant="body2" color="error">
                      {auxError}
                    </Typography>
                  ) : null}
                  {recomputeError ? (
                    <Typography variant="body2" color="error">
                      {recomputeError}
                    </Typography>
                  ) : null}
                </Stack>
              </Paper>
              {tab === 'signals' ? (
                <Paper sx={{ p: 2 }}>
                  <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                    <TextField
                      label="История с (ГГГГ-ММ-ДД)"
                      size="small"
                      value={historyFrom}
                      onChange={(event) => setHistoryFrom(event.target.value)}
                      sx={{ minWidth: 200 }}
                    />
                    <TextField
                      label="История по (ГГГГ-ММ-ДД)"
                      size="small"
                      value={historyTo}
                      onChange={(event) => setHistoryTo(event.target.value)}
                      sx={{ minWidth: 200 }}
                    />
                    <Button variant="outlined" onClick={fetchSignalHistory} disabled={historyLoading}>
                      Загрузить историю
                    </Button>
                    {historyLoading ? (
                      <Typography variant="body2" color="text.secondary">
                        Загрузка истории...
                      </Typography>
                    ) : null}
                    {historyError ? (
                      <Typography variant="body2" color="error">
                        {historyError}
                      </Typography>
                    ) : null}
                  </Stack>
                </Paper>
              ) : null}
              <Paper sx={{ p: 2 }}>
                <TableContainer sx={{ maxHeight: '68vh' }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        {showPairDetails ? <TableCell /> : null}
                        {tableVisibleColumns.map((column) => (
                          <TableCell
                            key={column}
                            sortDirection={tableSortKey === column ? tableSortDirection : false}
                          >
                            <TableSortLabel
                              active={tableSortKey === column}
                              direction={tableSortKey === column ? tableSortDirection : 'asc'}
                              onClick={() => handleTableSort(column)}
                            >
                              {renderFieldLabel(column)}
                            </TableSortLabel>
                          </TableCell>
                        ))}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {sortedTableRows.map((row) => {
                        const pairKey =
                          (row.stock && row.future ? `${row.stock}-${row.future}` : null) ??
                          String(row.id)
                        const isExpanded = expandedRowKey === pairKey
                        const snapshotEntries = stripDuplicates(
                          snapshotFields
                            .map((key) => ({
                              key,
                              value: row[key],
                            }))
                            .filter((field) => field.value !== null && field.value !== undefined),
                        )
                        const overviewEntries = stripDuplicates(
                          overviewFields
                            .map((key) => ({
                              key,
                              value: row[key],
                            }))
                            .filter((field) => field.value !== null && field.value !== undefined),
                        )
                        const alphaEntries = stripDuplicates(
                          alphaFields
                            .map((key) => ({
                              key,
                              value: row[key],
                            }))
                            .filter((field) => field.value !== null && field.value !== undefined),
                        )
                        const liquidityEntries = stripDuplicates(
                          liquidityFields
                            .map((key) => ({
                              key,
                              value: row[key],
                            }))
                            .filter((field) => field.value !== null && field.value !== undefined),
                        )
                        const executionEntries = stripDuplicates(
                          executionFields
                            .map((key) => ({
                              key,
                              value: row[key],
                            }))
                            .filter((field) => field.value !== null && field.value !== undefined),
                        )

                        return (
                          <Fragment key={pairKey}>
                            <TableRow>
                              {showPairDetails ? (
                                <TableCell>
                                  <Button size="small" onClick={() => handleToggleDetails(row)}>
                                    {isExpanded ? 'Скрыть' : 'Детали'}
                                  </Button>
                                </TableCell>
                              ) : null}
                              {tableVisibleColumns.map((column) => (
                                <TableCell key={column}>
                                  {formatCellValue(row[column], column)}
                                </TableCell>
                              ))}
                            </TableRow>
                            {showPairDetails && isExpanded ? (
                              <TableRow>
                                <TableCell colSpan={tableVisibleColumns.length + 1}>
                                  <Stack spacing={2}>
                                    <Box>
                                      <Typography variant="subtitle2" fontWeight={600}>
                                        Снимок
                                      </Typography>
                                      {renderFieldGrid(snapshotEntries)}
                                    </Box>
                                    <Box>
                                      <Tabs
                                        value={detailTab}
                                        onChange={(_, value) => setDetailTab(value)}
                                      >
                                        <Tab label="Обзор" value="overview" />
                                        <Tab label="Альфа" value="alpha" />
                                        <Tab label="Ликвидность" value="liquidity" />
                                        <Tab label="Исполнение" value="execution" />
                                      </Tabs>
                                      {detailTab === 'overview' && overviewEntries.length
                                        ? renderFieldGrid(overviewEntries)
                                        : null}
                                      {detailTab === 'alpha' && alphaEntries.length
                                        ? renderFieldGrid(alphaEntries)
                                        : null}
                                      {detailTab === 'liquidity' && liquidityEntries.length
                                        ? renderFieldGrid(liquidityEntries)
                                        : null}
                                      {detailTab === 'execution' && executionEntries.length
                                        ? renderFieldGrid(executionEntries)
                                        : null}
                                    </Box>
                                    <Box>
                                      <Typography variant="subtitle2" fontWeight={600}>
                                        График спреда (жизнь контракта)
                                      </Typography>
                                      {spreadError[pairKey] ? (
                                        <Typography variant="body2" color="error">
                                          {spreadError[pairKey]}
                                        </Typography>
                                      ) : null}
                                      {spreadLoadingKey === pairKey ? (
                                        <Typography variant="body2" color="text.secondary">
                                          Загрузка серии спреда...
                                        </Typography>
                                      ) : (
                                        <SpreadChart data={spreadSeries[pairKey] ?? []} />
                                      )}
                                    </Box>
                                    {tab === 'signals' ? (
                                      <Box>
                                      <Typography variant="subtitle2" fontWeight={600}>
                                        Исполнить сигнал
                                      </Typography>
                                      <Stack direction="row" spacing={2} flexWrap="wrap">
                                        <TextField
                                          label="Цена"
                                          size="small"
                                          value={executionForm.price}
                                          onChange={(event) =>
                                            setExecutionForm((prev) => ({
                                              ...prev,
                                                price: event.target.value,
                                              }))
                                            }
                                            sx={{ minWidth: 140 }}
                                        />
                                        <TextField
                                          label="Кол-во"
                                          size="small"
                                          value={executionForm.quantity}
                                          onChange={(event) =>
                                            setExecutionForm((prev) => ({
                                              ...prev,
                                                quantity: event.target.value,
                                              }))
                                            }
                                            sx={{ minWidth: 120 }}
                                        />
                                        <TextField
                                          label="Сторона"
                                          size="small"
                                          value={executionForm.side}
                                          onChange={(event) =>
                                            setExecutionForm((prev) => ({
                                              ...prev,
                                                side: event.target.value,
                                              }))
                                            }
                                            sx={{ minWidth: 120 }}
                                        />
                                        <TextField
                                          label="Статус"
                                          size="small"
                                          value={executionForm.status}
                                          onChange={(event) =>
                                            setExecutionForm((prev) => ({
                                              ...prev,
                                                status: event.target.value,
                                              }))
                                            }
                                            sx={{ minWidth: 120 }}
                                        />
                                        <TextField
                                          label="Комментарий"
                                          size="small"
                                          value={executionForm.note}
                                          onChange={(event) =>
                                            setExecutionForm((prev) => ({
                                              ...prev,
                                                note: event.target.value,
                                              }))
                                            }
                                            sx={{ minWidth: 240 }}
                                        />
                                        <Button
                                          variant="contained"
                                          onClick={() => handleExecuteSignal(row)}
                                        >
                                          Исполнить
                                        </Button>
                                      </Stack>
                                      <Box sx={{ mt: 2 }}>
                                        <Typography variant="subtitle2" fontWeight={600}>
                                          История исполнений
                                        </Typography>
                                        {executionError[pairKey] ? (
                                          <Typography variant="body2" color="error">
                                            {executionError[pairKey]}
                                          </Typography>
                                        ) : null}
                                        {executionLoadingKey === pairKey ? (
                                          <Typography variant="body2" color="text.secondary">
                                            Загрузка исполнений...
                                          </Typography>
                                        ) : executionLogs[pairKey]?.length ? (
                                            <Table size="small">
                                              <TableHead>
                                                <TableRow>
                                                  {[
                                                    'timestamp',
                                                    'action',
                                                    'direction',
                                                    'price',
                                                    'quantity',
                                                    'side',
                                                    'status',
                                                    'note',
                                                  ].map((col) => (
                                                    <TableCell key={col}>{renderFieldLabel(col)}</TableCell>
                                                  ))}
                                                </TableRow>
                                              </TableHead>
                                              <TableBody>
                                                {executionLogs[pairKey].map((entry, index) => (
                                                  <TableRow key={`${entry.timestamp}-${index}`}>
                                                    <TableCell>{formatDate(entry.timestamp)}</TableCell>
                                                    <TableCell>
                                                      {formatValue(entry.action, 'action')}
                                                    </TableCell>
                                                    <TableCell>
                                                      {formatValue(entry.direction ?? '', 'direction')}
                                                    </TableCell>
                                                    <TableCell>
                                                      {formatValue(entry.price, 'future_price')}
                                                    </TableCell>
                                                    <TableCell>
                                                      {formatValue(entry.quantity, 'quantity')}
                                                    </TableCell>
                                                    <TableCell>
                                                      {formatValue(entry.side ?? '', 'side')}
                                                    </TableCell>
                                                    <TableCell>
                                                      {formatValue(entry.status ?? '', 'status')}
                                                    </TableCell>
                                                    <TableCell>{entry.note ?? ''}</TableCell>
                                                  </TableRow>
                                                ))}
                                              </TableBody>
                                            </Table>
                                          ) : (
                                            <Typography variant="body2" color="text.secondary">
                                              Исполнений пока нет.
                                            </Typography>
                                          )}
                                        </Box>
                                      </Box>
                                    ) : null}
                                  </Stack>
                                </TableCell>
                              </TableRow>
                            ) : null}
                          </Fragment>
                        )
                      })}
                    </TableBody>
                  </Table>
                </TableContainer>
                {!sortedTableRows.length ? (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    {tab === 'signals' && !auxLoading && signals.length === 0
                      ? 'Пока нет активных сигналов. Откройте детали активной строки, чтобы исполнить.'
                      : 'Нет строк по текущему фильтру.'}
                  </Typography>
                ) : null}
              </Paper>
              {tab === 'signals' && signalHistory.length ? (
                <Paper sx={{ p: 2 }}>
                  <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
                    История сигналов
                  </Typography>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        {[
                          'timestamp',
                          'stock',
                          'future',
                          'signal_action',
                          'signal_direction',
                          'signal_score',
                        ].map(
                          (col) => (
                            <TableCell key={col}>{renderFieldLabel(col)}</TableCell>
                          ),
                        )}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {filteredSignalHistory.map((row, index) => (
                        <TableRow
                          key={`${row.run_id}-${row.timestamp}-${row.stock}-${row.future}-${row.signal_action ?? ''}-${index}`}
                        >
                          <TableCell>{formatDate(row.timestamp)}</TableCell>
                          <TableCell>{row.stock}</TableCell>
                          <TableCell>{row.future}</TableCell>
                          <TableCell>{formatValue(row.signal_action, 'signal_action')}</TableCell>
                          <TableCell>
                            {formatValue(row.signal_direction ?? '', 'signal_direction')}
                          </TableCell>
                          <TableCell>{formatValue(row.signal_score, 'signal_score')}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {!filteredSignalHistory.length ? (
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                      Нет строк истории по текущему фильтру.
                    </Typography>
                  ) : null}
                </Paper>
              ) : null}
            </>
          ) : null}
          {tab === 'backtest_v2' ? (
            <Stack spacing={2}>
              <Paper sx={{ p: 2 }}>
                <Stack spacing={2}>
                  <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                    <TextField
                      label="Пресет (опционально)"
                      size="small"
                      value={paramPreset}
                      onChange={(event) => setParamPreset(event.target.value)}
                      sx={{ minWidth: 200 }}
                    />
                    <Button
                      variant="outlined"
                      onClick={() => fetchParamSpecs({ resetValues: true })}
                      disabled={paramSpecsLoading}
                    >
                      {paramSpecsLoading ? 'Загрузка параметров...' : 'Загрузить параметры'}
                    </Button>
                    <Button
                      variant="text"
                      onClick={handleParamReset}
                      disabled={!paramSpecs.length}
                    >
                      Сбросить по умолчанию
                    </Button>
                    <FormControlLabel
                      control={
                        <Switch
                          checked={backtestPrecompute}
                          onChange={(event) => setBacktestPrecompute(event.target.checked)}
                        />
                      }
                      label="Предрасчёт кэша"
                    />
                    <Typography variant="body2" color="text.secondary">
                      {paramSpecs.length ? `Параметров: ${paramSpecs.length}` : 'Параметров: н/д'}
                    </Typography>
                    {paramSpecsError ? (
                      <Typography variant="body2" color="error">
                        {paramSpecsError}
                      </Typography>
                    ) : null}
                  </Stack>
                  <TextField
                    label="Фильтр параметров"
                    size="small"
                    value={paramFilter}
                    onChange={(event) => setParamFilter(event.target.value)}
                    sx={{ maxWidth: 320 }}
                  />
                  {paramSpecs.length ? (
                    paramSections.length ? (
                      paramSections.map(([section, specs], index) => (
                        <Accordion key={section} defaultExpanded={index === 0 || section === 'test'}>
                          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                            <Typography variant="subtitle2">
                              {toTitleCase(section)} ({specs.length})
                            </Typography>
                          </AccordionSummary>
                          <AccordionDetails>
                            <Box
                              sx={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                                gap: 2,
                              }}
                            >
                              {specs.map((spec) => renderParamInput(spec))}
                            </Box>
                          </AccordionDetails>
                        </Accordion>
                      ))
                    ) : (
                      <Typography variant="body2" color="text.secondary">
                        Нет параметров, подходящих под фильтр.
                      </Typography>
                    )
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      Загрузите параметры, чтобы редактировать запрос бэктеста.
                    </Typography>
                  )}
                  <Divider />
                  <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                    <Button
                      variant="contained"
                      onClick={handleBacktestRun}
                      disabled={backtestRunLoading || !paramSpecs.length}
                    >
                      Запустить бэктест
                    </Button>
                    {backtestRunLoading ? (
                      <Typography variant="body2" color="text.secondary">
                        Запуск бэктеста...
                      </Typography>
                    ) : null}
                    {backtestRunParseError ? (
                      <Typography variant="body2" color="error">
                        {backtestRunParseError}
                      </Typography>
                    ) : null}
                    {backtestRunError ? (
                      <Typography variant="body2" color="error">
                        {backtestRunError}
                      </Typography>
                    ) : null}
                  </Stack>
                </Stack>
              </Paper>
              {backtestRunReport ? (
                <Stack spacing={2}>
                  <Paper sx={{ p: 2 }}>
                    <Stack spacing={1}>
                      <Typography variant="subtitle1" fontWeight={600}>
                        Итоговые метрики
                      </Typography>
                      {backtestSummaryEntries.length
                        ? renderFieldGrid(backtestSummaryEntries)
                        : renderKeyValueGrid({}, 'Итоговые метрики пока недоступны.')}
                      {backtestRunReport.warnings && backtestRunReport.warnings.length ? (
                        <Stack direction="row" spacing={1} flexWrap="wrap">
                          {backtestRunReport.warnings.map((warning, index) => (
                            <Chip
                              key={`${warning}-${index}`}
                              label={`Предупреждение: ${warning}`}
                              size="small"
                            />
                          ))}
                        </Stack>
                      ) : null}
                    </Stack>
                  </Paper>
                  <Paper sx={{ p: 2 }}>
                    <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1 }}>
                      Кривая эквити
                    </Typography>
                    {renderTable(backtestEquityRows, backtestEquityColumns, 'Кривая эквити пуста.')}
                  </Paper>
                  <Paper sx={{ p: 2 }}>
                    <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1 }}>
                      Сделки
                    </Typography>
                    {renderTable(backtestTradeRows, backtestTradeColumns, 'Список сделок пуст.')}
                  </Paper>
                  {backtestRunReport.resolved_config ? (
                    <Accordion>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography variant="subtitle2">Развёрнутый конфиг</Typography>
                      </AccordionSummary>
                      <AccordionDetails>{renderJsonBlock(backtestRunReport.resolved_config)}</AccordionDetails>
                    </Accordion>
                  ) : null}
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Запустите бэктест, чтобы увидеть метрики, кривую эквити и сделки.
                </Typography>
              )}
            </Stack>
          ) : null}
          {tab === 'forward' ? (
            <Stack spacing={2}>
              <Paper sx={{ p: 2 }}>
                <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                    <TextField
                      label="ID прогона (опционально)"
                    size="small"
                    value={forwardRunId}
                    onChange={(event) => setForwardRunId(event.target.value)}
                    sx={{ minWidth: 220 }}
                  />
                  <Button variant="contained" onClick={fetchForwardStatus} disabled={forwardLoading}>
                    Загрузить статус
                  </Button>
                  {forwardLoading ? (
                    <Typography variant="body2" color="text.secondary">
                      Загрузка статуса...
                    </Typography>
                  ) : null}
                  {forwardError ? (
                    <Typography variant="body2" color="error">
                      {forwardError}
                    </Typography>
                  ) : null}
                </Stack>
              </Paper>
              {forwardStatus ? (
                <Stack spacing={2}>
                  <Paper sx={{ p: 2 }}>
                    <Stack direction="row" spacing={1} flexWrap="wrap">
                      <Chip label={`Прогон: ${forwardStatus.run_id ?? 'н/д'}`} size="small" />
                      <Chip
                        label={`Статус: ${formatValue(forwardStatus.status ?? 'н/д', 'status')}`}
                        size="small"
                      />
                    </Stack>
                  </Paper>
                  <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
                    <Paper sx={{ p: 2, flex: 1 }}>
                      <Typography variant="subtitle2" fontWeight={600}>
                        Последний отчёт по эквити
                      </Typography>
                      {renderKeyValueGrid(forwardStatus.last_equity ?? undefined, 'Отчёта по эквити пока нет.')}
                    </Paper>
                    <Paper sx={{ p: 2, flex: 1 }}>
                      <Typography variant="subtitle2" fontWeight={600}>
                        Последняя сделка
                      </Typography>
                      {renderKeyValueGrid(forwardStatus.last_trade ?? undefined, 'Сделок пока нет.')}
                    </Paper>
                    <Paper sx={{ p: 2, flex: 1 }}>
                      <Typography variant="subtitle2" fontWeight={600}>
                        Последнее уведомление
                      </Typography>
                      {renderKeyValueGrid(
                        forwardStatus.last_alert ?? undefined,
                        'Уведомлений пока нет.',
                      )}
                    </Paper>
                  </Stack>
                  <Accordion>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Typography variant="subtitle2">Снимок состояния</Typography>
                    </AccordionSummary>
                    <AccordionDetails>{renderJsonBlock(forwardStatus.state ?? {})}</AccordionDetails>
                  </Accordion>
                  {forwardStatus.run_meta ? (
                    <Accordion>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography variant="subtitle2">Метаданные прогона</Typography>
                      </AccordionSummary>
                      <AccordionDetails>{renderJsonBlock(forwardStatus.run_meta)}</AccordionDetails>
                    </Accordion>
                  ) : null}
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Загрузите статус форварда, чтобы увидеть отчёты и уведомления.
                </Typography>
              )}
            </Stack>
          ) : null}
          {tab === 'hpo' ? (
            <Stack spacing={2}>
              <Paper sx={{ p: 2 }}>
                <Stack spacing={2}>
                  <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                    <Button variant="outlined" onClick={() => fetchParamSpecs({ resetValues: false })}>
                      Загрузить параметры
                    </Button>
                    <Typography variant="body2" color="text.secondary">
                      {paramSpecs.length
                        ? `Базовые параметры загружены: ${paramSpecs.length}`
                        : 'Базовые параметры не загружены (будут использованы значения по умолчанию)'}
                    </Typography>
                  </Stack>
                  <TextField
                    label="Пространство поиска (JSON)"
                    size="small"
                    value={hpoSearchSpace}
                    onChange={(event) => setHpoSearchSpace(event.target.value)}
                    placeholder='{"strategy.z_window":{"kind":"int","min_value":20,"max_value":120}}'
                    multiline
                    minRows={6}
                  />
                  <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                    <Button variant="contained" onClick={handleHpoRun} disabled={hpoLoading}>
                      Запустить HPO
                    </Button>
                    {hpoLoading ? (
                      <Typography variant="body2" color="text.secondary">
                        Запуск HPO...
                      </Typography>
                    ) : null}
                    {hpoError ? (
                      <Typography variant="body2" color="error">
                        {hpoError}
                      </Typography>
                    ) : null}
                  </Stack>
                </Stack>
              </Paper>
              {hpoResponse ? (
                <Stack spacing={2}>
                  <Paper sx={{ p: 2 }}>
                    <Stack direction="row" spacing={1} flexWrap="wrap">
                      {hpoResponse.status ? (
                        <Chip
                          label={`Статус: ${formatValue(hpoResponse.status, 'status')}`}
                          size="small"
                        />
                      ) : null}
                      {hpoResponse.message ? (
                        <Chip label={hpoResponse.message} size="small" />
                      ) : null}
                    </Stack>
                  </Paper>
                  <Paper sx={{ p: 2 }}>
                    <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1 }}>
                      Лидерборд
                    </Typography>
                    {renderTable(
                      hpoLeaderboardRows as GenericRow[],
                      hpoLeaderboardColumns,
                      'Пока нет записей в лидерборде.',
                    )}
                  </Paper>
                  <Accordion>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Typography variant="subtitle2">Сырой ответ HPO</Typography>
                    </AccordionSummary>
                    <AccordionDetails>{renderJsonBlock(hpoResponse)}</AccordionDetails>
                  </Accordion>
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Запустите HPO, чтобы увидеть лидерборд.
                </Typography>
              )}
            </Stack>
          ) : null}
        </Stack>
      </Container>
    </Box>
  )
}

export default App

