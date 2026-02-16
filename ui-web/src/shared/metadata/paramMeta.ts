import { valueLabels } from './valueLabels'

export type ParamMeta = {
  label: string
  tooltip?: string
  valueLabels?: Record<string, string>
  order?: string[]
}

export const paramMeta: Record<string, ParamMeta> = {
  'test.start_date': {
    label: 'Дата начала',
    tooltip:
      'Формула: start_date. ' +
      'Интерпретация: дата начала исторического периода.',
  },
  'test.end_date': {
    label: 'Дата окончания',
    tooltip:
      'Формула: end_date. ' +
      'Интерпретация: дата окончания исторического периода.',
  },
  'test.timezone': {
    label: 'Часовой пояс',
    tooltip:
      'Формула: timezone. ' +
      'Интерпретация: таймзона для приведения дат/времени.',
  },
  'test.cost_stress_mult': {
    label: 'Множитель издержек',
    tooltip:
      'Формула: costs *= cost_stress_mult. ' +
      'Интерпретация: стресс-множитель издержек.',
  },
  'test.seed': {
    label: 'Сид генератора',
    tooltip:
      'Формула: seed. ' +
      'Интерпретация: фиксирует случайность для повторяемости.',
  },
  'universe.pair_ids': {
    label: 'Список пар',
    tooltip:
      'Формула: использовать только pair_ids. ' +
      'Интерпретация: ручной список пар.',
  },
  'universe.include_stocks': {
    label: 'Тикеры акций',
    tooltip:
      'Формула: фильтр по акциям. ' +
      'Интерпретация: разрешённые тикеры акций.',
  },
  'universe.include_futures': {
    label: 'Тикеры фьючерсов',
    tooltip:
      'Формула: фильтр по фьючерсам. ' +
      'Интерпретация: разрешённые тикеры фьючерсов.',
  },
  'universe.max_pairs': {
    label: 'Лимит пар',
    tooltip:
      'Формула: limit = max_pairs. ' +
      'Интерпретация: максимальное число пар в расчёте.',
  },
  'universe.allowed_expiry_months': {
    label: 'Месяцы экспирации',
    tooltip:
      'Формула: expiry_month ? allowed_expiry_months. ' +
      'Интерпретация: допустимые месяцы экспирации.',
  },
  'universe.allowed_expiry_years': {
    label: 'Годы экспирации',
    tooltip:
      'Формула: expiry_year ? allowed_expiry_years. ' +
      'Интерпретация: допустимые годы экспирации.',
  },
  'execution.price_mode': {
    label: 'Режим цены',
    tooltip:
      'Формула: mode = price_mode (BIDASK/OHLC/AUTO). ' +
      'Интерпретация: источник цены исполнения.',
  },
  'execution.half_spread_bps': {
    label: 'Половина спреда, б.п.',
    tooltip:
      'Формула: price ± half_spread_bps. ' +
      'Интерпретация: половина спреда в б.п.',
  },
  'execution.slip_stock_bps': {
    label: 'Проскальзывание акций, б.п.',
    tooltip:
      'Формула: slip_stock_bps. ' +
      'Интерпретация: проскальзывание по акциям в б.п.',
  },
  'execution.slip_fut_bps': {
    label: 'Проскальзывание фьючерса, б.п.',
    tooltip:
      'Формула: slip_fut_bps. ' +
      'Интерпретация: проскальзывание по фьючерсу в б.п.',
  },
  'execution.slip_fut_ticks': {
    label: 'Проскальзывание фьючерса, тиков',
    tooltip:
      'Формула: slip_fut_ticks ? tick_size_fut. ' +
      'Интерпретация: проскальзывание в тиках.',
  },
  'execution.tick_size_fut': {
    label: 'Шаг цены фьючерса',
    tooltip:
      'Формула: tick_size_fut. ' +
      'Интерпретация: шаг цены фьючерса для пересчёта тиков.',
  },
  'rates.day_count': {
    label: 'База дней',
    tooltip:
      'Формула: tau = days / day_count. ' +
      'Интерпретация: база дней для годовых ставок.',
  },
  'rates.use_trading_days': {
    label: 'Торговые дни',
    tooltip:
      'Формула: использовать торговые дни вместо календарных. ' +
      'Интерпретация: пересчёт tau и ставок.',
  },
  'costs.stock_commission_bps': {
    label: 'Комиссия акций, б.п.',
    tooltip:
      'Формула: комиссия = notional ? stock_commission_bps. ' +
      'Интерпретация: комиссия по акциям в б.п.',
  },
  'costs.futures_commission_bps': {
    label: 'Комиссия фьючерсов, б.п.',
    tooltip:
      'Формула: комиссия = notional ? futures_commission_bps. ' +
      'Интерпретация: комиссия по фьючерсам в б.п.',
  },
  'costs.exchange_fee_bps': {
    label: 'Биржевой сбор, б.п.',
    tooltip:
      'Формула: сбор = notional ? exchange_fee_bps. ' +
      'Интерпретация: биржевой сбор в б.п.',
  },
  'costs.fee_stock_per_share': {
    label: 'Комиссия за акцию, ?',
    tooltip:
      'Формула: fee_stock_per_share ? qty. ' +
      'Интерпретация: фиксированная комиссия за акцию.',
  },
  'costs.fee_stock_bps': {
    label: 'Доп. комиссия акций, б.п.',
    tooltip:
      'Формула: fee_stock_bps. ' +
      'Интерпретация: дополнительная комиссия по акциям.',
  },
  'costs.fee_fut_per_contract': {
    label: 'Комиссия за контракт, ?',
    tooltip:
      'Формула: fee_fut_per_contract ? contracts. ' +
      'Интерпретация: фиксированная комиссия за контракт.',
  },
  'liquidity.max_spread_bps_stock': {
    label: 'Макс. спред акций, б.п.',
    tooltip:
      'Формула: spread_bps_stock ? max_spread_bps_stock. ' +
      'Интерпретация: фильтр по спреду акций.',
  },
  'liquidity.max_spread_bps_fut': {
    label: 'Макс. спред фьючерса, б.п.',
    tooltip:
      'Формула: spread_bps_fut ? max_spread_bps_fut. ' +
      'Интерпретация: фильтр по спреду фьючерса.',
  },
  'liquidity.min_avg_dollarvol_stock': {
    label: 'Мин. оборот акций, ?',
    tooltip:
      'Формула: avg_dollarvol_stock ? min_avg_dollarvol_stock. ' +
      'Интерпретация: минимум оборота по акциям.',
  },
  'liquidity.min_avg_dollarvol_fut': {
    label: 'Мин. оборот фьючерса, ?',
    tooltip:
      'Формула: avg_dollarvol_fut ? min_avg_dollarvol_fut. ' +
      'Интерпретация: минимум оборота по фьючерсу.',
  },
  'liquidity.min_open_interest': {
    label: 'Мин. открытый интерес',
    tooltip:
      'Формула: open_interest ? min_open_interest. ' +
      'Интерпретация: минимум открытого интереса.',
  },
  'liquidity.participation_rate': {
    label: 'Доля участия',
    tooltip:
      'Формула: days_to_exit(position, avg_dollar, participation_rate). ' +
      'Интерпретация: доля участия в дневном объёме.',
  },
  'liquidity.max_days_to_exit': {
    label: 'Макс. дней на выход',
    tooltip:
      'Формула: days_to_exit ? max_days_to_exit. ' +
      'Интерпретация: ограничение по сроку выхода.',
  },
  'liquidity.use_adv': {
    label: 'Использовать ADV',
    tooltip:
      'Формула: use_adv. ' +
      'Интерпретация: использовать среднедневной оборот (ADV) в фильтрах ликвидности.',
  },
  'strategy.floor_tolerance': {
    label: 'Допуск floor',
    tooltip:
      'Формула: floor_pass = floor_rate_annual ? r_cb_annual - floor_tolerance. ' +
      'Интерпретация: допуск к ключевой ставке.',
  },
  'strategy.riskbuffer_floor': {
    label: 'Риск-буфер floor',
    tooltip:
      'Формула: costs_hold += riskbuffer_floor. ' +
      'Интерпретация: дополнительный буфер издержек удержания.',
  },
  'strategy.capital_base_mode': {
    label: 'База капитала',
    tooltip:
      'Формула: FULL_CASH > spot_buy; MARGIN_AWARE > margin_stock + margin_fut + var_buffer. ' +
      'Интерпретация: база капитала для floor_rate.',
  },
  'strategy.margin_stock_pct': {
    label: 'Маржа акций, доля',
    tooltip:
      'Формула: margin_stock = spot ? margin_stock_pct. ' +
      'Интерпретация: доля маржи по акциям.',
  },
  'strategy.margin_fut_pct': {
    label: 'Маржа фьючерса, доля',
    tooltip:
      'Формула: margin_fut = fut ? margin_fut_pct. ' +
      'Интерпретация: доля маржи по фьючерсу.',
  },
  'strategy.var_margin_buffer_pct': {
    label: 'Буфер вариационки, доля',
    tooltip:
      'Формула: var_buffer = margin_fut ? var_margin_buffer_pct. ' +
      'Интерпретация: буфер вариационной маржи.',
  },
  'strategy.min_dte_entry': {
    label: 'Мин. DTE для входа',
    tooltip:
      'Формула: DTE ? min_DTE_entry. ' +
      'Интерпретация: минимум дней до экспирации для входа.',
  },
  'strategy.close_buffer_days': {
    label: 'Буфер до экспирации, дней',
    tooltip:
      'Формула: выход за close_buffer_days до экспирации. ' +
      'Интерпретация: временной буфер закрытия.',
  },
  'strategy.roll_trigger_days': {
    label: 'Триггер ролловера, дней',
    tooltip:
      'Формула: DTE ? roll_trigger_days. ' +
      'Интерпретация: порог для ролловера.',
  },
  'strategy.h_max_days': {
    label: 'Горизонт H, дней',
    tooltip:
      'Формула: горизонт расчёта alpha-метрик. ' +
      'Интерпретация: число дней вперёд для TP/SL.',
  },
  'strategy.spread_history_days': {
    label: 'История спреда, дней',
    tooltip:
      'Формула: использовать последние spread_history_days. ' +
      'Интерпретация: глубина истории спреда.',
  },
  'strategy.tp_pct': {
    label: 'TP-порог',
    tooltip:
      'Формула: выход по TP при spread_pct ? TP_pct. ' +
      'Интерпретация: порог фиксации прибыли (доля, 0.01 = 1%).',
  },
  'strategy.sl_pct': {
    label: 'SL-порог',
    tooltip:
      'Формула: выход по SL при spread_pct ? -SL_pct. ' +
      'Интерпретация: порог стоп-лосса (доля, 0.01 = 1%).',
  },
  'strategy.z_window': {
    label: 'Окно Z-score',
    tooltip:
      'Формула: zscore = (last - mean) / std на окне z_window. ' +
      'Интерпретация: длина окна расчёта.',
  },
  'strategy.z_entry_threshold': {
    label: 'Порог входа Z-score',
    tooltip:
      'Формула: |zscore| ? z_entry_threshold. ' +
      'Интерпретация: порог стат-входа.',
  },
  'strategy.min_floor_score': {
    label: 'Мин. floor-скор',
    tooltip:
      'Формула: score_floor ? min_floor_score. ' +
      'Интерпретация: минимум floor-скора для входа.',
  },
  'strategy.min_alpha_score': {
    label: 'Мин. alpha-скор',
    tooltip:
      'Формула: score_alpha ? min_alpha_score. ' +
      'Интерпретация: минимум alpha-скора для входа.',
  },
  'strategy.min_total_score': {
    label: 'Мин. итоговый скор',
    tooltip:
      'Формула: total_score ? min_total_score. ' +
      'Интерпретация: минимум итогового скора.',
  },
  'strategy.w_floor': {
    label: 'Вес floor-скора',
    tooltip:
      'Формула: total_score = w_floor*score_floor + ... ' +
      'Интерпретация: вес floor-скора.',
  },
  'strategy.w_alpha': {
    label: 'Вес alpha-скора',
    tooltip:
      'Формула: total_score = ... + w_alpha*score_alpha + ... ' +
      'Интерпретация: вес alpha-скора.',
  },
  'strategy.w_liq': {
    label: 'Вес штрафа ликвидности',
    tooltip:
      'Формула: total_score -= w_liq*penalty_liq. ' +
      'Интерпретация: вес штрафа ликвидности.',
  },
  'strategy.w_event': {
    label: 'Вес событийного штрафа',
    tooltip:
      'Формула: total_score -= w_event*penalty_event. ' +
      'Интерпретация: вес событийного штрафа.',
  },
  'strategy.k_event': {
    label: 'Коэф. событийного штрафа',
    tooltip:
      'Формула: penalty_event = k_event * event_score. ' +
      'Интерпретация: коэффициент событийного штрафа.',
  },
  'portfolio.account_equity': {
    label: 'Капитал счёта, ?',
    tooltip:
      'Формула: account_equity. ' +
      'Интерпретация: размер капитала для расчётов.',
  },
  'portfolio.account_currency': {
    label: 'Валюта счёта',
    tooltip:
      'Формула: account_currency. ' +
      'Интерпретация: валюта портфеля.',
  },
  'portfolio.max_gross_notional': {
    label: 'Лимит общей позиции, ?',
    tooltip:
      'Формула: gross_notional ? max_gross_notional. ' +
      'Интерпретация: лимит по общей позиции.',
  },
  'portfolio.max_contracts_per_pair': {
    label: 'Лимит контрактов на пару',
    tooltip:
      'Формула: contracts ? max_contracts_per_pair. ' +
      'Интерпретация: ограничение контрактов на пару.',
  },
  'portfolio.capital_allocated_per_trade': {
    label: 'Капитал на сделку, ?',
    tooltip:
      'Формула: capital_allocated_per_trade. ' +
      'Интерпретация: капитал на одну сделку.',
  },
  'portfolio.margin_proxy': {
    label: 'Множитель маржи',
    tooltip:
      'Формула: margin = notional ? margin_proxy. ' +
      'Интерпретация: множитель маржи.',
  },
  'allocation.weights': {
    label: 'Вес корзин',
    tooltip:
      'Формула: target_weight[basket]. ' +
      'Интерпретация: распределение веса по корзинам (сумма обычно = 1).',
    valueLabels: valueLabels.basket,
    order: ['fundamental', 'speculative', 'arbitrage'],
  },
  'allocation.min_confidence': {
    label: 'Мин. уверенность',
    tooltip:
      'Формула: confidence ? min_confidence. ' +
      'Интерпретация: минимальная уверенность пары.',
  },
  'allocation.max_signals': {
    label: 'Макс. сигналов',
    tooltip:
      'Формула: top N ? max_signals. ' +
      'Интерпретация: ограничение числа сигналов.',
  },
  'allocation.max_turnover_pct': {
    label: 'Лимит оборота',
    tooltip:
      'Формула: turnover ? max_turnover_pct. ' +
      'Интерпретация: ограничение оборота (доля, 0.1 = 10%).',
  },
  'allocation.min_trade_weight': {
    label: 'Мин. вес сделки',
    tooltip:
      'Формула: trade_weight ? min_trade_weight. ' +
      'Интерпретация: минимальный вес сделки.',
  },
  'rebalance.cadence': {
    label: 'Частота ребаланса',
    tooltip:
      'Формула: cadence (daily/weekly). ' +
      'Интерпретация: периодичность ребалансировки.',
  },
  'rebalance.threshold_pct': {
    label: 'Порог ребаланса',
    tooltip:
      'Формула: |target - current| ? threshold_pct. ' +
      'Интерпретация: порог для ребалансировки.',
  },
  'rebalance.cooldown_days': {
    label: 'Пауза ребаланса, дней',
    tooltip:
      'Формула: cooldown_days между ребалансами. ' +
      'Интерпретация: пауза после ребаланса.',
  },
}

