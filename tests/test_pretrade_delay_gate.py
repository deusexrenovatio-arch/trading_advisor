from moex_carry.pretrade.delay_gate import run_delay_gate


class _FakeMoexClientSequence:
    def __init__(self, stock: str, future: str, frames: list[dict[str, dict[str, object]]]) -> None:
        self._stock = stock
        self._future = future
        self._frames = frames
        self._idx = 0

    def get_marketdata(self, _engine: str, _market: str, _board: str, secid: str):
        idx = min(self._idx, len(self._frames) - 1)
        frame = self._frames[idx]
        if secid == self._stock:
            return [frame["stock"]]
        if secid == self._future:
            self._idx += 1
            return [frame["future"]]
        return []


def _frame(stock_numtrades: int, fut_numtrades: int):
    return {
        "stock": {
            "BID": 99.9,
            "OFFER": 100.1,
            "LAST": 100.0,
            "VOLTODAY": 1000,
            "NUMTRADES": stock_numtrades,
            "SYSTIME": "2026-02-09 16:40:00",
        },
        "future": {
            "BID": None,
            "OFFER": None,
            "LAST": 1010.0,
            "VOLTODAY": 100,
            "NUMTRADES": fut_numtrades,
            "SYSTIME": "2026-02-09 16:40:30",
        },
    }


def test_delay_gate_strict_tradeflow_blocks_missing_fut_price_hit():
    frames = [_frame(10, 10), _frame(10, 10), _frame(10, 10)]
    client = _FakeMoexClientSequence("AAA", "AAH6", frames)
    result = run_delay_gate(
        client,
        stock="AAA",
        future="AAH6",
        direction="cash_and_carry",
        spot_target=100.0,
        future_target=101.0,
        spread_target=-1.0,
        future_scale=10.0,
        qty_fut=1.0,
        participation_rate=0.1,
        snapshots=3,
        min_hits=2,
        eps=0.002,
        sync_sec=120.0,
        poll_sec=0.0,
        require_tradeflow_for_last=True,
    )
    assert result["ready_to_place"] is False
    assert result["status"] == "CHECK"
    assert result["gates"]["fut_quote_pass"] is False
    assert "fut_quote_missing" in result["reasons"]
    assert "fut_range_miss" in result["reasons"]


def test_delay_gate_practical_last_fallback_passes_with_volume_and_spread():
    frames = [_frame(10, 10), _frame(10, 10), _frame(10, 10)]
    client = _FakeMoexClientSequence("AAA", "AAH6", frames)
    result = run_delay_gate(
        client,
        stock="AAA",
        future="AAH6",
        direction="cash_and_carry",
        spot_target=100.0,
        future_target=101.0,
        spread_target=-1.0,
        future_scale=10.0,
        qty_fut=1.0,
        participation_rate=0.1,
        snapshots=3,
        min_hits=2,
        eps=0.002,
        sync_sec=120.0,
        poll_sec=0.0,
        require_tradeflow_for_last=False,
        require_live_quotes_for_legs=False,
    )
    assert result["ready_to_place"] is True
    assert result["status"] == "PLACE"
    assert result["gates"]["fut_quote_pass"] is False
    assert "fut_quote_missing" in result["warnings"]
    assert result["gates"]["stock_volume_pass"] is True
    assert result["gates"]["fut_volume_pass"] is True
