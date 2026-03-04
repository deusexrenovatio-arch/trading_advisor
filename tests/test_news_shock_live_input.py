from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from moex_carry.news_shock_live_input import LiveShockInputConfig, _build_shocks_for_symbol


def _prices_with_single_jump() -> tuple[pd.DataFrame, datetime]:
    start = datetime(2026, 1, 20, 8, 0, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    price = 100.0
    shock_ts = start + timedelta(minutes=5 * 12)
    for idx in range(30):
        ts = start + timedelta(minutes=5 * idx)
        if ts == shock_ts:
            price += 4.5
        else:
            price += 0.03
        rows.append({"ts": ts, "price": price, "secid": "TEST"})
    return pd.DataFrame(rows), shock_ts


def _single_news(*, published_dt: datetime) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "article_id": "news-15m-before",
                "published_at_utc": published_dt.isoformat().replace("+00:00", "Z"),
                "published_dt": published_dt,
                "title": "Natural gas weather disruption supports prices",
                "description": "",
                "url": "https://example/news-15m-before",
                "relevance": 1.2,
                "is_same_commodity": True,
                "confidence": 0.95,
                "impact_score": 0.92,
                "commodity": "NG_US",
            }
        ]
    )


def _cfg(*, strict_minutes: float) -> LiveShockInputConfig:
    return LiveShockInputConfig(
        bar_minutes=5,
        min_abs_z=2.0,
        rolling_window_bars=8,
        rolling_min_bars=4,
        max_delay_minutes=60.0,
        strict_pre_shock_minutes=strict_minutes,
        broad_context_lookback_minutes=2880.0,
        v2_min_relevance=0.4,
        broad_min_relevance=0.2,
        cross_commodity_min_relevance=2.5,
    )


def _row_at_shock_ts(df: pd.DataFrame, *, shock_ts: datetime) -> pd.Series:
    assert not df.empty
    iso = shock_ts.isoformat().replace("+00:00", "Z")
    matched = df[df["shock_ts"].astype(str) == iso]
    assert not matched.empty
    return matched.iloc[0]


def test_strict_pre_shock_window_blocks_15m_news_when_window_is_10m() -> None:
    prices, shock_ts = _prices_with_single_jump()
    news = _single_news(published_dt=shock_ts - timedelta(minutes=15))

    result = _build_shocks_for_symbol(
        symbol="NG_US",
        prices=prices,
        news_rows=news,
        start_utc=prices["ts"].min().to_pydatetime(),
        end_utc=prices["ts"].max().to_pydatetime(),
        cfg=_cfg(strict_minutes=10.0),
    )

    row = _row_at_shock_ts(result, shock_ts=shock_ts)
    assert str(row.get("selected_event_id") or "") == ""
    assert str(row.get("selected_match_mode") or "none") in {"none", "root_reuse"}


def test_strict_pre_shock_window_allows_15m_news_when_window_is_20m() -> None:
    prices, shock_ts = _prices_with_single_jump()
    news = _single_news(published_dt=shock_ts - timedelta(minutes=15))

    result = _build_shocks_for_symbol(
        symbol="NG_US",
        prices=prices,
        news_rows=news,
        start_utc=prices["ts"].min().to_pydatetime(),
        end_utc=prices["ts"].max().to_pydatetime(),
        cfg=_cfg(strict_minutes=20.0),
    )

    row = _row_at_shock_ts(result, shock_ts=shock_ts)
    assert str(row.get("selected_event_id") or "") == "news-15m-before"
    assert str(row.get("selected_match_mode") or "") == "v2_strict"
    assert float(pd.to_numeric(row.get("selected_delay_min"), errors="coerce")) == 15.0
