import { useCallback, useEffect, useMemo, useState } from 'react'
import { Box, Container, FormControl, InputLabel, MenuItem, Select, Stack, Tab, Tabs, TextField, Typography } from '@mui/material'
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
import { formatDate } from './shared/utils/date'
import TopPairsTab from './features/top-pairs/TopPairsTab'
import { useMarketTables } from './features/market/useMarketTables'
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
  ParamValue,
} from './entities/decision/types'
import './App.css'

const AUTO_REFRESH_LABEL = '60 с'

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
  const [tab, setTab] = useState<
    'decisions' | 'top_pairs' | 'signals' | 'backtests' | 'backtest_v2' | 'forward' | 'hpo'
  >('decisions')
  const market = useMarketTables({ tab, compareValues })
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
    forwardStatus,
    forwardLoading,
    forwardError,
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
    handleHpoRequestJsonChange,
    setHpoSearchSpace,
    fetchParamSpecs,
    handleParamValueChange,
    handleParamReset,
    handleBacktestRun,
    fetchForwardStatus,
    handleHpoRun,
  } = useBacktestForwardHpo({ tab, buildParamDefaults, collectParamRequest })

  const handleRefresh = useCallback(() => {
    fetchDecisionView()
    market.fetchAuxData()
  }, [fetchDecisionView, market.fetchAuxData])

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
    [formatDate, formatValue, getFieldLabel, getFieldTooltip],
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
              onSubmitDecisionAction={submitDecisionAction}
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
          {tab === 'top_pairs' ? (
            <TopPairsTab
              market={market}
              autoRefreshLabel={AUTO_REFRESH_LABEL}
              formatCellValue={formatCellValue}
              renderFieldLabel={renderFieldLabel}
              formatDate={formatDate}
              formatValue={formatValue}
            />
          ) : null}
          {tab === 'signals' ? (
            <SignalsTab
              market={market}
              autoRefreshLabel={AUTO_REFRESH_LABEL}
              formatCellValue={formatCellValue}
              renderFieldLabel={renderFieldLabel}
              formatDate={formatDate}
              formatValue={formatValue}
            />
          ) : null}
          {tab === 'backtests' ? (
            <BacktestsTab
              market={market}
              autoRefreshLabel={AUTO_REFRESH_LABEL}
              formatCellValue={formatCellValue}
              renderFieldLabel={renderFieldLabel}
              formatDate={formatDate}
              formatValue={formatValue}
            />
          ) : null}
          {tab === 'backtest_v2' ? (
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
          {tab === 'forward' ? (
            <ForwardTab
              forwardRunId={forwardRunId}
              onForwardRunIdChange={setForwardRunId}
              onFetchForwardStatus={fetchForwardStatus}
              forwardLoading={forwardLoading}
              forwardError={forwardError}
              forwardStatus={forwardStatus}
              formatValue={formatValue}
              renderFieldLabel={renderFieldLabel}
              formatCellValue={formatCellValue}
            />
          ) : null}
          {tab === 'hpo' ? (
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
        </Stack>
      </Container>
    </Box>
  )
}

export default App


