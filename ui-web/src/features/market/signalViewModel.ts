import type { GenericRow, SignalActiveV2, SignalHistoryRow } from '../../entities/decision/types'

const SIGNAL_ACTION_ENTER = 'enter'
const SIGNAL_ACTION_EXIT = 'exit'
const SIGNAL_ACTION_HOLD = 'hold'
const SIGNAL_ACTION_HOLD_PRETRADE = 'hold_pretrade'
const SIGNAL_ACTION_CHECK_PRETRADE = 'check_pretrade'
const SIGNAL_ACTION_HOLD_OPEN = 'hold_open'

const EXECUTION_LEG_STOCK = 'stock'
const EXECUTION_LEG_FUTURE = 'future'

export const normalizeExecutionLeg = (value: string) => {
  const normalized = value.trim().toLowerCase()
  if (normalized === EXECUTION_LEG_STOCK || normalized === 'акция') return EXECUTION_LEG_STOCK
  if (normalized === EXECUTION_LEG_FUTURE || normalized === 'фьючерс') return EXECUTION_LEG_FUTURE
  return ''
}

export const normalizeExecutionAction = (value: unknown) => {
  const normalized = String(value ?? '').trim().toLowerCase()
  if (normalized === SIGNAL_ACTION_EXIT) return SIGNAL_ACTION_EXIT
  if (
    normalized === SIGNAL_ACTION_ENTER ||
    normalized === SIGNAL_ACTION_HOLD_OPEN ||
    normalized === SIGNAL_ACTION_HOLD
  ) {
    return SIGNAL_ACTION_ENTER
  }
  return SIGNAL_ACTION_ENTER
}

export const resolveEffectiveSignalAction = (row: GenericRow): string => {
  const action = String(row.signal_action_effective ?? '').toLowerCase()
  if (action) return action
  return String(row.signal_action ?? '').toLowerCase() || SIGNAL_ACTION_HOLD
}

export const isEntrySignal = (row: GenericRow) => {
  const action = resolveEffectiveSignalAction(row)
  return (
    action === SIGNAL_ACTION_ENTER ||
    action === SIGNAL_ACTION_HOLD_PRETRADE ||
    action === SIGNAL_ACTION_CHECK_PRETRADE
  )
}

export const toHistorySignalAction = (action: string): SignalHistoryRow['signal_action'] | undefined => {
  if (!action) return undefined
  if (action === SIGNAL_ACTION_HOLD_PRETRADE || action === SIGNAL_ACTION_CHECK_PRETRADE) {
    return SIGNAL_ACTION_ENTER
  }
  if (action === SIGNAL_ACTION_HOLD_OPEN) {
    return SIGNAL_ACTION_HOLD
  }
  return action as SignalHistoryRow['signal_action']
}

export const resolveSignalDirection = (value: unknown): 'cash_and_carry' | 'reverse' => {
  return String(value ?? '').toLowerCase() === 'reverse' ? 'reverse' : 'cash_and_carry'
}

export const toSignalFilterAction = (row: GenericRow, isSignalTab: boolean) => {
  if (!isSignalTab) return String(row.signal_action ?? '').toLowerCase()
  return resolveEffectiveSignalAction(row)
}

export const mapSignalV2Row = (row: SignalActiveV2): GenericRow => {
  const pairTokens = String(row.entity_ref?.entity_id ?? '').split(':')
  const stock = String(row.stock ?? pairTokens[0] ?? '').trim()
  const future = String(row.future ?? pairTokens[1] ?? '').trim()
  const fallbackAction = String(row.signal_action ?? '').toLowerCase()
  const backendEffectiveAction = String(
    row.signal_action_effective ?? row.signal_action ?? fallbackAction,
  ).toLowerCase()
  const pretradeGate = Array.isArray(row.gate_results)
    ? row.gate_results.find((gate) => gate.gate_type === 'pretrade')
    : undefined
  return {
    ...row,
    stock,
    future,
    signal_action: fallbackAction || backendEffectiveAction,
    signal_action_effective: backendEffectiveAction,
    pretrade_status:
      pretradeGate?.status === 'pass'
        ? 'pass'
        : pretradeGate?.status === 'block'
          ? 'block'
          : row.pretrade_status,
    pretrade_reasons: pretradeGate?.reasons ?? row.pretrade_reasons,
  }
}

export const SIGNAL_ACTION_HOLD_OPEN_VALUE = SIGNAL_ACTION_HOLD_OPEN
export const PRETRADE_PREFETCH_LIMIT = 12
