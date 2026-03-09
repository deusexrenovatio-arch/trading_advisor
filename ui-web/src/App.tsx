import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { Box, Chip, Container, Paper, Stack, Tab, Tabs, Typography } from '@mui/material'
import type { GridRowParams } from '@mui/x-data-grid'
import BacktestV2Tab from './features/backtest-run/BacktestV2Tab'
import { useBacktestForwardHpo } from './features/backtest-run/useBacktestForwardHpo'
import DecisionsTab from './features/decisions/DecisionsTab'
import { createDecisionColumns } from './features/decisions/decisionColumns'
import { useDecisionView } from './features/decisions/useDecisionView'
import ForwardTab from './features/forward/ForwardTab'
import HpoTab from './features/hpo/HpoTab'
import BacktestsTab from './features/backtests/BacktestsTab'
import SignalsTab from './features/signals/SignalsTab'
import NewsIntelligenceTab from './features/news/NewsIntelligenceTab'
import PortfolioControlTab from './features/portfolio/PortfolioControlTab'
import { formatDate } from './shared/utils/date'
import TopPairsTab from './features/top-pairs/TopPairsTab'
import { useMarketTables } from './features/market/useMarketTables'
import type { AppTab } from './features/market/useMarketTables'
import { formatNumber } from './shared/utils/format'
import { getString } from './shared/utils/guards'
import { isDateColumn } from './shared/utils/tables'
import { mapDecisionRows } from './shared/mappers/decisionMappers'
import { compareValues, formatCellValue, formatValue } from './shared/utils/formatValue'
import { getFieldLabel, getFieldTooltip, toTitleCase } from './shared/utils/field'
import { buildParamDefaults, collectParamRequest } from './shared/utils/params'
import ParamInput from './shared/ui/ParamInput'
import { renderFieldLabel } from './shared/ui/FieldLabel'
import {
  buildBacktestEquityColumns,
  buildBacktestTradeColumns,
  buildHpoLeaderboardColumns,
  buildHpoLeaderboardRows,
  buildParamSections,
  filterParamSpecs,
} from './shared/utils/backtestView'
import type {
  DecisionView,
  GenericRow,
  HpoTrial,
  ParameterSpec,
} from './entities/decision/types'
import './App.css'

const ProcessGovernanceTab = lazy(() => import('./features/process-governance/ProcessGovernanceTab'))

type WorkspaceTab =
  | 'trade_console'
  | 'research_lab'
  | 'news_intelligence'
  | 'portfolio_control'
  | 'process_governance'
type TradeConsoleTab = 'decisions' | 'top_pairs' | 'signals' | 'backtests'
type ResearchTab = 'backtest_v2' | 'forward' | 'hpo'
const BLOCKED_SIGNAL_ACTIONS = new Set(['hold_pretrade', 'check_pretrade'])
const APP_SESSION_STARTED_AT_MS = Date.now()

type UiRouteState = {
  workspace: WorkspaceTab
  tradeTab: TradeConsoleTab
  researchTab: ResearchTab
  canonicalPath: string
}

const DEFAULT_PATH = '/trade-console/signals'

const renderLazyFallback = (
  title: string,
  description: string,
) => (
  <Paper variant="outlined" className="governance-surface">
    <Stack spacing={0.75}>
      <Typography variant="subtitle1">{title}</Typography>
      <Typography variant="body2" color="text.secondary">
        {description}
      </Typography>
    </Stack>
  </Paper>
)

const tradeTabToPath = (tab: TradeConsoleTab) => {
  if (tab === 'decisions') return '/decision-audit'
  if (tab === 'top_pairs') return '/trade-console/top-pairs'
  if (tab === 'backtests') return '/trade-console/backtests'
  return '/trade-console/signals'
}

const researchTabToPath = (tab: ResearchTab) => {
  if (tab === 'forward') return '/research-system/forward'
  if (tab === 'hpo') return '/research-system/hpo'
  return '/research-system/backtest-v2'
}

