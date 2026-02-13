from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from moex_carry.config import AppSettings, load_settings, resolve_paths
from moex_carry.decision_log import load_jsonl
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.decision_projection import (
    PROJECTION_PARITY_FIELDS,
    compute_projection_parity,
)
from moex_carry.storage.repositories import (
    load_decision_view_projection,
    upsert_decision_view_projection,
)


def _runtime_settings(args: argparse.Namespace) -> AppSettings:
    settings = load_settings(args.config)
    if args.data_dir:
        settings = settings.model_copy(
            update={"data": settings.data.model_copy(update={"data_dir": str(args.data_dir)})}
        )
    if args.db_url:
        settings = settings.model_copy(
            update={"database": settings.database.model_copy(update={"url": str(args.db_url)})}
        )
    return settings


def _load_source_rows(path: Path) -> list[dict[str, object]]:
    rows = load_jsonl(path)
    return [row for row in rows if isinstance(row, dict)]


def run(args: argparse.Namespace) -> int:
    settings = _runtime_settings(args)
    paths = resolve_paths(settings)
    source_path = Path(args.source_jsonl) if args.source_jsonl else paths.data_dir / "decisions" / "decision_view.jsonl"
    if not source_path.exists():
        print(f"source file not found: {source_path}")
        return 1

    source_rows = _load_source_rows(source_path)
    print(f"source rows loaded: {len(source_rows)} from {source_path}")

    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    stored = 0
    if args.mode in {"backfill", "all"}:
        with session_factory() as session:
            stored = upsert_decision_view_projection(session, source_rows)
        print(f"backfill upserted rows: {stored}")

    if args.mode in {"parity", "all"}:
        with session_factory() as session:
            db_rows = load_decision_view_projection(session, limit=0)
        report = compute_projection_parity(
            source_rows,
            db_rows,
            fields=PROJECTION_PARITY_FIELDS,
            sample_mismatches=max(int(args.sample_mismatches), 0),
        )
        print("parity report:")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        ratio = float(report.get("parity_ratio") or 0.0)
        if ratio < float(args.parity_threshold):
            print(
                f"parity check failed: ratio={ratio:.6f} threshold={float(args.parity_threshold):.6f}"
            )
            return 2
        print(
            f"parity check passed: ratio={ratio:.6f} threshold={float(args.parity_threshold):.6f}"
        )

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill decision_view JSONL into DB projection and validate parity."
    )
    parser.add_argument(
        "--config",
        default="configs/default.yaml",
        help="Path to app config yaml.",
    )
    parser.add_argument(
        "--mode",
        choices=["backfill", "parity", "all"],
        default="all",
        help="Run backfill only, parity only, or both.",
    )
    parser.add_argument(
        "--source-jsonl",
        default="",
        help="Override source JSONL path. Defaults to <data_dir>/decisions/decision_view.jsonl.",
    )
    parser.add_argument(
        "--data-dir",
        default="",
        help="Override settings.data.data_dir.",
    )
    parser.add_argument(
        "--db-url",
        default="",
        help="Override settings.database.url.",
    )
    parser.add_argument(
        "--parity-threshold",
        type=float,
        default=0.995,
        help="Minimal parity ratio to pass parity mode.",
    )
    parser.add_argument(
        "--sample-mismatches",
        type=int,
        default=20,
        help="Max number of mismatch samples in report.",
    )
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
