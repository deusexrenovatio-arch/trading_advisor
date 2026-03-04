from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


SUPPORTED_SYMBOLS = ("BRN", "GOLD", "NG_US")


@dataclass(frozen=True)
class ShockCurationConfig:
    max_abs_move_pct_by_symbol: dict[str, float]
    max_abs_z_by_symbol: dict[str, float]

    @staticmethod
    def defaults() -> "ShockCurationConfig":
        return ShockCurationConfig(
            max_abs_move_pct_by_symbol={
                "BRN": 15.0,
                "GOLD": 8.0,
                "NG_US": 40.0,
            },
            max_abs_z_by_symbol={
                "BRN": 15.0,
                "GOLD": 15.0,
                "NG_US": 25.0,
            },
        )


@dataclass(frozen=True)
class LabelPackConfig:
    min_abs_z: float = 2.5
    max_tasks_total: int = 1200
    max_tasks_per_day_symbol: int = 20
    max_secondary_candidates: int = 4
    max_delay_minutes: float = 60.0
    candidate_sources: tuple[str, ...] | None = None
    causal_only: bool = False


_DIRECTION_MAP = {
    "up": "up",
    "bull": "up",
    "bullish": "up",
    "long": "up",
    "buy": "up",
    "down": "down",
    "bear": "down",
    "bearish": "down",
    "short": "down",
    "sell": "down",
    "hold": "hold",
    "neutral": "hold",
    "flat": "hold",
    "none": "hold",
}
_VALID_CANDIDATE_SOURCES = ("v2_clean", "broad", "none")


def _norm_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).strip().split())


