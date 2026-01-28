import { Box } from '@mui/material'

type Props = {
  payload: unknown
}

const JsonBlock = ({ payload }: Props) => (
  <Box
    component="pre"
    sx={{
      margin: 0,
      padding: 1.5,
      borderRadius: 1,
      backgroundColor: '#0b1020',
      color: '#e2e8f0',
      fontSize: '12px',
      overflow: 'auto',
    }}
  >
    {JSON.stringify(payload, null, 2)}
  </Box>
)

export default JsonBlock
