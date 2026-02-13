from __future__ import annotations

from moex_carry.news.bridge import build_news_items_for_gate, build_signal_news_links, run_news_gate
from moex_carry.news.ingestion import fetch_rss_news, normalize_news_record
from moex_carry.news.inference import run_dual_model_inference
from moex_carry.news.linking import default_tag_rows, link_news_item
from moex_carry.news.research import compare_news_models, run_news_backtest

__all__ = [
    "build_news_items_for_gate",
    "build_signal_news_links",
    "run_news_gate",
    "fetch_rss_news",
    "normalize_news_record",
    "run_dual_model_inference",
    "default_tag_rows",
    "link_news_item",
    "compare_news_models",
    "run_news_backtest",
]