def _normalize_candidate_sources(value: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    normalized = tuple(
        dict.fromkeys(
            _norm_text(item).lower()
            for item in value
            if _norm_text(item)
        )
    )
    if not normalized:
        return None
    unknown = sorted(item for item in normalized if item not in _VALID_CANDIDATE_SOURCES)
    if unknown:
        raise ValueError(
            f"Unsupported candidate source filter values: {unknown}. "
            f"Supported: {list(_VALID_CANDIDATE_SOURCES)}"
        )
    return normalized


def _parse_ts_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def _to_float(value: object) -> float | None:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return None
    return float(num)


def _candidate(row: pd.Series, source: str) -> dict[str, Any] | None:
    prefix = "v2" if source == "v2_clean" else "broad"
    event_id = _norm_text(row.get(f"{prefix}_event_id"))
    if not event_id:
        return None
    delay = _to_float(row.get(f"{prefix}_delay_min"))
    return {
        "source": source,
        "event_id": event_id,
        "event_ts_utc": _norm_text(row.get(f"{prefix}_event_ts")),
        "delay_min": delay,
        "title": _norm_text(row.get(f"{prefix}_title")),
        "url": _norm_text(row.get(f"{prefix}_url")),
    }


def _choose_primary_candidate(
    row: pd.Series,
    max_delay_minutes: float,
    candidate_sources: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    allowed = set(candidate_sources or [])
    ranked_candidates: list[dict[str, Any]] = []
    for source in ("v2_clean", "broad"):
        item = _candidate(row, source)
        if item is None:
            continue
        if allowed and item["source"] not in allowed:
            continue
        ranked_candidates.append(item)

    for item in ranked_candidates:
        if item is None:
            continue
        delay = item.get("delay_min")
        if delay is not None and 0.0 <= float(delay) <= max_delay_minutes:
            return item
    if ranked_candidates:
        return ranked_candidates[0]
    return {
        "source": "none",
        "event_id": "",
        "event_ts_utc": "",
        "delay_min": None,
        "title": "",
        "url": "",
    }


def curate_shock_dataset(
    raw_df: pd.DataFrame,
    config: ShockCurationConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cfg = config or ShockCurationConfig.defaults()
    df = raw_df.copy()
    required = {"symbol", "shock_ts", "z_score", "abs_move_pct", "prev_price", "price"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df["shock_ts_dt"] = _parse_ts_utc(df["shock_ts"])
    df["z_score"] = pd.to_numeric(df["z_score"], errors="coerce")
    df["abs_move_pct"] = pd.to_numeric(df["abs_move_pct"], errors="coerce")
    df["prev_price"] = pd.to_numeric(df["prev_price"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")

    issue_rows: list[dict[str, Any]] = []
    keep_mask: list[bool] = []
    for idx, row in df.iterrows():
        symbol = _norm_text(row.get("symbol")).upper()
        reasons: list[str] = []
        critical = False

        if symbol not in SUPPORTED_SYMBOLS:
            reasons.append("unsupported_symbol")
            critical = True
        if pd.isna(row.get("shock_ts_dt")):
            reasons.append("invalid_timestamp")
            critical = True
        if pd.isna(row.get("z_score")):
            reasons.append("invalid_z_score")
            critical = True
        if pd.isna(row.get("abs_move_pct")):
            reasons.append("invalid_abs_move_pct")
            critical = True
        if pd.isna(row.get("prev_price")) or pd.isna(row.get("price")):
            reasons.append("missing_price")
            critical = True
        else:
            if float(row["prev_price"]) <= 0.0 or float(row["price"]) <= 0.0:
                reasons.append("non_positive_price")
                critical = True

        if symbol in cfg.max_abs_move_pct_by_symbol and pd.notna(row.get("abs_move_pct")):
            if abs(float(row["abs_move_pct"])) > float(cfg.max_abs_move_pct_by_symbol[symbol]):
                reasons.append("abs_move_over_cap")
                critical = True
        if symbol in cfg.max_abs_z_by_symbol and pd.notna(row.get("z_score")):
            if abs(float(row["z_score"])) > float(cfg.max_abs_z_by_symbol[symbol]):
                reasons.append("z_over_cap")
                critical = True

        selected_source = _norm_text(row.get("selected_event_source")).lower()
        if not selected_source:
            if _norm_text(row.get("v2_event_id")):
                selected_source = "v2_clean"
            elif _norm_text(row.get("broad_event_id")):
                selected_source = "broad"
            else:
                selected_source = "none"

        issue_rows.append(
            {
                "row_index": int(idx),
                "symbol": symbol,
                "shock_ts": _norm_text(row.get("shock_ts")),
                "selected_source": selected_source,
                "critical_issue": int(critical),
                "issue_count": len(reasons),
                "issue_codes": "|".join(reasons),
            }
        )
        keep_mask.append(not critical)

    issues_df = pd.DataFrame(issue_rows)
    curated_df = df.loc[keep_mask].copy()
    curated_df["selected_source"] = curated_df.apply(
        lambda r: (_norm_text(r.get("selected_event_source")).lower() or ("v2_clean" if _norm_text(r.get("v2_event_id")) else ("broad" if _norm_text(r.get("broad_event_id")) else "none"))),
        axis=1,
    )
    curated_df["direction_layer_eligible"] = (
        (curated_df["selected_source"] == "v2_clean")
        & pd.to_numeric(curated_df.get("v2_delay_min"), errors="coerce").between(0.0, 60.0, inclusive="both")
    ).astype(int)
    curated_df["shock_ts"] = curated_df["shock_ts_dt"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    curated_df = curated_df.drop(columns=["shock_ts_dt"])

    summary_rows: list[dict[str, Any]] = []
    for symbol in list(SUPPORTED_SYMBOLS) + ["ALL"]:
        src = issues_df if symbol == "ALL" else issues_df[issues_df["symbol"] == symbol]
        total = int(len(src))
        critical = int(src["critical_issue"].sum()) if total else 0
        curated = total - critical
        summary_rows.append(
            {
                "symbol": symbol,
                "rows_total": total,
                "rows_curated": curated,
                "rows_critical_dropped": critical,
                "critical_drop_share": (critical / total) if total else 0.0,
            }
        )
    summary_df = pd.DataFrame(summary_rows)
    return curated_df, issues_df, summary_df


def build_shock_label_pack(
    curated_df: pd.DataFrame,
    config: LabelPackConfig | None = None,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    cfg = config or LabelPackConfig()
    candidate_sources = _normalize_candidate_sources(cfg.candidate_sources)
    df = curated_df.copy()
    required = {"symbol", "shock_ts", "z_score", "shock_direction", "abs_move_pct"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df["shock_ts_dt"] = _parse_ts_utc(df["shock_ts"])
    df["abs_z"] = pd.to_numeric(df["z_score"], errors="coerce").abs()
    df = df[df["abs_z"] >= float(cfg.min_abs_z)].dropna(subset=["shock_ts_dt"])
    df = df.sort_values(["shock_ts_dt", "abs_z"], ascending=[True, False])

    tasks: list[dict[str, Any]] = []
    day_symbol_count: dict[tuple[str, str], int] = {}
    for _, row in df.iterrows():
        if len(tasks) >= int(cfg.max_tasks_total):
            break
        symbol = _norm_text(row.get("symbol")).upper()
        day_key = str(row["shock_ts_dt"].date())
        counter_key = (day_key, symbol)
        used = day_symbol_count.get(counter_key, 0)
        if used >= int(cfg.max_tasks_per_day_symbol):
            continue

        available_sources = {
            source
            for source in ("v2_clean", "broad")
            if _candidate(row, source) is not None
        }
        if candidate_sources is not None:
            has_allowed_candidate = bool(available_sources.intersection(candidate_sources))
            allow_none_fallback = ("none" in candidate_sources) and not available_sources
            if not has_allowed_candidate and not allow_none_fallback:
                continue

        primary = _choose_primary_candidate(
            row,
            cfg.max_delay_minutes,
            candidate_sources=candidate_sources,
        )
        if candidate_sources is not None and primary["source"] not in candidate_sources:
            continue
        secondary: list[dict[str, Any]] = []
        for source in ("v2_clean", "broad"):
            cand = _candidate(row, source)
            if cand is None:
                continue
            if cand["event_id"] == primary.get("event_id") and cand["source"] == primary.get("source"):
                continue
            secondary.append(cand)
        secondary = secondary[: int(cfg.max_secondary_candidates)]

        shock_ts = row["shock_ts_dt"].strftime("%Y-%m-%dT%H:%M:%SZ")
        task_id = f"shock-{len(tasks)+1:05d}-{symbol}-{shock_ts}"
        if cfg.causal_only:
            instruction = {
                "goal": "Determine if primary candidate is causal for this shock. Direction is optional.",
                "required_fields": ["task_id", "is_causal", "confidence"],
                "optional_fields": ["direction", "root_topic_key", "reasoning"],
            }
            label_mode = "causal_only"
        else:
            instruction = {
                "goal": "Determine if primary candidate is causal for this shock and assign direction.",
                "allowed_direction": ["up", "down", "hold"],
                "required_fields": ["task_id", "is_causal", "direction", "confidence"],
            }
            label_mode = "directional"
        task = {
            "task_id": task_id,
            "label_mode": label_mode,
            "symbol": symbol,
            "shock_ts_utc": shock_ts,
            "shock": {
                "symbol": symbol,
                "shock_ts_utc": shock_ts,
                "shock_direction": _norm_text(row.get("shock_direction")).lower(),
                "abs_move_pct": _to_float(row.get("abs_move_pct")),
                "z_score": _to_float(row.get("z_score")),
                "logret": _to_float(row.get("logret")),
                "prev_price": _to_float(row.get("prev_price")),
                "price": _to_float(row.get("price")),
            },
            "candidate_primary": primary,
            "secondary_candidates": secondary,
            "labeling_instruction": instruction,
        }
        tasks.append(task)
        day_symbol_count[counter_key] = used + 1

    summary = (
        pd.DataFrame(
            [
                {
                    "task_id": item["task_id"],
                    "label_mode": item.get("label_mode", "directional"),
                    "symbol": item["symbol"],
                    "shock_ts_utc": item["shock_ts_utc"],
                    "z_score_abs": abs(item["shock"]["z_score"]) if item["shock"]["z_score"] is not None else None,
                    "candidate_source": item["candidate_primary"]["source"],
                    "candidate_delay_min": item["candidate_primary"]["delay_min"],
                }
                for item in tasks
            ]
        )
        if tasks
        else pd.DataFrame(
            columns=[
                "task_id",
                "label_mode",
                "symbol",
                "shock_ts_utc",
                "z_score_abs",
                "candidate_source",
                "candidate_delay_min",
            ]
        )
    )
    return tasks, summary


def write_label_pack_jsonl(tasks: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for task in tasks:
            handle.write(json.dumps(task, ensure_ascii=False))
            handle.write("\n")


def _coerce_direction(value: object) -> str | None:
    text = _norm_text(value).lower()
    if not text:
        return None
    return _DIRECTION_MAP.get(text)


def _extract_label_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    task_id = _norm_text(raw.get("task_id") or raw.get("id"))
    if not task_id:
        return None

    payload = raw
    for key in ("label", "result", "answer", "output"):
        maybe = raw.get(key)
        if isinstance(maybe, dict):
            payload = maybe
            break

    direction = (
        _coerce_direction(payload.get("direction"))
        or _coerce_direction(payload.get("label"))
        or _coerce_direction(payload.get("signal"))
    )
    confidence = _to_float(payload.get("confidence"))
    if confidence is None:
        confidence = _to_float(payload.get("probability"))
    is_causal = payload.get("is_causal")
    if isinstance(is_causal, str):
        is_causal = is_causal.strip().lower() in {"1", "true", "yes", "y", "causal"}
    elif is_causal is None:
        is_causal = True
    else:
        is_causal = bool(is_causal)

    return {
        "task_id": task_id,
        "direction": direction or "hold",
        "confidence": confidence if confidence is not None else 0.0,
        "is_causal": int(is_causal),
        "reasoning": _norm_text(payload.get("reasoning") or payload.get("rationale")),
        "root_topic_key": _norm_text(payload.get("root_topic_key") or payload.get("topic_key")),
    }


def ingest_chat_labels(
    tasks_jsonl: Path,
    labels_jsonl: Path,
    *,
    min_confidence: float = 0.60,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not tasks_jsonl.exists():
        raise FileNotFoundError(f"Tasks JSONL not found: {tasks_jsonl}")
    if not labels_jsonl.exists():
        raise FileNotFoundError(f"Labels JSONL not found: {labels_jsonl}")

    tasks: list[dict[str, Any]] = []
    with tasks_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            item = json.loads(raw)
            tasks.append(item)
    tasks_df = pd.DataFrame(
        [
            {
                "task_id": _norm_text(item.get("task_id")),
                "symbol": _norm_text(item.get("symbol") or item.get("shock", {}).get("symbol")).upper(),
                "shock_ts_utc": _norm_text(item.get("shock_ts_utc") or item.get("shock", {}).get("shock_ts_utc")),
                "shock_direction": _norm_text(item.get("shock", {}).get("shock_direction")).lower(),
                "z_score": _to_float(item.get("shock", {}).get("z_score")),
                "abs_move_pct": _to_float(item.get("shock", {}).get("abs_move_pct")),
                "primary_source": _norm_text(item.get("candidate_primary", {}).get("source")),
                "primary_event_id": _norm_text(item.get("candidate_primary", {}).get("event_id")),
                "primary_delay_min": _to_float(item.get("candidate_primary", {}).get("delay_min")),
                "primary_title": _norm_text(item.get("candidate_primary", {}).get("title")),
                "primary_url": _norm_text(item.get("candidate_primary", {}).get("url")),
            }
            for item in tasks
            if _norm_text(item.get("task_id"))
        ]
    )

    labels: list[dict[str, Any]] = []
    with labels_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            item = json.loads(raw)
            parsed = _extract_label_record(item)
            if parsed is not None:
                labels.append(parsed)
    labels_df = pd.DataFrame(labels)
    if labels_df.empty:
        merged = tasks_df.copy()
        merged["label_direction"] = "hold"
        merged["label_confidence"] = 0.0
        merged["label_is_causal"] = 0
        merged["is_high_conf"] = 0
        return merged, pd.DataFrame(columns=["metric", "value"])

    merged = tasks_df.merge(labels_df, on="task_id", how="left")
    merged["direction"] = merged["direction"].fillna("hold")
    merged["confidence"] = pd.to_numeric(merged["confidence"], errors="coerce").fillna(0.0)
    merged["is_causal"] = pd.to_numeric(merged["is_causal"], errors="coerce").fillna(0).astype(int)
    merged["is_high_conf"] = (
        (merged["is_causal"] == 1)
        & (merged["confidence"] >= float(min_confidence))
        & (merged["direction"].isin(["up", "down"]))
    ).astype(int)
    merged = merged.rename(
        columns={
            "direction": "label_direction",
            "confidence": "label_confidence",
            "is_causal": "label_is_causal",
        }
    )

    summary = pd.DataFrame(
        [
            {"metric": "tasks_total", "value": int(len(tasks_df))},
            {"metric": "labels_total", "value": int(len(labels_df))},
            {"metric": "labels_matched", "value": int(merged["label_direction"].notna().sum())},
            {"metric": "high_conf_count", "value": int(merged["is_high_conf"].sum())},
            {
                "metric": "high_conf_share",
                "value": float(merged["is_high_conf"].mean()) if len(merged) else 0.0,
            },
            {
                "metric": "up_share_high_conf",
                "value": float((merged[merged["is_high_conf"] == 1]["label_direction"] == "up").mean())
                if int(merged["is_high_conf"].sum()) > 0
                else 0.0,
            },
        ]
    )
    return merged, summary