const workspaceToPath = (
  workspace: WorkspaceTab,
  tradeTab: TradeConsoleTab,
  researchTab: ResearchTab,
) => {
  if (workspace === 'research_lab') return researchTabToPath(researchTab)
  if (workspace === 'news_intelligence') return '/news-intelligence'
  if (workspace === 'portfolio_control') return '/portfolio-control'
  if (workspace === 'process_governance') return '/process-governance'
  return tradeTabToPath(tradeTab)
}

const normalizePath = (pathname: string) => {
  const trimmed = pathname.trim()
  if (!trimmed) return '/'
  const normalized = trimmed.replace(/\/{2,}/g, '/')
  if (normalized.length > 1 && normalized.endsWith('/')) {
    return normalized.slice(0, -1)
  }
  return normalized
}

const parseRouteState = (pathname: string): UiRouteState => {
  const normalized = normalizePath(pathname || '/')

  if (normalized === '/decision-audit' || normalized === '/trade-console/decisions') {
    return {
      workspace: 'trade_console',
      tradeTab: 'decisions',
      researchTab: 'backtest_v2',
      canonicalPath: '/decision-audit',
    }
  }
  if (normalized === '/trade-console/top-pairs') {
    return {
      workspace: 'trade_console',
      tradeTab: 'top_pairs',
      researchTab: 'backtest_v2',
      canonicalPath: '/trade-console/top-pairs',
    }
  }
  if (normalized === '/trade-console/backtests') {
    return {
      workspace: 'trade_console',
      tradeTab: 'backtests',
      researchTab: 'backtest_v2',
      canonicalPath: '/trade-console/backtests',
    }
  }
  if (normalized === '/trade-console' || normalized === '/trade-console/signals') {
    return {
      workspace: 'trade_console',
      tradeTab: 'signals',
      researchTab: 'backtest_v2',
      canonicalPath: '/trade-console/signals',
    }
  }

  if (normalized === '/research-system' || normalized === '/research-system/backtest-v2') {
    return {
      workspace: 'research_lab',
      tradeTab: 'signals',
      researchTab: 'backtest_v2',
      canonicalPath: '/research-system/backtest-v2',
    }
  }
  if (normalized === '/research-system/forward') {
    return {
      workspace: 'research_lab',
      tradeTab: 'signals',
      researchTab: 'forward',
      canonicalPath: '/research-system/forward',
    }
  }
  if (normalized === '/research-system/hpo') {
    return {
      workspace: 'research_lab',
      tradeTab: 'signals',
      researchTab: 'hpo',
      canonicalPath: '/research-system/hpo',
    }
  }

  if (normalized === '/news-intelligence') {
    return {
      workspace: 'news_intelligence',
      tradeTab: 'signals',
      researchTab: 'backtest_v2',
      canonicalPath: '/news-intelligence',
    }
  }

  if (normalized === '/portfolio-control') {
    return {
      workspace: 'portfolio_control',
      tradeTab: 'signals',
      researchTab: 'backtest_v2',
      canonicalPath: '/portfolio-control',
    }
  }

  if (normalized === '/process-governance') {
    return {
      workspace: 'process_governance',
      tradeTab: 'signals',
      researchTab: 'backtest_v2',
      canonicalPath: '/process-governance',
    }
  }

  return {
    workspace: 'trade_console',
    tradeTab: 'signals',
    researchTab: 'backtest_v2',
    canonicalPath: DEFAULT_PATH,
  }
}

