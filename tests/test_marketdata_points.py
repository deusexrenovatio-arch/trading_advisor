from moex_carry.data.marketdata import build_fut_point, build_stock_point


def test_build_stock_point_extracts_orderbook_depth_and_age():
    row = {
        "BID": 100.0,
        "OFFER": 100.2,
        "BIDDEPTHT": 1200,
        "OFFERDEPTHT": 800,
        "VOLTODAY": 5000,
        "SYSTIME": "2026-02-09 10:20:00",
        "UPDATETIME": "10:15:00",
    }
    point = build_stock_point(row)
    assert point.bid_depth == 1200.0
    assert point.ask_depth == 800.0
    assert point.quote_age_sec == 300.0


def test_build_fut_point_extracts_orderbook_depth_and_age():
    row = {
        "BID": 300.0,
        "OFFER": 300.5,
        "BIDDEPTH": 250,
        "OFFERDEPTH": 200,
        "OPENPOSITION": 12_000,
        "SYSTIME": "2026-02-09 10:20:10",
        "UPDATETIME": "10:19:40",
    }
    point = build_fut_point(row)
    assert point.bid_depth == 250.0
    assert point.ask_depth == 200.0
    assert point.quote_age_sec == 30.0
