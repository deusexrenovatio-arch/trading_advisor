import AutoGraphRoundedIcon from '@mui/icons-material/AutoGraphRounded'
import FlagRoundedIcon from '@mui/icons-material/FlagRounded'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import InsightsRoundedIcon from '@mui/icons-material/InsightsRounded'
import RuleRoundedIcon from '@mui/icons-material/RuleRounded'
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded'
import {
  Alert,
  Button,
  Chip,
  Grid,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import type { TypographyProps } from '@mui/material'
import { LineChart } from '@mui/x-charts/LineChart'
import { useDeferredValue } from 'react'
import type { ProcessTaskRecord, WeeklyReport } from '../../entities/governance/types'
import {
  CONTROL_META,
  DECISION_QUALITY_META,
  METRIC_META,
  OUTCOME_STATUS_LABELS,
  ROUTE_MATCH_META,
  SECTION_META,
  STATUS_META,
  translateIncidentSignature,
  translateRecommendation,
  translateRisk,
} from './processGovernanceMeta'
import { useProcessGovernance } from './useProcessGovernance'

const WEEK_OPTIONS = [4, 8, 12, 16]
const WINDOW_OPTIONS = [10, 20, 30]

const renderTooltipTitle = (text: string) => (
  <Typography variant="caption" sx={{ whiteSpace: 'pre-line', display: 'block', maxWidth: 320 }}>
    {text}
  </Typography>
)

const HintLabel = ({
  label,
  tooltip,
  variant = 'subtitle2',
}: {
  label: string
  tooltip: string
  variant?: TypographyProps['variant']
}) => (
  <Stack direction="row" spacing={0.5} alignItems="center" useFlexGap>
    <Typography variant={variant}>{label}</Typography>
    <Tooltip title={renderTooltipTitle(tooltip)} arrow placement="top">
      <InfoOutlinedIcon sx={{ fontSize: 16, color: 'text.secondary' }} />
    </Tooltip>
  </Stack>
)

const formatPercent = (value: number | undefined) =>
  value === undefined ? '—' : `${(value * 100).toFixed(0)}%`

const formatSeconds = (value: number | undefined) => {
  if (value === undefined) return '—'
  const total = Math.max(0, Math.round(value))
  if (total < 60) return `${total} с`
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}м ${String(seconds).padStart(2, '0')}с`
}

const formatDelta = (value: number | undefined, kind: 'percent' | 'seconds') => {
  if (value === undefined) return '—'
  if (kind === 'seconds') {
    const rounded = Math.round(value)
    return `${rounded >= 0 ? '+' : ''}${rounded} с`
  }
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(0)} п.п.`
}

const renderRankedList = ({
  title,
  tooltip,
  items,
  emptyLabel,
  formatName,
}: {
  title: string
  tooltip: string
  items: Array<[string, number]>
  emptyLabel: string
  formatName?: (value: string) => string
}) => (
  <Paper variant="outlined" className="governance-surface">
    <Stack spacing={1.25}>
      <HintLabel label={title} tooltip={tooltip} />
      {items.length ? (
        items.map(([name, count]) => (
          <Stack
            key={`${title}-${name}`}
            direction="row"
            justifyContent="space-between"
            alignItems="center"
            spacing={1}
          >
            <Typography variant="body2">{formatName ? formatName(name) : name}</Typography>
            <Chip size="small" label={count} />
          </Stack>
        ))
      ) : (
        <Typography variant="body2" color="text.secondary">
          {emptyLabel}
        </Typography>
      )}
    </Stack>
  </Paper>
)

