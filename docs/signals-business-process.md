# Signals Tab Business Process (Stock/Futures Spread, ISS Delayed Mode)

## Purpose
Define an end-to-end operator process in `Signals` from entry decision to exit execution for two-leg stock/futures trades under ISS delayed data constraints.

## Scope
- Included:
  - Signal review and filtering in `Signals`
  - Pre-trade validation (`/api/pretrade/check`)
  - Manual execution logging (`/api/signals/execute`)
  - Position monitoring and exit handling
  - Audit trail in signal history and execution history
- Excluded:
  - Broker auto-routing and guaranteed fills
  - Real-time low-latency feed logic
  - Portfolio-level optimization across multiple open pairs

## Stakeholders
- Operator: reviews, decides, executes, and confirms both legs.
- Quant/Risk owner: defines thresholds and validates reasons.
- Engineering: guarantees API/UI consistency and traceability.

## Preconditions
- Fresh signal cycle exists (`signal_runs` + `signal_history` populated).
- Pair has strategy output fields (`signal_action`, `signal_metrics`).
- Operator has terminal access for mandatory manual quote confirmation.

## Runtime Model (Unified Minute-First)
- Active UI market tables (`Top pairs`, `Signals`, `Backtests`, `Spread series`) are served by unified minute replay runtime.
- Canonical execution in minute mode:
  - all common stock/future minutes inside day,
  - causal submit/fill windows (`signal_exec_lag_days`, `execution_lag_minutes`, `execution_max_wait_minutes`),
  - day cutoff (`signal_cutoff_before_day_end_minutes`),
  - split tolerance (`entry_stock_tolerance_pct`, `entry_future_tolerance_pct`, `entry_spread_tolerance_pct`) with fallback.
- `common_minute_anchor` is not used for minute execution (kept only for daily compatibility modes).
- `Signals refresh` uses unified runtime and persists run/history; legacy pipeline is fallback-only.

## Main Flow
| Stage | Operator Action | System Behavior | Record of Fact |
|---|---|---|---|
| 1. Discover | Open `Signals`, apply filters | Load active/history signals and compute `signal_action_effective` | `signal_history` rows visible in UI |
| 2. Candidate Review | Pick a pair with entry intent | Show entry corridors, risk levels, forecast horizon | `signal_metrics` fields (`entry_*`, `tp/sl_*`, `forecast_*`) |
| 3. Pre-trade Check | Trigger `Refresh pre-trade` if needed | Call `/api/pretrade/check`, evaluate two-leg gates, return `ready_to_place` | Pre-trade payload (`status`, `gates`, `hits`, `reasons`) |
| 4. Entry Decision | Compare app output with terminal quotes | Resolve effective action: `enter` or `hold_pretrade` or `check_pretrade` | Effective status in main `Signal` column |
| 5. Entry Execution | Submit both legs manually | Allow `Execute` only when entry is not pre-trade blocked | `signal_executions` rows with action `enter` |
| 6. Active Monitoring | Re-open details for open pair | Keep open pair visible in `Signals` and show risk/forecast/model checks/new updates | New `signal_history` rows per cycle + `signal_executions` open state |
| 7. Exit Trigger | React to `exit` signal and reason | Surface reason (`tp`, `sl`, `time`, `expiry`) and supporting metrics | Exit reason in `signal_reasons` / `signal_metrics` |
| 8. Exit Execution | Close both legs manually | Persist exit action and update actionable view | `signal_executions` rows with action `exit` |
| 9. Audit | Review full lifecycle for pair | Provide history of signals + executions for replay | `signal_history` + `signal_executions` |

## User Stories and Acceptance

### US-SIG-01 Review actionability before opening details
- As an operator, I want the top-level signal status to already include pre-trade constraints.
- Acceptance:
  - `Signal` column shows `enter`, `hold_pretrade`, `check_pretrade`, `hold_open`, or `exit`.
  - Entry rows without pre-trade payload are not shown as final `enter`.

### US-SIG-02 Validate two-leg entry readiness
- As an operator, I want deterministic pre-trade checks for both legs and spread consistency.
- Acceptance:
  - `/api/pretrade/check` returns `ready_to_place`, `gates`, `hits`, `reasons`.
  - Missing quote on either leg keeps entry blocked.
  - `manual_confirm_required` remains true in ISS delayed mode.

