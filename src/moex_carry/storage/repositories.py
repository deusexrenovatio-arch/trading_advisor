from __future__ import annotations

import moex_carry.storage.repositories_core as _core
import moex_carry.storage.repositories_news_base as _news_base
import moex_carry.storage.repositories_news_events as _news_events
import moex_carry.storage.repositories_news_governance as _news_governance
import moex_carry.storage.repositories_v2 as _v2

upsert_instruments = _core.upsert_instruments
upsert_contract_specs = _core.upsert_contract_specs
store_dividends = _core.store_dividends
store_key_rates = _core.store_key_rates
load_instruments = _core.load_instruments
load_contract_specs = _core.load_contract_specs
load_dividends = _core.load_dividends
load_key_rates = _core.load_key_rates
store_signal_run = _core.store_signal_run
store_signal_history = _core.store_signal_history
delete_signal_history_run = _core.delete_signal_history_run
store_signal_execution = _core.store_signal_execution
load_latest_signal_run = _core.load_latest_signal_run
load_signal_history = _core.load_signal_history
load_active_signals = _core.load_active_signals
load_open_executions = _core.load_open_executions
upsert_quotes = _core.upsert_quotes
load_signal_executions = _core.load_signal_executions
upsert_decision_view_projection = _core.upsert_decision_view_projection
load_decision_view_projection = _core.load_decision_view_projection
upsert_news_items = _news_base.upsert_news_items
load_news_items = _news_base.load_news_items
load_news_items_by_ids = _news_base.load_news_items_by_ids
upsert_news_entity_links = _news_base.upsert_news_entity_links
load_news_entity_links = _news_base.load_news_entity_links
upsert_news_tags = _news_base.upsert_news_tags
load_news_tags = _news_base.load_news_tags
upsert_news_item_tags = _news_base.upsert_news_item_tags
load_news_item_tags = _news_base.load_news_item_tags
upsert_news_impact_scores = _news_base.upsert_news_impact_scores
load_news_impact_scores = _news_base.load_news_impact_scores
load_primary_news_scores = _news_base.load_primary_news_scores
upsert_news_signal_links = _news_base.upsert_news_signal_links
load_news_signal_links = _news_base.load_news_signal_links
upsert_news_backtest_report = _news_base.upsert_news_backtest_report
load_news_backtest_reports = _news_base.load_news_backtest_reports
upsert_news_events = _news_events.upsert_news_events
load_news_events = _news_events.load_news_events
upsert_news_event_items = _news_events.upsert_news_event_items
load_news_event_items = _news_events.load_news_event_items
upsert_news_labels = _news_events.upsert_news_labels
load_news_labels = _news_events.load_news_labels
upsert_news_llm_runs = _news_events.upsert_news_llm_runs
load_news_llm_runs = _news_events.load_news_llm_runs
upsert_event_market_reactions = _news_governance.upsert_event_market_reactions
load_event_market_reactions = _news_governance.load_event_market_reactions
upsert_news_annotations = _news_governance.upsert_news_annotations
load_news_annotations = _news_governance.load_news_annotations
upsert_news_event_updates = _news_governance.upsert_news_event_updates
load_news_event_updates = _news_governance.load_news_event_updates
upsert_news_event_links = _news_governance.upsert_news_event_links
load_news_event_links = _news_governance.load_news_event_links
upsert_news_gold_labels = _news_governance.upsert_news_gold_labels
load_news_gold_labels = _news_governance.load_news_gold_labels
upsert_news_unmatched_gold = _news_governance.upsert_news_unmatched_gold
load_news_unmatched_gold = _news_governance.load_news_unmatched_gold
upsert_news_model_eval_record = _news_governance.upsert_news_model_eval_record
load_news_model_eval_records = _news_governance.load_news_model_eval_records
upsert_event_target_v2 = _v2.upsert_event_target_v2
load_event_target_v2 = _v2.load_event_target_v2
delete_event_target_v2_window = _v2.delete_event_target_v2_window
upsert_exp_return_bucket_stats_v2 = _v2.upsert_exp_return_bucket_stats_v2
load_exp_return_bucket_stats_v2 = _v2.load_exp_return_bucket_stats_v2
upsert_event_factor_scores_v2 = _v2.upsert_event_factor_scores_v2
load_event_factor_scores_v2 = _v2.load_event_factor_scores_v2
upsert_model_pred_v2 = _v2.upsert_model_pred_v2
load_model_pred_v2 = _v2.load_model_pred_v2
upsert_gate_run_v2 = _v2.upsert_gate_run_v2
load_gate_run_v2 = _v2.load_gate_run_v2

__all__ = [
    "upsert_instruments",
    "upsert_contract_specs",
    "store_dividends",
    "store_key_rates",
    "load_instruments",
    "load_contract_specs",
    "load_dividends",
    "load_key_rates",
    "store_signal_run",
    "store_signal_history",
    "delete_signal_history_run",
    "store_signal_execution",
    "load_latest_signal_run",
    "load_signal_history",
    "load_active_signals",
    "load_open_executions",
    "upsert_quotes",
    "load_signal_executions",
    "upsert_decision_view_projection",
    "load_decision_view_projection",
    "upsert_news_items",
    "load_news_items",
    "load_news_items_by_ids",
    "upsert_news_entity_links",
    "load_news_entity_links",
    "upsert_news_tags",
    "load_news_tags",
    "upsert_news_item_tags",
    "load_news_item_tags",
    "upsert_news_impact_scores",
    "load_news_impact_scores",
    "load_primary_news_scores",
    "upsert_news_signal_links",
    "load_news_signal_links",
    "upsert_news_backtest_report",
    "load_news_backtest_reports",
    "upsert_news_events",
    "load_news_events",
    "upsert_news_event_items",
    "load_news_event_items",
    "upsert_news_labels",
    "load_news_labels",
    "upsert_news_llm_runs",
    "load_news_llm_runs",
    "upsert_event_market_reactions",
    "load_event_market_reactions",
    "upsert_news_annotations",
    "load_news_annotations",
    "upsert_news_event_updates",
    "load_news_event_updates",
    "upsert_news_event_links",
    "load_news_event_links",
    "upsert_news_gold_labels",
    "load_news_gold_labels",
    "upsert_news_unmatched_gold",
    "load_news_unmatched_gold",
    "upsert_news_model_eval_record",
    "load_news_model_eval_records",
    "upsert_event_target_v2",
    "load_event_target_v2",
    "delete_event_target_v2_window",
    "upsert_exp_return_bucket_stats_v2",
    "load_exp_return_bucket_stats_v2",
    "upsert_event_factor_scores_v2",
    "load_event_factor_scores_v2",
    "upsert_model_pred_v2",
    "load_model_pred_v2",
    "upsert_gate_run_v2",
    "load_gate_run_v2",
]
