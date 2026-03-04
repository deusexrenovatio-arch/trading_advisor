from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

from moex_carry.signal_engine.core.calendar import MarketCalendar, TimeWindow
from moex_carry.signal_engine.core.types import Candle, Level, OrderIntent, OrderType, Setup, Side, TF
from moex_carry.signal_engine.data.candles import InMemoryCandleProvider
from moex_carry.signal_engine.plan.builder import MorningPlanBuilder


def _trend_series(start: datetime, count: int, step: timedelta, slope: float) -> list[Candle]:
    rows: list[Candle] = []
    for idx in range(count):
        close = 100.0 + slope * idx
        rows.append(
            Candle(
                ts=start + idx * step,
                open=close - 0.2,
                high=close + 0.7,
                low=close - 0.7,
                close=close,
                volume=1_000.0 + idx,
            )
        )
    return rows


def _init_news_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE news_articles (
                article_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                commodity TEXT NOT NULL,
                source_name TEXT,
                published_at_utc TEXT NOT NULL,
                fetched_at_utc TEXT NOT NULL,
                title TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE news_scores (
                article_id TEXT PRIMARY KEY,
                model_name TEXT NOT NULL,
                scored_at_utc TEXT NOT NULL,
                direction TEXT NOT NULL,
                impact_score REAL NOT NULL,
                confidence REAL NOT NULL,
                severity TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_news(path: Path, *, article_id: str, commodity: str, ts: datetime, severity: str) -> None:
    iso = ts.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO news_articles (
                article_id, provider, commodity, source_name, published_at_utc, fetched_at_utc, title
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (article_id, "test", commodity, "UnitTestFeed", iso, iso, f"{commodity} headline"),
        )
        conn.execute(
            """
            INSERT INTO news_scores (
                article_id, model_name, scored_at_utc, direction, impact_score, confidence, severity
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (article_id, "keyword_v1", iso, "neutral", 0.8, 0.95, severity),
        )
        conn.commit()
    finally:
        conn.close()


def _sample_setup(setup_id: str, side: Side) -> Setup:
    direction = 1 if side == Side.BUY else -1
    entry_ticks = 10_000
    sl_ticks = entry_ticks - direction * 40
    tp_ticks = entry_ticks + direction * 80
    level = Level(tf=TF.H1, kind="BOX_H", price_ticks=entry_ticks, score=0.9, meta={})
    return Setup(
        setup_id=setup_id,
        side=side,
        entry_level=level,
        entry_order=OrderIntent(
            order_type=OrderType.STOP_LIMIT,
            side=side,
            price_ticks=entry_ticks,
            qty_lots=1,
            tif="GTT",
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL if side == Side.BUY else Side.BUY,
            price_ticks=sl_ticks,
            qty_lots=1,
            tif="GTT",
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL if side == Side.BUY else Side.BUY,
            price_ticks=tp_ticks,
            qty_lots=1,
            tif="GTT",
        ),
        horizon="EOD",
        rationale=["unit_test"],
        risk_ticks=40,
    )


def test_morning_plan_builder_is_deterministic():
    tz = ZoneInfo("Europe/Moscow")
    start = datetime(2026, 1, 1, 10, 0, tzinfo=tz)
    instrument = "BRH6"
    payload = {
        (instrument, TF.D1): _trend_series(start, 80, timedelta(days=1), slope=0.8),
        (instrument, TF.H1): _trend_series(start, 300, timedelta(hours=1), slope=0.05),
        (instrument, TF.M5): _trend_series(start, 1_000, timedelta(minutes=5), slope=0.005),
    }
    provider = InMemoryCandleProvider(payload)
    calendar = MarketCalendar(
        tz_name="Europe/Moscow",
        sessions=[TimeWindow(start=time(10, 0), end=time(23, 50))],
        clearing=[TimeWindow(start=time(14, 0), end=time(14, 5)), TimeWindow(start=time(18, 50), end=time(19, 5))],
        forbid_margin_min=5,
    )
    cfg = {
        "data": {"d1_limit": 80, "h1_limit": 300, "m5_limit": 1000},
        "regime": {
            "d1": {
                "ema_fast": 5,
                "ema_slow": 10,
                "adx_period": 5,
                "er_period": 5,
                "dir_band_atr_mult": 0.10,
                "adx_trend_min": 10,
                "adx_range_max": 8,
                "er_trend_min": 0.1,
                "er_range_max": 0.05,
                "atr_period": 5,
                "atr_rank_lookback": 20,
                "vol_high_pct": 0.7,
                "vol_low_pct": 0.3,
            },
            "h1": {"ema_fast": 5, "ema_slow": 10, "atr_period": 5, "dir_band_atr_mult": 0.1},
            "liquidity": {"spread_thin_ticks": 2, "spread_vacuum_ticks": 4, "depth_thin_lots": 50, "depth_vacuum_lots": 20},
        },
        "levels": {
            "merge_distance_ticks": 1,
            "d1": {"donchian_period": 20, "pivots": True},
            "h1": {"swing_k": 2, "max_swings_each_side": 8, "box_hours": 6, "box_range_atr_mult": 1.2, "include_ema20_level": True},
        },
        "execution": {
            "m5_atr_period": 14,
            "buffer_atr_mult": 0.10,
            "buffer_min_ticks": 1,
            "limit_slip_ticks": 2,
            "noise_warn_high": 2.5,
            "noise_warn_low": 0.4,
            "swing_k": 2,
        },
        "setups": {
            "max_setups_per_instrument": 2,
            "require_vol_not_low": True,
            "pullback_max_dist_atr_mult": 1.0,
            "rr_default": 1.6,
            "min_target_ticks": 3,
            "max_risk_atr_mult": 1.2,
            "entry_expiry_policy": "EOD_BEFORE_EVENING_CLEARING",
        },
    }
    builder = MorningPlanBuilder(provider, calendar, cfg)
    as_of_ts = payload[(instrument, TF.M5)][-1].ts
    plan_a = builder.build_plan(as_of_ts=as_of_ts, instrument_id=instrument, tick_size=0.01)
    plan_b = builder.build_plan(as_of_ts=as_of_ts, instrument_id=instrument, tick_size=0.01)

    assert plan_a == plan_b
    assert len(plan_a.levels) > 0
    assert len(plan_a.setups) <= 2


def test_morning_plan_news_gate_blocks_setups(tmp_path):
    tz = ZoneInfo("Europe/Moscow")
    start = datetime(2026, 1, 1, 10, 0, tzinfo=tz)
    instrument = "BRH6"
    payload = {
        (instrument, TF.D1): _trend_series(start, 80, timedelta(days=1), slope=0.8),
        (instrument, TF.H1): _trend_series(start, 300, timedelta(hours=1), slope=0.05),
        (instrument, TF.M5): _trend_series(start, 1_000, timedelta(minutes=5), slope=0.005),
    }
    provider = InMemoryCandleProvider(payload)
    calendar = MarketCalendar(
        tz_name="Europe/Moscow",
        sessions=[TimeWindow(start=time(10, 0), end=time(23, 50))],
        clearing=[TimeWindow(start=time(14, 0), end=time(14, 5)), TimeWindow(start=time(18, 50), end=time(19, 5))],
        forbid_margin_min=5,
    )
    db_path = tmp_path / "news.db"
    _init_news_db(db_path)
    as_of_ts = payload[(instrument, TF.M5)][-1].ts
    _insert_news(
        db_path,
        article_id="block-1",
        commodity="BRN",
        ts=as_of_ts - timedelta(minutes=20),
        severity="high",
    )
    cfg = {
        "data": {"d1_limit": 80, "h1_limit": 300, "m5_limit": 1000},
        "news_gate": {
            "enabled": True,
            "db_url": f"sqlite:///{db_path}",
            "lookback_minutes": 180,
            "block_severity_threshold": "high",
            "reduce_severity_threshold": "medium",
            "commodity_map": {"BR": "BRN"},
            "reduce_max_setups": 1,
        },
    }
    builder = MorningPlanBuilder(provider, calendar, cfg)
    builder.setup_gen.generate = lambda **_: [_sample_setup("S1", Side.BUY), _sample_setup("S2", Side.BUY)]  # type: ignore[assignment]

    plan = builder.build_plan(as_of_ts=as_of_ts, instrument_id=instrument, tick_size=0.01)

    assert plan.setups == []
    assert any("news_gate:block" in item for item in plan.warnings)


def test_morning_plan_news_gate_reduces_setups(tmp_path):
    tz = ZoneInfo("Europe/Moscow")
    start = datetime(2026, 1, 1, 10, 0, tzinfo=tz)
    instrument = "NGH6"
    payload = {
        (instrument, TF.D1): _trend_series(start, 80, timedelta(days=1), slope=0.6),
        (instrument, TF.H1): _trend_series(start, 300, timedelta(hours=1), slope=0.03),
        (instrument, TF.M5): _trend_series(start, 1_000, timedelta(minutes=5), slope=0.003),
    }
    provider = InMemoryCandleProvider(payload)
    calendar = MarketCalendar(
        tz_name="Europe/Moscow",
        sessions=[TimeWindow(start=time(10, 0), end=time(23, 50))],
        clearing=[TimeWindow(start=time(14, 0), end=time(14, 5)), TimeWindow(start=time(18, 50), end=time(19, 5))],
        forbid_margin_min=5,
    )
    db_path = tmp_path / "news.db"
    _init_news_db(db_path)
    as_of_ts = payload[(instrument, TF.M5)][-1].ts
    _insert_news(
        db_path,
        article_id="reduce-1",
        commodity="NG_US",
        ts=as_of_ts - timedelta(minutes=30),
        severity="medium",
    )
    cfg = {
        "data": {"d1_limit": 80, "h1_limit": 300, "m5_limit": 1000},
        "news_gate": {
            "enabled": True,
            "db_url": f"sqlite:///{db_path}",
            "lookback_minutes": 180,
            "block_severity_threshold": "high",
            "reduce_severity_threshold": "medium",
            "commodity_map": {"NG": "NG_US"},
            "reduce_max_setups": 1,
        },
    }
    builder = MorningPlanBuilder(provider, calendar, cfg)
    builder.setup_gen.generate = lambda **_: [_sample_setup("S1", Side.BUY), _sample_setup("S2", Side.BUY)]  # type: ignore[assignment]

    plan = builder.build_plan(as_of_ts=as_of_ts, instrument_id=instrument, tick_size=0.01)

    assert len(plan.setups) == 1
    assert plan.setups[0].setup_id == "S1"
    assert any("news_gate:reduce" in item for item in plan.warnings)
