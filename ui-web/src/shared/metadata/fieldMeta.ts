export type FieldFormat = 'percent' | 'bps' | 'currency' | 'days'
export type FieldMeta = {
  label: string
  tooltip?: string
  format?: FieldFormat
  digits?: number
}

export const fieldMeta: Record<string, FieldMeta> = {
  created_at: {
    label: 'Время',
    tooltip: 'Дата и время создания записи.',
  },
  decision_id: {
    label: 'ID решения',
    tooltip: 'Уникальный идентификатор решения.',
  },
  decision_view_id: {
    label: 'ID витрины',
    tooltip: 'Идентификатор записи decision_view.',
  },
  strategy_type: {
    label: 'Стратегия',
    tooltip: 'Тип стратегии, сформировавшей решение.',
  },
  primary_instrument: {
    label: 'Инструмент',
    tooltip: 'Основной инструмент решения.',
  },
  proposal_type: {
    label: 'Тип предложения',
    tooltip: 'Тип предложения оркестратора.',
  },
  action: {
    label: 'Действие',
    tooltip: 'Операционное решение (approve/reject/hold).',
  },
  risk_state: {
    label: 'Риск',
    tooltip: 'Оценка риска: зелёный/жёлтый/красный.',
  },
  news_severity: {
    label: 'Новости',
    tooltip: 'Сила новостного риска.',
  },
  execution_status: {
    label: 'Исполнение',
    tooltip: 'Текущий статус исполнения.',
  },
  cost_round_trip: {
    label: 'Стоимость round-trip',
    tooltip:
      'Формула: (buy_stock - sell_stock) + (buy_fut - sell_fut) + fees_rt. ' +
      'Полные издержки вход-выход.',
    digits: 2,
    format: 'currency',
  },
  basket: {
    label: 'Корзина',
    tooltip: 'Категория корзины стратегии.',
  },
  basket_weight: {
    label: 'Вес корзины, %',
    tooltip:
      'Формула: weight. ' +
      'Интерпретация: доля корзины в портфеле.',
    format: 'percent',
    digits: 2,
  },
  break_even_ticks: {
    label: 'Безубыток, тиков',
    tooltip:
      'Формула: break_even_ticks = round_trip_cost / tick_value. ' +
      'Интерпретация: сколько тиков нужно пройти, чтобы покрыть издержки.',
    digits: 2,
  },
  break_even_points: {
    label: 'Безубыток, пунктов',
    tooltip:
      'Формула: break_even_points = break_even_ticks * price_step. ' +
      'Интерпретация: требуемое движение цены в пунктах.',
    digits: 2,
  },
  max_drawdown: {
    label: 'Макс. просадка',
    tooltip:
      'Формула: min(equity / rolling_max - 1). ' +
      'Интерпретация: максимальная просадка капитала.',
    format: 'percent',
    digits: 2,
  },
  stock: {
    label: 'Акция',
    tooltip: 'Тикер акции.',
  },
  stock_name: {
    label: 'Название акции',
    tooltip: 'Краткое название эмитента.',
  },
  future: {
    label: 'Фьючерс',
    tooltip: 'Тикер фьючерсного контракта.',
  },
  expiry: {
    label: 'Экспирация',
    tooltip: 'Дата экспирации фьючерса.',
  },
  dte: {
    label: 'DTE (дней до экспирации)',
    tooltip: 'Количество дней до экспирации.',
    format: 'days',
    digits: 0,
  },
  spot: {
    label: 'Спот',
    tooltip: 'Текущая цена спота.',
    digits: 2,
  },
  future_price: {
    label: 'Цена фьючерса',
    tooltip: 'Текущая цена фьючерса.',
    digits: 2,
  },
  spread_mid: {
    label: 'Спред (mid)',
    tooltip:
      'Формула: (Spot_mid - PV(div) - Futures_mid). ' +
      'Интерпретация: абсолютный спред между спотом и фьючерсом.',
    digits: 4,
  },
  spread_pct: {
    label: 'Спред, %',
    tooltip:
      'Формула: spread_mid / spot_mid. ' +
      'Интерпретация: доля спреда относительно цены спота.',
    format: 'percent',
    digits: 2,
  },
  rtc_pct: {
    label: 'Издержки RT, %',
    tooltip:
      'Формула: rtc / spot_mid, где rtc = (buy_stock - sell_stock) + ' +
      '(buy_fut - sell_fut) + fees_rt. ' +
      'Интерпретация: доля round-trip издержек в цене спота.',
    format: 'percent',
    digits: 2,
  },
  floor_rate_annual: {
    label: 'Floor-ставка, % год.',
    tooltip:
      'Формула: (floor_pnl / capital_base) * 365 / DTE. ' +
      'Интерпретация: годовая carry-доходность при удержании до экспирации.',
    format: 'percent',
    digits: 2,
  },
  floor_pnl: {
    label: 'Floor PnL, ₽',
    tooltip:
      'Формула: (fut_sell - spot_buy) + div_sum - costs_hold. ' +
      'Интерпретация: ожидаемая прибыль floor-удержания до экспирации.',
    format: 'currency',
    digits: 2,
  },
  capital_base: {
    label: 'База капитала, ₽',
    tooltip:
      'Формула: FULL_CASH -> spot_buy; MARGIN_AWARE -> margin_stock + margin_fut + var_buffer. ' +
      'Интерпретация: капитал, на который нормируется floor_rate_annual.',
    format: 'currency',
    digits: 2,
  },
  costs_hold: {
    label: 'Издержки удержания, ₽',
    tooltip:
      'Формула: fees_rt + funding_cost + riskbuffer_floor. ' +
      'Интерпретация: ожидаемые издержки на удержание до экспирации.',
    format: 'currency',
    digits: 2,
  },
  score_floor: {
    label: 'Floor-скор',
    tooltip:
      'Формула: floor_rate_annual - r_cb_annual. ' +
      'Интерпретация: превышение над бенчмарком.',
    format: 'percent',
    digits: 2,
  },
  implied_rate_net: {
    label: 'Имплайд-ставка (net), % год.',
    tooltip:
      'Формула: (future_price + pv_div - spot) / (spot * tau). ' +
      'Интерпретация: implied ставка, скорректированная на дивиденды/издержки.',
    format: 'percent',
    digits: 2,
  },
  required_rate: {
    label: 'Требуемая ставка, % год.',
    tooltip:
      'Формула: required_rate (бенчмарк/ставка из настроек). ' +
      'Интерпретация: порог для сравнения с implied_rate_net.',
    format: 'percent',
    digits: 2,
  },
  score_alpha: {
    label: 'Alpha-скор',
    tooltip:
      'Формула: p_hit_tp * tp_net - p_hit_sl * sl_pct - rtc_pct. ' +
      'Интерпретация: ожидаемая alpha-доходность с учетом TP/SL и издержек.',
    format: 'percent',
    digits: 2,
  },
  total_score: {
    label: 'Итоговый скор',
    tooltip:
      'Формула: w1*score_floor + w2*score_alpha - w3*penalty_liq - w4*penalty_event. ' +
      'Интерпретация: итоговый скор пары (выше лучше).',
    digits: 4,
  },
  signal_score: {
    label: 'Скор сигнала',
    tooltip:
      'Формула: total_score. ' +
      'Интерпретация: скор сигнала для ранжирования.',
    digits: 4,
  },
  signal_score_norm: {
    label: 'Норм. скор сигнала',
    tooltip:
      'Формула: 0.5 * (|zscore| / z_entry + |implied_rate_net - required_rate| / implied_rate_buffer). ' +
      'Интерпретация: нормированная сила сигнала (выше = сильнее).',
    digits: 3,
  },
  signal_action: {
    label: 'Сигнал',
    tooltip: 'Действие по паре: вход/выход/держать.',
  },
  signal_direction: {
    label: 'Направление',
    tooltip: 'Тип позиции: cash-and-carry или reverse.',
  },
  signal_reasons: {
    label: 'Причины сигнала',
    tooltip: 'Список причин решения по сигналу.',
  },
  signal_metrics: {
    label: 'Метрики сигнала',
    tooltip: 'Метрики, использованные при расчёте сигнала.',
  },
  decision: {
    label: 'Решение',
    tooltip: 'Техническое решение: ENTER_OK / SKIP_*.',
  },
  floor_pass: {
    label: 'Floor-проход',
    tooltip: 'Истина, если floor_rate_annual ≥ r_cb_annual − floor_tolerance.',
  },
  liquidity_pass: {
    label: 'Ликвидность пройдена',
    tooltip: 'Истина, если пройдены пороги ликвидности (спреды, объёмы, OI, days_to_exit).',
  },
  r_cb_annual: {
    label: 'Ключевая ставка, % год.',
    tooltip: 'Ключевая ставка (r_cb).',
    format: 'percent',
    digits: 2,
  },
  r_fund_annual: {
    label: 'Ставка фондирования, % год.',
    tooltip: 'Ставка фондирования позиции.',
    format: 'percent',
    digits: 2,
  },
  r_disc_annual: {
    label: 'Ставка дисконт., % год.',
    tooltip: 'Ставка дисконтирования дивидендов.',
    format: 'percent',
    digits: 2,
  },
  expected_return: {
    label: 'Ожидаемая доходность, % год.',
    tooltip:
      'Формула: expected_return = floor_rate_annual. ' +
      'Интерпретация: ожидаемая годовая carry-доходность.',
    format: 'percent',
    digits: 2,
  },
  risk_estimate: {
    label: 'Оценка риска',
    tooltip:
      'Формула: risk_estimate = sigma_h (волатильность spread_pct на горизонте H). ' +
      'Интерпретация: риск-оценка стратегии.',
    digits: 4,
  },
  liquidity_score: {
    label: 'Ликвидность, скор',
    tooltip:
      'Формула: liquidity_score (0..1). ' +
      'Интерпретация: 0 - низкая, 1 - высокая ликвидность.',
    format: 'percent',
    digits: 1,
  },
  snapshot_as_of: {
    label: 'Снимок на',
    tooltip: 'Дата/время расчёта снимка.',
  },
  avg_trade_return_annual_recent: {
    label: 'Средн. годовая доходность (посл. 5)',
    tooltip:
      'Формула: mean(trade_return_annual последних 5 сделок). ' +
      'Интерпретация: средняя годовая доходность по последним выходам.',
    format: 'percent',
    digits: 2,
  },
  share_alpha_exits: {
    label: 'Доля alpha-выходов',
    tooltip:
      'Формула: alpha_exit_count / total_trades. ' +
      'Интерпретация: доля выходов по alpha-триггерам.',
    format: 'percent',
    digits: 2,
  },
  avg_hold_days: {
    label: 'Средн. дни удержания',
    tooltip:
      'Формула: mean(hold_days). ' +
      'Интерпретация: средняя длительность удержания позиции.',
    format: 'days',
    digits: 1,
  },
  p_hit_tp: {
    label: 'P(достиж. TP)',
    tooltip:
      'Формула: mean(1{MFE ≥ TP}) по окну H. ' +
      'Интерпретация: вероятность достижения take-profit.',
    format: 'percent',
    digits: 2,
  },
  p_hit_sl: {
    label: 'P(достиж. SL)',
    tooltip:
      'Формула: mean(1{MAE ≤ −SL}) по окну H. ' +
      'Интерпретация: вероятность достижения stop-loss.',
    format: 'percent',
    digits: 2,
  },
  sigma_h: {
    label: 'Сигма спреда (H)',
    tooltip:
      'Формула: σ(Δspread_pct) на горизонте H. ' +
      'Интерпретация: волатильность спреда на окне H.',
    digits: 4,
  },
  half_life: {
    label: 'Период полураспада',
    tooltip:
      'Формула: ln(2)/-ln(phi), где phi — коэффициент AR(1) spread_pct. ' +
      'Интерпретация: скорость возврата к среднему.',
    digits: 2,
  },
  mfe_q50: {
    label: 'MFE q50, %',
    tooltip:
      'Формула: медиана(max(spread_pct_window - entry)). ' +
      'Интерпретация: типичное благоприятное движение.',
    format: 'percent',
    digits: 2,
  },
  mfe_q75: {
    label: 'MFE q75, %',
    tooltip:
      'Формула: 75-й процентиль max(spread_pct_window - entry). ' +
      'Интерпретация: сильное благоприятное движение.',
    format: 'percent',
    digits: 2,
  },
  mfe_q90: {
    label: 'MFE q90, %',
    tooltip:
      'Формула: 90-й процентиль max(spread_pct_window - entry). ' +
      'Интерпретация: экстремальное благоприятное движение.',
    format: 'percent',
    digits: 2,
  },
  mae_q50: {
    label: 'MAE q50, %',
    tooltip:
      'Формула: медиана(min(spread_pct_window - entry)). ' +
      'Интерпретация: типичное неблагоприятное движение.',
    format: 'percent',
    digits: 2,
  },
  mae_q75: {
    label: 'MAE q75, %',
    tooltip:
      'Формула: 75-й процентиль min(spread_pct_window - entry). ' +
      'Интерпретация: сильное неблагоприятное движение.',
    format: 'percent',
    digits: 2,
  },
  mae_q90: {
    label: 'MAE q90, %',
    tooltip:
      'Формула: 90-й процентиль min(spread_pct_window - entry). ' +
      'Интерпретация: экстремальное неблагоприятное движение.',
    format: 'percent',
    digits: 2,
  },
  spread_bps_stock: {
    label: 'Спред акции, б.п.',
    tooltip:
      'Формула: (ask - bid) / mid * 10 000. ' +
      'Интерпретация: относительная ширина спреда акции.',
    format: 'bps',
    digits: 2,
  },
  spread_bps_fut: {
    label: 'Спред фьючерса, б.п.',
    tooltip:
      'Формула: (ask - bid) / mid * 10 000. ' +
      'Интерпретация: относительная ширина спреда фьючерса.',
    format: 'bps',
    digits: 2,
  },
  dollar_vol_stock: {
    label: 'Денежный объём акций',
    tooltip:
      'Формула: price * volume. ' +
      'Интерпретация: денежный оборот акций.',
    digits: 0,
  },
  dollar_vol_fut: {
    label: 'Денежный объём фьючерса',
    tooltip:
      'Формула: price * volume * multiplier. ' +
      'Интерпретация: денежный оборот фьючерса.',
    digits: 0,
  },
  days_to_exit: {
    label: 'Дней до выхода',
    tooltip:
      'Формула: position_notional / (avg_dollar_vol * participation_rate). ' +
      'Интерпретация: оценка времени выхода из позиции.',
    format: 'days',
    digits: 1,
  },
  open_interest: {
    label: 'Открытый интерес',
    tooltip: 'Количество открытых контрактов.',
    digits: 0,
  },
  tp_pct: {
    label: 'TP, %',
    tooltip:
      'Формула: TP_pct (параметр стратегии). ' +
      'Интерпретация: целевой профит по spread_pct.',
    format: 'percent',
    digits: 2,
  },
  sl_pct: {
    label: 'SL, %',
    tooltip:
      'Формула: SL_pct (параметр стратегии). ' +
      'Интерпретация: стоп-уровень по spread_pct.',
    format: 'percent',
    digits: 2,
  },
  tp_net: {
    label: 'TP net, %',
    tooltip:
      'Формула: TP_pct + rtc_pct. ' +
      'Интерпретация: TP с учётом издержек.',
    format: 'percent',
    digits: 2,
  },
  sl_net: {
    label: 'SL net, %',
    tooltip:
      'Формула: SL_pct + rtc_pct. ' +
      'Интерпретация: SL с учётом издержек.',
    format: 'percent',
    digits: 2,
  },
  spread_entry_exec: {
    label: 'Спред входа (exec)',
    tooltip:
      'Формула: stock_buy - pv_div - fut_sell. ' +
      'Интерпретация: спред по ценам исполнения на входе.',
    digits: 4,
  },
  spread_exit_exec: {
    label: 'Спред выхода (exec)',
    tooltip:
      'Формула: stock_sell - pv_div - fut_buy. ' +
      'Интерпретация: спред по ценам исполнения на выходе.',
    digits: 4,
  },
  spread_pct_entry_exec: {
    label: 'Спред входа, %',
    tooltip:
      'Формула: spread_entry_exec / spot_mid. ' +
      'Интерпретация: спред входа в процентах от спота.',
    format: 'percent',
    digits: 2,
  },
  spread_pct_exit_exec: {
    label: 'Спред выхода, %',
    tooltip:
      'Формула: spread_exit_exec / spot_mid. ' +
      'Интерпретация: спред выхода в процентах от спота.',
    format: 'percent',
    digits: 2,
  },
  entry_spread_pct_exec: {
    label: 'Entry spread, % (exec)',
    tooltip:
      'Формула: spread_entry_exec / spot_mid. ' +
      'Интерпретация: спред входа (серия спредов).',
    format: 'percent',
    digits: 2,
  },
  exit_spread_pct_exec: {
    label: 'Exit spread, % (exec)',
    tooltip:
      'Формула: spread_exit_exec / spot_mid. ' +
      'Интерпретация: спред выхода (серия спредов).',
    format: 'percent',
    digits: 2,
  },
  pnl_spread_pct: {
    label: 'PnL по спреду, %',
    tooltip:
      'Формула: spread_pct_exit_exec - spread_pct_entry_exec. ' +
      'Интерпретация: прибыль/убыток по спреду.',
    format: 'percent',
    digits: 2,
  },
  entry_spread_exec_pct: {
    label: 'Entry spread (exec), %',
    tooltip:
      'Формула: spread_entry_exec / spot_mid. ' +
      'Интерпретация: зафиксированный спред входа.',
    format: 'percent',
    digits: 2,
  },
  trail_peak_spread_pct: {
    label: 'Пик трейла, %',
    tooltip:
      'Формула: max(exit_spread_pct - entry_spread_pct). ' +
      'Интерпретация: лучшая достигнутая доходность по трейлу.',
    format: 'percent',
    digits: 2,
  },
  cycle_return_pct: {
    label: 'Доходность цикла, %',
    tooltip:
      'Формула: cash_and_carry => (entry_spread - spread) / entry_spot * 100; ' +
      'reverse => (spread - entry_spread) / entry_spot * 100. ' +
      'Интерпретация: результат завершённого цикла.',
    format: 'percent',
    digits: 2,
  },
  trade_return_pct: {
    label: 'Доходность спреда, %',
    tooltip:
      'Формула: spread_pct_exit_exec - spread_pct_entry_exec. ' +
      'Интерпретация: изменение спреда между входом и выходом.',
    format: 'percent',
    digits: 2,
  },
  trade_pnl_cash: {
    label: 'P&L, руб.',
    tooltip:
      'Формула: (sell_stock - buy_stock) - (buy_fut - sell_fut) + дивиденды - фондирование - комиссии. ' +
      'Интерпретация: денежный результат сделки.',
    format: 'currency',
    digits: 2,
  },
  trade_return_pct_net: {
    label: 'Доходность (net), %',
    tooltip:
      'Формула: trade_pnl_cash / entry_spot_exec. ' +
      'Интерпретация: net-доходность относительно спота на входе.',
    format: 'percent',
    digits: 2,
  },
  trade_return_annual: {
    label: 'Годовая доходность (net), %',
    tooltip:
      'Формула: trade_return_net / hold_tau. ' +
      'Интерпретация: годовая net-доходность сделки.',
    format: 'percent',
    digits: 2,
  },
  trade_hold_days: {
    label: 'Дней в сделке',
    tooltip:
      'Формула: exit_date - entry_date. ' +
      'Интерпретация: длительность удержания сделки.',
    format: 'days',
    digits: 0,
  },
  pnl: {
    label: 'P&L',
    tooltip: 'Прибыль/убыток по сделке.',
    digits: 2,
  },
  entry_price_stock: {
    label: 'Цена входа (акция)',
    tooltip: 'Цена входа по акции.',
    digits: 2,
  },
  entry_price_fut: {
    label: 'Цена входа (фьючерс)',
    tooltip: 'Цена входа по фьючерсу.',
    digits: 2,
  },
  exit_price_stock: {
    label: 'Цена выхода (акция)',
    tooltip: 'Цена выхода по акции.',
    digits: 2,
  },
  exit_price_fut: {
    label: 'Цена выхода (фьючерс)',
    tooltip: 'Цена выхода по фьючерсу.',
    digits: 2,
  },
  quantity_stock: {
    label: 'Кол-во (акция)',
    tooltip: 'Количество акций.',
    digits: 0,
  },
  quantity_fut: {
    label: 'Кол-во (фьючерс)',
    tooltip: 'Количество фьючерсов.',
    digits: 0,
  },
  hold_days: {
    label: 'Дней в позиции',
    tooltip: 'Длительность сделки в днях.',
    format: 'days',
    digits: 0,
  },
  exit_reason: {
    label: 'Причина выхода',
    tooltip: 'Причина закрытия позиции.',
  },
  equity: {
    label: 'Эквити',
    tooltip: 'Размер капитала в моменте.',
    digits: 0,
  },
  cash: {
    label: 'Кэш',
    tooltip: 'Свободные денежные средства.',
    digits: 0,
  },
  drawdown: {
    label: 'Просадка',
    tooltip:
      'Формула: equity / rolling_max - 1. ' +
      'Интерпретация: текущая просадка капитала.',
    format: 'percent',
    digits: 2,
  },
  turnover: {
    label: 'Оборачиваемость',
    tooltip:
      'Формула: v1 -> #trades / years; v2 -> turnover_notional / equity. ' +
      'Интерпретация: частота/доля оборота.',
    digits: 2,
  },
  positions: {
    label: 'Позиции',
    tooltip: 'Количество открытых позиций.',
    digits: 0,
  },
  cagr: {
    label: 'CAGR, % год.',
    tooltip:
      'Формула: equity_last^(1/years) - 1. ' +
      'Интерпретация: среднегодовой темп роста капитала.',
    format: 'percent',
    digits: 2,
  },
  sharpe: {
    label: 'Sharpe',
    tooltip:
      'Формула: mean(ret)/std(ret) * sqrt(252). ' +
      'Интерпретация: доходность на единицу риска.',
    digits: 2,
  },
  hit_rate: {
    label: 'Доля прибыльных',
    tooltip:
      'Формула: #profit / #trades. ' +
      'Интерпретация: доля прибыльных сделок.',
    format: 'percent',
    digits: 2,
  },
  objective: {
    label: 'Целевая метрика',
    tooltip:
      'Формула: excess_ann - penalty_dd - penalty_to (с ограничениями по dd/turnover). ' +
      'Интерпретация: итоговая цель для HPO.',
    digits: 4,
  },
  params: {
    label: 'Параметры',
    tooltip: 'Набор параметров эксперимента.',
  },
  fold_objectives: {
    label: 'Метрики фолдов',
    tooltip: 'Значения метрики по фолдам.',
  },
  run_id: {
    label: 'ID прогона',
    tooltip: 'Идентификатор прогона.',
  },
  status: {
    label: 'Статус',
    tooltip: 'Статус процесса.',
  },
  message: {
    label: 'Сообщение',
    tooltip: 'Текстовое сообщение.',
  },
  code: {
    label: 'Код',
    tooltip: 'Код события/ошибки.',
  },
  confidence: {
    label: 'Достоверность',
    tooltip: 'Доля уверенности (0–1).',
    format: 'percent',
    digits: 2,
  },
  timestamp: {
    label: 'Время',
    tooltip: 'Дата и время события.',
  },
  date: {
    label: 'Дата',
    tooltip: 'Дата записи.',
  },
  action_note: {
    label: 'Комментарий',
  },
  pair_id: {
    label: 'Пара',
    tooltip: 'Код пары акция-фьючерс.',
  },
  stock_secid: {
    label: 'Акция',
    tooltip: 'Код акции.',
  },
  future_secid: {
    label: 'Фьючерс',
    tooltip: 'Код фьючерса.',
  },
  direction: {
    label: 'Направление',
    tooltip: 'Тип позиции.',
  },
  entry_date: {
    label: 'Дата входа',
    tooltip: 'Дата открытия позиции.',
  },
  exit_date: {
    label: 'Дата выхода',
    tooltip: 'Дата закрытия позиции.',
  },
  price: {
    label: 'Цена',
    tooltip: 'Цена исполнения.',
    digits: 2,
  },
  quantity: {
    label: 'Количество',
    tooltip: 'Количество контрактов/акций.',
    digits: 0,
  },
  side: {
    label: 'Сторона',
    tooltip: 'Buy/Sell сторона сделки.',
  },
  note: {
    label: 'Комментарий',
    tooltip: 'Комментарий оператора/системы.',
  },
  trade_cycle: {
    label: 'Цикл сделки',
    tooltip: 'Идентификатор торгового цикла.',
    digits: 0,
  },
  entry_cycle: {
    label: 'Цикл входа',
    tooltip: 'Идентификатор цикла при входе.',
    digits: 0,
  },
  exit_cycle: {
    label: 'Цикл выхода',
    tooltip: 'Идентификатор цикла при выходе.',
    digits: 0,
  },
  cycle_id: {
    label: 'Активный цикл',
    tooltip: 'Номер текущего цикла, если позиция открыта.',
    digits: 0,
  },
  entry_flag: {
    label: 'Вход',
    tooltip: 'Маркер события входа.',
  },
  exit_flag: {
    label: 'Выход',
    tooltip: 'Маркер события выхода.',
  },
  zscore: {
    label: 'Z-score',
    tooltip:
      'Формула: (last - mean) / std на окне z_window. ' +
      'Интерпретация: насколько спред отклонился от среднего.',
    digits: 2,
  },
  z_entry: {
    label: 'Z-entry',
    tooltip:
      'Формула: порог входа по z-score. ' +
      'Интерпретация: значение z-score для входа.',
    digits: 2,
  },
  z_exit: {
    label: 'Z-exit',
    tooltip:
      'Формула: порог выхода по z-score. ' +
      'Интерпретация: значение z-score для выхода.',
    digits: 2,
  },
  zscore_raw: {
    label: 'Z-score (raw)',
    tooltip:
      'Формула: (last - mean) / std на окне window. ' +
      'Интерпретация: базовый z-score без тренд-коррекции.',
    digits: 2,
  },
  window: {
    label: 'Окно',
    tooltip:
      'Формула: размер окна расчёта статистики. ' +
      'Интерпретация: длина истории в точках.',
    digits: 0,
  },
  mean: {
    label: 'Среднее',
    tooltip:
      'Формула: mean(series) на окне window. ' +
      'Интерпретация: средний уровень ряда.',
    digits: 4,
  },
  std: {
    label: 'Стандартное отклонение',
    tooltip:
      'Формула: std(series) на окне window. ' +
      'Интерпретация: разброс значений ряда.',
    digits: 4,
  },
  trend: {
    label: 'Тренд',
    tooltip:
      'Формула: значение трендовой линии в последней точке. ' +
      'Интерпретация: ожидаемый уровень по тренду.',
    digits: 4,
  },
  spread_vol: {
    label: 'Волатильность спреда',
    tooltip:
      'Формула: std(spread_series) на окне window. ' +
      'Интерпретация: разброс значений спреда.',
    digits: 4,
  },
  spread_vol_pct: {
    label: 'Волатильность спреда, %',
    tooltip:
      'Формула: std(spread_pct) на окне window. ' +
      'Интерпретация: разброс спреда в процентах.',
    format: 'percent',
    digits: 2,
  },
  trend_pos: {
    label: 'Отклонение от тренда',
    tooltip:
      'Формула: last - trend_last. ' +
      'Интерпретация: позиция относительно тренда.',
    digits: 4,
  },
  trend_slope: {
    label: 'Наклон тренда',
    tooltip:
      'Формула: slope линейной регрессии spread_pct. ' +
      'Интерпретация: направление тренда.',
    digits: 4,
  },
  trend_zscore: {
    label: 'Z-score тренда',
    tooltip:
      'Формула: residual / std(residual) на окне window. ' +
      'Интерпретация: насколько текущая точка отклоняется от тренда.',
    digits: 2,
  },
  spread_trend_z: {
    label: 'Z-score тренда (abs)',
    tooltip:
      'Формула: |trend_zscore|. ' +
      'Интерпретация: сила трендового отклонения.',
    digits: 2,
  },
  expected_net_irr: {
    label: 'Ожид. net IRR',
    tooltip:
      'Формула: expected_net_irr (из модели carry/alpha). ' +
      'Интерпретация: ожидаемая годовая доходность.',
    format: 'percent',
    digits: 2,
  },
  mae: {
    label: 'MAE',
    tooltip:
      'Формула: min(spread_pct_window - entry). ' +
      'Интерпретация: максимальное неблагоприятное отклонение.',
    digits: 4,
  },
  model_breaks: {
    label: 'Сбои модели',
    tooltip:
      'Формула: счётчик нарушений модели. ' +
      'Интерпретация: количество флагов качества данных.',
    digits: 0,
  },
  universe: {
    label: 'Вселенная',
  },
  execution: {
    label: 'Исполнение',
  },
  rates: {
    label: 'Ставки',
  },
  costs: {
    label: 'Издержки',
  },
  portfolio: {
    label: 'Портфель',
  },
  rebalance: {
    label: 'Ребалансировка',
  },
  general: {
    label: 'Общие',
  },
  test: {
    label: 'Тест',
  },
  strategy: {
    label: 'Стратегия',
  },
  allocation: {
    label: 'Аллокация',
  },
  liquidity: {
    label: 'Ликвидность',
  },
}
