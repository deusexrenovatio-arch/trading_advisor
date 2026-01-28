import type { DecisionView } from '../../entities/decision/types'

export type DecisionTableRow = DecisionView & {
  id: string
  cost_round_trip?: number | null
  max_drawdown?: number | null
}

export const mapDecisionRows = (rows: DecisionView[]): DecisionTableRow[] =>
  rows.map((row) => ({
    id: row.decision_id,
    ...row,
    cost_round_trip: row.cost_summary?.round_trip_cost ?? null,
    max_drawdown: row.backtest_metrics?.max_drawdown ?? null,
  }))
