export type GovernanceChipColor = 'default' | 'success' | 'warning' | 'error'

type GovernanceMeta = {
  label: string
  tooltip: string
  color?: GovernanceChipColor
}

const RECOMMENDATION_TRANSLATIONS: Record<string, string> = {
  'No files provided. Use --from-git, --stdin, or --changed-files.':
    'Файлы не переданы. Укажите diff через `--from-git`, `--stdin` или `--changed-files`.',
  'No diff yet. Using request/session intent fallback.':
    'Дифф ещё не появился. Используется fallback по запросу и session handoff.',
  'Patch touches multiple contexts. Split by ownership to keep review and agent context small.':
    'Патч затрагивает несколько контекстов. Разделите изменения по зонам владения, чтобы ревью и агентный контекст оставались узкими.',
  'Intent spans multiple contexts. Set an explicit target module before implementation.':
    'Намерение задачи затрагивает несколько контекстов. До реализации явно выберите целевой модуль.',
  'CTX-CONTRACTS is combined with other contexts. Use ordered patch series: contracts -> code -> docs.':
    'CTX-CONTRACTS смешан с другими контекстами. Ведите серию патчей в порядке: контракты -> код -> документация.',
  'Some files are unmapped. Classify manually before implementation.':
    'Есть неразмеченные файлы. Перед реализацией вручную определите их контекст.',
  'Patch is scoped to one context.': 'Патч ограничен одним контекстом.',
}

const translateCrossCuttingRecommendation = (value: string) => {
  const suffix = ' imports span multiple neighboring contexts. Treat as cross-cutting and keep adapters thin.'
  if (!value.endsWith(suffix)) return value
  const prefix = value.slice(0, -suffix.length)
  return `${prefix} затрагивает несколько соседних контекстов. Считайте это сквозной зоной и держите адаптеры тонкими.`
}

export const translateRecommendation = (value: string) =>
  RECOMMENDATION_TRANSLATIONS[value] ?? translateCrossCuttingRecommendation(value)

export const STATUS_META: Record<string, GovernanceMeta> = {
  healthy: {
    label: 'Стабильно',
    tooltip:
      'Формула: статус = healthy, если burn-in завершён и ни одно rolling-пороговое измерение не нарушено. Интерпретация: текущий процесс не требует дополнительного вмешательства.',
    color: 'success',
  },
  watch: {
    label: 'Нужно внимание',
    tooltip:
      'Формула: статус = watch, если burn-in завершён и нарушено ровно одно измерение governance. Интерпретация: есть локальный дрейф, но ещё без системного срыва.',
    color: 'warning',
  },
  critical: {
    label: 'Нужна интервенция',
    tooltip:
      'Формула: статус = critical, если burn-in завершён и нарушено больше одного измерения governance. Интерпретация: процесс деградировал сразу по нескольким направлениям.',
    color: 'error',
  },
  'burn-in': {
    label: 'Прогрев',
    tooltip:
      'Формула: статус = burn-in, пока закрытых задач меньше размера rolling-окна. Интерпретация: сигналы уже полезны, но пороги ещё не должны блокировать по тренду.',
    color: 'default',
  },
  empty: {
    label: 'Нет данных',
    tooltip:
      'Формула: статус = empty, если в ledger нет завершённых задач. Интерпретация: отчёт ещё не может показать недельный процессный сигнал.',
    color: 'default',
  },
}

export const CONTROL_META = {
  status: STATUS_META,
  tasksTracked: {
    label: 'Задач в учёте',
    tooltip:
      'Формула: completed_tasks_count из process report. Интерпретация: сколько завершённых задач уже попало в исторический ledger и влияет на weekly/rolling аналитику.',
  },
  rollingWindow: {
    label: 'Размер rolling-окна',
    tooltip:
      'Формула: rolling_window_size из process report. Интерпретация: сколько последних завершённых задач участвуют в текущих rolling-метриках и блокирующих порогах.',
  },
  weeks: {
    label: 'Горизонт недель',
    tooltip:
      'Формула: число недель, запрошенных у weekly history. Интерпретация: определяет глубину исторического обзора в списке недель и на графике.',
  },
  windowSize: {
    label: 'Rolling-окно',
    tooltip:
      'Формула: число последних завершённых задач в rolling summary. Интерпретация: меньшее окно быстрее показывает изменения, большее сглаживает шум.',
  },
} as const