const renderTaskCard = (task: ProcessTaskRecord) => {
  const decisionMeta = DECISION_QUALITY_META[task.decision_quality] ?? DECISION_QUALITY_META.pending
  const routeMeta = ROUTE_MATCH_META[task.route_match] ?? ROUTE_MATCH_META.pending
  const outcomeLabel = OUTCOME_STATUS_LABELS[task.outcome_status] ?? task.outcome_status

  return (
    <Paper key={task.task_id} variant="outlined" className="governance-note-card">
      <Stack spacing={1}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
          <Typography variant="subtitle2" className="cell-mono">
            {task.task_id}
          </Typography>
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" justifyContent="flex-end">
            <Tooltip title={renderTooltipTitle(decisionMeta.tooltip)} arrow>
              <Chip size="small" label={decisionMeta.label} color={decisionMeta.color ?? 'default'} />
            </Tooltip>
            <Tooltip title={renderTooltipTitle(routeMeta.tooltip)} arrow>
              <Chip
                size="small"
                label={routeMeta.label}
                color={routeMeta.color ?? 'default'}
                variant="outlined"
              />
            </Tooltip>
          </Stack>
        </Stack>

        <Typography variant="body2" color="text.secondary">
          Итог: {outcomeLabel}
          {task.incident_signature && task.incident_signature !== 'none'
            ? ` | Сигнатура: ${translateIncidentSignature(task.incident_signature)}`
            : ''}
        </Typography>

        {task.start_recommendations?.length ? (
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
            {task.start_recommendations.slice(0, 2).map((item) => (
              <Tooltip key={`${task.task_id}-${item}`} title={renderTooltipTitle(translateRecommendation(item))} arrow>
                <Chip size="small" label={translateRecommendation(item)} variant="outlined" />
              </Tooltip>
            ))}
          </Stack>
        ) : null}
      </Stack>
    </Paper>
  )
}

