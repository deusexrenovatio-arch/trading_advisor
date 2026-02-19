from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from moex_carry.config import load_settings, resolve_paths  # noqa: E402
from moex_carry.news.gold_bootstrap import promote_human_labels_to_gold  # noqa: E402
from moex_carry.news.hitl import (  # noqa: E402
    apply_news_hitl_labels,
    build_news_hitl_tasks,
    export_news_hitl_tasks,
    load_hitl_label_rows,
)
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db  # noqa: E402


DEFAULT_TICKERS = ("NG_US", "BRN", "GOLD")


def _parse_tickers(raw: str | None) -> list[str]:
    if raw is None:
        return list(DEFAULT_TICKERS)
    values = [str(item).strip().upper() for item in str(raw).split(",")]
    normalized = [item for item in values if item]
    return normalized or list(DEFAULT_TICKERS)


def _sanitize_filename(value: str) -> str:
    token = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value))
    return token.strip("_") or "value"


def _default_out_dir(config_path: str | None) -> Path:
    settings = load_settings(config_path)
    return resolve_paths(settings).data_dir / "output" / "news_hitl_tripack"


def _resolve_ext(output_format: str) -> str:
    normalized = str(output_format or "batch").strip().lower()
    if normalized in {"jsonl", "json", "md", "batch"}:
        return normalized
    return "batch"


def _build_export_readme(
    *,
    out_dir: Path,
    format_name: str,
    ticker_files: dict[str, dict[str, object]],
) -> Path:
    lines: list[str] = [
        "# News HITL Tripack",
        "",
        "## Step 1: Upload files to ChatGPT Pro",
        "Upload each task file and ask for JSONL-only output (no markdown).",
        "",
        "## Step 2: Save answers",
        "Save answers to the expected files in the same directory:",
        "",
    ]
    for ticker, meta in ticker_files.items():
        lines.append(f"- `{ticker}`")
        lines.append(f"  task: `{meta['task_path']}`")
        lines.append(f"  answer: `{meta['answer_path']}`")
    lines += [
        "",
        "## Step 3: Import all answers in one command",
        "```powershell",
        f"python scripts/news_hitl_tripack.py import --input-dir \"{out_dir}\"",
        "```",
        "",
        "## Prompt for ChatGPT Pro",
        "Return ONLY JSONL. One line per event_id. Use allowed enums and numeric ranges from task schema.",
        "",
        f"Task format exported: `{format_name}`",
    ]
    path = out_dir / "README_HITL_TRIPACK.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def cmd_export(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir(args.config)
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = _resolve_ext(args.format)
    tickers = _parse_tickers(args.tickers)

    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    report: dict[str, object] = {
        "mode": "export",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "config": args.config,
        "out_dir": str(out_dir),
        "format": ext,
        "max_items": max(int(args.max_items), 0),
        "min_impact": float(args.min_impact),
        "include_labeled": bool(args.include_labeled),
        "tickers": {},
    }

    with session_factory() as session:
        for ticker in tickers:
            tasks = build_news_hitl_tasks(
                session,
                settings,
                max_items=max(int(args.max_items), 0),
                min_impact=float(args.min_impact),
                only_unlabeled=not bool(args.include_labeled),
                ticker=ticker,
            )
            task_path = out_dir / f"news_hitl_tasks_{_sanitize_filename(ticker)}.{ext}"
            export_news_hitl_tasks(tasks=tasks, output_path=task_path, output_format=ext)
            answer_path = out_dir / f"news_hitl_answer_{_sanitize_filename(ticker)}.jsonl"
            report["tickers"][ticker] = {
                "tasks": len(tasks),
                "task_path": str(task_path),
                "answer_path": str(answer_path),
            }

    readme_path = _build_export_readme(
        out_dir=out_dir,
        format_name=ext,
        ticker_files={str(k): dict(v) for k, v in report["tickers"].items()},
    )
    report["readme"] = str(readme_path)

    manifest_path = out_dir / "news_hitl_tripack_manifest.json"
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["manifest"] = str(manifest_path)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _collect_answer_files(
    *,
    input_dir: Path,
    tickers: Iterable[str],
    answer_files_arg: str | None,
) -> list[Path]:
    if answer_files_arg:
        paths = [Path(item.strip()) for item in str(answer_files_arg).split(",") if item.strip()]
        return [path if path.is_absolute() else (input_dir / path) for path in paths]

    files: list[Path] = []
    for ticker in tickers:
        candidate = input_dir / f"news_hitl_answer_{_sanitize_filename(ticker)}.jsonl"
        if candidate.exists():
            files.append(candidate)
    if files:
        return files

    return sorted(input_dir.glob("news_hitl_answer*.jsonl"))