export const METRIC_META: Record<string, GovernanceMeta> = {
  correct_first_time_pct: {
    label: 'С первого раза',
    tooltip:
      'Формула: correct_first_time / completed_tasks. Интерпретация: доля задач, где маршрут и реализация оказались верными без перепланирования.',
  },
  start_match_pct: {
    label: 'Совпадение старта',
    tooltip:
      'Формула: route_match = matched / completed_tasks. Интерпретация: как часто стартовый выбор контекста оказался достаточным без расширения или смены маршрута.',
  },
  context_expansion_rate: {
    label: 'Расширение контекста',
    tooltip:
      'Формула: expanded_or_more_contexts / completed_tasks. Интерпретация: чем выше значение, тем чаще стартовый контекст оказался слишком узким.',
  },
  repeat_error_rate: {
    label: 'Повторы ошибок',
    tooltip:
      'Формула: repeated_incident_signature / completed_tasks. Интерпретация: показывает, как часто система снова сталкивается с уже известной ошибкой.',
  },
  environment_blocker_rate: {
    label: 'Блокеры среды',
    tooltip:
      'Формула: environment_blocked_or_environment_rework / completed_tasks. Интерпретация: доля задач, где основной источник срыва связан со средой, окружением или инфраструктурой.',
  },
  median_time_to_first_patch_sec: {
    label: 'До первого патча',
    tooltip:
      'Формула: median(time_to_first_patch_sec) по rolling-окну. Интерпретация: насколько быстро задача превращается в первый осмысленный кодовый шаг.',
  },
  same_path_attempts_p90: {
    label: 'Повторы по тому же пути p90',
    tooltip:
      'Формула: 90-й перцентиль same_path_attempts по rolling-окну. Интерпретация: показывает, насколько часто задачи застревают в повторении одной и той же тактики.',
  },
} as const

export const SECTION_META = {
  weeklyTrend: {
    label: 'Недельный тренд',
    tooltip:
      'Формула: weekly history по correct_first_time_pct, start_match_pct и repeat_error_rate. Интерпретация: позволяет увидеть, становится ли процесс устойчивее или дрейфует от недели к неделе.',
  },
  currentWindow: {
    label: 'Текущее rolling-окно',
    tooltip:
      'Формула: агрегаты по последним завершённым задачам в текущем окне. Интерпретация: это главный срез, который влияет на текущую процессную оценку и rolling-пороги.',
  },
  repeatedSignatures: {
    label: 'Повторяющиеся сигнатуры',
    tooltip:
      'Формула: incident_signature, которые повторились в текущем окне. Интерпретация: список показывает, какие ошибки уже случались раньше и требуют нового профилактического артефакта.',
  },
  environmentBlockers: {
    label: 'Блокеры среды',
    tooltip:
      'Формула: incident_signature задач с primary_rework_cause = environment. Интерпретация: помогает увидеть, где процесс тормозится не кодом, а средой.',
  },
  weeklyReports: {
    label: 'Недельные срезы',
    tooltip:
      'Формула: одна карточка на календарную неделю закрытия задач. Интерпретация: это быстрый способ выбрать период и посмотреть, что именно происходило.',
  },
  whatHappened: {
    label: 'Что произошло',
    tooltip:
      'Формула: человекочитаемое summary по ключевым weekly/rolling метрикам. Интерпретация: краткий итог недели без чтения сырых чисел.',
  },
  whyItDrifted: {
    label: 'Почему был дрейф',
    tooltip:
      'Формула: summary по контекстным расширениям, повторам ошибок, блокерам среды и wrong-path задачам. Интерпретация: объясняет источник отклонения процесса.',
  },
  whatToChangeNext: {
    label: 'Что менять дальше',
    tooltip:
      'Формула: автоматические next actions из текущего состояния метрик и рисков. Интерпретация: это короткий список процессных вмешательств на следующий цикл.',
  },
  highRiskRecommendations: {
    label: 'Рискованные стартовые рекомендации',
    tooltip:
      'Формула: стартовые рекомендации, которые чаще встречались у проблемных задач недели. Интерпретация: помогает увидеть, какие ранние сигналы чаще всего предшествуют rework.',
  },
  tasksOfNote: {
    label: 'Задачи внимания',
    tooltip:
      'Формула: задачи с wrong_path, partial_outcome или route drift в выбранном weekly slice. Интерпретация: это примеры, которые стоит разобрать вручную.',
  },
} as const

