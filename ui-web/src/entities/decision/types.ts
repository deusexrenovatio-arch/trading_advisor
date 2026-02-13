export type AggregationSummary = {
  action?: string
  score?: number
  strategies?: string[]
  blocked_strategies?: string[]
}
export type ProposalSummary = {
  type?: string
  cadence?: string
  effective_date?: string
  summary?: string
}
export type BasketAllocation = {
  basket?: string
  weight?: number
}
export type BasketSummary = {
  current?: BasketAllocation[]
  target?: BasketAllocation[]
  delta?: BasketAllocation[]
}
export type OperatorAction = {
  action?: string
  status?: string
  actor?: string
  note?: string
  created_at?: string
}
export type ExecutionStatus = {
  request_id?: string
  action?: string
  status?: string
  requested_at?: string
  executed_at?: string
  actor?: string
  source?: string
  reason_code?: string
  idempotency_key?: string
}

export type DecisionRefV2 = {
  decision_id?: string | null
  action_id?: string | null
  latest_action?: string | null
  latest_status?: string | null
  actor_id?: string | null
  source?: string | null
  idempotency_key?: string | null
  updated_at?: string | null
}

export type ExecutionRefV2 = {
  request_id?: string | null
  action?: string | null
  status?: string | null
  requested_at?: string | null
  executed_at?: string | null
  actor_id?: string | null
  source?: string | null
  reason_code?: string | null
  idempotency_key?: string | null
}

export type DecisionView = {
  decision_id: string
  projection_version?: string
  projection_source?: 'jsonl' | 'db' | 'jsonl_fallback'
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
  decision_ref?: DecisionRefV2
  execution_ref?: ExecutionRefV2
}

export type DecisionLog = Record<string, unknown>
export type GenericRow = Record<string, unknown>
export type SpreadSeriesPoint = {
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
export type SignalHistoryRow = {
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
export type ExecutionRow = {
  timestamp: string
  stock: string
  future: string
  direction?: string | null
  action: string
  price?: number | null
  quantity?: number | null
  side?: string | null
  order_id?: string | null
  status?: string | null
  note?: string | null
}
export type RefreshStatus = {
  enabled?: boolean
  interval_sec?: number
  status?: string
  last_started_at?: string | null
  last_success_at?: string | null
  last_error?: string | null
  next_run_at?: string | null
}

export type PretradeCheckResult = {
  status: string
  ready_to_place: boolean
  manual_confirm_required?: boolean
  reasons?: string[]
  pair?: {
    stock: string
    future: string
    direction: string
  }
  targets?: {
    spot_target?: number
    future_target_per_share?: number
    spread_target?: number
  }
  order_price_bands?: Record<string, number | null>
  volume_requirements?: Record<string, number | null>
  gates?: Record<string, boolean>
  hits?: Record<string, number>
  last_snapshot?: Record<string, unknown>
  params?: Record<string, unknown>
}

export type ParameterSpec = {
  key: string
  value_type: string
  default?: unknown
  min_value?: number | null
  max_value?: number | null
  options?: unknown[] | null
  description?: string | null
}

export type ParamPrimitive = string | number | boolean | null
export type ParamValue = ParamPrimitive | ParamPrimitive[] | Record<string, ParamPrimitive | unknown>

export type BacktestEquityPoint = {
  date: string
  equity?: number | null
  cash?: number | null
  drawdown?: number | null
  turnover?: number | null
  positions?: number | null
}

export type BacktestTrade = {
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

export type BacktestReport = {
  summary_metrics?: Record<string, unknown>
  equity_curve?: BacktestEquityPoint[]
  trades?: BacktestTrade[]
  resolved_config?: Record<string, unknown>
  warnings?: string[]
}

export type ForwardStatus = {
  run_id?: string
  status?: string
  state?: Record<string, unknown>
  last_trade?: Record<string, unknown> | null
  last_equity?: Record<string, unknown> | null
  last_alert?: Record<string, unknown> | null
  run_meta?: Record<string, unknown>
}

export type HpoTrial = {
  objective?: number
  params?: Record<string, unknown>
  fold_objectives?: number[]
  fold_results?: unknown[]
}

export type HpoResponse = {
  run_id?: string
  status?: string
  message?: string
  created_at?: string
  started_at?: string
  finished_at?: string
  progress?: {
    completed?: number
    total?: number
  }
  error?: string
  mode?: string
  leaderboard?: HpoTrial[]
  trials?: HpoTrial[]
  result?: {
    mode?: string
    leaderboard?: HpoTrial[]
    trials?: HpoTrial[]
  }
}

export type EntityRef = {
  entity_type: 'instrument' | 'pair' | 'portfolio'
  entity_id: string
  asset_id?: string | null
  ticker?: string | null
}

export type SignalLifecycleState =
  | 'candidate'
  | 'blocked'
  | 'ready'
  | 'acknowledged'
  | 'entered'
  | 'hold_open'
  | 'exit_ready'
  | 'closed'
  | 'rejected'

export type GateResultV2 = {
  gate_result_id: string
  gate_type: string
  status: 'pass' | 'warn' | 'block'
  reasons?: string[]
}

export type SignalActiveV2 = {
  signal_id: string
  entity_ref: EntityRef
  lifecycle_state: SignalLifecycleState
  gate_results: GateResultV2[]
  decision_ref?: {
    decision_id?: string | null
  }
  execution_ref?: Record<string, unknown>
  run_id?: string
  timestamp?: string
  signal_action?: string
  signal_action_effective?: string
  signal_direction?: string | null
  signal_score?: number
  signal_reasons?: string[]
  signal_metrics?: Record<string, unknown>
  stock?: string
  future?: string
  pretrade_status?: string
  pretrade_reasons?: string[]
  position_open?: boolean
  position_state?: string
  position_open_leg_total?: number
  position_net_orders?: number
  [key: string]: unknown
}

export type NewsEventV2 = {
  news_event_id: string
  published_at: string
  severity: string
  headline: string
  summary?: string
  headline_count?: number
  decision_ref?: {
    decision_id?: string | null
  }
  entity_links?: EntityRef[]
}

export type RebalancePreviewV2 = {
  rebalance_plan_id: string
  generated_at: string
  positions: Array<{
    entity_ref: EntityRef
    target_weight: number
    signal_id?: string
    lifecycle_state?: SignalLifecycleState
    signal_action?: string
    signal_score?: number
    reasons?: string[]
  }>
  summary?: Record<string, unknown>
  risk_checks?: Array<Record<string, unknown>>
}

export type RebalanceCommitV2 = {
  status: string
  commit_id: string
  rebalance_plan_id: string
  positions_committed: number
  committed_at: string
}