def cmd_import(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    input_dir = Path(args.input_dir) if args.input_dir else _default_out_dir(args.config)
    input_dir.mkdir(parents=True, exist_ok=True)
    tickers = _parse_tickers(args.tickers)
    answer_files = _collect_answer_files(
        input_dir=input_dir,
        tickers=tickers,
        answer_files_arg=args.answer_files,
    )

    if not answer_files:
        print(
            json.dumps(
                {
                    "mode": "import",
                    "status": "no_answer_files",
                    "input_dir": str(input_dir),
                    "tickers": tickers,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    loaded_by_file: dict[str, int] = {}
    rows_all: list[dict[str, object]] = []
    for path in answer_files:
        if not path.exists():
            loaded_by_file[str(path)] = 0
            continue
        rows = load_hitl_label_rows(path)
        loaded_by_file[str(path)] = len(rows)
        rows_all.extend(rows)

    dedup_by_event: dict[str, dict[str, object]] = {}
    for row in rows_all:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id") or row.get("target_id") or "").strip()
        if not event_id:
            continue
        if event_id in dedup_by_event:
            continue
        dedup_by_event[event_id] = row
    rows_unique = list(dedup_by_event.values())

    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    import_started = datetime.utcnow()
    with session_factory() as session:
        apply_report = apply_news_hitl_labels(
            session,
            label_rows=rows_unique,
            author_id=str(args.author_id or "chatgpt-pro").strip(),
            reason=str(args.reason or "chatgpt_pro_verification").strip(),
            label_version=str(args.label_version or "v2").strip(),
            prompt_version=str(args.prompt_version or "news-v1").strip(),
        )
        gold_report = None
        if not bool(args.no_promote_gold):
            gold_report = promote_human_labels_to_gold(
                session,
                source=str(args.gold_source or "human_hitl").strip(),
                quality=str(args.gold_quality or "gold").strip(),
                label_schema_version=str(args.gold_schema_version or "v1").strip(),
                created_from=import_started - timedelta(seconds=2),
                created_to=None,
                max_rows=0,
            )

    result = {
        "mode": "import",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "input_dir": str(input_dir),
        "answer_files": [str(path) for path in answer_files],
        "loaded_rows_by_file": loaded_by_file,
        "loaded_rows_total": len(rows_all),
        "unique_event_rows": len(rows_unique),
        "apply_report": apply_report,
        "gold_report": (
            {
                "scanned": gold_report.scanned,
                "accepted": gold_report.accepted,
                "stored": gold_report.stored,
                "source": str(args.gold_source or "human_hitl").strip(),
                "quality": str(args.gold_quality or "gold").strip(),
                "label_schema_version": str(args.gold_schema_version or "v1").strip(),
            }
            if gold_report is not None
            else None
        ),
    }

    out_path = input_dir / "news_hitl_tripack_import_report.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["report_path"] = str(out_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="news_hitl_tripack",
        description="Batch export/import workflow for NG_US/BRN/GOLD manual ChatGPT Pro labeling.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_export = sub.add_parser("export", help="Export HITL task files for multiple tickers.")
    p_export.add_argument("--config", type=str, default=None)
    p_export.add_argument("--tickers", type=str, default="NG_US,BRN,GOLD")
    p_export.add_argument("--max-items", type=int, default=80)
    p_export.add_argument("--min-impact", type=float, default=0.65)
    p_export.add_argument("--include-labeled", action="store_true")
    p_export.add_argument("--format", type=str, default="batch", choices=["jsonl", "json", "md", "batch"])
    p_export.add_argument("--out-dir", type=str, default=None)
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="Import all answer files and optionally promote to gold.")
    p_import.add_argument("--config", type=str, default=None)
    p_import.add_argument("--tickers", type=str, default="NG_US,BRN,GOLD")
    p_import.add_argument("--input-dir", type=str, default=None)
    p_import.add_argument(
        "--answer-files",
        type=str,
        default=None,
        help="Optional comma-separated answer file paths. Default: news_hitl_answer_<ticker>.jsonl in input-dir.",
    )
    p_import.add_argument("--author-id", type=str, default="chatgpt-pro")
    p_import.add_argument("--reason", type=str, default="chatgpt_pro_verification")
    p_import.add_argument("--label-version", type=str, default="v2")
    p_import.add_argument("--prompt-version", type=str, default="news-v1")
    p_import.add_argument("--no-promote-gold", action="store_true")
    p_import.add_argument("--gold-source", type=str, default="human_hitl")
    p_import.add_argument("--gold-quality", type=str, default="gold")
    p_import.add_argument("--gold-schema-version", type=str, default="v1")
    p_import.set_defaults(func=cmd_import)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
