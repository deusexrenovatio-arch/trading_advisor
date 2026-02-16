import { Box, Button, Stack, Typography } from '@mui/material'
import type { ReactNode } from 'react'
import type { PretradeCheckResult } from '../../../entities/decision/types'
import KeyValueGrid from '../../../shared/ui/KeyValueGrid'

type Entry = {
  key: string
  value: unknown
}

type Props = {
  isEntrySignal: boolean
  pretradeLoading: boolean
  pretradeError?: string
  pretradePayload?: PretradeCheckResult
  pretradeSummaryEntries: Entry[]
  hitEntries: Entry[]
  diagnosticGateEntries: Entry[]
  pretradeCheckedAt?: string
  onRefreshPretrade: () => void
  renderFieldLabel: (column: string) => ReactNode
  formatCellValue: (value: unknown, column?: string) => string
  formatDate: (value?: string) => string
  formatValue: (value: unknown, column?: string) => string
}

const PretradePanel = ({
  isEntrySignal,
  pretradeLoading,
  pretradeError,
  pretradePayload,
  pretradeSummaryEntries,
  hitEntries,
  diagnosticGateEntries,
  pretradeCheckedAt,
  onRefreshPretrade,
  renderFieldLabel,
  formatCellValue,
  formatDate,
  formatValue,
}: Props) => (
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
          <Button variant="outlined" onClick={onRefreshPretrade} disabled={pretradeLoading}>
            {pretradeLoading ? 'Проверка...' : 'Обновить pre-trade'}
          </Button>
          {pretradeCheckedAt ? (
            <Typography variant="body2" color="text.secondary">
              Последняя проверка: {formatDate(pretradeCheckedAt)}
            </Typography>
          ) : null}
        </Stack>
        {pretradeError ? (
          <Typography variant="body2" color="error">
            {pretradeError}
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
                  payload={pretradePayload.order_price_bands as Record<string, unknown>}
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
                  payload={pretradePayload.volume_requirements as Record<string, unknown>}
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
                        payload={pretradePayload.last_snapshot as Record<string, unknown>}
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
  </Box>
)

export default PretradePanel
