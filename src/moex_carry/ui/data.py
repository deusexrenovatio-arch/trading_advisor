from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()


def _safe_read_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    if not records:
        return pd.DataFrame()
    return pd.json_normalize(records)


def _parse_struct_value(value: object):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
    return value


def _parse_struct_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    for column in columns:
        if column in df.columns:
            df[column] = df[column].map(_parse_struct_value)
    return df


def load_top_pairs(data_dir: Path) -> pd.DataFrame:
    df = _safe_read_csv(data_dir / "output" / "top_pairs.csv")
    return _parse_struct_columns(df, ["signal_reasons", "signal_metrics"])


def load_signals(data_dir: Path) -> pd.DataFrame:
    df = _safe_read_csv(data_dir / "output" / "signals.csv")
    return _parse_struct_columns(df, ["signal_reasons", "signal_metrics"])


def load_backtest_summary(data_dir: Path) -> pd.DataFrame:
    return _safe_read_csv(data_dir / "output" / "backtest_summary.csv")


def load_decision_view(data_dir: Path) -> pd.DataFrame:
    return _safe_read_jsonl(data_dir / "decisions" / "decision_view.jsonl")


def load_decision_log(data_dir: Path) -> pd.DataFrame:
    return _safe_read_jsonl(data_dir / "decisions" / "decision_log.jsonl")
