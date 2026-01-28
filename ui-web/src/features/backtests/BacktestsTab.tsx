import MarketTablesTab from '../market/MarketTablesTab'
import type { MarketTablesState } from '../market/useMarketTables'

type Props = {
  market: MarketTablesState
  autoRefreshLabel: string
  formatCellValue: (value: unknown, column?: string) => string
  renderFieldLabel: (column: string) => string
  formatDate: (value?: string) => string
  formatValue: (value: unknown, column?: string) => string
}

const BacktestsTab = ({
  market,
  autoRefreshLabel,
  formatCellValue,
  renderFieldLabel,
  formatDate,
  formatValue,
}: Props) => (
  <MarketTablesTab
    tab="backtests"
    market={market}
    autoRefreshLabel={autoRefreshLabel}
    formatCellValue={formatCellValue}
    renderFieldLabel={renderFieldLabel}
    formatDate={formatDate}
    formatValue={formatValue}
  />
)

export default BacktestsTab
