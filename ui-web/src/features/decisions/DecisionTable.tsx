import { Paper } from '@mui/material'
import {
  DataGrid,
  type GridColDef,
  type GridRowParams,
  GridToolbar,
} from '@mui/x-data-grid'
import { ruRU } from '@mui/x-data-grid/locales'
import type { DecisionView } from '../../entities/decision/types'

type Props = {
  decisionRows: DecisionView[]
  decisionColumns: GridColDef[]
  loading: boolean
  onRowClick: (params: GridRowParams) => void
}

const DecisionTable = ({ decisionRows, decisionColumns, loading, onRowClick }: Props) => (
  <Paper sx={{ flex: 2, p: 2 }}>
    <DataGrid
      rows={decisionRows}
      columns={decisionColumns}
      loading={loading}
      onRowClick={onRowClick}
      disableRowSelectionOnClick
      pageSizeOptions={[10, 25, 50, 100]}
      initialState={{
        pagination: { paginationModel: { pageSize: 10, page: 0 } },
      }}
      slots={{ toolbar: GridToolbar }}
      slotProps={{ toolbar: { showQuickFilter: false } }}
      localeText={ruRU.components.MuiDataGrid.defaultProps.localeText}
      sx={{ height: '68vh' }}
    />
  </Paper>
)

export default DecisionTable
