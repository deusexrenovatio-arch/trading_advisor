from __future__ import annotations

from moex_carry.news.linking import link_news_item


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
