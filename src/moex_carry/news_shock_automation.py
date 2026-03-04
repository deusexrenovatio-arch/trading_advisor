from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from moex_carry.news_topic import (
    classify_shock_impact_tier,
    derive_root_topic_key,
)
from moex_carry.news_shock_pipeline import (
    LabelPackConfig,
    ShockCurationConfig,
    SUPPORTED_SYMBOLS,
    build_shock_label_pack,
    curate_shock_dataset,
    ingest_chat_labels,
    write_label_pack_jsonl,
)
from moex_carry.news_shock_readiness import ReadinessConfig, run_readiness_assessment
from moex_carry.news_shock_store import read_live_shock_rows
from moex_carry.news_silver_store import (
    persist_task_merged_labels_to_db,
    upsert_silver_from_shock_rows,
)


@dataclass(frozen=True)
class ShockLabelCycleConfig:
    min_abs_z: float = 2.5
    max_tasks_per_day_symbol: int = 20
    max_delay_minutes: float = 60.0
    direction_max_tasks_total: int = 300
    causal_max_tasks_total: int = 900
    direction_candidate_sources: tuple[str, ...] | None = ("v2_clean",)
    causal_candidate_sources: tuple[str, ...] | None = ("broad", "none")
    ingest_min_confidence: float = 0.60
    export_telegram_feed: bool = True
    telegram_feed_path: Path = field(
        default_factory=lambda: Path("data/output/shock_alerts/live_shocks.csv")
    )
    telegram_feed_min_abs_z: float = 2.0
    telegram_feed_max_rows: int = 5000
    telegram_episode_gap_minutes: int = 2880
    allow_empty_after_filter: bool = True
    run_readiness: bool = False
    readiness_config: ReadinessConfig = field(default_factory=ReadinessConfig)
    persist_ingested_silver_to_db: bool = True
    silver_database_url: str = "sqlite:///./data/news_livecheck_ng.db"
    silver_data_dir: str = "./data"
    auto_derive_silver_from_curated: bool = True
    auto_derive_silver_min_abs_z: float = 2.5
    auto_derive_silver_max_delay_minutes: float = 120.0
    auto_derive_silver_min_samples_per_event: int = 2
    auto_derive_silver_min_direction_confidence: float = 0.60
    input_database_url: str = "sqlite:///./data/news_livecheck_ng.db"
    input_data_dir: str = "./data"
    input_bar_minutes: int = 5
    input_max_rows: int = 0


_TELEGRAM_FEED_COLUMNS = [
    "shock_ts",
    "symbol",
    "shock_direction",
    "z_score",
    "abs_move_pct",
    "impact_tier",
    "topic_key",
    "root_topic_id",
    "selected_source",
    "selected_event_id",
    "selected_match_mode",
    "episode_event_index",
    "episode_cum_signed_move_pct",
    "episode_signed_increment_pct",
    "headline",
    "url",
]