### US-SIG-03 Execute entry with traceability
- As an operator, I want each execution step captured for later audit.
- Acceptance:
  - Entry `Execute` writes a row to `signal_executions`.
  - Stored fields include pair, direction, action, price, quantity, side, order_id, note, timestamp.
  - For two-leg execution, both legs can be linked by one `order_id`; one-leg execution remains valid with a single row.

### US-SIG-04 Monitor open position until exit condition
- As an operator, I want clear transition from monitoring to exit-ready behavior.
- Acceptance:
  - If a pair has an open position (entered and not closed), it remains visible in `Signals` with explicit status `hold_open` until closure.
  - Ongoing refresh updates reasons/metrics in `signal_history`.
  - Exit rationale is visible in details and not hidden in raw payload only.

### US-SIG-05 Close position and complete lifecycle
- As an operator, I want clean closure with both-leg accountability.
- Acceptance:
  - Exit action is logged in `signal_executions`.
  - Pair is no longer shown as actionable `exit` after closure.

## Alternative and Exception Flows

### AF-01 Pre-trade endpoint unavailable (e.g., 404)
- Behavior:
  - Effective action for entry remains `check_pretrade`.
  - Entry execution is blocked until successful check.

### AF-02 Futures quote/depth missing in ISS snapshot
- Behavior:
  - Pre-trade returns reasons like `fut_quote_missing`.
  - Effective action may still allow entry in ISS manual-drive mode.
  - Futures diagnostics remain visible for manual terminal verification.

### AF-03 Snapshot desync or spread outside corridor
- Behavior:
  - Pre-trade returns `snapshot_unsynced` or `spread_out_of_band`.
  - Entry remains blocked.

### AF-04 One leg executed, second leg pending (operational risk)
- Current process:
  - Must be handled by operator procedure via execution notes and immediate follow-up action.
- Gap:
  - No automated unwind workflow in current `Signals` flow.

## Traceability Matrix
| Requirement | UI | API | Persistence | Evidence |
|---|---|---|---|---|
| Effective signal with pre-trade constraints | `signals` table `signal_action_effective` | `/api/signals/active`, `/api/pretrade/check` | `signal_history` + transient pre-trade cache in UI state | Visible status and details block |
| Two-leg pre-trade validation | `Pre-trade` panel | `/api/pretrade/check` | Not persisted server-side as a separate table | `status/gates/hits/reasons` payload |
| Entry execution logging | `Execute signal` form | `POST /api/signals/execute` | `signal_executions` | Execution history table |
| Exit reason transparency | Signal details (`Context`, `Risk`, `Forecast`) | `/api/signals/active`, `/api/signals/history` | `signal_history.metrics/reasons` | Reason codes (`tp/sl/time/expiry`) |
| Lifecycle auditability | History + details | `/api/signals/history`, `/api/signals/executions` | `signal_history` + `signal_executions` | Pair replay from first entry to final exit |

## MVP vs Next

### MVP (must keep)
- Effective signal status that includes pre-trade outcome.
- Deterministic pre-trade gate with explicit blocking and advisory reasons.
- Mandatory manual confirmation in ISS delayed mode.
- Entry/exit execution logging with pair-level history.

Implemented policy note:
- Current ISS mode uses stock-leg blocking gates for `ready_to_place`.
- Futures/spread/sync gates are computed as advisory diagnostics and do not block execution.

### Next (recommended)
- Automated leg-risk control when one leg fills and second does not.
- Exit-side pre-trade check symmetry (not only entry-side).
- Alerting channel for exit urgency and stale-data risk.
- Persisted pre-trade check snapshots for compliance-grade replay.

## Open Decisions
- Should pre-trade payload be persisted server-side for every check?
- Should exit action also be gated by dedicated two-leg executable corridor checks?

## Interim Results: 96-Scenario Intraday Sweep (2026-02-11)

Source files:
- `data/output/intraday_minute_sweep_summary.csv`
- `data/output/intraday_minute_sweep_pairs.csv`

Grid used:
- `execution_lag_minutes`: `15, 30`
- `execution_max_wait_minutes`: `30, 60, 120, 240`
- `entry_price_tolerance_pct`: `0.0015, 0.003, 0.005, 0.01`
- `signal_cutoff_before_day_end_minutes`: `0, 30, 60`

