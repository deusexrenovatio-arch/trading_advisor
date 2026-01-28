import { Tooltip } from '@mui/material'
import type { ReactNode } from 'react'
import { getFieldLabel, getFieldTooltip } from '../utils/field'

export const renderFieldLabel = (key: string, labelOverride?: string): ReactNode => {
  const label = labelOverride ?? getFieldLabel(key)
  const tooltip = getFieldTooltip(key)
  if (!tooltip) return label
  return (
    <Tooltip title={tooltip} arrow placement="top">
      <span>{label}</span>
    </Tooltip>
  )
}
