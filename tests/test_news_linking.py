from __future__ import annotations

from pathlib import Path

from moex_carry.news.linking import link_news_item
from moex_carry.news.linking import score_commodity_links
from moex_carry.news.linking_benchmark import evaluate_link_benchmark, load_link_benchmark_cases
from moex_carry.news_live_runtime import NewsIngestConfig


def _discovery_predictions(title: str) -> list[str]:
    cfg = NewsIngestConfig.from_yaml(Path("configs/news-livecheck-ng.yaml"))
    allowed = {profile.ticker for profile in cfg.commodity_profiles}
    return [
        item.commodity_id
        for item in score_commodity_links(title=title)
        if item.commodity_id in allowed and float(item.score) >= float(cfg.discovery_min_link_score)
    ]


def test_warmer_goes_to_weather_not_geopolitics():
    result = link_news_item(
        news_id="news-1",
        title="Scientists say warmer temperatures may lift gas demand this winter",
        content="Natural gas consumption can rise during cold and weather shocks.",
    )
    assert "WEATHER" in result.tag_codes
    assert "GEO_POL" not in result.tag_codes


def test_war_word_still_maps_to_geopolitics():
    result = link_news_item(
        news_id="news-2",
        title="War risk in shipping lanes threatens commodity flows",
        content="Geopolitical conflict impacts exports.",
    )
    assert "GEO_POL" in result.tag_codes


def test_score_commodity_links_rejects_generic_mine_strike_leakage() -> None:
    predicted = _discovery_predictions("South Africa mine strike threatens platinum and palladium supply")

    assert "PLATINUM" in predicted
    assert "PALLADIUM" in predicted
    assert "COPPER" not in predicted


def test_score_commodity_links_rejects_weather_only_wheat_leakage() -> None:
    predicted = _discovery_predictions("Brazil drought damages coffee and sugar cane crops")

    assert "COFFEE" in predicted
    assert "SUGAR" in predicted
    assert "WHEAT" not in predicted


def test_score_commodity_links_keeps_cross_commodity_energy_story() -> None:
    predicted = _discovery_predictions(
        "Oil and natural gas surge after Iran orders Strait of Hormuz closure"
    )

    assert "BRN" in predicted
    assert "NG_US" in predicted


def test_multi_commodity_link_benchmark_meets_false_assignment_threshold() -> None:
    cfg = NewsIngestConfig.from_yaml(Path("configs/news-livecheck-ng.yaml"))
    cases = load_link_benchmark_cases(Path("docs/research/news_multi_commodity_benchmark.csv"))
    allowed = tuple(profile.ticker for profile in cfg.commodity_profiles)
    summary, _rows = evaluate_link_benchmark(
        cases=cases,
        allowed_commodities=allowed,
        min_link_score=float(cfg.discovery_min_link_score),
    )

    assert summary["false_multi_commodity_assignment_rate"] <= 0.10
    assert summary["assignment_recall"] >= 0.95
    assert summary["rows_with_missing"] == 0
