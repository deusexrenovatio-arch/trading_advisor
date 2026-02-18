from __future__ import annotations

from moex_carry.news.benchmark import choose_recommended_case, parse_positive_int_list


def test_parse_positive_int_list_uses_default_when_invalid_input():
    values = parse_positive_int_list("abc,-1,0", default=[2, 4])
    assert values == [2, 4]


def test_parse_positive_int_list_deduplicates_and_preserves_order():
    values = parse_positive_int_list("4,2,4,1,2", default=[1])
    assert values == [4, 2, 1]


def test_choose_recommended_case_prefers_higher_throughput_then_lower_p95():
    cases = [
        {
            "thread_cap": 4,
            "batch_size": 1,
            "text_max_chars": 1500,
            "throughput_items_per_sec": 10.0,
            "latency_ms_p95": 120.0,
        },
        {
            "thread_cap": 2,
            "batch_size": 2,
            "text_max_chars": 1500,
            "throughput_items_per_sec": 12.0,
            "latency_ms_p95": 160.0,
        },
        {
            "thread_cap": 3,
            "batch_size": 1,
            "text_max_chars": 1500,
            "throughput_items_per_sec": 12.0,
            "latency_ms_p95": 130.0,
        },
    ]

    selected = choose_recommended_case(cases)
    assert selected is not None
    assert selected["thread_cap"] == 3
    assert selected["batch_size"] == 1