Object.assign(paramMeta, {
  'execution.mode': {
    label: 'Execution mode',
    tooltip: 'Backtest execution model (intraday minute or daily variants).',
  },
  'execution.price_source': {
    label: 'Price source',
    tooltip: 'Input price source for spread execution simulation.',
  },
  'execution.common_minute_anchor': {
    label: 'Common minute anchor',
    tooltip: 'Used only for DAILY_COMMON_MINUTE mode.',
  },
  'strategy.entry_price_tolerance_pct': {
    label: 'Entry tolerance (fallback)',
    tooltip: 'Fallback tolerance if split tolerances are not set.',
  },
  'strategy.entry_stock_tolerance_pct': {
    label: 'Entry stock tolerance',
    tooltip: 'Stock-leg tolerance for executable entry/exit matching.',
  },
  'strategy.entry_future_tolerance_pct': {
    label: 'Entry future tolerance',
    tooltip: 'Future-leg tolerance for executable entry/exit matching.',
  },
  'strategy.entry_spread_tolerance_pct': {
    label: 'Entry spread tolerance',
    tooltip: 'Spread tolerance for executable entry/exit matching.',
  },
  'strategy.signal_cutoff_before_day_end_minutes': {
    label: 'Signal cutoff before day end',
    tooltip: 'Exclude late-day minute signals by cutoff minutes before session end.',
  },
})

export const paramSectionOrder = [
  'test',
  'universe',
  'execution',
  'rates',
  'costs',
  'liquidity',
  'strategy',
  'portfolio',
  'allocation',
  'rebalance',
  'general',
]

export const valueTypeLabels: Record<string, string> = {
  bool: 'да/нет',
  int: 'целое',
  float: 'число',
  str: 'текст',
  dict: 'словарь',
  list: 'список',
  tuple: 'список',
  set: 'набор',
  union: 'смешанный',
  date: 'дата',
  datetime: 'дата/время',
}