export const DECISION_QUALITY_META: Record<string, GovernanceMeta> = {
  pending: {
    label: 'Ожидается',
    tooltip:
      'Формула: decision_quality = pending до закрытия задачи. Интерпретация: качество решения ещё не оценено.',
    color: 'default',
  },
  correct_first_time: {
    label: 'С первого раза',
    tooltip:
      'Формула: верный путь выбран сразу и задача закрылась без перепланирования. Интерпретация: лучший базовый исход для process governance.',
    color: 'success',
  },
  correct_after_replan: {
    label: 'После перепланирования',
    tooltip:
      'Формула: стартовый путь пришлось пересобрать, но после replanning задача завершилась корректно. Интерпретация: итог рабочий, но был потерян процессный запас.',
    color: 'warning',
  },
  wrong_path: {
    label: 'Неверный путь',
    tooltip:
      'Формула: задача пошла по неверному маршруту и это стало самостоятельной причиной rework. Интерпретация: сильный сигнал, что стартовая маршрутизация была ошибочной.',
    color: 'error',
  },
  partial_outcome: {
    label: 'Частичный итог',
    tooltip:
      'Формула: задача закрыта не полностью или с незавершённым intended outcome. Интерпретация: решение не доведено до полноценного результата.',
    color: 'warning',
  },
  environment_blocked: {
    label: 'Заблокировано средой',
    tooltip:
      'Формула: главный срыв вызван окружением, инфраструктурой или локальной средой. Интерпретация: чинить нужно среду или runbook, а не повторять тот же кодовый путь.',
    color: 'error',
  },
}

export const ROUTE_MATCH_META: Record<string, GovernanceMeta> = {
  pending: {
    label: 'Ожидается',
    tooltip:
      'Формула: route_match = pending до финального closeout. Интерпретация: совпадение стартового и итогового контекста ещё не зафиксировано.',
    color: 'default',
  },
  matched: {
    label: 'Совпал',
    tooltip:
      'Формула: стартовый и итоговый контекст совпали. Интерпретация: изначальный маршрут был выбран точно.',
    color: 'success',
  },
  expanded: {
    label: 'Расширен',
    tooltip:
      'Формула: итоговый контекст пришлось расширить относительно стартового. Интерпретация: старт был частично верным, но недостаточно полным.',
    color: 'warning',
  },
  mismatched: {
    label: 'Не совпал',
    tooltip:
      'Формула: итоговый контекст не совпал со стартовым маршрутом. Интерпретация: задача ушла в другой путь и требует ручного разбора.',
    color: 'error',
  },
}

export const OUTCOME_STATUS_LABELS: Record<string, string> = {
  completed: 'Завершено',
  partial: 'Частично',
  blocked: 'Заблокировано',
  in_progress: 'В работе',
}

export const translateIncidentSignature = (value: string | undefined) => {
  if (!value || value === 'none') return '—'
  if (value === 'environment/no-signature') return 'Среда без сигнатуры'
  return value
}

export const translateMetricName = (value: string) => METRIC_META[value]?.label ?? value

export const translateRisk = (value: string) => {
  const metricLabel = translateMetricName(value)
  if (metricLabel !== value) return metricLabel
  const prefix = 'most common start recommendation: '
  if (value.startsWith(prefix)) {
    return `Самая частая стартовая рекомендация: ${translateRecommendation(value.slice(prefix.length))}`
  }
  return value
}
