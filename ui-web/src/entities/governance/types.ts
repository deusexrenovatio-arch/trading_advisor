export type GoalClassMetrics = {
  tasks: number
  correct_first_time_pct: number
  correct_after_replan_pct: number
}

export type ProcessMetrics = {
  correct_first_time_pct: number
  correct_after_replan_pct: number
  wrong_path_rate: number
  rework_rate: number
  decision_quality_by_goal_class: Record<string, GoalClassMetrics>
  start_resolution_pct: number
  start_match_pct: number
  single_context_task_pct: number
  context_expansion_rate: number
  unmapped_significant_file_rate: number
  median_time_to_first_patch_sec: number
  repeat_error_rate: number
  environment_blocker_rate: number
  same_path_attempts_p50: number
  same_path_attempts_p90: number
}

export type ThresholdCheck = {
  metric: string
  operator: string
  threshold: number
  actual: number
  passed: boolean
}

export type ThresholdResult = {
  ok: boolean
  checks: ThresholdCheck[]
}

export type ProcessTaskRecord = {
  task_id: string
  decision_quality: string
  route_match: string
  outcome_status: string
  incident_signature?: string
  improvement_action?: string
  improvement_artifact?: string
  start_recommendations?: string[]
}

export type HumanSummary = {
  status: string
  headline: string
  what_happened: string
  why_it_drifted: string
  what_to_change_next: string[]
  current_risks: string[]
}

export type WeeklyReport = {
  week_start: string
  week_end: string
  week_label: string
  tasks_count: number
  metrics: ProcessMetrics
  metric_deltas: Partial<Record<string, number>>
  top_repeated_error_signatures: Array<[string, number]>
  top_environment_blockers: Array<[string, number]>
  top_start_recommendations: Array<[string, number]>
  high_risk_start_recommendations: Array<[string, number]>
  tasks_of_note: ProcessTaskRecord[]
  human_summary: HumanSummary
}

export type CurrentRollup = {
  completed_tasks_count: number
  window_size: number
  current_window_count: number
  burn_in_complete: boolean
  current_metrics: ProcessMetrics
  previous_metrics: Partial<Record<string, number>>
  deltas: Partial<Record<string, number>>
  top_repeated_error_signatures: Array<[string, number]>
  repeat_signature_recurrence: Array<[string, number]>
  top_environment_blockers: Array<[string, number]>
  tasks_with_wrong_path_or_partial: ProcessTaskRecord[]
  improvement_actions_without_followup: ProcessTaskRecord[]
  improvement_action_mix: Record<string, number>
  top_start_recommendations: Array<[string, number]>
  high_risk_start_recommendations: Array<[string, number]>
  threshold_results: Record<string, ThresholdResult>
}

export type ProcessImprovementReport = {
  generated_at: string
  completed_tasks_count: number
  rolling_window_size: number
  burn_in_complete: boolean
  human_summary: HumanSummary
  current_rollup: CurrentRollup
  weekly_reports: WeeklyReport[]
  weekly_trend: WeeklyReport[]
  query: {
    weeks: number
    window_size: number
  }
}