function ProcessGovernanceTab() {
  const {
    weeks,
    setWeeks,
    windowSize,
    setWindowSize,
    report,
    weeklyReports,
    weeklyTrend,
    selectedWeek,
    selectedWeekStart,
    selectWeek,
    loading,
    error,
    load,
  } = useProcessGovernance()

  const deferredTrend = useDeferredValue(weeklyTrend)
  const summary = report?.human_summary
  const currentMetrics = report?.current_rollup.current_metrics
  const currentRollup = report?.current_rollup

  const chartLabels = deferredTrend.map((item) => item.week_start.slice(5))
  const cftSeries = deferredTrend.map((item) => Number(item.metrics.correct_first_time_pct.toFixed(3)))
  const matchSeries = deferredTrend.map((item) => Number(item.metrics.start_match_pct.toFixed(3)))
  const repeatSeries = deferredTrend.map((item) => Number(item.metrics.repeat_error_rate.toFixed(3)))

  const selectedTasks = selectedWeek?.tasks_of_note ?? []
  const statusMeta = STATUS_META[summary?.status ?? 'empty'] ?? STATUS_META.empty

  return (
    <Stack spacing={2.5} className="governance-page">
      <Paper variant="outlined" className="governance-hero">
        <Stack spacing={2}>
          <Stack
            direction={{ xs: 'column', lg: 'row' }}
            justifyContent="space-between"
            alignItems={{ xs: 'flex-start', lg: 'flex-start' }}
            spacing={2}
          >
            <Stack spacing={1.25} sx={{ maxWidth: 760 }}>
              <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                <Tooltip title={renderTooltipTitle(statusMeta.tooltip)} arrow>
                  <Chip
                    size="small"
                    color={statusMeta.color ?? 'default'}
                    icon={<FlagRoundedIcon />}
                    label={statusMeta.label}
                  />
                </Tooltip>
                <Tooltip title={renderTooltipTitle(CONTROL_META.tasksTracked.tooltip)} arrow>
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`${CONTROL_META.tasksTracked.label}: ${report?.completed_tasks_count ?? 0}`}
                  />
                </Tooltip>
                <Tooltip title={renderTooltipTitle(CONTROL_META.rollingWindow.tooltip)} arrow>
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`${CONTROL_META.rollingWindow.label}: ${report?.rolling_window_size ?? windowSize}`}
                  />
                </Tooltip>
              </Stack>
              <Typography variant="h6">Говернанс процесса</Typography>
              <Typography variant="body1" className="governance-headline">
                {summary?.headline ?? 'Еженедельный отчёт по процессу загружается.'}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {summary?.what_happened ?? 'Ждём актуальные process-метрики для сводки.'}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {summary?.why_it_drifted ?? 'После загрузки здесь появится краткое объяснение процессного дрейфа.'}
              </Typography>
            </Stack>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25} useFlexGap flexWrap="wrap">
              <Stack spacing={0.5}>
                <HintLabel label={CONTROL_META.weeks.label} tooltip={CONTROL_META.weeks.tooltip} variant="caption" />
                <TextField
                  select
                  size="small"
                  value={weeks}
                  onChange={(event) => setWeeks(Number(event.target.value))}
                  sx={{ minWidth: 136 }}
                >
                  {WEEK_OPTIONS.map((value) => (
                    <MenuItem key={`weeks-${value}`} value={value}>
                      Последние {value}
                    </MenuItem>
                  ))}
                </TextField>
              </Stack>
              <Stack spacing={0.5}>
                <HintLabel
                  label={CONTROL_META.windowSize.label}
                  tooltip={CONTROL_META.windowSize.tooltip}
                  variant="caption"
                />
                <TextField
                  select
                  size="small"
                  value={windowSize}
                  onChange={(event) => setWindowSize(Number(event.target.value))}
                  sx={{ minWidth: 148 }}
                >
                  {WINDOW_OPTIONS.map((value) => (
                    <MenuItem key={`window-${value}`} value={value}>
                      {value} задач
                    </MenuItem>
                  ))}
                </TextField>
              </Stack>
              <Button variant="contained" onClick={() => void load()} disabled={loading} sx={{ alignSelf: 'flex-end' }}>
                {loading ? 'Обновление...' : 'Обновить отчёт'}
              </Button>
            </Stack>
          </Stack>

          {summary?.what_to_change_next?.length ? (
            <Stack spacing={0.75}>
              <HintLabel
                label={SECTION_META.whatToChangeNext.label}
                tooltip={SECTION_META.whatToChangeNext.tooltip}
                variant="caption"
              />
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
                {summary.what_to_change_next.slice(0, 3).map((item) => (
                  <Chip key={item} icon={<RuleRoundedIcon />} label={item} className="governance-action-chip" />
                ))}
              </Stack>
            </Stack>
          ) : null}
        </Stack>
      </Paper>

      {error ? <Alert severity="error">{error}</Alert> : null}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <Paper variant="outlined" className="governance-stat-card">
            <Stack spacing={0.75}>
              <HintLabel
                label={METRIC_META.correct_first_time_pct.label}
                tooltip={METRIC_META.correct_first_time_pct.tooltip}
                variant="overline"
              />
              <Typography variant="h4">{formatPercent(currentMetrics?.correct_first_time_pct)}</Typography>
              <Typography variant="body2" color="text.secondary">
                Дельта {formatDelta(currentRollup?.deltas.correct_first_time_pct, 'percent')}
              </Typography>
            </Stack>
          </Paper>
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <Paper variant="outlined" className="governance-stat-card">
            <Stack spacing={0.75}>
              <HintLabel
                label={METRIC_META.start_match_pct.label}
                tooltip={METRIC_META.start_match_pct.tooltip}
                variant="overline"
              />
              <Typography variant="h4">{formatPercent(currentMetrics?.start_match_pct)}</Typography>
              <Typography variant="body2" color="text.secondary">
                {METRIC_META.context_expansion_rate.label} {formatPercent(currentMetrics?.context_expansion_rate)}
              </Typography>
            </Stack>
          </Paper>
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <Paper variant="outlined" className="governance-stat-card">
            <Stack spacing={0.75}>
              <HintLabel
                label={METRIC_META.repeat_error_rate.label}
                tooltip={METRIC_META.repeat_error_rate.tooltip}
                variant="overline"
              />
              <Typography variant="h4">{formatPercent(currentMetrics?.repeat_error_rate)}</Typography>
              <Typography variant="body2" color="text.secondary">
                {METRIC_META.environment_blocker_rate.label} {formatPercent(currentMetrics?.environment_blocker_rate)}
              </Typography>
            </Stack>
          </Paper>
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <Paper variant="outlined" className="governance-stat-card">
            <Stack spacing={0.75}>
              <HintLabel
                label={METRIC_META.median_time_to_first_patch_sec.label}
                tooltip={METRIC_META.median_time_to_first_patch_sec.tooltip}
                variant="overline"
              />
              <Typography variant="h4">{formatSeconds(currentMetrics?.median_time_to_first_patch_sec)}</Typography>
              <Typography variant="body2" color="text.secondary">
                {METRIC_META.same_path_attempts_p90.label} {currentMetrics?.same_path_attempts_p90 ?? '—'}
              </Typography>
            </Stack>
          </Paper>
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, xl: 7 }}>
          <Paper variant="outlined" className="governance-surface governance-chart-card">
            <Stack spacing={1.5}>
              <Stack direction="row" spacing={1} alignItems="center">
                <AutoGraphRoundedIcon fontSize="small" />
                <HintLabel label={SECTION_META.weeklyTrend.label} tooltip={SECTION_META.weeklyTrend.tooltip} />
              </Stack>
              {deferredTrend.length ? (
                <LineChart
                  height={320}
                  xAxis={[{ scaleType: 'point', data: chartLabels }]}
                  series={[
                    {
                      id: 'correct-first-time',
                      label: 'С первого раза',
                      data: cftSeries,
                      color: '#14746f',
                    },
                    {
                      id: 'start-match',
                      label: 'Совпадение старта',
                      data: matchSeries,
                      color: '#1d3557',
                    },
                    {
                      id: 'repeat-error',
                      label: 'Повторы ошибок',
                      data: repeatSeries,
                      color: '#bc6c25',
                    },
                  ]}
                  margin={{ top: 16, right: 24, bottom: 24, left: 36 }}
                  yAxis={[{ min: 0, max: 1 }]}
                />
              ) : (
                <Typography variant="body2" color="text.secondary">
                  История по неделям появится после первых завершённых задач в outcome ledger.
                </Typography>
              )}
            </Stack>
          </Paper>
        </Grid>

        <Grid size={{ xs: 12, xl: 5 }}>
          <Paper variant="outlined" className="governance-surface">
            <Stack spacing={1.5}>
              <Stack direction="row" spacing={1} alignItems="center">
                <InsightsRoundedIcon fontSize="small" />
                <HintLabel label={SECTION_META.currentWindow.label} tooltip={SECTION_META.currentWindow.tooltip} />
              </Stack>
              {summary?.current_risks?.length ? (
                <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                  {summary.current_risks.slice(0, 4).map((risk) => (
                    <Chip key={risk} size="small" variant="outlined" label={translateRisk(risk)} />
                  ))}
                </Stack>
              ) : null}
              {renderRankedList({
                title: SECTION_META.repeatedSignatures.label,
                tooltip: SECTION_META.repeatedSignatures.tooltip,
                items: currentRollup?.top_repeated_error_signatures ?? [],
                emptyLabel: 'В текущем окне нет повторяющихся сигнатур.',
                formatName: translateIncidentSignature,
              })}
              {renderRankedList({
                title: SECTION_META.environmentBlockers.label,
                tooltip: SECTION_META.environmentBlockers.tooltip,
                items: currentRollup?.top_environment_blockers ?? [],
                emptyLabel: 'В текущем окне нет устойчивого кластера блокеров среды.',
                formatName: translateIncidentSignature,
              })}
            </Stack>
          </Paper>
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 4 }}>
          <Paper variant="outlined" className="governance-surface governance-week-list">
            <Stack spacing={1.25}>
              <HintLabel label={SECTION_META.weeklyReports.label} tooltip={SECTION_META.weeklyReports.tooltip} variant="subtitle1" />
              <List disablePadding>
                {weeklyReports.length ? (
                  weeklyReports.map((item: WeeklyReport) => {
                    const weeklyStatus = STATUS_META[item.human_summary.status] ?? STATUS_META.empty
                    return (
                      <ListItemButton
                        key={item.week_start}
                        selected={selectedWeekStart === item.week_start}
                        onClick={() => selectWeek(item.week_start)}
                        className="governance-week-item"
                      >
                        <ListItemText
                          primary={item.week_label}
                          secondary={`${item.tasks_count} задач | ${formatPercent(item.metrics.correct_first_time_pct)} с первого раза`}
                        />
                        <Tooltip title={renderTooltipTitle(weeklyStatus.tooltip)} arrow>
                          <Chip size="small" color={weeklyStatus.color ?? 'default'} label={weeklyStatus.label} />
                        </Tooltip>
                      </ListItemButton>
                    )
                  })
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    Недельных срезов пока нет.
                  </Typography>
                )}
              </List>
            </Stack>
          </Paper>
        </Grid>

        <Grid size={{ xs: 12, lg: 8 }}>
          <Paper variant="outlined" className="governance-surface">
            <Stack spacing={2}>
              <Stack
                direction={{ xs: 'column', md: 'row' }}
                justifyContent="space-between"
                alignItems={{ xs: 'flex-start', md: 'center' }}
                spacing={1}
              >
                <Stack spacing={0.5}>
                  <Typography variant="subtitle1">{selectedWeek?.week_label ?? 'Выбранная неделя'}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {selectedWeek?.human_summary.headline ?? 'Выберите недельный срез слева, чтобы посмотреть детали.'}
                  </Typography>
                </Stack>
                {selectedWeek ? (
                  <Chip
                    size="small"
                    icon={<WarningAmberRoundedIcon />}
                    label={`${selectedWeek.tasks_count} задач`}
                    variant="outlined"
                  />
                ) : null}
              </Stack>

              <Grid container spacing={1.5}>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <Paper variant="outlined" className="governance-note-card">
                    <Stack spacing={0.5}>
                      <HintLabel
                        label={SECTION_META.whatHappened.label}
                        tooltip={SECTION_META.whatHappened.tooltip}
                        variant="overline"
                      />
                      <Typography variant="body2">
                        {selectedWeek?.human_summary.what_happened ?? 'Сводка по этой неделе пока недоступна.'}
                      </Typography>
                    </Stack>
                  </Paper>
                </Grid>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <Paper variant="outlined" className="governance-note-card">
                    <Stack spacing={0.5}>
                      <HintLabel
                        label={SECTION_META.whyItDrifted.label}
                        tooltip={SECTION_META.whyItDrifted.tooltip}
                        variant="overline"
                      />
                      <Typography variant="body2">
                        {selectedWeek?.human_summary.why_it_drifted ?? 'Объяснение дрейфа для этой недели пока недоступно.'}
                      </Typography>
                    </Stack>
                  </Paper>
                </Grid>
              </Grid>

              {selectedWeek?.human_summary.what_to_change_next?.length ? (
                <Stack spacing={1}>
                  <HintLabel
                    label={SECTION_META.whatToChangeNext.label}
                    tooltip={SECTION_META.whatToChangeNext.tooltip}
                  />
                  <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                    {selectedWeek.human_summary.what_to_change_next.map((item) => (
                      <Chip key={item} size="small" label={item} className="governance-action-chip" />
                    ))}
                  </Stack>
                </Stack>
              ) : null}

              <Grid container spacing={1.5}>
                <Grid size={{ xs: 12, md: 6 }}>
                  {renderRankedList({
                    title: SECTION_META.highRiskRecommendations.label,
                    tooltip: SECTION_META.highRiskRecommendations.tooltip,
                    items: selectedWeek?.high_risk_start_recommendations ?? [],
                    emptyLabel: 'На этой неделе нет устойчивого кластера рискованных стартовых рекомендаций.',
                    formatName: translateRecommendation,
                  })}
                </Grid>
                <Grid size={{ xs: 12, md: 6 }}>
                  {renderRankedList({
                    title: SECTION_META.environmentBlockers.label,
                    tooltip: SECTION_META.environmentBlockers.tooltip,
                    items: selectedWeek?.top_environment_blockers ?? [],
                    emptyLabel: 'На этой неделе нет кластера блокеров среды.',
                    formatName: translateIncidentSignature,
                  })}
                </Grid>
              </Grid>

              <Stack spacing={1}>
                <HintLabel label={SECTION_META.tasksOfNote.label} tooltip={SECTION_META.tasksOfNote.tooltip} />
                {selectedTasks.length ? (
                  <Grid container spacing={1.25}>
                    {selectedTasks.map((task) => (
                      <Grid key={task.task_id} size={{ xs: 12, md: 6 }}>
                        {renderTaskCard(task)}
                      </Grid>
                    ))}
                  </Grid>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    В этом недельном срезе нет задач с неверным маршрутом или частичным исходом.
                  </Typography>
                )}
              </Stack>
            </Stack>
          </Paper>
        </Grid>
      </Grid>
    </Stack>
  )
}

export default ProcessGovernanceTab