### 1) Highest annualized return in this grid
- Best by `avg_oper_mean`:
  - `lag30_wait120_tol0.001500_cut30`
  - `avg_oper_mean = 31.43%`
  - `unfilled_entry_rate_mean = 75.37%`
  - `forced_exit_rate_mean = 92.62%`
  - `trades_closed_total = 44`
- Conclusion: peak return in this sweep is strongly linked to poor executability (very high timeout-driven behavior).

### 2) Best executability in this grid
- Best by `unfilled + forced` objective:
  - `lag15_wait240_tol0.010000_cut0`
  - `avg_oper_mean = 18.37%`
  - `unfilled_entry_rate_mean = 13.17%`
  - `forced_exit_rate_mean = 23.47%`
  - `trades_closed_total = 56`
- Conclusion: this is the most practical candidate from the original 96-grid.

### 3) What performance depended on (from 96-scenario analysis)
- `entry_price_tolerance_pct` was the dominant factor for executability.
  - Correlation with objective (`unfilled + forced`): about `-0.916` (larger tolerance => fewer misses/forced exits).
- `signal_cutoff_before_day_end_minutes` had weak/unstable impact versus lag/wait/tolerance.
- `execution_max_wait_minutes`:
  - increasing wait generally reduced forced exits and unfilled entries;
  - but very long waits (`240`) tended to reduce average annualized return versus mid waits (`120`) in this specific grid.
- `execution_lag_minutes`:
  - `15` was better on average than `30` for both return and executability in this sweep.
- Highest `avg_oper_mean` scenarios were positively associated with higher forced/unfilled rates (selection/annualization artifact risk).

### 4) Interim strategy tuning decisions (to reduce unnecessary compute)
- For "realistic + efficient" runs, prioritize:
  - `entry_price_tolerance_pct` in `[0.01, 0.02]`
  - `execution_max_wait_minutes` in `[240, 360]` (next-stage sweep)
  - `execution_lag_minutes` in `{15, 30}`, with preference to `15` in ranking
  - keep `signal_cutoff_before_day_end_minutes = 0` unless a specific hypothesis is tested
- De-prioritize combinations with:
  - `entry_price_tolerance_pct <= 0.003` for production-like evaluation
  - objective `unfilled + forced > 1.0` (too timeout-heavy for practical deployment)

### 5) Current shortlist to carry forward
- Practical anchor from original 96-grid:
  - `lag15_wait240_tol0.010000_cut0`
- Secondary candidates from original 96-grid:
  - `lag15_wait120_tol0.010000_cut0`
  - `lag15_wait240_tol0.010000_cut30`
  - `lag15_wait240_tol0.010000_cut60`

## Interim Results: 25-Pair Validation With Cache + Median Metric (2026-02-11)

Source files:
- `data/output/top25_lag20_30_summary.csv`
- `data/output/top25_lag20_30_pairs.csv`
- `data/output/top25_lag20_30_robust_metrics.csv`
- `data/output/top25_lag20_vs_lag30_diff.csv`

### Scope and constraints
- Universe: 25 pairs from current `top_pairs.csv`.
- Tested lags: `20` and `30` minutes (`lag >= 20` operator constraint).
- Evaluation now includes robust metric:
  - `avg_oper_median_pairs` (median annual operational return across pairs),
  - plus `p25/p75`, `unfilled_mean_pairs`, `forced_mean_pairs`.
- Fast mode was used:
  - `--preload-cache-mode readonly`,
  - preload cache hits `25/25` for the 25-pair run.

### Key findings (median-focused)
- Highest median in this tested set:
  - `lag30_wait120_st0.003_ft0.003_spt0.003_cut30`
  - `median = 25.80%`, but `unfilled = 68.65%`, `forced = 83.34%` (not practical).
- Best median with practical executability (`objective <= 0.6`):
  - `lag30_wait360_st0.020_ft0.020_spt0.030_cut0`
  - `median = 19.59%`, `p25 = 13.34%`, `p75 = 27.41%`,
  - `unfilled = 27.93%`, `forced = 19.45%`, `trades_closed = 288`.
- Close alternative with lower `forced`:
  - `lag30_wait360_st0.020_ft0.025_spt0.030_cut0`
  - `median = 19.28%`, `unfilled = 27.87%`, `forced = 17.32%`, `trades_closed = 297`.

