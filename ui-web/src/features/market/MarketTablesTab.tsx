import { Fragment } from 'react'
import {
  Box,
  Button,
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


type Props = {
  tab: MarketTab
  market: MarketTablesState
  autoRefreshLabel: string
  formatCellValue: (value: unknown, column?: string) => string
  renderFieldLabel: (column: string) => string
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
              const snapshotEntries = market.stripDuplicates(
                market.snapshotFields
                  .map((key) => ({
                    key,
                    value: row[key],
                  }))
                  .filter((field) => field.value !== null && field.value !== undefined),
              )
              const overviewEntries = market.stripDuplicates(
                market.overviewFields
                  .map((key) => ({
                    key,
                    value: row[key],
                  }))
                  .filter((field) => field.value !== null && field.value !== undefined),
              )
              const alphaEntries = market.stripDuplicates(
                market.alphaFields
                  .map((key) => ({
                    key,
                    value: row[key],
                  }))
                  .filter((field) => field.value !== null && field.value !== undefined),
              )
              const liquidityEntries = market.stripDuplicates(
                market.liquidityFields
                  .map((key) => ({
                    key,
                    value: row[key],
                  }))
                  .filter((field) => field.value !== null && field.value !== undefined),
              )
              const executionEntries = market.stripDuplicates(
                market.executionFields
                  .map((key) => ({
                    key,
                    value: row[key],
                  }))
                  .filter((field) => field.value !== null && field.value !== undefined),
              )

              return (
                <Fragment key={pairKey}>
                  <TableRow>
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
                              <Tab label="Обзор" value="overview" />
                              <Tab label="Альфа" value="alpha" />
                              <Tab label="Ликвидность" value="liquidity" />
                              <Tab label="Исполнение" value="execution" />
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
                            {market.detailTab === 'execution' && executionEntries.length ? (
                              <KeyValueGrid
                                entries={executionEntries}
                                renderLabel={renderFieldLabel}
                                renderValue={(value, key) => formatCellValue(value, key)}
                              />
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
                                Исполнить сигнал
                              </Typography>
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
                                <TextField
                                  label="Сторона"
                                  size="small"
                                  value={market.executionForm.side}
                                  onChange={(event) =>
                                    market.onExecutionFormFieldChange('side', event.target.value)
                                  }
                                  sx={{ minWidth: 120 }}
                                />
                                <TextField
                                  label="Статус"
                                  size="small"
                                  value={market.executionForm.status}
                                  onChange={(event) =>
                                    market.onExecutionFormFieldChange('status', event.target.value)
                                  }
                                  sx={{ minWidth: 120 }}
                                />
                                <TextField
                                  label="Комментарий"
                                  size="small"
                                  value={market.executionForm.note}
                                  onChange={(event) =>
                                    market.onExecutionFormFieldChange('note', event.target.value)
                                  }
                                  sx={{ minWidth: 240 }}
                                />
                                <Button variant="contained" onClick={() => market.handleExecuteSignal(row)}>
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
                                          'status',
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
