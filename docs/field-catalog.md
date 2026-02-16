# Field Catalog (UI + Schemas)

## Parameter UX notes (Backtest v2)
- Human-friendly parameter labels + tooltips live in `ui-web/src/App.tsx` (`paramMeta`).
- Dict parameters are rendered as labeled rows (e.g., allocation weights per basket).
- See `docs/ui-ux-standards.md` for the full UI metadata approach.

## UI field catalog (App.tsx + SpreadChart)

Columns: key | label | format | units | digits | default display | schema paths | UI surfaces

| key | label | format | units | digits | default display | schema paths | UI surfaces |
| --- | --- | --- | --- | --- | --- | --- | --- |
| action | Действие |  |  |  | - / Yes-No (bool) | decision-log:aggregation.action, decision-log:decision.action, decision-log:execution_request.action, decision-log:operator_action.action, decision-log:risk_checks.[].action, decision-log:strategy_signals.[].action, decision-view:action, decision-view:aggregation_summary.action, decision-view:operator_action.action | Decisions table, Formatted via formatValue |
| action_note | Комментарий |  |  |  | - / Yes-No (bool) | - | - |
| allocation | Аллокация |  |  |  | - / Yes-No (bool) | - | - |
| avg_hold_days | Средн. дни удержания | days | days | 1 | - / Yes-No (bool) | - | Backtest v2: summary_metrics (dynamic) |
| avg_trade_return_annual_recent | Средн. годовая доходность (посл. 5) | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Alpha, Top pairs table |
| avg_trade_return_annual_operational_recent | Средн. годовая доходность (операц., посл. 5) | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Alpha, Top pairs table |
| share_target_pass | Доля прохода годового target | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Alpha, Top pairs table |
| unfilled_entry_rate | Доля неисполненных входов | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Alpha, Top pairs table |
| unfilled_exit_rate | Доля неисполненных выходов | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Alpha, Top pairs table |
| forced_exit_rate | Доля forced exit | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Alpha, Top pairs table |
| basket | Корзина |  |  |  | - / Yes-No (bool) | decision-log:basket_allocations.current.[].basket, decision-log:basket_allocations.delta.[].basket, decision-log:basket_allocations.target.[].basket, decision-view:basket_summary.current.[].basket, decision-view:basket_summary.delta.[].basket, decision-view:basket_summary.target.[].basket | Formatted via formatValue |
| basket_weight | Вес корзины, % | percent | % | 2 | - / Yes-No (bool) | decision-log:basket_allocations.current.[].weight, decision-view:basket_summary.current.[].weight | Formatted via formatValue |
| break_even_points | Безубыток, пунктов |  |  | 2 | - / Yes-No (bool) | decision-log:cost_model.break_even_points, decision-view:cost_summary.break_even_points | - |
| break_even_ticks | Безубыток, тиков |  |  | 2 | - / Yes-No (bool) | decision-log:cost_model.break_even_ticks, decision-view:cost_summary.break_even_ticks | - |
| cagr | CAGR, % год. | percent | % | 2 | - / Yes-No (bool) | decision-log:backtest_metrics.cagr, decision-view:backtest_metrics.cagr | Backtest v2: summary_metrics (dynamic) |
| capital_base | База капитала, ₽ | currency | RUB | 2 | - / Yes-No (bool) | - | - |
| cash | Кэш |  |  | 0 | - / Yes-No (bool) | - | Backtest v2: equity curve |
| code | Код |  |  |  | - / Yes-No (bool) | - | - |
| confidence | Достоверность | percent | % | 2 | - / Yes-No (bool) | decision-log:facts.[].confidence, decision-log:proposal.confidence, decision-log:strategies.[].signals.[].confidence, decision-log:strategy_signals.[].confidence | Formatted via formatValue |
| cost_round_trip | Стоимость round-trip | currency | RUB | 2 | - / Yes-No (bool) | decision-log:cost_model.round_trip_cost, decision-view:cost_summary.round_trip_cost | Decisions table, Formatted via formatValue |
| costs_hold | Издержки удержания, ₽ | currency | RUB | 2 | - / Yes-No (bool) | - | - |
| created_at | Время |  |  |  | - / Yes-No (bool) | decision-log:created_at, decision-log:operator_action.created_at, decision-view:created_at, decision-view:operator_action.created_at | Decisions table |
| cycle_id | Активный цикл |  |  | 0 | - / Yes-No (bool) | - | - |
| cycle_return_pct | Доходность цикла, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| date | Дата |  |  |  | - / Yes-No (bool) | - | Backtest v2: equity curve, Spread series / chart |
| days_to_exit | Дней до выхода | days | days | 1 | - / Yes-No (bool) | - | Top pairs / Signals details: Liquidity |
| decision | Решение |  |  |  | - / Yes-No (bool) | - | Top pairs / Signals details: Execution, Top pairs table |
| decision_id | ID решения |  |  |  | - / Yes-No (bool) | decision-log:decision_id, decision-view:decision_id | Decisions table |
| decision_view_id | ID витрины |  |  |  | - / Yes-No (bool) | decision-log:decision_view_id, decision-view:decision_view_id | - |
| direction | Направление |  |  |  | - / Yes-No (bool) | decision-log:strategies.[].signals.[].direction | Backtest v2: trades, Formatted via formatValue |
| div_sum | div_sum |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| dollar_vol_fut | Денежный объём фьючерса |  |  | 0 | - / Yes-No (bool) | - | Top pairs / Signals details: Liquidity |
| dollar_vol_stock | Денежный объём акций |  |  | 0 | - / Yes-No (bool) | - | Top pairs / Signals details: Liquidity |
| drawdown | Просадка | percent | % | 2 | - / Yes-No (bool) | - | Backtest v2: equity curve |
| dte | DTE (дней до экспирации) | days | days | 0 | - / Yes-No (bool) | - | Top pairs / Signals details: Overview |
| entry_cycle | Цикл входа |  |  | 0 | - / Yes-No (bool) | - | - |
| entry_date | Дата входа |  |  |  | - / Yes-No (bool) | - | Backtest v2: trades |
| entry_flag | Вход |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| entry_price_fut | Цена входа (фьючерс) |  |  | 2 | - / Yes-No (bool) | - | Backtest v2: trades |
| entry_price_stock | Цена входа (акция) |  |  | 2 | - / Yes-No (bool) | - | Backtest v2: trades |
| entry_spread_exec_pct | Entry spread (exec), % | percent | % | 2 | - / Yes-No (bool) | - | - |
| entry_spread_pct_exec | Entry spread, % (exec) | percent | % | 2 | - / Yes-No (bool) | - | - |
| equity | Эквити |  |  | 0 | - / Yes-No (bool) | - | Backtest v2: equity curve |
| execution_status | Исполнение |  |  |  | - / Yes-No (bool) | decision-log:execution_request, decision-view:execution_status | Decisions table |
| exit_cycle | Цикл выхода |  |  | 0 | - / Yes-No (bool) | - | - |
| exit_date | Дата выхода |  |  |  | - / Yes-No (bool) | - | Backtest v2: trades |
| exit_flag | Выход |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| exit_price_fut | Цена выхода (фьючерс) |  |  | 2 | - / Yes-No (bool) | - | Backtest v2: trades |
| exit_price_stock | Цена выхода (акция) |  |  | 2 | - / Yes-No (bool) | - | Backtest v2: trades |
| exit_reason | Причина выхода |  |  |  | - / Yes-No (bool) | - | Backtest v2: trades |
| exit_spread_pct_exec | Exit spread, % (exec) | percent | % | 2 | - / Yes-No (bool) | - | - |
| expected_net_irr | Ожид. net IRR | percent | % | 2 | - / Yes-No (bool) | - | - |
| expected_return | Ожидаемая доходность, % год. | percent | % | 2 | - / Yes-No (bool) | decision-log:strategy_signals.[].expected_return | - |
| expiry | Экспирация |  |  |  | - / Yes-No (bool) | - | Top pairs / Signals details: Snapshot, Top pairs table |
| floor_pass | Floor-проход |  |  |  | - / Yes-No (bool) | - | Spread series / chart, Top pairs / Signals details: Overview |
| floor_pnl | Floor PnL, ₽ | currency | RUB | 2 | - / Yes-No (bool) | - | - |
| floor_rate_annual | Floor-ставка, % год. | percent | % | 2 | - / Yes-No (bool) | - | Signals table, Spread series / chart, Top pairs / Signals details: Overview, Top pairs table |
| fold_objectives | Метрики фолдов |  |  |  | - / Yes-No (bool) | - | HPO: leaderboard |
| future | Фьючерс |  |  |  | - / Yes-No (bool) | - | Signals table, Top pairs / Signals details: Snapshot, Top pairs table |
| future_mid | future_mid |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| future_price | Цена фьючерса |  |  | 2 | - / Yes-No (bool) | - | Formatted via formatValue, Top pairs / Signals details: Snapshot |
| future_secid | Фьючерс |  |  |  | - / Yes-No (bool) | - | Backtest v2: trades |
| general | Общие |  |  |  | - / Yes-No (bool) | - | - |
| half_life | Период полураспада |  |  | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Alpha |
| hit_rate | Доля прибыльных | percent | % | 2 | - / Yes-No (bool) | decision-log:backtest_metrics.hit_rate, decision-view:backtest_metrics.hit_rate | Backtest v2: summary_metrics (dynamic) |
| hold_days | Дней в позиции | days | days | 0 | - / Yes-No (bool) | - | Backtest v2: trades |
| implied_rate_net | Имплайд-ставка (net), % год. | percent | % | 2 | - / Yes-No (bool) | - | - |
| liquidity | Ликвидность |  |  |  | - / Yes-No (bool) | - | - |
| liquidity_pass | Ликвидность пройдена |  |  |  | - / Yes-No (bool) | - | Spread series / chart, Top pairs / Signals details: Overview |
| liquidity_score | Ликвидность, скор | percent | % | 1 | - / Yes-No (bool) | decision-log:strategy_signals.[].liquidity_score | - |
| mae | MAE |  |  | 4 | - / Yes-No (bool) | - | - |
| mae_q50 | MAE q50, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| mae_q75 | MAE q75, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| mae_q90 | MAE q90, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| max_drawdown | Макс. просадка | percent | % | 2 | - / Yes-No (bool) | decision-log:backtest_metrics.max_drawdown, decision-view:backtest_metrics.max_drawdown | Backtest v2: summary_metrics (dynamic), Decisions table, Formatted via formatValue |
| mean | Среднее |  |  | 4 | - / Yes-No (bool) | - | - |
| message | Сообщение |  |  |  | - / Yes-No (bool) | - | Forward/HPO status header |
| mfe_q50 | MFE q50, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| mfe_q75 | MFE q75, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| mfe_q90 | MFE q90, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| model_breaks | Сбои модели |  |  | 0 | - / Yes-No (bool) | - | - |
| news_severity | Новости |  |  |  | - / Yes-No (bool) | decision-view:news_severity | Decisions table, Formatted via formatValue |
| note | Комментарий |  |  |  | - / Yes-No (bool) | decision-log:operator_action.note, decision-view:operator_action.note | - |
| objective | Целевая метрика |  |  | 4 | - / Yes-No (bool) | - | HPO: leaderboard |
| open_interest | Открытый интерес |  |  | 0 | - / Yes-No (bool) | - | Top pairs / Signals details: Liquidity |
| p_hit_sl | P(достиж. SL) | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Alpha |
| p_hit_tp | P(достиж. TP) | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Alpha |
| pair_id | Пара |  |  |  | - / Yes-No (bool) | - | Backtest v2: trades |
| params | Параметры |  |  |  | - / Yes-No (bool) | decision-log:strategies.[].rules_evaluated.[].params | HPO: leaderboard |
| pnl | P&L |  |  | 2 | - / Yes-No (bool) | - | Backtest v2: trades |
| pnl_spread_pct | PnL по спреду, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| positions | Позиции |  |  | 0 | - / Yes-No (bool) | - | Backtest v2: equity curve |
| price | Цена |  |  | 2 | - / Yes-No (bool) | decision-log:portfolio_proposal.allocations.[].price | - |
| primary_instrument | Инструмент |  |  |  | - / Yes-No (bool) | decision-view:primary_instrument | Decisions table |
| proposal_type | Тип предложения |  |  |  | - / Yes-No (bool) | decision-log:proposal.type, decision-view:proposal_summary.type | Decisions table, Formatted via formatValue |
| pv_div | pv_div |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| quantity | Количество |  |  | 0 | - / Yes-No (bool) | decision-log:portfolio_proposal.allocations.[].quantity, decision-log:strategy_signals.[].intent_allocations.[].quantity, decision-view:allocations.[].quantity | Formatted via formatValue |
| quantity_fut | Кол-во (фьючерс) |  |  | 0 | - / Yes-No (bool) | - | Backtest v2: trades |
| quantity_stock | Кол-во (акция) |  |  | 0 | - / Yes-No (bool) | - | Backtest v2: trades |
| r_cb_annual | Ключевая ставка, % год. | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Overview |
| r_disc_annual | Ставка дисконт., % год. | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Overview |
| r_fund_annual | Ставка фондирования, % год. | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Overview |
| required_rate | Требуемая ставка, % год. | percent | % | 2 | - / Yes-No (bool) | - | - |
| risk_estimate | Оценка риска |  |  | 4 | - / Yes-No (bool) | decision-log:strategy_signals.[].risk_estimate | - |
| risk_state | Риск |  |  |  | - / Yes-No (bool) | decision-log:decision.risk_state, decision-view:risk_state | Decisions table, Formatted via formatValue |
| rtc_pct | Издержки RT, % | percent | % | 2 | - / Yes-No (bool) | - | Spread series / chart, Top pairs / Signals details: Snapshot, Top pairs table |
| run_id | ID прогона |  |  |  | - / Yes-No (bool) | decision-log:run_id | Forward/HPO status header |
| score_alpha | Alpha-скор | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Alpha |
| score_floor | Floor-скор | percent | % | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Overview, Top pairs table |
| share_alpha_exits | Доля alpha-выходов | percent | % | 2 | - / Yes-No (bool) | - | Backtest v2: summary_metrics (dynamic) |
| sharpe | Sharpe |  |  | 2 | - / Yes-No (bool) | decision-log:backtest_metrics.sharpe, decision-view:backtest_metrics.sharpe | Backtest v2: summary_metrics (dynamic) |
| side | Сторона |  |  |  | - / Yes-No (bool) | decision-log:portfolio_proposal.allocations.[].side, decision-log:strategy_signals.[].intent_allocations.[].side, decision-view:allocations.[].side | Formatted via formatValue |
| sigma_h | Сигма спреда (H) |  |  | 4 | - / Yes-No (bool) | - | Top pairs / Signals details: Alpha |
| signal_action | Сигнал |  |  |  | - / Yes-No (bool) | - | Formatted via formatValue, Signals table, Top pairs / Signals details: Execution, Top pairs table |
| signal_direction | Направление |  |  |  | - / Yes-No (bool) | - | Formatted via formatValue, Signals table, Top pairs / Signals details: Execution, Top pairs table |
| signal_metrics | Метрики сигнала |  |  |  | - / Yes-No (bool) | - | Top pairs / Signals details: Execution |
| signal_reasons | Причины сигнала |  |  |  | - / Yes-No (bool) | - | Top pairs / Signals details: Execution |
| signal_score | Скор сигнала | percent | % | 4 | - / Yes-No (bool) | - | Formatted via formatValue, Signals table, Top pairs / Signals details: Execution |
| signal_score_norm | Норм. скор сигнала |  |  | 3 | - / Yes-No (bool) | - | - |
| sl_net | SL net, % | percent | % | 2 | - / Yes-No (bool) | - | Spread series / chart |
| sl_pct | SL, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| snapshot_as_of | Снимок на |  |  |  | - / Yes-No (bool) | - | Top pairs / Signals details: Overview |
| spot | Спот |  |  | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Snapshot |
| spot_mid | spot_mid |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| spread | spread |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| spread_bps_fut | Спред фьючерса, б.п. | bps | bps | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Liquidity |
| spread_bps_stock | Спред акции, б.п. | bps | bps | 2 | - / Yes-No (bool) | - | Top pairs / Signals details: Liquidity |
| spread_entry_exec | Спред входа (exec) |  |  | 4 | - / Yes-No (bool) | - | - |
| spread_exit_exec | Спред выхода (exec) |  |  | 4 | - / Yes-No (bool) | - | - |
| spread_mid | Спред (mid) |  |  | 4 | - / Yes-No (bool) | - | Spread series / chart, Top pairs / Signals details: Snapshot |
| spread_pct | Спред, % | percent | % | 2 | - / Yes-No (bool) | - | Signals table, Spread series / chart, Top pairs / Signals details: Snapshot, Top pairs table |
| spread_pct_entry_exec | Спред входа, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| spread_pct_exit_exec | Спред выхода, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| spread_trend_z | Z-score тренда (abs) |  |  | 2 | - / Yes-No (bool) | - | - |
| spread_vol | Волатильность спреда |  |  | 4 | - / Yes-No (bool) | - | - |
| spread_vol_pct | Волатильность спреда, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| status | Статус |  |  |  | - / Yes-No (bool) | decision-log:execution_request.status, decision-log:operator_action.status, decision-view:execution_status.status, decision-view:operator_action.status | Formatted via formatValue, Forward/HPO status header |
| std | Стандартное отклонение |  |  | 4 | - / Yes-No (bool) | - | - |
| stock | Акция |  |  |  | - / Yes-No (bool) | - | Signals table, Top pairs / Signals details: Snapshot, Top pairs table |
| stock_name | Название акции |  |  |  | - / Yes-No (bool) | - | Top pairs / Signals details: Snapshot, Top pairs table |
| stock_secid | Акция |  |  |  | - / Yes-No (bool) | - | Backtest v2: trades |
| strategy | Стратегия |  |  |  | - / Yes-No (bool) | - | - |
| strategy_type | Стратегия |  |  |  | - / Yes-No (bool) | decision-log:strategies.[].type, decision-log:strategy_signals.[].strategy_type, decision-view:strategy_type | Decisions table, Formatted via formatValue |
| test | Тест |  |  |  | - / Yes-No (bool) | - | - |
| timestamp | Время |  |  |  | - / Yes-No (bool) | decision-log:facts.[].timestamp | Signals table |
| total_score | Итоговый скор | percent | % | 4 | - / Yes-No (bool) | - | Top pairs / Signals details: Snapshot, Top pairs table |
| tp_net | TP net, % | percent | % | 2 | - / Yes-No (bool) | - | Spread series / chart |
| tp_pct | TP, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| trade_cycle | Цикл сделки |  |  | 0 | - / Yes-No (bool) | - | Spread series / chart |
| trade_hold_days | Дней в сделке | days | days | 0 | - / Yes-No (bool) | - | Spread series / chart |
| trade_pnl_cash | P&L, руб. | currency | RUB | 2 | - / Yes-No (bool) | - | Spread series / chart |
| trade_return_annual | Годовая доходность (net), % | percent | % | 2 | - / Yes-No (bool) | - | Spread series / chart |
| trade_return_annual_fill_to_fill | Годовая доходность (fill-to-fill), % | percent | % | 2 | - / Yes-No (bool) | - | Spread series / chart |
| trade_return_annual_operational | Годовая доходность (операц.), % | percent | % | 2 | - / Yes-No (bool) | - | Spread series / chart |
| annual_target_threshold | Годовой порог target, % | percent | % | 2 | - / Yes-No (bool) | - | Spread series / chart |
| annual_target_pass | Target пройден |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| trade_return_pct | Доходность спреда, % | percent | % | 2 | - / Yes-No (bool) | - | Spread series / chart |
| trade_return_pct_net | Доходность (net), % | percent | % | 2 | - / Yes-No (bool) | - | Spread series / chart |
| entry_signal_day | День сигнала входа |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| entry_submit_ts | TS отправки входа |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| entry_fill_ts | TS исполнения входа |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| entry_wait_minutes | Ожидание входа, мин |  | min | 1 | - / Yes-No (bool) | - | Spread series / chart |
| exit_signal_day | День сигнала выхода |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| exit_submit_ts | TS отправки выхода |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| exit_fill_ts | TS исполнения выхода |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| exit_wait_minutes | Ожидание выхода, мин |  | min | 1 | - / Yes-No (bool) | - | Spread series / chart |
| entry_fill_status | Статус входа |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| exit_fill_status | Статус выхода |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| exit_forced | Forced exit |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| unfilled_reason | Причина неисполнения |  |  |  | - / Yes-No (bool) | - | Spread series / chart |
| trail_peak_spread_pct | Пик трейла, % | percent | % | 2 | - / Yes-No (bool) | - | - |
| trend | Тренд |  |  | 4 | - / Yes-No (bool) | - | - |
| trend_pos | Отклонение от тренда |  |  | 4 | - / Yes-No (bool) | - | - |
| trend_slope | Наклон тренда |  |  | 4 | - / Yes-No (bool) | - | - |
| trend_zscore | Z-score тренда |  |  | 2 | - / Yes-No (bool) | - | - |
| turnover | Оборачиваемость |  |  | 2 | - / Yes-No (bool) | decision-log:backtest_metrics.turnover, decision-view:backtest_metrics.turnover | Backtest v2: equity curve, Backtest v2: summary_metrics (dynamic) |
| window | Окно |  |  | 0 | - / Yes-No (bool) | - | - |
| z_entry | Z-entry |  |  | 2 | - / Yes-No (bool) | - | - |
| z_exit | Z-exit |  |  | 2 | - / Yes-No (bool) | - | - |
| zscore | Z-score |  |  | 2 | - / Yes-No (bool) | - | Spread series / chart |
| zscore_raw | Z-score (raw) |  |  | 2 | - / Yes-No (bool) | - | - |