function App() {
  const {
    loading,
    error,
    fetchDecisionView,
    selectedId,
    selectDecision,
    detail,
    detailError,
    decisionActionLoading,
    decisionActionError,
    decisionActionSubmitting,
    decisionActionNote,
    setDecisionActionNote,
    submitDecisionAction,
    quickFilter,
    setQuickFilter,
    strategyFilter,
    setStrategyFilter,
    instrumentFilter,
    setInstrumentFilter,
    riskFilter,
    setRiskFilter,
    newsFilter,
    setNewsFilter,
    createdFrom,
    setCreatedFrom,
    createdTo,
    setCreatedTo,
    filteredRows,
    strategyOptions,
    instrumentOptions,
    riskOptions,
    newsOptions,
    selectedDecision,
    detailDecision,
    detailAggregation,
    detailProposal,
    detailFacts,
    basketRows,
    operatorAction,
    executionStatus,
  } = useDecisionView()
  const [routePath, setRoutePath] = useState(() => {
    if (typeof window === 'undefined') return DEFAULT_PATH
    return window.location.pathname || DEFAULT_PATH
  })
  const routeState = useMemo(() => parseRouteState(routePath), [routePath])
  const workspace = routeState.workspace
  const tradeTab = routeState.tradeTab
  const researchTab = routeState.researchTab
  const activeTab: AppTab = workspace === 'research_lab' ? researchTab : tradeTab
  const [tabSwitchCount, setTabSwitchCount] = useState(0)
  const [firstActionAtMs, setFirstActionAtMs] = useState<number | null>(null)
  const markFirstAction = useCallback(() => {
    setFirstActionAtMs((current) => current ?? Date.now())
  }, [])
  const market = useMarketTables({ tab: activeTab, compareValues, onOperatorAction: markFirstAction })
  const {
    paramSpecs,
    paramValues,
    paramFilter,
    paramPreset,
    paramSpecsLoading,
    paramSpecsError,
    backtestPrecompute,
    backtestRunReport,
    backtestRunLoading,
    backtestRunError,
    backtestRunParseError,
    forwardRunId,
    forwardRequestJson,
    forwardRequestJsonError,
    forwardStatus,
    forwardLoading,
    forwardError,
    forwardStartLoading,
    forwardStartError,
    forwardStartMessage,
    hpoRequestJson,
    hpoRequestJsonError,
    hpoSearchSpace,
    hpoResponse,
    hpoLoading,
    hpoError,
    setParamFilter,
    setParamPreset,
    setBacktestPrecompute,
    setForwardRunId,
    handleForwardRequestJsonChange,
    handleHpoRequestJsonChange,
    setHpoSearchSpace,
    fetchParamSpecs,
    handleParamValueChange,
    handleParamReset,
    handleBacktestRun,
    fetchForwardStatus,
    startForwardRun,
    handleHpoRun,
  } = useBacktestForwardHpo({ tab: activeTab, buildParamDefaults, collectParamRequest })

  useEffect(() => {
    if (typeof window === 'undefined') return undefined
    const handlePopState = () => {
      const nextPath = window.location.pathname || DEFAULT_PATH
      setRoutePath((currentPath) => {
        if (currentPath !== nextPath) {
          setTabSwitchCount((value) => value + 1)
        }
        return nextPath
      })
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const browserPath = normalizePath(window.location.pathname || DEFAULT_PATH)
    if (routeState.canonicalPath === browserPath) return
    window.history.replaceState(null, '', routeState.canonicalPath)
  }, [routeState.canonicalPath])

  const navigateTo = useCallback(
    (nextPath: string) => {
      if (typeof window === 'undefined') return
      const canonicalPath = parseRouteState(nextPath).canonicalPath
      if (canonicalPath === routePath) return
      window.history.pushState(null, '', canonicalPath)
      setTabSwitchCount((value) => value + 1)
      setRoutePath(canonicalPath)
    },
    [routePath],
  )

  const handleWorkspaceChange = useCallback(
    (_: unknown, value: WorkspaceTab) => {
      navigateTo(workspaceToPath(value, tradeTab, researchTab))
    },
    [navigateTo, researchTab, tradeTab],
  )

  const handleTradeTabChange = useCallback(
    (_: unknown, value: TradeConsoleTab) => {
      navigateTo(tradeTabToPath(value))
    },
    [navigateTo],
  )

  const handleResearchTabChange = useCallback(
    (_: unknown, value: ResearchTab) => {
      navigateTo(researchTabToPath(value))
    },
    [navigateTo],
  )

  const handleRefresh = useCallback(() => {
    fetchDecisionView()
    market.fetchAuxData()
  }, [fetchDecisionView, market])

  const handleSubmitDecisionAction = useCallback(
    async (action: 'approve' | 'reject') => {
      markFirstAction()
      await submitDecisionAction(action)
    },
    [markFirstAction, submitDecisionAction],
  )

  const filteredParamSpecs = useMemo(
    () => filterParamSpecs(paramSpecs, paramFilter),
    [paramSpecs, paramFilter],
  )

  const paramSections = useMemo<[string, ParameterSpec[]][]>(() => buildParamSections(filteredParamSpecs), [filteredParamSpecs])

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

  const backtestEquityColumns = useMemo(
    () => buildBacktestEquityColumns(backtestEquityRows),
    [backtestEquityRows],
  )

  const backtestTradeColumns = useMemo(
    () => buildBacktestTradeColumns(backtestTradeRows),
    [backtestTradeRows],
  )

  const hpoLeaderboardRows = useMemo<HpoTrial[]>(
    () => buildHpoLeaderboardRows(hpoResponse),
    [hpoResponse],
  )

  const hpoLeaderboardColumns = useMemo(
    () => buildHpoLeaderboardColumns(hpoLeaderboardRows),
    [hpoLeaderboardRows],
  )

  const decisionColumns = useMemo(
    () =>
      createDecisionColumns({
        getFieldLabel,
        getFieldTooltip,
        formatDate,
        formatValue,
      }),
    [],
  )

  const handleRowClick = useCallback(
    (params: GridRowParams<DecisionView> | undefined) => {
      const decisionId = params?.row?.decision_id
      if (!decisionId) return
      selectDecision(decisionId)
    },
    [selectDecision],
  )

  const isLoading = loading || market.auxLoading || market.recomputeLoading

  const decisionRows = useMemo(
    () => mapDecisionRows(filteredRows),
    [filteredRows],
  )

  const renderParamInput = (spec: ParameterSpec) => (
    <ParamInput
      key={spec.key}
      spec={spec}
      value={paramValues[spec.key]}
      onValueChange={handleParamValueChange}
    />
  )

  const blockedActionRate = useMemo(() => {
    if (workspace !== 'trade_console' || tradeTab !== 'signals') return null
    const entryRows = market.sortedTableRows.filter((row) => market.isEntrySignal(row))
    if (!entryRows.length) return null
    const blockedCount = entryRows.filter((row) => {
      const effectiveAction = String(
        row.signal_action_effective ?? row.signal_action ?? '',
      ).toLowerCase()
      return BLOCKED_SIGNAL_ACTIONS.has(effectiveAction)
    }).length
    return blockedCount / entryRows.length
  }, [workspace, tradeTab, market])

  const timeToFirstActionSec =
    firstActionAtMs === null
      ? null
      : Math.max(0, Math.round((firstActionAtMs - APP_SESSION_STARTED_AT_MS) / 1000))

  return (
    <Box className="app-root">
      <Container maxWidth="xl" sx={{ py: 3 }}>
        <Stack spacing={2}>
          <Typography variant="h5" fontWeight={600}>
            Решения торгового советника
          </Typography>
          <Tabs value={workspace} onChange={handleWorkspaceChange}>
            <Tab label="Trade Console" value="trade_console" />
            <Tab label="Research Lab" value="research_lab" />
            <Tab label="News Intelligence" value="news_intelligence" />
            <Tab label="Portfolio Control" value="portfolio_control" />
            <Tab label="Говернанс процесса" value="process_governance" />
          </Tabs>
          {workspace === 'trade_console' ? (
            <Tabs value={tradeTab} onChange={handleTradeTabChange}>
              <Tab label="Решения" value="decisions" />
              <Tab label="Топ пар" value="top_pairs" />
              <Tab label="Сигналы" value="signals" />
              <Tab label="Бэктесты" value="backtests" />
            </Tabs>
          ) : null}
          {workspace === 'research_lab' ? (
            <Tabs value={researchTab} onChange={handleResearchTabChange}>
              <Tab label="Бэктест v2" value="backtest_v2" />
              <Tab label="Статус форварда" value="forward" />
              <Tab label="HPO" value="hpo" />
            </Tabs>
          ) : null}
          {workspace !== 'process_governance' ? (
          <Paper variant="outlined" sx={{ p: 1.25 }}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
              <Chip label={`Переключений вкладок: ${tabSwitchCount}`} size="small" />
              <Chip
                label={`Время до первого действия (сек): ${
                  timeToFirstActionSec === null ? 'n/a' : timeToFirstActionSec
                }`}
                size="small"
              />
              <Chip
                label={`Доля блокировок входа: ${
                  blockedActionRate === null ? 'n/a' : `${(blockedActionRate * 100).toFixed(1)}%`
                }`}
                size="small"
                color={
                  blockedActionRate === null
                    ? 'default'
                    : blockedActionRate > 0.3
                      ? 'warning'
                      : 'success'
                }
              />
            </Stack>
          </Paper>
          ) : null}
          {workspace === 'trade_console' && tradeTab === 'decisions' ? (
            <DecisionsTab
              quickFilter={quickFilter}
              onQuickFilterChange={setQuickFilter}
              strategyFilter={strategyFilter}
              instrumentFilter={instrumentFilter}
              riskFilter={riskFilter}
              newsFilter={newsFilter}
              strategyOptions={strategyOptions}
              instrumentOptions={instrumentOptions}
              riskOptions={riskOptions}
              newsOptions={newsOptions}
              onStrategyFilterChange={setStrategyFilter}
              onInstrumentFilterChange={setInstrumentFilter}
              onRiskFilterChange={setRiskFilter}
              onNewsFilterChange={setNewsFilter}
              createdFrom={createdFrom}
              createdTo={createdTo}
              onCreatedFromChange={setCreatedFrom}
              onCreatedToChange={setCreatedTo}
              onRefresh={handleRefresh}
              isLoading={isLoading}
              filteredCount={filteredRows.length}
              error={error}
              decisionRows={decisionRows}
              decisionColumns={decisionColumns}
              loading={loading}
              onRowClick={handleRowClick}
              selectedId={selectedId}
              detail={detail}
              detailError={detailError}
              selectedDecision={selectedDecision}
              detailDecision={detailDecision}
              detailProposal={detailProposal}
              detailAggregation={detailAggregation}
              detailFacts={detailFacts}
              basketRows={basketRows}
              decisionActionNote={decisionActionNote}
              onDecisionActionNoteChange={setDecisionActionNote}
              decisionActionSubmitting={decisionActionSubmitting}
              onSubmitDecisionAction={handleSubmitDecisionAction}
              decisionActionError={decisionActionError}
              decisionActionLoading={decisionActionLoading}
              operatorAction={operatorAction}
              executionStatus={executionStatus}
              formatValue={formatValue}
              formatNumber={formatNumber}
              formatDate={formatDate}
              getString={getString}
            />
          ) : null}
          {workspace === 'trade_console' && tradeTab === 'top_pairs' ? (
            <TopPairsTab
              market={market}
              formatCellValue={formatCellValue}
              renderFieldLabel={renderFieldLabel}
              formatDate={formatDate}
              formatValue={formatValue}
            />
          ) : null}
          {workspace === 'trade_console' && tradeTab === 'signals' ? (
            <SignalsTab
              market={market}
              formatCellValue={formatCellValue}
              renderFieldLabel={renderFieldLabel}
              formatDate={formatDate}
              formatValue={formatValue}
            />
          ) : null}
          {workspace === 'trade_console' && tradeTab === 'backtests' ? (
            <BacktestsTab
              market={market}
              formatCellValue={formatCellValue}
              renderFieldLabel={renderFieldLabel}
              formatDate={formatDate}
              formatValue={formatValue}
            />
          ) : null}
          {workspace === 'research_lab' && researchTab === 'backtest_v2' ? (
            <BacktestV2Tab
              paramPreset={paramPreset}
              onParamPresetChange={setParamPreset}
              onFetchParamSpecs={fetchParamSpecs}
              paramSpecsLoading={paramSpecsLoading}
              onParamReset={handleParamReset}
              paramSpecs={paramSpecs}
              backtestPrecompute={backtestPrecompute}
              onBacktestPrecomputeChange={setBacktestPrecompute}
              paramSpecsError={paramSpecsError}
              paramFilter={paramFilter}
              onParamFilterChange={setParamFilter}
              paramSections={paramSections}
              renderParamInput={renderParamInput}
              onBacktestRun={handleBacktestRun}
              backtestRunLoading={backtestRunLoading}
              backtestRunError={backtestRunError}
              backtestRunParseError={backtestRunParseError}
              backtestRunReport={backtestRunReport}
              backtestSummaryEntries={backtestSummaryEntries}
              backtestEquityRows={backtestEquityRows}
              backtestEquityColumns={backtestEquityColumns}
              backtestTradeRows={backtestTradeRows}
              backtestTradeColumns={backtestTradeColumns}
              toTitleCase={toTitleCase}
              renderFieldLabel={renderFieldLabel}
              formatCellValue={formatCellValue}
              formatDate={formatDate}
              isDateColumn={isDateColumn}
            />
          ) : null}
          {workspace === 'research_lab' && researchTab === 'forward' ? (
            <ForwardTab
              forwardRunId={forwardRunId}
              onForwardRunIdChange={setForwardRunId}
              forwardRequestJson={forwardRequestJson}
              onForwardRequestJsonChange={handleForwardRequestJsonChange}
              onStartForwardRun={startForwardRun}
              onFetchForwardStatus={fetchForwardStatus}
              forwardLoading={forwardLoading}
              forwardStartLoading={forwardStartLoading}
              forwardError={forwardError}
              forwardRequestJsonError={forwardRequestJsonError}
              forwardStartError={forwardStartError}
              forwardStartMessage={forwardStartMessage}
              forwardStatus={forwardStatus}
              formatValue={formatValue}
              renderFieldLabel={renderFieldLabel}
              formatCellValue={formatCellValue}
            />
          ) : null}
          {workspace === 'research_lab' && researchTab === 'hpo' ? (
            <HpoTab
              onFetchParamSpecs={() => fetchParamSpecs({ resetValues: false })}
              paramSpecsCount={paramSpecs.length}
              hpoRequestJson={hpoRequestJson}
              hpoRequestJsonError={hpoRequestJsonError}
              onHpoRequestJsonChange={handleHpoRequestJsonChange}
              hpoSearchSpace={hpoSearchSpace}
              onHpoSearchSpaceChange={setHpoSearchSpace}
              onHpoRun={handleHpoRun}
              hpoLoading={hpoLoading}
              hpoError={hpoError}
              hpoResponse={hpoResponse}
              formatValue={formatValue}
              hpoLeaderboardRows={hpoLeaderboardRows as GenericRow[]}
              hpoLeaderboardColumns={hpoLeaderboardColumns}
              renderFieldLabel={renderFieldLabel}
              formatCellValue={formatCellValue}
              formatDate={formatDate}
              isDateColumn={isDateColumn}
            />
          ) : null}
          {workspace === 'news_intelligence' ? <NewsIntelligenceTab /> : null}
          {workspace === 'portfolio_control' ? <PortfolioControlTab /> : null}
          {workspace === 'process_governance' ? (
            <Suspense
              fallback={renderLazyFallback(
                'Загрузка говернанса процесса',
                'Подготавливаем weekly-отчёт по процессу и связанные графики.',
              )}
            >
              <ProcessGovernanceTab />
            </Suspense>
          ) : null}
        </Stack>
      </Container>
    </Box>
  )
}

export default App


