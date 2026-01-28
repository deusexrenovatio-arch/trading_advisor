import {
  Box,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import type { ParameterSpec, ParamValue } from '../../entities/decision/types'
import {
  buildParamHelperText,
  compactJson,
  getParamDictEntries,
  getParamLabel,
  getParamOptionLabel,
  getParamTooltip,
  isJsonValueType,
  parseParamDictValue,
} from '../utils/params'
import ParamLabel from './ParamLabel'

type Props = {
  spec: ParameterSpec
  value: ParamValue
  onValueChange: (key: string, value: ParamValue) => void
}

const ParamInput = ({ spec, value, onValueChange }: Props) => {
  const label = getParamLabel(spec)
  const tooltip = getParamTooltip(spec)
  const helperText = buildParamHelperText(spec)
  const labelNode = <ParamLabel label={label} tooltip={tooltip} />
  const inputLabelProps = { sx: { pointerEvents: 'auto' } }

  if (spec.value_type === 'dict') {
    const dictValue = parseParamDictValue(value)
    const entries = getParamDictEntries(spec, dictValue)
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        <Typography variant="caption" fontWeight={600}>
          {labelNode}
        </Typography>
        {entries.length ? (
          <Stack spacing={1}>
            {entries.map((entry) => (
              <Stack key={entry.key} direction="row" spacing={1} alignItems="center">
                <Typography variant="body2" sx={{ minWidth: 160 }}>
                  {entry.label}
                </Typography>
                <TextField
                  size="small"
                  type="number"
                  value={
                    entry.value === null || entry.value === undefined
                      ? ''
                      : String(entry.value)
                  }
                  onChange={(event) => {
                    const nextValue = event.target.value
                    const next = { ...dictValue, [entry.key]: nextValue }
                    onValueChange(spec.key, next)
                  }}
                  inputProps={{ step: 'any' }}
                  sx={{ flex: 1 }}
                />
              </Stack>
            ))}
          </Stack>
        ) : (
          <Typography variant="body2" color="text.secondary">
            Нет значений.
          </Typography>
        )}
        {helperText ? (
          <Typography variant="caption" color="text.secondary">
            {helperText}
          </Typography>
        ) : null}
      </Box>
    )
  }

  if (spec.value_type === 'bool') {
    return (
      <Box>
        <FormControlLabel
          control={
            <Switch
              checked={Boolean(value)}
              onChange={(event) => onValueChange(spec.key, event.target.checked)}
            />
          }
          label={labelNode}
        />
        {helperText ? (
          <Typography variant="caption" color="text.secondary">
            {helperText}
          </Typography>
        ) : null}
      </Box>
    )
  }

  if (spec.options && spec.options.length) {
    const stringValue = typeof value === 'string' ? value : compactJson(value)
    return (
      <TextField
        select
        fullWidth
        size="small"
        label={labelNode}
        InputLabelProps={inputLabelProps}
        value={stringValue}
        onChange={(event) => onValueChange(spec.key, event.target.value)}
        helperText={helperText}
      >
        {spec.options.map((option) => (
          <MenuItem key={String(option)} value={String(option)}>
            {getParamOptionLabel(spec, option)}
          </MenuItem>
        ))}
      </TextField>
    )
  }

  const inputValue =
    typeof value === 'string' || typeof value === 'number'
      ? String(value)
      : value === undefined || value === null
        ? ''
        : compactJson(value)
  const multiline = isJsonValueType(spec.value_type) || spec.value_type === 'union'
  const inputType =
    spec.value_type === 'int' || spec.value_type === 'float' ? 'number' : 'text'
  const step = spec.value_type === 'int' ? '1' : 'any'

  return (
    <TextField
      fullWidth
      size="small"
      label={labelNode}
      InputLabelProps={inputLabelProps}
      value={inputValue}
      onChange={(event) => onValueChange(spec.key, event.target.value)}
      helperText={helperText}
      type={inputType}
      multiline={multiline}
      minRows={multiline ? 3 : undefined}
      inputProps={inputType === 'number' ? { step } : undefined}
    />
  )
}

export default ParamInput
