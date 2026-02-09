import MarketTablesTab from '../market/MarketTablesTab'
import type { ReactNode } from 'react'
import type { MarketTablesState } from '../market/useMarketTables'

type Props = {
  market: MarketTablesState
  autoRefreshLabel: string
  formatCellValue: (value: unknown, column?: string) => string
  renderFieldLabel: (column: string) => ReactNode
  formatDate: (value?: string) => string
  formatValue: (value: unknown, column?: string) => string
}

const TopPairsTab = ({
  market,
  autoRefreshLabel,
  formatCellValue,
  renderFieldLabel,
  formatDate,
  formatValue,
}: Props) => (
  <MarketTablesTab
    tab="top_pairs"
    market={market}
    autoRefreshLabel={autoRefreshLabel}
    formatCellValue={formatCellValue}
    renderFieldLabel={renderFieldLabel}
    formatDate={formatDate}
    formatValue={formatValue}
  />
)

export default TopPairsTab
