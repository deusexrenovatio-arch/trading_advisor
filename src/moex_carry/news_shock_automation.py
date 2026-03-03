from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from moex_carry.news_shock_pipeline import (
    LabelPackConfig,
    ShockCurationConfig,
    build_shock_label_pack,
    curate_shock_dataset,
    ingest_chat_labels,
    write_label_pack_jsonl,
)
from moex_carry.news_shock_readiness import ReadinessConfig, run_readiness_assessment


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
    run_readiness: bool = False
    readiness_config: ReadinessConfig = field(default_factory=ReadinessConfig)


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


def _save_ingested_labels(
    *,
    tasks_jsonl: Path,
    labels_jsonl: Path,
    output_dir: Path,
    min_confidence: float,
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
    return {
        "rows_total": int(len(merged)),
        "high_conf_count": high_conf,
        "labels_path": str(labels_path),
        "summary_path": str(summary_path),
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
    input_csv: Path,
    output_dir: Path,
    config: ShockLabelCycleConfig,
    start_ts: str | None = None,
    end_ts: str | None = None,
    direction_labels_jsonl: Path | None = None,
    causal_labels_jsonl: Path | None = None,
) -> dict[str, object]:
    if not input_csv.exists():
        raise FileNotFoundError(f"Input file not found: {input_csv}")

    output_dir.mkdir(parents=True, exist_ok=True)
    source_df = pd.read_csv(input_csv)
    source_df["shock_ts_dt"] = pd.to_datetime(source_df["shock_ts"], utc=True, errors="coerce")
    start = _parse_ts(start_ts)
    end = _parse_ts(end_ts)
    if start is not None:
        source_df = source_df[source_df["shock_ts_dt"] >= start]
    if end is not None:
        source_df = source_df[source_df["shock_ts_dt"] <= end]
    if source_df.empty:
        raise ValueError("No rows available after date filtering.")
    source_df = source_df.drop(columns=["shock_ts_dt"])

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
        "curated_rows": int(len(curated)),
        "curated_path": str(curated_path),
        "issues_path": str(issues_path),
        "curation_summary_path": str(curation_summary_path),
        "direction_pack": direction_pack,
        "causal_pack": causal_pack,
    }

    if direction_labels_jsonl is not None:
        outputs["direction_ingest"] = _save_ingested_labels(
            tasks_jsonl=Path(str(direction_pack["tasks_path"])),
            labels_jsonl=direction_labels_jsonl,
            output_dir=output_dir / "direction_ingest",
            min_confidence=config.ingest_min_confidence,
        )
    if causal_labels_jsonl is not None:
        outputs["causal_ingest"] = _save_ingested_labels(
            tasks_jsonl=Path(str(causal_pack["tasks_path"])),
            labels_jsonl=causal_labels_jsonl,
            output_dir=output_dir / "causal_ingest",
            min_confidence=config.ingest_min_confidence,
        )

    if config.run_readiness:
        readiness_dir = output_dir / "readiness"
        readiness_outputs = run_readiness_assessment(
            input_csv=input_csv,
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
