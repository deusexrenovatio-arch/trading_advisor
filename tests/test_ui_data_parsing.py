import pandas as pd

from moex_carry.ui.data import load_signals, load_top_pairs


def _write_csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)


def test_signal_fields_parse_from_csv(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "top_pairs.csv",
        [
            {
                "stock": "AAA",
                "future": "AAH6",
                "signal_reasons": "['zscore_revert', 'implied_rate_above_required']",
                "signal_metrics": "{'zscore': -0.12, 'required_rate': 0.17}",
            }
        ],
    )
    _write_csv(
        output_dir / "signals.csv",
        [
            {
                "stock": "AAA",
                "future": "AAH6",
                "signal_reasons": "['zscore_revert']",
                "signal_metrics": "{'zscore': -0.12}",
            }
        ],
    )

    top_pairs = load_top_pairs(tmp_path)
    signals = load_signals(tmp_path)

    assert isinstance(top_pairs.loc[0, "signal_reasons"], list)
    assert isinstance(top_pairs.loc[0, "signal_metrics"], dict)
    assert isinstance(signals.loc[0, "signal_reasons"], list)
    assert isinstance(signals.loc[0, "signal_metrics"], dict)
