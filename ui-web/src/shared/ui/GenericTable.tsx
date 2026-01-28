import { Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material'
import type { ReactNode } from 'react'

export type GenericRow = Record<string, unknown>

type Props = {
  rows: GenericRow[]
  columns: string[]
  emptyLabel: string
  renderHeader: (column: string) => ReactNode
  renderCell: (row: GenericRow, column: string) => ReactNode
  getRowKey?: (row: GenericRow, index: number) => string
  maxHeight?: string | number
}

const defaultGetRowKey = (row: GenericRow, index: number) => {
  const candidate = row.id ?? row.pair_id ?? row.date ?? `row-${index}`
  return String(candidate)
}

const GenericTable = ({
  rows,
  columns,
  emptyLabel,
  renderHeader,
  renderCell,
  getRowKey = defaultGetRowKey,
  maxHeight = '60vh',
}: Props) => {
  if (!rows.length || !columns.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        {emptyLabel}
      </Typography>
    )
  }

  return (
    <TableContainer sx={{ maxHeight }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            {columns.map((column) => (
              <TableCell key={column}>{renderHeader(column)}</TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${getRowKey(row, index)}-${index}`}>
              {columns.map((column) => (
                <TableCell key={`${column}-${index}`}>{renderCell(row, column)}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

export default GenericTable