### Lag 20 vs lag 30 (same parameters)
- At `wait=240` and moderate tolerances (`st/ft` around `0.015..0.025`), `lag=20` improved median vs `lag=30` by about `+2.96..+3.90 p.p.` and slightly improved objective.
- At `wait=360` configurations, `lag=30` generally had better median than `lag=20`.
- `lag=20` often improved objective (lower `unfilled+forced`) because entries are reached earlier, but median return leadership depends on wait/tolerance regime.

### Interim decisions for next runs
- Keep two main practical candidates:
  - `lag30_wait360_st0.020_ft0.020_spt0.030_cut0` (median-first practical anchor),
  - `lag30_wait360_st0.020_ft0.025_spt0.030_cut0` (slightly lower median, better forced exits).
- Keep one lag-20 challenger for comparison:
  - `lag20_wait240_st0.015_ft0.015_spt0.020_cut0` (strong lag-20 median uplift in `wait=240` regime).
- Continue rejecting timeout-heavy profiles:
  - scenarios with `unfilled + forced > 1.0` are not considered operationally viable.

---

## ТЗ: Реалистичный расчет стратегии спреда (цель: годовой порог)

### 1. Цель
- Перейти от "идеальных" дневных оценок к исполнимой модели сделок.
- Считать результат так, чтобы учитывались:
  - задержка между сигналом и исполнением;
  - синхронность двух ног (акция + фьючерс);
  - ограничение по доступности цены в реальное время рынка.
- Критерий успеха: итоговая годовая доходность стратегии сравнивается с годовым порогом (`r_cb_annual` / `required_rate`) на операционной метрике "с учетом ожидания".

### 2. Область применения
- Модуль: spread carry alpha (cash-and-carry / reverse).
- Горизонт расчета: минимум `compute_lookback_days` из конфига.
- Режим цены: `price_source=common_minute_close`.
- Анкер общей минуты: `common_minute_anchor in {first,last}`.

### 3. Термины и определения
- `signal_day (D)`: день, в который стратегия сформировала `enter/exit` на данных, известных к концу D.
- `submit_day (D+1)`: первый допустимый день выставления/эмуляции приказа.
- `fill_ts`: фактический timestamp, где обе ноги могут быть исполнены в одной и той же минуте.
- `wait_time`: время ожидания от `submit_ts` до `fill_ts`.
- `operational annual return`: годовая доходность, где в знаменателе учитывается полный операционный цикл (включая ожидание исполнения).

### 4. Функциональные требования

#### 4.1 Генерация исполнимой дневной точки
- Для каждого торгового дня по паре:
  - загрузить 1m свечи акции и фьючерса;
  - пересечь timestamps;
  - выбрать общую точку по `common_minute_anchor`:
    - `first` -> первая общая минута;
    - `last` -> последняя общая минута.
- Если общих минут нет, день помечается как `no_common_minute` и не участвует в сигнальном расчете.

#### 4.2 Каузальность сигналов
- Сигнал дня D строится только по данным `<= D`.
- Исполнение в день D запрещено.
- Минимально допустимое исполнение: следующий торговый день (`D+1`).

#### 4.3 Модель исполнения входа/выхода
- Для каждого сигнала (entry/exit) на `signal_day=D`:
  - `submit_ts = open(submit_day) + lag_minutes`;
  - окно поиска исполнения: `[submit_ts, submit_ts + max_wait_minutes]`;
  - исполнение возможно только на общей минуте обеих ног;
  - для исполнения проверяются условия:
    - цена в допустимом коридоре (`entry_price_tolerance_pct` для входа, аналогичный коридор для выхода);
    - ликвидность/валидность котировок (если включены соответствующие гейты).
- Если в окне нет исполнения:
  - `entry`: статус `entry_unfilled`, сигнал закрывается как пропущенный;
  - `exit`: статус `exit_unfilled`, применяется аварийная политика закрытия (см. 4.6).

#### 4.4 Знак доходности спреда (обязательно)
- Для `cash_and_carry`:  
  `pnl_spread_pct = exit_spread_pct_exec - entry_spread_pct_exec`.
