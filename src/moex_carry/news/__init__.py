from __future__ import annotations

from moex_carry.news.bridge import build_news_items_for_gate, build_signal_news_links, run_news_gate
from moex_carry.news.anchors import (
    AnchorLinkReport,
    AnchorSeedReport,
    EpisodicAnchorSeedReport,
    link_news_to_scheduled_anchors,
    seed_canonical_scheduled_events,
    seed_episodic_anchor_events,
)
from moex_carry.news.benchmark import (
    choose_recommended_case,
    parse_positive_int_list,
    run_news_inference_benchmark,
)
from moex_carry.news.backfill import NewsBackfillReport, run_news_backfill, run_news_qc
from moex_carry.news.events import (
    EventClusteringReport,
    cluster_news_events,
    compute_event_fragmentation_report,
)
from moex_carry.news.ingestion import fetch_rss_news, normalize_news_record
from moex_carry.news.inference import (
    apply_inference_runtime_limits,
    run_dual_model_inference,
    run_dual_model_inference_batch,
)
from moex_carry.news.llm_gateway import (
    NewsLlmPassReport,
    build_news_llm_batch_requests,
    run_news_llm_full_pass,
)
from moex_carry.news.linking import default_tag_rows, link_news_item
from moex_carry.news.reaction import (
    EventReactionBuildReport,
    build_event_study_leakage_audit,
    rebuild_event_market_reactions,
    summarize_event_study,
)
from moex_carry.news.research import compare_news_models, run_news_backtest
from moex_carry.news.sync import NewsSyncSnapshot, run_news_sync_worker, sync_news_runtime

__all__ = [
    "build_news_items_for_gate",
    "build_signal_news_links",
    "run_news_gate",
    "AnchorSeedReport",
    "AnchorLinkReport",
    "EpisodicAnchorSeedReport",
    "seed_canonical_scheduled_events",
    "seed_episodic_anchor_events",
    "link_news_to_scheduled_anchors",
    "parse_positive_int_list",
    "choose_recommended_case",
    "run_news_inference_benchmark",
    "NewsBackfillReport",
    "run_news_backfill",
    "run_news_qc",
    "EventClusteringReport",
    "cluster_news_events",
    "compute_event_fragmentation_report",
    "fetch_rss_news",
    "normalize_news_record",
    "apply_inference_runtime_limits",
    "run_dual_model_inference",
    "run_dual_model_inference_batch",
    "NewsLlmPassReport",
    "build_news_llm_batch_requests",
    "run_news_llm_full_pass",
    "default_tag_rows",
    "link_news_item",
    "EventReactionBuildReport",
    "build_event_study_leakage_audit",
    "rebuild_event_market_reactions",
    "summarize_event_study",
    "compare_news_models",
    "run_news_backtest",
    "NewsSyncSnapshot",
    "sync_news_runtime",
    "run_news_sync_worker",
]