def _parse_ts(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid timestamp: {value}")
    return parsed


def _pack_filename(
    *,
    mode: str,
    min_abs_z: float,
    candidate_sources: tuple[str, ...] | None,
) -> str:
    z_tag = str(min_abs_z).replace(".", "p")
    source_tag = "any" if not candidate_sources else "-".join(candidate_sources)
    return f"shock_label_pack_{mode}_{source_tag}_zge{z_tag}.jsonl"


def _slug_topic_token(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def _empty_telegram_feed() -> pd.DataFrame:
    return pd.DataFrame(columns=_TELEGRAM_FEED_COLUMNS)


def _text_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df.columns:
        return df[column].fillna("").astype(str).str.strip()
    return pd.Series("", index=df.index, dtype="object")


def _safe_int(value: object) -> int:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return 0
    return int(num)


def _attach_episode_metrics(df: pd.DataFrame, *, max_gap_minutes: int) -> pd.DataFrame:
    if df.empty:
        return df
    work = df.sort_values("shock_ts_dt").copy()
    work["_topic_key_work"] = _text_series(work, "topic_key").where(
        _text_series(work, "topic_key").ne(""),
        _text_series(work, "root_topic_id"),
    ).str.lower()
    work["symbol_norm"] = _text_series(work, "symbol").str.upper()
    work["signed_move_pct"] = pd.to_numeric(work.get("abs_move_pct"), errors="coerce").fillna(0.0) * (
        _text_series(work, "shock_direction").str.lower().map({"up": 1.0, "down": -1.0}).fillna(0.0)
    )
    work["episode_event_index"] = 0
    work["episode_cum_signed_move_pct"] = 0.0
    work["episode_signed_increment_pct"] = 0.0

    state: dict[tuple[str, str], dict[str, object]] = {}
    gap_limit = max(int(max_gap_minutes), 0)
    for idx, row in work.iterrows():
        key = (str(row["symbol_norm"]), str(row["_topic_key_work"]))
        ts = row["shock_ts_dt"]
        signed_move = float(row["signed_move_pct"])
        prev = state.get(key)
        new_episode = True
        if prev is not None:
            prev_ts = prev.get("last_ts")
            if isinstance(prev_ts, pd.Timestamp):
                gap_min = (ts - prev_ts).total_seconds() / 60.0
                if gap_min <= gap_limit:
                    new_episode = False
        if new_episode:
            prev_cum = 0.0
            event_idx = 1
        else:
            prev_cum = float(prev.get("cum_signed") or 0.0)
            event_idx = int(prev.get("event_idx") or 0) + 1

        new_cum = prev_cum + signed_move
        increment = abs(new_cum) - abs(prev_cum)
        work.at[idx, "episode_event_index"] = int(event_idx)
        work.at[idx, "episode_cum_signed_move_pct"] = float(new_cum)
        work.at[idx, "episode_signed_increment_pct"] = float(increment)
        state[key] = {
            "last_ts": ts,
            "cum_signed": new_cum,
            "event_idx": event_idx,
        }
    return work.drop(columns=["_topic_key_work", "symbol_norm", "signed_move_pct"])


def _build_telegram_feed(
    curated: pd.DataFrame,
    *,
    min_abs_z: float,
    max_rows: int,
    episode_gap_minutes: int,
) -> pd.DataFrame:
    if curated.empty:
        return _empty_telegram_feed()

    df = curated.copy()
    df["shock_ts_dt"] = pd.to_datetime(df["shock_ts"], utc=True, errors="coerce")
    df["abs_z"] = pd.to_numeric(df["z_score"], errors="coerce").abs()
    df = df.dropna(subset=["shock_ts_dt", "abs_z"])
    df = df[df["abs_z"] >= float(min_abs_z)]
    if df.empty:
        return _empty_telegram_feed()

    v2_event_id = _text_series(df, "v2_event_id")
    broad_event_id = _text_series(df, "broad_event_id")
    v2_title = _text_series(df, "v2_title")
    broad_title = _text_series(df, "broad_title")
    v2_url = _text_series(df, "v2_url")
    broad_url = _text_series(df, "broad_url")

    selected_source = _text_series(df, "selected_source").str.lower()
    fallback_source = pd.Series("none", index=df.index, dtype="object")
    fallback_source.loc[v2_event_id.ne("")] = "v2_clean"
    fallback_source.loc[fallback_source.eq("none") & broad_event_id.ne("")] = "broad"
    selected_source = selected_source.where(
        selected_source.isin(("v2_clean", "broad", "none")),
        "",
    )
    selected_source = selected_source.where(selected_source.ne(""), fallback_source)
    df["selected_source"] = selected_source

    selected_event_id = pd.Series("", index=df.index, dtype="object")
    selected_event_id.loc[selected_source.eq("v2_clean")] = v2_event_id.loc[selected_source.eq("v2_clean")]
    selected_event_id.loc[selected_source.eq("broad")] = broad_event_id.loc[selected_source.eq("broad")]
    selected_event_id = selected_event_id.where(
        selected_event_id.ne(""),
        v2_event_id.where(v2_event_id.ne(""), broad_event_id),
    )
    df["selected_event_id"] = selected_event_id
    df["selected_match_mode"] = _text_series(df, "selected_match_mode").str.lower()

    headline = pd.Series("", index=df.index, dtype="object")
    headline.loc[selected_source.eq("v2_clean")] = v2_title.loc[selected_source.eq("v2_clean")]
    headline.loc[selected_source.eq("broad")] = broad_title.loc[selected_source.eq("broad")]
    headline = headline.where(headline.ne(""), v2_title.where(v2_title.ne(""), broad_title))
    df["headline"] = headline

    url = pd.Series("", index=df.index, dtype="object")
    url.loc[selected_source.eq("v2_clean")] = v2_url.loc[selected_source.eq("v2_clean")]
    url.loc[selected_source.eq("broad")] = broad_url.loc[selected_source.eq("broad")]
    url = url.where(url.ne(""), v2_url.where(v2_url.ne(""), broad_url))
    df["url"] = url

    df["root_topic_id"] = df.apply(
        lambda row: derive_root_topic_key(
            symbol=row.get("symbol"),
            headline=row.get("headline"),
            url=row.get("url"),
            selected_event_id=row.get("selected_event_id"),
            selected_source=row.get("selected_source"),
            explicit_root_topic_id=row.get("root_topic_id"),
        ),
        axis=1,
    )
    df["topic_key"] = df["root_topic_id"]
    df = _attach_episode_metrics(df, max_gap_minutes=episode_gap_minutes)
    df["impact_tier"] = df.apply(
        lambda row: classify_shock_impact_tier(
            z_score_abs=pd.to_numeric(row.get("z_score"), errors="coerce"),
            abs_move_pct=pd.to_numeric(row.get("abs_move_pct"), errors="coerce"),
            episode_signed_increment_pct=pd.to_numeric(row.get("episode_signed_increment_pct"), errors="coerce"),
            episode_cum_signed_move_pct=pd.to_numeric(row.get("episode_cum_signed_move_pct"), errors="coerce"),
            episode_event_index=_safe_int(row.get("episode_event_index")),
        ),
        axis=1,
    )

    feed = df[
        [
            "shock_ts_dt",
            *_TELEGRAM_FEED_COLUMNS,
        ]
    ].copy()
    feed = feed.sort_values("shock_ts_dt")
    if max_rows > 0 and len(feed) > int(max_rows):
        feed = feed.tail(int(max_rows))
    return feed.drop(columns=["shock_ts_dt"]).reset_index(drop=True)


def _write_csv_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp_path, index=False)
    tmp_path.replace(path)


def _save_ingested_labels(
    *,
    tasks_jsonl: Path,
    labels_jsonl: Path,
    output_dir: Path,
    min_confidence: float,
    persist_to_db: bool,
    silver_database_url: str,
    silver_data_dir: str,
    source_tag: str,
) -> dict[str, object]:
    merged, summary = ingest_chat_labels(
        tasks_jsonl=tasks_jsonl,
        labels_jsonl=labels_jsonl,
        min_confidence=min_confidence,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    labels_path = output_dir / "shock_silver_labels.csv"
    summary_path = output_dir / "shock_silver_labels_summary.csv"
    merged.to_csv(labels_path, index=False)
    summary.to_csv(summary_path, index=False)
    high_conf = int((merged.get("is_high_conf", 0) == 1).sum()) if not merged.empty else 0
    db_upserted = 0
    if persist_to_db:
        db_upserted = int(
            persist_task_merged_labels_to_db(
                merged=merged,
                database_url=silver_database_url,
                data_dir=silver_data_dir,
                source_tag=source_tag,
                source_ref=str(labels_jsonl),
            )
        )
    return {
        "rows_total": int(len(merged)),
        "high_conf_count": high_conf,
        "labels_path": str(labels_path),
        "summary_path": str(summary_path),
        "db_upserted": db_upserted,
    }


def _build_pack(
    *,
    curated: pd.DataFrame,
    output_dir: Path,
    mode: str,
    config: LabelPackConfig,
) -> dict[str, object]:
    mode_dir = output_dir / mode
    mode_dir.mkdir(parents=True, exist_ok=True)

    tasks, summary_df = build_shock_label_pack(curated, config)
    jsonl_name = _pack_filename(
        mode=mode,
        min_abs_z=config.min_abs_z,
        candidate_sources=config.candidate_sources,
    )
    tasks_path = mode_dir / jsonl_name
    summary_path = mode_dir / "shock_label_pack_summary.csv"
    write_label_pack_jsonl(tasks, tasks_path)
    summary_df.to_csv(summary_path, index=False)
    return {
        "tasks_count": len(tasks),
        "tasks_path": str(tasks_path),
        "summary_path": str(summary_path),
    }


def run_shock_label_cycle(
    *,
    input_csv: Path | None = None,
    output_dir: Path,
    config: ShockLabelCycleConfig,
    start_ts: str | None = None,
    end_ts: str | None = None,
    direction_labels_jsonl: Path | None = None,
    causal_labels_jsonl: Path | None = None,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_df = pd.DataFrame()
    input_source = "none"
    if input_csv is not None:
        if not input_csv.exists():
            raise FileNotFoundError(f"Input file not found: {input_csv}")
        source_df = pd.read_csv(input_csv)
        input_source = "csv"
    else:
        source_df = read_live_shock_rows(
            database_url=config.input_database_url,
            data_dir=config.input_data_dir,
            start_ts=start_ts,
            end_ts=end_ts,
            bar_minutes=config.input_bar_minutes,
            max_rows=config.input_max_rows,
        )
        input_source = "db"
        if source_df.empty and not config.allow_empty_after_filter:
            raise ValueError("No rows available from DB source.")

    if "shock_ts" not in source_df.columns:
        source_df["shock_ts"] = pd.Series(dtype="object")
    source_df["shock_ts_dt"] = pd.to_datetime(source_df["shock_ts"], utc=True, errors="coerce")
    start = _parse_ts(start_ts)
    end = _parse_ts(end_ts)
    if start is not None:
        source_df = source_df[source_df["shock_ts_dt"] >= start]
    if end is not None:
        source_df = source_df[source_df["shock_ts_dt"] <= end]
    if source_df.empty and not config.allow_empty_after_filter:
        raise ValueError("No rows available after date filtering.")
    source_df = source_df.drop(columns=["shock_ts_dt"])

    if source_df.empty:
        curated = pd.DataFrame(
            columns=[
                "symbol",
                "shock_ts",
                "z_score",
                "shock_direction",
                "abs_move_pct",
                "selected_source",
                "direction_layer_eligible",
                "v2_event_id",
                "v2_event_ts",
                "v2_delay_min",
                "v2_title",
                "v2_url",
                "broad_event_id",
                "broad_event_ts",
                "broad_delay_min",
                "broad_title",
                "broad_url",
                "selected_event_source",
                "selected_event_id",
                "selected_event_ts",
                "selected_delay_min",
                "selected_match_mode",
                "selected_title",
                "selected_url",
                "root_topic_id",
                "prev_price",
                "price",
            ]
        )
        issues = pd.DataFrame(
            columns=[
                "row_index",
                "symbol",
                "shock_ts",
                "selected_source",
                "critical_issue",
                "issue_count",
                "issue_codes",
            ]
        )
        curation_summary = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "rows_total": 0,
                    "rows_curated": 0,
                    "rows_critical_dropped": 0,
                    "critical_drop_share": 0.0,
                }
                for symbol in [*SUPPORTED_SYMBOLS, "ALL"]
            ]
        )
    else:
        curated, issues, curation_summary = curate_shock_dataset(source_df, ShockCurationConfig.defaults())
    curated_path = output_dir / "curated_shocks.csv"
    issues_path = output_dir / "curation_issues.csv"
    curation_summary_path = output_dir / "curation_summary.csv"
    curated.to_csv(curated_path, index=False)
    issues.to_csv(issues_path, index=False)
    curation_summary.to_csv(curation_summary_path, index=False)

    direction_pack = _build_pack(
        curated=curated,
        output_dir=output_dir,
        mode="direction",
        config=LabelPackConfig(
            min_abs_z=config.min_abs_z,
            max_tasks_total=config.direction_max_tasks_total,
            max_tasks_per_day_symbol=config.max_tasks_per_day_symbol,
            max_delay_minutes=config.max_delay_minutes,
            candidate_sources=config.direction_candidate_sources,
            causal_only=False,
        ),
    )
    causal_pack = _build_pack(
        curated=curated,
        output_dir=output_dir,
        mode="causal",
        config=LabelPackConfig(
            min_abs_z=config.min_abs_z,
            max_tasks_total=config.causal_max_tasks_total,
            max_tasks_per_day_symbol=config.max_tasks_per_day_symbol,
            max_delay_minutes=config.max_delay_minutes,
            candidate_sources=config.causal_candidate_sources,
            causal_only=True,
        ),
    )

    outputs: dict[str, object] = {
        "output_dir": str(output_dir),
        "input_source": input_source,
        "input_rows": int(len(source_df)),
        "curated_rows": int(len(curated)),
        "curated_path": str(curated_path),
        "issues_path": str(issues_path),
        "curation_summary_path": str(curation_summary_path),
        "direction_pack": direction_pack,
        "causal_pack": causal_pack,
    }

    if config.auto_derive_silver_from_curated:
        outputs["auto_silver"] = upsert_silver_from_shock_rows(
            shocks_df=curated,
            database_url=config.silver_database_url,
            data_dir=config.silver_data_dir,
            source_tag="shock_backfill_auto",
            min_abs_z=config.auto_derive_silver_min_abs_z,
            max_delay_min=config.auto_derive_silver_max_delay_minutes,
            min_samples_per_event=config.auto_derive_silver_min_samples_per_event,
            min_direction_confidence=config.auto_derive_silver_min_direction_confidence,
        )

    if config.export_telegram_feed and not curated.empty:
        feed = _build_telegram_feed(
            curated,
            min_abs_z=config.telegram_feed_min_abs_z,
            max_rows=config.telegram_feed_max_rows,
            episode_gap_minutes=config.telegram_episode_gap_minutes,
        )
        _write_csv_atomic(feed, config.telegram_feed_path)
        feed_path = output_dir / "telegram_live_shocks.csv"
        feed.to_csv(feed_path, index=False)
        outputs["telegram_feed"] = {
            "rows": int(len(feed)),
            "min_abs_z": float(config.telegram_feed_min_abs_z),
            "path": str(config.telegram_feed_path),
            "snapshot_path": str(feed_path),
        }
    elif config.export_telegram_feed:
        outputs["telegram_feed"] = {
            "rows": 0,
            "min_abs_z": float(config.telegram_feed_min_abs_z),
            "path": str(config.telegram_feed_path),
            "snapshot_path": "",
            "skipped": "curated_empty_after_filter",
        }

    if direction_labels_jsonl is not None:
        outputs["direction_ingest"] = _save_ingested_labels(
            tasks_jsonl=Path(str(direction_pack["tasks_path"])),
            labels_jsonl=direction_labels_jsonl,
            output_dir=output_dir / "direction_ingest",
            min_confidence=config.ingest_min_confidence,
            persist_to_db=config.persist_ingested_silver_to_db,
            silver_database_url=config.silver_database_url,
            silver_data_dir=config.silver_data_dir,
            source_tag="chatpro_task_direction",
        )
    if causal_labels_jsonl is not None:
        outputs["causal_ingest"] = _save_ingested_labels(
            tasks_jsonl=Path(str(causal_pack["tasks_path"])),
            labels_jsonl=causal_labels_jsonl,
            output_dir=output_dir / "causal_ingest",
            min_confidence=config.ingest_min_confidence,
            persist_to_db=config.persist_ingested_silver_to_db,
            silver_database_url=config.silver_database_url,
            silver_data_dir=config.silver_data_dir,
            source_tag="chatpro_task_causal",
        )

    if config.run_readiness:
        readiness_dir = output_dir / "readiness"
        readiness_input_csv = input_csv
        if readiness_input_csv is None:
            readiness_input_csv = output_dir / "_readiness_input_snapshot.csv"
            source_df.drop(columns=["shock_ts_dt"], errors="ignore").to_csv(readiness_input_csv, index=False)
        readiness_outputs = run_readiness_assessment(
            input_csv=readiness_input_csv,
            output_dir=readiness_dir,
            config=config.readiness_config,
            start_ts=start_ts,
            end_ts=end_ts,
        )
        outputs["readiness"] = {key: str(value) for key, value in readiness_outputs.items()}

    manifest_path = output_dir / "shock_label_cycle_manifest.json"
    manifest_path.write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["manifest_path"] = str(manifest_path)
    return outputs
