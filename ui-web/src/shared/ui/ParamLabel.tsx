import { Box, Tooltip } from '@mui/material'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'

type Props = {
  label: string
  tooltip?: string
}

const ParamLabel = ({ label, tooltip }: Props) => (
  <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
    <span>{label}</span>
    {tooltip ? (
      <Tooltip title={tooltip} arrow placement="top">
        <InfoOutlinedIcon fontSize="inherit" sx={{ color: 'text.secondary' }} />
      </Tooltip>
    ) : null}
  </Box>
)

export default ParamLabel