Additional causal-replay keys: avg_trade_return_annual_operational_recent, share_target_pass, unfilled_entry_rate, unfilled_exit_rate, forced_exit_rate, trade_return_annual_fill_to_fill, trade_return_annual_operational, annual_target_threshold, annual_target_pass, entry_signal_day, entry_submit_ts, entry_fill_ts, entry_wait_minutes, exit_signal_day, exit_submit_ts, exit_fill_ts, exit_wait_minutes, entry_fill_status, exit_fill_status, exit_forced, unfilled_reason

## UI keys without schema mapping (likely other APIs / derived)

action_note, allocation, avg_hold_days, avg_trade_return_annual_recent, capital_base, cash, code, costs_hold, cycle_id, cycle_return_pct, date, days_to_exit, decision, div_sum, dollar_vol_fut, dollar_vol_stock, drawdown, dte, entry_cycle, entry_date, entry_flag, entry_price_fut, entry_price_stock, entry_spread_exec_pct, entry_spread_pct_exec, equity, exit_cycle, exit_date, exit_flag, exit_price_fut, exit_price_stock, exit_reason, exit_spread_pct_exec, expected_net_irr, expiry, floor_pass, floor_pnl, floor_rate_annual, fold_objectives, future, future_mid, future_price, future_secid, general, half_life, hold_days, implied_rate_net, liquidity, liquidity_pass, mae, mae_q50, mae_q75, mae_q90, mean, message, mfe_q50, mfe_q75, mfe_q90, model_breaks, objective, open_interest, p_hit_sl, p_hit_tp, pair_id, pnl, pnl_spread_pct, positions, pv_div, quantity_fut, quantity_stock, r_cb_annual, r_disc_annual, r_fund_annual, required_rate, rtc_pct, score_alpha, score_floor, share_alpha_exits, sigma_h, signal_action, signal_direction, signal_metrics, signal_reasons, signal_score, signal_score_norm, sl_net, sl_pct, snapshot_as_of, spot, spot_mid, spread, spread_bps_fut, spread_bps_stock, spread_entry_exec, spread_exit_exec, spread_mid, spread_pct, spread_pct_entry_exec, spread_pct_exit_exec, spread_trend_z, spread_vol, spread_vol_pct, std, stock, stock_name, stock_secid, strategy, test, total_score, tp_net, tp_pct, trade_cycle, trade_hold_days, trade_pnl_cash, trade_return_annual, trade_return_pct, trade_return_pct_net, trail_peak_spread_pct, trend, trend_pos, trend_slope, trend_zscore, window, z_entry, z_exit, zscore, zscore_raw


