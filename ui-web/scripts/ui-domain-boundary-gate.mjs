import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const checks = [
  {
    file: 'src/features/market/signalViewModel.ts',
    required: [
      {
        pattern: /signal_action_effective:\s*backendEffectiveAction/,
        message:
          'signal_action_effective must come directly from backend payload in signalViewModel.ts',
      },
    ],
  },
  {
    file: 'src/features/market/useMarketTables.ts',
    forbidden: [
      {
        pattern: /lifecycleToSignalAction\s*\(/,
        message: 'UI must not derive signal status from lifecycle mapping',
      },
      {
        pattern: /row\.lifecycle_state/,
        message: 'UI must not compute effective signal status from lifecycle_state',
      },
      {
        pattern: /ready_to_place\s*\?\s*['"`]enter['"`]\s*:\s*['"`](hold_pretrade|check_pretrade)['"`]/,
        message: 'UI must not derive business statuses from pretrade readiness ternary logic',
      },
      {
        pattern: /pretrade\.(ready_to_place|status)\s*\?\s*SIGNAL_ACTION_ENTER/,
        message: 'UI must not derive business statuses from pretrade fields',
      },
    ],
  },
  {
    file: 'src/features/market/MarketTablesTab.tsx',
    forbidden: [
      {
        pattern: /isPretrade(Pending|Missing|Blocked)/,
        message: 'MarketTablesTab must not calculate pretrade-based business statuses',
      },
      {
        pattern: /ready_to_place\s*\?/,
        message: 'MarketTablesTab must not branch business statuses by ready_to_place',
      },
    ],
  },
]

const failures = []

for (const check of checks) {
  const filePath = resolve(process.cwd(), check.file)
  const source = readFileSync(filePath, 'utf-8')

  for (const rule of check.required ?? []) {
    if (!rule.pattern.test(source)) {
      failures.push(`${check.file}: ${rule.message}`)
    }
  }
  for (const rule of check.forbidden ?? []) {
    if (rule.pattern.test(source)) {
      failures.push(`${check.file}: ${rule.message}`)
    }
  }
}

if (failures.length > 0) {
  console.error('UI domain-boundary gate failed:')
  for (const failure of failures) {
    console.error(`- ${failure}`)
  }
  process.exit(1)
}

console.log('UI domain-boundary gate passed')
