import { Fragment, type ReactNode } from 'react'
import {
  Box,
  Button,
  Chip,
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
  Typography,
} from '@mui/material'
import SpreadChart from '../../SpreadChart'
import KeyValueGrid from '../../shared/ui/KeyValueGrid'
import type { MarketTablesState, MarketTab } from './useMarketTables'

const SIGNAL_MODEL_PRIMARY_KEYS = new Set([
  'orderbook_pass',
  'orderbook_stock_quote_available',
  'orderbook_fut_quote_available',
  'orderbook_stock_depth_available',
  'orderbook_fut_depth_available',
  'orderbook_data_warnings',
])

const PRETRADE_PRIMARY_GATE_KEYS = [
  'quote_pass',
  'stock_quote_pass',
  'fut_quote_pass',
  'stock_price_pass',
  'fut_price_pass',
  'spread_pass',
  'sync_pass',
  'stock_volume_pass',
  'fut_volume_pass',
]

const PRETRADE_PRIMARY_HIT_KEYS = [
  'required',
  'snapshots',
  'stock_quote_hits',
  'fut_quote_hits',
  'stock_price_hits',
  'fut_price_hits',
  'spread_hits',
  'sync_hits',
  'stock_volume_hits',
  'fut_volume_hits',
]

const PRETRADE_GATE_CHIPS = [
  { key: 'quote_pass', label: 'Котировки' },
  { key: 'stock_price_pass', label: 'Акция' },
  { key: 'fut_price_pass', label: 'Фьючерс' },
  { key: 'spread_pass', label: 'Спред' },
  { key: 'sync_pass', label: 'Синхронность' },
  { key: 'stock_volume_pass', label: 'Объём акции' },
  { key: 'fut_volume_pass', label: 'Объём фьючерса' },
] as const

const EXECUTION_SIDE_OPTIONS = [
  { value: '', label: 'Не выбрано' },
  { value: 'stock', label: 'Акция' },
  { value: 'future', label: 'Фьючерс' },
] as const

const toOrderedEntries = (
  payload: Record<string, unknown> | undefined,
  orderedKeys: string[],
  excludeKeys?: Set<string>,
) => {
  if (!payload) return []
  const entries = orderedKeys
    .filter((key) => key in payload)
    .map((key) => ({ key, value: payload[key] }))

  const seen = new Set(entries.map((entry) => entry.key))
  const rest = Object.entries(payload)
    .filter(([key]) => !seen.has(key))
    .filter(([key]) => (excludeKeys ? !excludeKeys.has(key) : true))
    .map(([key, value]) => ({ key, value }))

  return [...entries, ...rest]
}

const gateChipColor = (value: unknown): 'success' | 'error' | 'default' => {
  if (value === true) return 'success'
  if (value === false) return 'error'
  return 'default'
}

const gateChipStatus = (value: unknown) => {
  if (value === true) return 'OK'
  if (value === false) return 'FAIL'
  return 'N/A'
}


type Props = {
  tab: MarketTab
  market: MarketTablesState
  autoRefreshLabel: string
  formatCellValue: (value: unknown, column?: string) => string
  renderFieldLabel: (column: string) => ReactNode
  formatDate: (value?: string) => string
  formatValue: (value: unknown, column?: string) => string
}

