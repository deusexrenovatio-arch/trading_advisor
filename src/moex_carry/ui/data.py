from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

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


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _projection_candidates(
    data_dir: Path,
    file_name: str,
    *,
    preferred_engine: str | None,
) -> list[dict[str, Any]]:
    output_dir = data_dir / "output"
    candidates: list[dict[str, Any]] = []
    engine = str(preferred_engine or "").strip().lower()
    if engine:
        engine_dir = output_dir / engine
        candidates.append(
            {
                "engine": engine,
                "path": engine_dir / file_name,
                "meta_path": engine_dir / "snapshot_meta.json",
            }
        )
    candidates.append(
        {
            "engine": "legacy",
            "path": output_dir / file_name,
            "meta_path": output_dir / "snapshot_meta.json",
        }
    )
    return candidates


def _dataset_key_from_file_name(file_name: str) -> str:
    if file_name.endswith(".csv"):
        return file_name[:-4]
    return file_name


def _candidate_state(candidate: dict[str, Any]) -> dict[str, Any]:
    path = Path(candidate["path"])
    meta_path = Path(candidate["meta_path"])
    csv_exists = path.exists()
    meta_exists = meta_path.exists()
    modified_at_utc = None
    if csv_exists:
        modified_at_utc = (
            pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC").isoformat().replace("+00:00", "Z")
        )
    return {
        "engine": candidate["engine"],
        "path": str(path).replace("\\", "/"),
        "exists": bool(csv_exists),
        "modified_at_utc": modified_at_utc,
        "meta_path": str(meta_path).replace("\\", "/"),
        "meta_exists": bool(meta_exists),
    }


def _extract_meta_info(meta: dict[str, Any], file_name: str) -> dict[str, Any]:
    dataset_key = _dataset_key_from_file_name(file_name)
    generated_at = meta.get("generated_at_utc") if isinstance(meta, dict) else None
    dataset_meta = {}
    datasets = meta.get("datasets") if isinstance(meta, dict) else None
    if isinstance(datasets, dict):
        payload = datasets.get(dataset_key)
        if isinstance(payload, dict):
            dataset_meta = payload
    return {
        "generated_at_utc": generated_at,
        "dataset_meta": dataset_meta,
    }


def _load_projection_csv(
    data_dir: Path,
    file_name: str,
    *,
    preferred_engine: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    candidates = _projection_candidates(
        data_dir,
        file_name,
        preferred_engine=preferred_engine,
    )
    source: dict[str, Any] = {
        "dataset": _dataset_key_from_file_name(file_name),
        "preferred_engine": str(preferred_engine).strip().lower() if preferred_engine else None,
        "selected_engine": None,
        "selected_path": None,
        "selected_meta_path": None,
        "selected_generated_at_utc": None,
        "selected_rows": 0,
        "selected_sha256": None,
        "fallback_to_legacy": False,
        "candidates": [_candidate_state(item) for item in candidates],
    }
    for candidate in candidates:
        path = Path(candidate["path"])
        if not path.exists():
            continue
        df = _safe_read_csv(path)
        meta_path = Path(candidate["meta_path"])
        meta = _safe_read_json(meta_path)
        meta_info = _extract_meta_info(meta, file_name)
        source["selected_engine"] = candidate["engine"]
        source["selected_path"] = str(path).replace("\\", "/")
        source["selected_meta_path"] = str(meta_path).replace("\\", "/") if meta_path.exists() else None
        source["selected_generated_at_utc"] = meta_info.get("generated_at_utc")
        source["selected_rows"] = int(len(df))
        dataset_meta = meta_info.get("dataset_meta")
        if isinstance(dataset_meta, dict):
            source["selected_sha256"] = dataset_meta.get("sha256")
        preferred = str(preferred_engine or "").strip().lower()
        source["fallback_to_legacy"] = bool(preferred and candidate["engine"] != preferred)
        return df, source
    return pd.DataFrame(), source


def load_top_pairs_with_source(
    data_dir: Path,
    *,
    preferred_engine: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    df, source = _load_projection_csv(data_dir, "top_pairs.csv", preferred_engine=preferred_engine)
    return _parse_struct_columns(df, ["signal_reasons", "signal_metrics"]), source


def load_signals_with_source(
    data_dir: Path,
    *,
    preferred_engine: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    df, source = _load_projection_csv(data_dir, "signals.csv", preferred_engine=preferred_engine)
    return _parse_struct_columns(df, ["signal_reasons", "signal_metrics"]), source


def load_backtest_summary_with_source(
    data_dir: Path,
    *,
    preferred_engine: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    return _load_projection_csv(data_dir, "backtest_summary.csv", preferred_engine=preferred_engine)


def load_top_pairs(data_dir: Path, *, preferred_engine: str | None = None) -> pd.DataFrame:
    df, _ = load_top_pairs_with_source(data_dir, preferred_engine=preferred_engine)
    return df


def load_signals(data_dir: Path, *, preferred_engine: str | None = None) -> pd.DataFrame:
    df, _ = load_signals_with_source(data_dir, preferred_engine=preferred_engine)
    return df


def load_backtest_summary(data_dir: Path, *, preferred_engine: str | None = None) -> pd.DataFrame:
    df, _ = load_backtest_summary_with_source(data_dir, preferred_engine=preferred_engine)
    return df


def load_projection_sources(
    data_dir: Path,
    *,
    preferred_engine: str | None = None,
) -> dict[str, Any]:
    _, top_source = load_top_pairs_with_source(data_dir, preferred_engine=preferred_engine)
    _, signals_source = load_signals_with_source(data_dir, preferred_engine=preferred_engine)
    _, backtest_source = load_backtest_summary_with_source(data_dir, preferred_engine=preferred_engine)
    return {
        "preferred_engine": str(preferred_engine).strip().lower() if preferred_engine else None,
        "datasets": {
            "top_pairs": top_source,
            "signals": signals_source,
            "backtest_summary": backtest_source,
        },
    }


def load_decision_view(data_dir: Path) -> pd.DataFrame:
    return _safe_read_jsonl(data_dir / "decisions" / "decision_view.jsonl")


def load_decision_log(data_dir: Path) -> pd.DataFrame:
    return _safe_read_jsonl(data_dir / "decisions" / "decision_log.jsonl")