- Для `reverse`:  
  `pnl_spread_pct = entry_spread_pct_exec - exit_spread_pct_exec`.
- Любые UI/tooltip/экспортные поля обязаны использовать ту же формулу.

#### 4.5 Доходность и годовой порог
- Для каждой завершенной сделки считать минимум две метрики:
  - `trade_return_pct_net`: net доходность сделки;
  - `trade_return_annual_operational`:  
    `trade_return_pct_net / tau_operational`,  
    где `tau_operational = (exit_fill_ts - entry_signal_ts) / year_basis`.
- Дополнительно хранить `trade_return_annual_fill_to_fill` для аналитики, но целевым KPI считать `trade_return_annual_operational`.
- Гейт цели:
  - `annual_target_pass = trade_return_annual_operational >= annual_target_threshold`;
  - `annual_target_threshold` берется из `r_cb_annual` (или явного override).

#### 4.6 Аварийное закрытие при `exit_unfilled`
- Обязательная политика (конфигурируемая):
  - `force_exit_policy=next_anchor` (по умолчанию) -> закрыть на следующей доступной общей минуте/анкере;
  - `force_exit_policy=market_worse` -> закрыть по ухудшенной цене с штрафом `force_exit_penalty_bps`.
- В отчете фиксировать `exit_forced=true` и причину.

### 5. Нефункциональные требования (скорость и масштаб)
- Производительность:
  - кэшировать минутные данные по инструменту/дню;
  - кэшировать пересечения общих минут по паре/дню;
  - избегать повторного пересчета истории, пересчитывать инкрементально последние N дней.
- Архитектура расчета:
  - этап 1 (batch/vectorized): подготовка исполнимых дневных точек;
  - этап 2 (event-driven): пошаговый replay сигналов и fills с задержками;
  - этап 3: агрегация KPI и отчетов.
- Целевой SLA расчета (для контроля):
  - Universe до 200 пар, горизонт 120 дней -> не более 5 минут на стандартной dev-машине.

### 6. Контракты данных (добавить/обновить поля)
- На уровне сделки/цикла:
  - `entry_signal_day`, `entry_submit_ts`, `entry_fill_ts`, `entry_wait_minutes`;
  - `exit_signal_day`, `exit_submit_ts`, `exit_fill_ts`, `exit_wait_minutes`;
  - `entry_fill_status`, `exit_fill_status`, `exit_forced`, `unfilled_reason`;
  - `trade_return_pct_net`;
  - `trade_return_annual_fill_to_fill`;
  - `trade_return_annual_operational`;
  - `annual_target_threshold`, `annual_target_pass`.
- На уровне агрегата:
  - `avg_trade_return_annual_operational_recent`;
  - `share_target_pass`;
  - `unfilled_entry_rate`, `unfilled_exit_rate`, `forced_exit_rate`.

### 7. Критерии приемки
- Каузальность:
  - тест доказывает, что для каждого входа/выхода `fill_day > signal_day`.
- Синхронность ног:
  - тест доказывает, что entry/exit fill используют общий timestamp обеих ног.
- Корректность знака PnL:
  - unit tests для `cash_and_carry` и `reverse`.
- Целевая метрика:
  - годовой порог проверяется по `trade_return_annual_operational`, а не по "идеальной" fill-to-fill.
- Устойчивость:
  - сценарии `entry_unfilled`, `exit_unfilled`, `forced_exit` покрыты тестами.
- Производительность:
  - smoke benchmark не хуже целевого SLA из раздела 5.

### 8. Этапы имплементации
1. Закрепить конфиг и контракт полей (без изменения стратегии).
2. Вынести отдельный execution-replay слой (D+1, lag, wait window, fill statuses).
3. Переключить расчет KPI на `annual_operational` как primary target.
4. Добавить аварийное закрытие и метрики качества исполнения.
5. Обновить UI/API (Top Pairs, Signals, Spread Series) новыми полями и пояснениями.
6. Добавить unit/integration/regression тесты и benchmark-smoke.

### 9. Ограничения и допущения
- ISS delayed режим не гарантирует реальный стакан/очередь, поэтому модель исполнения является консервативной аппроксимацией.
- При отсутствии live-depth контроль исполнимости опирается на общую минуту и ценовой коридор.
- Для production-routing с брокером потребуется отдельный модуль ордеров и фактических fills.