const MarketTablesTab = ({
  tab,
  market,
  autoRefreshLabel,
  formatCellValue,
  renderFieldLabel,
  formatDate,
  formatValue,
}: Props) => (
  <>
    <Paper sx={{ p: 2 }}>
      <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
        <TextField
          label="Быстрый поиск"
          size="small"
          value={market.tableFilter}
          onChange={(event) => market.setTableFilter(event.target.value)}
          sx={{ minWidth: 240 }}
        />
        {tab === 'top_pairs' || tab === 'signals' ? (
          <>
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>Акция</InputLabel>
              <Select
                label="Акция"
                value={market.tableStockFilter}
                onChange={(event) => market.setTableStockFilter(event.target.value)}
              >
                <MenuItem value="">Все</MenuItem>
                {market.tableStockOptions.map((item) => (
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
                value={market.tableFutureFilter}
                onChange={(event) => market.setTableFutureFilter(event.target.value)}
              >
                <MenuItem value="">Все</MenuItem>
                {market.tableFutureOptions.map((item) => (
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
                value={market.tableSignalFilter}
                onChange={(event) => market.setTableSignalFilter(event.target.value)}
              >
                <MenuItem value="">Все</MenuItem>
                {market.tableSignalOptions.map((item) => (
                  <MenuItem key={item} value={item}>
                    {formatValue(item, tab === 'signals' ? 'signal_action_effective' : 'signal_action')}
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
              value={market.topPairsLimit}
              onChange={(event) => market.setTopPairsLimit(event.target.value)}
              disabled={market.topPairsAll}
              sx={{ minWidth: 140 }}
            />
            <FormControlLabel
              control={
                <Switch
                  checked={market.topPairsAll}
                  onChange={(event) => market.setTopPairsAll(event.target.checked)}
                />
              }
              label="Все пары"
            />
          </>
        ) : null}
        <Button
          variant="outlined"
          onClick={market.refreshAuxData}
          disabled={market.auxLoading || market.recomputeLoading}
        >
          {market.recomputeLoading ? 'Пересчёт...' : 'Обновить'}
        </Button>
        <FormControlLabel
          control={
            <Switch
              checked={market.autoRefresh}
              onChange={(event) => market.setAutoRefresh(event.target.checked)}
            />
          }
          label={`Автообновление (${autoRefreshLabel})`}
        />
        <Typography variant="body2" color="text.secondary">
          {market.auxLastUpdated
            ? `Обновлено ${formatDate(market.auxLastUpdated)}`
            : 'Обновлено: н/д'}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {market.refreshStatus?.last_success_at
            ? `Пересчитано ${formatDate(market.refreshStatus.last_success_at)}`
            : 'Пересчитано: н/д'}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {market.auxLoading ? 'Загрузка...' : `${market.sortedTableRows.length} строк`}
        </Typography>
        {!market.auxLoading ? (
          <Typography variant="body2" color="text.secondary">
            Топ пар: {market.topPairs.length} · Сигналы: {market.signals.length} · Бэктесты:{' '}
            {market.backtests.length}
          </Typography>
        ) : null}
        {market.auxError ? (
          <Typography variant="body2" color="error">
            {market.auxError}
          </Typography>
        ) : null}
        {market.recomputeError ? (
          <Typography variant="body2" color="error">
            {market.recomputeError}
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
            value={market.historyFrom}
            onChange={(event) => market.setHistoryFrom(event.target.value)}
            sx={{ minWidth: 200 }}
          />
          <TextField
            label="История по (ГГГГ-ММ-ДД)"
            size="small"
            value={market.historyTo}
            onChange={(event) => market.setHistoryTo(event.target.value)}
            sx={{ minWidth: 200 }}
          />
          <Button variant="outlined" onClick={market.fetchSignalHistory} disabled={market.historyLoading}>
            Загрузить историю
          </Button>
          {market.historyLoading ? (
            <Typography variant="body2" color="text.secondary">
              Загрузка истории...
            </Typography>
          ) : null}
          {market.historyError ? (
            <Typography variant="body2" color="error">
              {market.historyError}
            </Typography>
          ) : null}
        </Stack>
      </Paper>
    ) : null}
    {tab === 'signals' && market.openSignalRows.length ? (
      <Paper sx={{ p: 2 }}>
        <Typography variant="subtitle2" fontWeight={600}>
          Открытые позиции ({market.openSignalRows.length})
        </Typography>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
          {market.openSignalRows.map((row) => {
            const stock = row.stock ? String(row.stock) : ''
            const future = row.future ? String(row.future) : ''
            const pairLabel = stock && future ? `${stock}/${future}` : 'Пара'
            const action = String(
              row.signal_action_effective ?? row.signal_action ?? 'hold_open',
            ).toLowerCase()
            return (
              <Chip
                key={`${stock}-${future}-${String(row.timestamp ?? '')}`}
                color="warning"
                variant="outlined"
                label={`${pairLabel}: ${formatValue(action, 'signal_action_effective')}`}
              />
            )
          })}
        </Stack>
      </Paper>
    ) : null}
    <Paper sx={{ p: 2 }}>
      <TableContainer sx={{ maxHeight: '68vh' }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              {market.showPairDetails ? <TableCell /> : null}
              {market.tableVisibleColumns.map((column) => (
                <TableCell
                  key={column}
                  sortDirection={market.tableSortKey === column ? market.tableSortDirection : false}
                >
                  <TableSortLabel
                    active={market.tableSortKey === column}
                    direction={market.tableSortKey === column ? market.tableSortDirection : 'asc'}
                    onClick={() => market.handleTableSort(column)}
                  >
                    {renderFieldLabel(column)}
                  </TableSortLabel>
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {market.sortedTableRows.map((row) => {
              const pairKey =
                (row.stock && row.future ? `${row.stock}-${row.future}` : null) ?? String(row.id)
              const isExpanded = market.expandedRowKey === pairKey
              const buildEntries = (keys: string[], stripVisible = true) => {
                const entries = keys
                  .map((key) => ({
                    key,
                    value: row[key],
                  }))
                  .filter((field) => field.value !== null && field.value !== undefined)
                return stripVisible ? market.stripDuplicates(entries) : entries
              }
              const snapshotEntries = buildEntries(market.snapshotFields)
              const overviewEntries = buildEntries(market.overviewFields)
              const alphaEntries = buildEntries(market.alphaFields)
              const liquidityEntries = buildEntries(market.liquidityFields)
              const executionEntries = buildEntries(market.executionFields)
              const signalContextEntries = buildEntries(market.signalContextFields, false)
              const signalEntryEntries = buildEntries(market.signalEntryFields, false)
              const signalRiskEntries = buildEntries(market.signalRiskFields, false)
              const signalForecastEntries = buildEntries(market.signalForecastFields, false)
              const signalModelEntries = buildEntries(market.signalModelFields, false)
              const signalModelPrimaryEntries = signalModelEntries.filter((entry) =>
                SIGNAL_MODEL_PRIMARY_KEYS.has(entry.key),
              )
              const signalModelTechnicalEntries = signalModelEntries.filter(
                (entry) => !SIGNAL_MODEL_PRIMARY_KEYS.has(entry.key),
              )
              const hasSignalPlanData =
                signalEntryEntries.length > 0 ||
                signalRiskEntries.length > 0 ||
                signalForecastEntries.length > 0
              const showOverviewTab = tab !== 'signals' || overviewEntries.length > 0
              const showAlphaTab = tab !== 'signals' || alphaEntries.length > 0
              const showLiquidityTab = tab !== 'signals' || liquidityEntries.length > 0
              const isEntrySignal = market.isEntrySignal(row)
              const pretradePayload = market.pretradeChecks[pairKey]
              const pretradeSummaryEntries = pretradePayload
                ? [
                    {
                      key: 'pretrade_status',
                      value: pretradePayload.status,
                    },
                    {
                      key: 'ready_to_place',
                      value: pretradePayload.ready_to_place,
                    },
                    {
                      key: 'manual_confirm_required',
                      value: pretradePayload.manual_confirm_required,
                    },
                    {
                      key: 'pretrade_checked_at',
                      value: market.pretradeCheckedAt[pairKey],
                    },
                  ]
                : []
              const pretradeGatePayload = pretradePayload?.gates as Record<string, unknown> | undefined
              const pretradeHitPayload = pretradePayload?.hits as Record<string, unknown> | undefined
              const primaryGateEntries = toOrderedEntries(pretradeGatePayload, PRETRADE_PRIMARY_GATE_KEYS)
              const primaryGateKeys = new Set(primaryGateEntries.map((entry) => entry.key))
              const diagnosticGateEntries = Object.entries(pretradeGatePayload ?? {})
                .filter(([key]) => !primaryGateKeys.has(key))
                .map(([key, value]) => ({ key, value }))
              const hitEntries = toOrderedEntries(pretradeHitPayload, PRETRADE_PRIMARY_HIT_KEYS)
              const pretradeGateMap = new Map(primaryGateEntries.map((entry) => [entry.key, entry.value]))
              const isPretradePending =
                isEntrySignal &&
                market.pretradeLoadingKey === pairKey
              const isPretradeMissing =
                isEntrySignal &&
                !pretradePayload &&
                !market.pretradeError[pairKey] &&
                !isPretradePending
              const isPretradeBlocked =
                isEntrySignal &&
                Boolean(pretradePayload) &&
                !pretradePayload.ready_to_place
              const signalActionRaw = String(row.signal_action ?? '').toLowerCase()
              const signalActionEffective =
                String(row.signal_action_effective ?? '').toLowerCase() ||
                (!isEntrySignal
                  ? signalActionRaw || 'hold'
                  : isPretradePending || isPretradeMissing || Boolean(market.pretradeError[pairKey])
                    ? 'check_pretrade'
                    : isPretradeBlocked
                      ? 'hold_pretrade'
                      : 'enter')
              const effectiveSignalEntries = [
                { key: 'signal_action_effective', value: signalActionEffective },
                ...(pretradePayload?.status ? [{ key: 'pretrade_status', value: pretradePayload.status }] : []),
                ...(market.pretradeCheckedAt[pairKey]
                  ? [{ key: 'pretrade_checked_at', value: market.pretradeCheckedAt[pairKey] }]
                  : []),
              ]
              const executionBlockedReason = !isEntrySignal
                ? ''
                : signalActionEffective === 'hold_pretrade'
                  ? 'Вход заблокирован pre-trade ограничениями.'
                  : signalActionEffective === 'check_pretrade'
                    ? 'Сначала подтвердите pre-trade проверку.'
                    : ''
              const isOpenPosition =
                row.position_open === true || String(row.position_state ?? '').toLowerCase() === 'open'

              return (
                <Fragment key={pairKey}>
                  <TableRow
                    sx={
                      tab === 'signals' && isOpenPosition
                        ? { backgroundColor: 'rgba(255, 183, 77, 0.12)' }
                        : undefined
                    }
                  >
                    {market.showPairDetails ? (
                      <TableCell>
                        <Button size="small" onClick={() => market.handleToggleDetails(row)}>
                          {isExpanded ? 'Скрыть' : 'Детали'}
                        </Button>
                      </TableCell>
                    ) : null}
                    {market.tableVisibleColumns.map((column) => (
                      <TableCell key={column}>{formatCellValue(row[column], column)}</TableCell>
                    ))}
                  </TableRow>
                  {market.showPairDetails && isExpanded ? (
                    <TableRow>
                      <TableCell colSpan={market.tableVisibleColumns.length + 1}>
                        <Stack spacing={2}>
                          <Box>
                            <Typography variant="subtitle2" fontWeight={600}>
                              Снимок
                            </Typography>
                            <KeyValueGrid
                              entries={snapshotEntries}
                              renderLabel={renderFieldLabel}
                              renderValue={(value, key) => formatCellValue(value, key)}
                            />
                          </Box>
                          <Box>
                            <Tabs value={market.detailTab} onChange={(_, value) => market.setDetailTab(value)}>
                              {tab === 'signals' ? <Tab label="Сигнал" value="execution" /> : null}
                              {showOverviewTab ? <Tab label="Обзор" value="overview" /> : null}
                              {showAlphaTab ? <Tab label="Альфа" value="alpha" /> : null}
                              {showLiquidityTab ? <Tab label="Ликвидность" value="liquidity" /> : null}
                              {tab !== 'signals' ? <Tab label="Исполнение" value="execution" /> : null}
                            </Tabs>
                            {market.detailTab === 'overview' && overviewEntries.length ? (
                              <KeyValueGrid
                                entries={overviewEntries}
                                renderLabel={renderFieldLabel}
                                renderValue={(value, key) => formatCellValue(value, key)}
                              />
                            ) : null}
                            {market.detailTab === 'alpha' && alphaEntries.length ? (
                              <KeyValueGrid
                                entries={alphaEntries}
                                renderLabel={renderFieldLabel}
                                renderValue={(value, key) => formatCellValue(value, key)}
                              />
                            ) : null}
                            {market.detailTab === 'liquidity' && liquidityEntries.length ? (
                              <KeyValueGrid
                                entries={liquidityEntries}
                                renderLabel={renderFieldLabel}
                                renderValue={(value, key) => formatCellValue(value, key)}
                              />
                            ) : null}
                            {market.detailTab === 'execution' ? (
                              tab === 'signals' ? (
                                <Stack spacing={2} sx={{ mt: 1 }}>
                                  <Typography variant="body2" color="text.secondary">
                                    Покрытие полей: вход {signalEntryEntries.length}/
                                    {market.signalEntryFields.length}, риск {signalRiskEntries.length}/
                                    {market.signalRiskFields.length}, прогноз {signalForecastEntries.length}/
                                    {market.signalForecastFields.length}
                                  </Typography>
                                  <Box>
                                    <Typography variant="subtitle2" fontWeight={600}>
                                      Контекст сигнала
                                    </Typography>
                                    <KeyValueGrid
                                      entries={signalContextEntries}
                                      renderLabel={renderFieldLabel}
                                      renderValue={(value, key) => formatCellValue(value, key)}
                                    />
                                  </Box>
                                  <Box>
                                    <Typography variant="subtitle2" fontWeight={600}>
                                      Итоговый сигнал
                                    </Typography>
                                    <KeyValueGrid
                                      entries={effectiveSignalEntries}
                                      renderLabel={renderFieldLabel}
                                      renderValue={(value, key) =>
                                        key === 'pretrade_checked_at'
                                          ? formatDate(typeof value === 'string' ? value : undefined)
                                          : formatCellValue(value, key)
                                      }
                                    />
                                    {isOpenPosition ? (
                                      <Chip
                                        size="small"
                                        color="warning"
                                        variant="outlined"
                                        label="Позиция открыта"
                                        sx={{ mt: 1 }}
                                      />
                                    ) : null}
                                    {isEntrySignal ? (
                                      primaryGateEntries.length ? (
                                        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
                                          {PRETRADE_GATE_CHIPS.map((chip) => (
                                            <Chip
                                              key={chip.key}
                                              size="small"
                                              variant="outlined"
                                              color={gateChipColor(pretradeGateMap.get(chip.key))}
                                              label={`${chip.label}: ${gateChipStatus(pretradeGateMap.get(chip.key))}`}
                                            />
                                          ))}
                                        </Stack>
                                      ) : (
                                        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                                          Выполните pre-trade проверку, чтобы подтвердить исполнимость входа.
                                        </Typography>
                                      )
                                    ) : null}
                                  </Box>
                                  {signalEntryEntries.length ? (
                                    <Box>
                                      <Typography variant="subtitle2" fontWeight={600}>
                                        План входа
                                      </Typography>
                                      <KeyValueGrid
                                        entries={signalEntryEntries}
                                        renderLabel={renderFieldLabel}
                                        renderValue={(value, key) => formatCellValue(value, key)}
                                      />
                                    </Box>
                                  ) : null}
                                  {signalRiskEntries.length ? (
                                    <Box>
                                      <Typography variant="subtitle2" fontWeight={600}>
                                        Риск и стоп-уровни
                                      </Typography>
                                      <KeyValueGrid
                                        entries={signalRiskEntries}
                                        renderLabel={renderFieldLabel}
                                        renderValue={(value, key) => formatCellValue(value, key)}
                                      />
                                    </Box>
                                  ) : null}
                                  {signalForecastEntries.length ? (
                                    <Box>
                                      <Typography variant="subtitle2" fontWeight={600}>
                                        Прогноз выхода
                                      </Typography>
                                      <KeyValueGrid
                                        entries={signalForecastEntries}
                                        renderLabel={renderFieldLabel}
                                        renderValue={(value, key) => formatCellValue(value, key)}
                                      />
                                    </Box>
                                  ) : null}
                                  {!hasSignalPlanData ? (
                                    <Typography variant="body2" color="text.secondary">
                                      Плановые поля (`entry_*`, `tp/sl`, `forecast_*`) не переданы API в этом запуске.
                                    </Typography>
                                  ) : null}
                                  {signalModelPrimaryEntries.length ? (
                                    <Box>
                                      <Typography variant="subtitle2" fontWeight={600}>
                                        Проверки исполнимости
                                      </Typography>
                                      <KeyValueGrid
                                        entries={signalModelPrimaryEntries}
                                        renderLabel={renderFieldLabel}
                                        renderValue={(value, key) => formatCellValue(value, key)}
                                      />
                                    </Box>
                                  ) : null}
                                  {signalModelTechnicalEntries.length ? (
                                    <Box component="details" sx={{ mt: 1 }}>
                                      <Box component="summary" sx={{ cursor: 'pointer' }}>
                                        <Typography variant="subtitle2" fontWeight={600} component="span">
                                          Технические метрики модели
                                        </Typography>
                                      </Box>
                                      <KeyValueGrid
                                        entries={signalModelTechnicalEntries}
                                        renderLabel={renderFieldLabel}
                                        renderValue={(value, key) => formatCellValue(value, key)}
                                      />
                                    </Box>
                                  ) : null}
                                </Stack>
                              ) : executionEntries.length ? (
                                <KeyValueGrid
                                  entries={executionEntries}
                                  renderLabel={renderFieldLabel}
                                  renderValue={(value, key) => formatCellValue(value, key)}
                                />
                              ) : (
                                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                                  Нет данных по исполнению.
                                </Typography>
                              )
                            ) : null}
                          </Box>
                          <Box>
                            <Typography variant="subtitle2" fontWeight={600}>
                              График спреда (жизнь контракта)
                            </Typography>
                            {market.spreadError[pairKey] ? (
                              <Typography variant="body2" color="error">
                                {market.spreadError[pairKey]}
                              </Typography>
                            ) : null}
                            {market.spreadLoadingKey === pairKey ? (
                              <Typography variant="body2" color="text.secondary">
                                Загрузка серии спреда...
                              </Typography>
                            ) : (
                              <SpreadChart data={market.spreadSeries[pairKey] ?? []} />
                            )}
                          </Box>
                          {tab === 'signals' ? (
                            <Box>
                              <Typography variant="subtitle2" fontWeight={600}>
                                Pre-trade проверка (ISS)
                              </Typography>
                              {!isEntrySignal ? (
                                <Typography variant="body2" color="text.secondary">
                                  Проверка применима только к входным сигналам.
                                </Typography>
                              ) : (
                                <Stack spacing={1} sx={{ mt: 1 }}>
                                  <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                                    <Button
                                      variant="outlined"
                                      onClick={() => market.handleRefreshPretrade(row)}
                                      disabled={market.pretradeLoadingKey === pairKey}
                                    >
                                      {market.pretradeLoadingKey === pairKey
                                        ? 'Проверка...'
                                        : 'Обновить pre-trade'}
                                    </Button>
                                  </Stack>
                                  {market.pretradeError[pairKey] ? (
                                    <Typography variant="body2" color="error">
                                      {market.pretradeError[pairKey]}
                                    </Typography>
                                  ) : null}
                                  {pretradePayload ? (
                                    <>
                                      <KeyValueGrid
                                        entries={pretradeSummaryEntries}
                                        renderLabel={renderFieldLabel}
                                        renderValue={(value, key) =>
                                          key === 'pretrade_checked_at'
                                            ? formatDate(typeof value === 'string' ? value : undefined)
                                            : formatCellValue(value, key)
                                        }
                                      />
                                      <Box>
                                        <Typography variant="subtitle2" fontWeight={600}>
                                          Решение по pre-trade
                                        </Typography>
                                        {pretradePayload.reasons?.length ? (
                                          <Typography variant="body2" color="error.main">
                                            {pretradePayload.reasons
                                              .map((reason) => formatValue(reason, 'pretrade_reasons'))
                                              .join(', ')}
                                          </Typography>
                                        ) : (
                                          <Typography variant="body2" color="text.secondary">
                                            Блокирующие причины не обнаружены.
                                          </Typography>
                                        )}
                                      </Box>
                                      {pretradePayload.order_price_bands ? (
                                        <Box>
                                          <Typography variant="subtitle2" fontWeight={600}>
                                            Коридор цен заявки
                                          </Typography>
                                          <KeyValueGrid
                                            payload={
                                              pretradePayload.order_price_bands as Record<string, unknown>
                                            }
                                            renderLabel={renderFieldLabel}
                                            renderValue={(value, key) => formatCellValue(value, key)}
                                          />
                                        </Box>
                                      ) : null}
                                      {pretradePayload.volume_requirements ? (
                                        <Box>
                                          <Typography variant="subtitle2" fontWeight={600}>
                                            Объём и размер заявки
                                          </Typography>
                                          <KeyValueGrid
                                            payload={
                                              pretradePayload.volume_requirements as Record<string, unknown>
                                            }
                                            renderLabel={renderFieldLabel}
                                            renderValue={(value, key) => formatCellValue(value, key)}
                                          />
                                        </Box>
                                      ) : null}
                                      {diagnosticGateEntries.length ||
                                      hitEntries.length ||
                                      pretradePayload.last_snapshot ||
                                      pretradePayload.params ? (
                                        <Box component="details" sx={{ mt: 1 }}>
                                          <Box component="summary" sx={{ cursor: 'pointer' }}>
                                            <Typography variant="subtitle2" fontWeight={600} component="span">
                                              Расширенная диагностика
                                            </Typography>
                                          </Box>
                                          <Stack spacing={1} sx={{ mt: 1 }}>
                                            {hitEntries.length ? (
                                              <Box>
                                                <Typography variant="subtitle2" fontWeight={600}>
                                                  Счётчики снапшотов
                                                </Typography>
                                                <KeyValueGrid
                                                  entries={hitEntries}
                                                  renderLabel={renderFieldLabel}
                                                  renderValue={(value, key) => formatCellValue(value, key)}
                                                />
                                              </Box>
                                            ) : null}
                                            {diagnosticGateEntries.length ? (
                                              <Box>
                                                <Typography variant="subtitle2" fontWeight={600}>
                                                  Дополнительные гейты
                                                </Typography>
                                                <KeyValueGrid
                                                  entries={diagnosticGateEntries}
                                                  renderLabel={renderFieldLabel}
                                                  renderValue={(value, key) => formatCellValue(value, key)}
                                                />
                                              </Box>
                                            ) : null}
                                            {pretradePayload.last_snapshot ? (
                                              <Box>
                                                <Typography variant="subtitle2" fontWeight={600}>
                                                  Последний снапшот ISS
                                                </Typography>
                                                <KeyValueGrid
                                                  payload={
                                                    pretradePayload.last_snapshot as Record<string, unknown>
                                                  }
                                                  renderLabel={renderFieldLabel}
                                                  renderValue={(value, key) => formatCellValue(value, key)}
                                                />
                                              </Box>
                                            ) : null}
                                            {pretradePayload.params ? (
                                              <Box>
                                                <Typography variant="subtitle2" fontWeight={600}>
                                                  Параметры проверки
                                                </Typography>
                                                <KeyValueGrid
                                                  payload={pretradePayload.params as Record<string, unknown>}
                                                  renderLabel={renderFieldLabel}
                                                  renderValue={(value, key) => formatCellValue(value, key)}
                                                />
                                              </Box>
                                            ) : null}
                                          </Stack>
                                        </Box>
                                      ) : null}
                                    </>
                                  ) : (
                                    <Typography variant="body2" color="text.secondary">
                                      Проверка ещё не выполнялась.
                                    </Typography>
                                  )}
                                </Stack>
                              )}
                              <Box sx={{ mt: 2 }}>
                              <Typography variant="subtitle2" fontWeight={600}>
                                Исполнить сигнал
                              </Typography>
                              {executionBlockedReason ? (
                                <Typography variant="body2" color="warning.main" sx={{ mt: 0.5 }}>
                                  {executionBlockedReason}
                                </Typography>
                              ) : null}
                              <Stack direction="row" spacing={2} flexWrap="wrap">
                                <TextField
                                  label="Цена"
                                  size="small"
                                  value={market.executionForm.price}
                                  onChange={(event) =>
                                    market.onExecutionFormFieldChange('price', event.target.value)
                                  }
                                  sx={{ minWidth: 140 }}
                                />
                                <TextField
                                  label="Кол-во"
                                  size="small"
                                  value={market.executionForm.quantity}
                                  onChange={(event) =>
                                    market.onExecutionFormFieldChange('quantity', event.target.value)
                                  }
                                  sx={{ minWidth: 120 }}
                                />
                                <FormControl size="small" sx={{ minWidth: 160 }}>
                                  <InputLabel>Нога сделки</InputLabel>
                                  <Select
                                    label="Нога сделки"
                                    value={market.executionForm.side}
                                    onChange={(event) =>
                                      market.onExecutionFormFieldChange(
                                        'side',
                                        String(event.target.value),
                                      )
                                    }
                                  >
                                    {EXECUTION_SIDE_OPTIONS.map((item) => (
                                      <MenuItem key={item.value || 'empty'} value={item.value}>
                                        {item.label}
                                      </MenuItem>
                                    ))}
                                  </Select>
                                </FormControl>
                                <TextField
                                  label="Комментарий"
                                  size="small"
                                  value={market.executionForm.note}
                                  onChange={(event) =>
                                    market.onExecutionFormFieldChange('note', event.target.value)
                                  }
                                  sx={{ minWidth: 240 }}
                                />
                                <Button
                                  variant="contained"
                                  onClick={() => market.handleExecuteSignal(row)}
                                  disabled={Boolean(executionBlockedReason)}
                                >
                                  Исполнить
                                </Button>
                              </Stack>
                              <Box sx={{ mt: 2 }}>
                                <Typography variant="subtitle2" fontWeight={600}>
                                  История исполнений
                                </Typography>
                                {market.executionError[pairKey] ? (
                                  <Typography variant="body2" color="error">
                                    {market.executionError[pairKey]}
                                  </Typography>
                                ) : null}
                                {market.executionLoadingKey === pairKey ? (
                                  <Typography variant="body2" color="text.secondary">
                                    Загрузка исполнений...
                                  </Typography>
                                ) : market.executionLogs[pairKey]?.length ? (
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
                                          'note',
                                        ].map((col) => (
                                          <TableCell key={col}>{renderFieldLabel(col)}</TableCell>
                                        ))}
                                      </TableRow>
                                    </TableHead>
                                    <TableBody>
                                      {market.executionLogs[pairKey].map((entry, index) => (
                                        <TableRow key={`${entry.timestamp}-${index}`}>
                                          <TableCell>{formatDate(entry.timestamp)}</TableCell>
                                          <TableCell>{formatValue(entry.action, 'action')}</TableCell>
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
      {!market.sortedTableRows.length ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          {tab === 'signals' && !market.auxLoading && market.signals.length === 0
            ? 'Пока нет активных сигналов. Откройте детали активной строки, чтобы исполнить.'
            : 'Нет строк по текущему фильтру.'}
        </Typography>
      ) : null}
    </Paper>
    {tab === 'signals' && market.signalHistory.length ? (
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
              ].map((col) => (
                <TableCell key={col}>{renderFieldLabel(col)}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {market.filteredSignalHistory.map((row, index) => (
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
        {!market.filteredSignalHistory.length ? (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            Нет строк истории по текущему фильтру.
          </Typography>
        ) : null}
      </Paper>
    ) : null}
  </>
)

export default MarketTablesTab