## Dynamic field groups (rendered via key/value grids)

- Backtest v2 summary_metrics: dynamic metrics shown in "???????? ???????" (example keys: cagr, sharpe, max_drawdown, hit_rate, turnover, share_alpha_exits, avg_hold_days).
- Backtest v2 resolved_config: full JSON of run config (keys mirror params/specs).
- Forward status: last_equity, last_trade, last_alert, state, run_meta (JSON objects, keys vary per run).
- Signals: signal_metrics (object) and signal_reasons (array). signal_metrics typically include spread_pct_entry_exec, spread_pct_exit_exec, tp_net, sl_net, dte, hold_days, pnl_spread_pct, zscore, zscore_raw, spread_vol, trend_pos, trend_slope, trend_zscore, implied_rate_net, required_rate, entry_spread_pct_min, entry_spread_pct_max, tp_spread_pct_level, sl_spread_pct_level, forecast_exit_days, forecast_exit_date.
- Decision log facts: facts[].{label,value,category,source,confidence} shown in details panel.


## Schema inventory: decision-view.schema.json

Columns: path | type | required | enum | description

| path | type | required | enum | description |
| --- | --- | --- | --- | --- |
| schema_version | string | yes |  |  |
| decision_view_id | string | yes |  |  |
| decision_id | string | yes |  | Reference to decision_log.decision_id. |
| created_at | string | yes |  |  |
| strategy_type | string | yes | fundamental,speculative,arbitrage,mixed |  |
| primary_instrument | string | yes |  |  |
| action | string | yes | approve,reject,hold |  |
| risk_state | string | yes | green,yellow,red |  |
| risk_summary | string |  |  |  |
| news_severity | string |  | low,medium,high,critical |  |
| cost_summary.round_trip_cost | number | yes |  |  |
| cost_summary.break_even_ticks | number | yes |  |  |
| cost_summary.break_even_points | number |  |  |  |
| key_features.[].name | string | yes |  |  |
| key_features.[].value | ['number', 'string', 'boolean'] | yes |  |  |
| key_features.[].units | string |  |  |  |
| allocations.[].instrument | string | yes |  |  |
| allocations.[].side | string | yes | long,short,flat |  |
| allocations.[].target_weight | number |  |  |  |
| allocations.[].quantity | number |  |  |  |
| backtest_metrics.cagr | number |  |  |  |
| backtest_metrics.max_drawdown | number |  |  |  |
| backtest_metrics.sharpe | number |  |  |  |
| backtest_metrics.hit_rate | number |  |  |  |
| backtest_metrics.turnover | number |  |  |  |
| aggregation_summary.action | string |  | enter,exit,hold |  |
| aggregation_summary.score | number |  |  |  |
| aggregation_summary.strategies.[] | string |  |  |  |
| aggregation_summary.blocked_strategies.[] | string |  |  |  |
| proposal_summary.type | string |  | rebalance,confirm |  |
| proposal_summary.cadence | string |  |  |  |
| proposal_summary.effective_date | string |  |  |  |
| proposal_summary.summary | string |  |  |  |
| basket_summary.current.[].basket | string | yes | fundamental,speculative,arbitrage |  |
| basket_summary.current.[].weight | number | yes |  |  |
| basket_summary.target.[].basket | string | yes | fundamental,speculative,arbitrage |  |
| basket_summary.target.[].weight | number | yes |  |  |
| basket_summary.delta.[].basket | string | yes | fundamental,speculative,arbitrage |  |
| basket_summary.delta.[].weight | number | yes |  |  |
| operator_action.action | string |  | approve,reject |  |
| operator_action.status | string |  |  |  |
| operator_action.actor | string |  |  |  |
| operator_action.note | string |  |  |  |
| operator_action.created_at | string |  |  |  |
| execution_status.status | string |  |  |  |
| execution_status.requested_at | string |  |  |  |
| execution_status.executed_at | string |  |  |  |
| links.decision_log | string | yes |  |  |
| links.input_snapshots.[] | string |  |  |  |


