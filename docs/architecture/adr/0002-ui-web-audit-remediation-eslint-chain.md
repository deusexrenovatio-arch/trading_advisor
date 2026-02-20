# 0002 UI Web Audit Remediation for ESLint Chain

## Status
Accepted

## Date
2026-02-20

## Context
`ui-web/package.json` and `ui-web/package-lock.json` were updated to remediate `npm audit` findings in the frontend toolchain.
The initial state contained high vulnerabilities in the ESLint/typescript-eslint transitive chain through `minimatch`.

## Decision
Adopt a minimal-risk dependency remediation for `ui-web`:
- keep ESLint on the compatible `9.x` line used by current plugins;
- upgrade `typescript-eslint` to `8.56.0`;
- force `minimatch` to `10.2.2` using `overrides` in `ui-web/package.json`.

## Consequences
- Pros:
  - removes `high/critical` findings from frontend dependency audit;
  - keeps existing lint config and plugin compatibility stable;
  - change scope is limited to dev-tooling dependencies.
- Cons:
  - moderate vulnerabilities remain in ESLint/AJV transitive dev dependencies;
  - full elimination requires upstream ecosystem changes or larger tooling migration.

## Alternatives Considered
1. Move to ESLint `10.x` immediately.
Rejected: peer incompatibility with `eslint-plugin-react-hooks` in current stack.
2. Leave dependencies unchanged and accept existing high findings.
Rejected: does not meet security remediation intent.
3. Replace ESLint stack with another linter immediately.
Rejected: too wide in scope for this hotfix.

## Validation and Rollout
- Commands:
  - `npm --prefix ui-web install`
  - `npm --prefix ui-web run lint`
  - `npm --prefix ui-web run build`
  - `npm --prefix ui-web audit --json`
  - `npm --prefix ui-web audit --omit=dev --json`
- Expected:
  - no `high/critical` vulnerabilities in full audit;
  - zero vulnerabilities in production dependencies (`--omit=dev`).