## Schema inventory: decision-log.schema.json

Columns: path | type | required | enum | description

| path | type | required | enum | description |
| --- | --- | --- | --- | --- |
| schema_version | string | yes |  | Semantic version of this schema. |
| decision_id | string | yes |  | Stable ID for traceability (UUID recommended). |
| created_at | string | yes |  |  |
| run_id | string |  |  | Pipeline run identifier. |
| environment.mode | string | yes | live,paper,backtest |  |
| environment.venue | string | yes |  | Trading venue/broker identifier. |
| environment.timezone | string | yes |  |  |
| input_snapshots.[].source | string | yes | MOEX_ISS,QUIK,NEWS,OTHER |  |
| input_snapshots.[].snapshot_id | string | yes |  | Stable snapshot identifier. |
| input_snapshots.[].as_of | string | yes |  |  |
| input_snapshots.[].hash | string | yes |  | Content hash for reproducibility. |
| input_snapshots.[].uri | string |  |  |  |
| input_snapshots.[].query | string |  |  |  |
| input_snapshots.[].is_cached | boolean |  |  |  |
| feature_set.feature_version | string | yes |  |  |
| feature_set.features.[].name | string | yes |  |  |
| feature_set.features.[].value | ['number', 'string', 'boolean'] | yes |  |  |
| feature_set.features.[].units | string |  |  |  |
| feature_set.features.[].source | string |  |  |  |
| feature_set.snapshot_ids.[] | string |  |  |  |
| strategies.[].name | string | yes |  |  |
| strategies.[].type | string | yes | fundamental,speculative,arbitrage |  |
| strategies.[].enabled | boolean | yes |  |  |
| strategies.[].signals.[].name | string | yes |  |  |
| strategies.[].signals.[].value | number | yes |  |  |
| strategies.[].signals.[].direction | string | yes | long,short,neutral |  |
| strategies.[].signals.[].confidence | number |  |  |  |
| strategies.[].signals.[].horizon | string |  |  |  |
| strategies.[].signals.[].units | string |  |  |  |
| strategies.[].rules_evaluated.[].id | string | yes |  |  |
| strategies.[].rules_evaluated.[].description | string |  |  |  |
| strategies.[].rules_evaluated.[].result | boolean | yes |  |  |
| strategies.[].rules_evaluated.[].severity | string |  | info,warn,block |  |
| strategies.[].rules_evaluated.[].params | object |  |  |  |
| strategies.[].notes | string |  |  |  |
| strategy_signals.[].strategy_id | string | yes |  |  |
| strategy_signals.[].strategy_type | string | yes | fundamental,speculative,arbitrage |  |
| strategy_signals.[].cadence | string | yes |  |  |
| strategy_signals.[].horizon | string | yes |  |  |
| strategy_signals.[].action | string | yes | enter,exit,hold |  |
| strategy_signals.[].confidence | number | yes |  |  |
| strategy_signals.[].expected_return | number |  |  |  |
| strategy_signals.[].risk_estimate | number |  |  |  |
| strategy_signals.[].liquidity_score | number |  |  |  |
| strategy_signals.[].instruments.[] | string |  |  |  |
| strategy_signals.[].intent_allocations.[].instrument | string | yes |  |  |
| strategy_signals.[].intent_allocations.[].side | string | yes | long,short,flat |  |
| strategy_signals.[].intent_allocations.[].target_weight | number |  |  |  |
| strategy_signals.[].intent_allocations.[].quantity | number |  |  |  |
| strategy_signals.[].rules_evaluated.[].rule_id | string | yes |  |  |
| strategy_signals.[].rules_evaluated.[].result | boolean | yes |  |  |
| strategy_signals.[].rules_evaluated.[].severity | string |  | info,warn,block |  |
| strategy_signals.[].rules_evaluated.[].description | string |  |  |  |
| strategy_signals.[].warnings.[] | string |  |  |  |
| strategy_signals.[].metadata | object |  |  |  |
| aggregation.action | string |  | enter,exit,hold |  |
| aggregation.score | number |  |  |  |
| aggregation.weights.fundamental | number |  |  |  |
| aggregation.weights.speculative | number |  |  |  |
| aggregation.weights.arbitrage | number |  |  |  |
| aggregation.used_strategies.[] | string |  |  |  |
| aggregation.blocked_strategies.[] | string |  |  |  |
| aggregation.reasons.[] | string |  |  |  |
| aggregation.warnings.[] | string |  |  |  |
| proposal.type | string |  | rebalance,confirm |  |
| proposal.cadence | string |  |  |  |
| proposal.effective_date | string |  |  |  |
| proposal.summary | string |  |  |  |
| proposal.confidence | number |  |  |  |
| basket_allocations.current.[].basket | string | yes | fundamental,speculative,arbitrage |  |
| basket_allocations.current.[].weight | number | yes |  |  |
| basket_allocations.target.[].basket | string | yes | fundamental,speculative,arbitrage |  |
| basket_allocations.target.[].weight | number | yes |  |  |
| basket_allocations.delta.[].basket | string | yes | fundamental,speculative,arbitrage |  |
| basket_allocations.delta.[].weight | number | yes |  |  |
| facts.[].category | string | yes |  |  |
| facts.[].label | string | yes |  |  |
| facts.[].value | ['number', 'string', 'boolean'] | yes |  |  |
| facts.[].units | string |  |  |  |
| facts.[].source | string |  |  |  |
| facts.[].confidence | number |  |  |  |
| facts.[].timestamp | string |  |  |  |
| operator_action.action | string |  | approve,reject |  |
| operator_action.status | string |  | recorded,revoked |  |
| operator_action.actor | string |  |  |  |
| operator_action.note | string |  |  |  |
| operator_action.created_at | string |  |  |  |
| execution_request.request_id | string |  |  |  |
| execution_request.action | string |  | approve,reject |  |
| execution_request.status | string |  | queued,sent,failed,succeeded,canceled |  |
| execution_request.requested_at | string |  |  |  |
| execution_request.executed_at | string |  |  |  |
| execution_request.error | string |  |  |  |
| news_context.severity | string |  | low,medium,high,critical |  |
| news_context.headline_count | integer |  |  |  |
| news_context.summary | string |  |  |  |
| portfolio_proposal.allocations.[].instrument | string | yes |  |  |
| portfolio_proposal.allocations.[].side | string | yes | long,short,flat |  |
| portfolio_proposal.allocations.[].target_weight | number |  |  |  |
| portfolio_proposal.allocations.[].quantity | number |  |  |  |
| portfolio_proposal.allocations.[].price | number |  |  |  |
| portfolio_proposal.allocations.[].rationale | string |  |  |  |
| risk_checks.[].id | string | yes |  |  |
| risk_checks.[].description | string |  |  |  |
| risk_checks.[].limit | ['number', 'string'] |  |  |  |
| risk_checks.[].value | ['number', 'string'] |  |  |  |
| risk_checks.[].unit | string |  |  |  |
| risk_checks.[].passed | boolean | yes |  |  |
| risk_checks.[].action | string |  | allow,reduce,block |  |
| cost_model.fee_side | number | yes |  |  |
| cost_model.slippage_ticks | number |  |  |  |
| cost_model.spread_ticks | number |  |  |  |
| cost_model.round_trip_cost | number | yes |  |  |
| cost_model.break_even_ticks | number | yes |  |  |
| cost_model.break_even_points | number |  |  |  |
| cost_model.tax_rate | number |  |  |  |
| cost_model.after_tax_pnl_estimate | number |  |  |  |
| backtest_metrics.cagr | number |  |  |  |
| backtest_metrics.max_drawdown | number |  |  |  |
| backtest_metrics.sharpe | number |  |  |  |
| backtest_metrics.hit_rate | number |  |  |  |
| backtest_metrics.turnover | number |  |  |  |
| decision.action | string | yes | approve,reject,hold |  |
| decision.risk_state | string | yes | green,yellow,red |  |
| decision.reasons.[] | string |  |  |  |
| decision.warnings.[] | string |  |  |  |
| decision_view_id | string |  |  | Optional pointer to decision_view projection. |
