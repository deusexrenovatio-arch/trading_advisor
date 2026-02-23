from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class ContextSpec:
    context_id: str
    summary: str
    owned_paths: tuple[str, ...]
    guarded_paths: tuple[str, ...]
    source_of_truth: tuple[str, ...]
    minimal_checks: tuple[str, ...]
    risk: str = "normal"


CONTEXTS: tuple[ContextSpec, ...] = (
    ContextSpec(
        context_id="CTX-DATA",
        summary="Ingestion and normalization of external market/reference data.",
        owned_paths=(
            "src/moex_carry/data/",
            "src/moex_carry/minute_ingest/",
            "src/moex_carry/history.py",
            "data/output/intraday_minute_series/",
            "data/state/incremental_replay/",
        ),
        guarded_paths=("contracts/", "docs/contracts/", "src/moex_carry/storage/", "ui-web/"),
        source_of_truth=(
            "AGENTS.md",
            "docs/architecture/modules/backend-core.md",
            "docs/architecture/modules/compute-stack-policy.md",
        ),
        minimal_checks=(
            "python scripts/run_lean_gate.py",
            "python scripts/check_data_integrity.py --data-dir data --max-day-gap 2",
        ),
    ),
    ContextSpec(
        context_id="CTX-STRATEGY",
        summary="Signals, gates, portfolio intent, and decision semantics.",
        owned_paths=(
            "src/moex_carry/strategy/",
            "src/moex_carry/selection/",
            "src/moex_carry/portfolio/",
            "src/moex_carry/pretrade/",
            "src/moex_carry/domain/",
        ),
        guarded_paths=("contracts/", "docs/contracts/", "src/moex_carry/storage/", "ui-web/"),
        source_of_truth=(
            "AGENTS.md",
            "docs/architecture/modules/strategy-signal-interface.md",
            "contracts/decision-log.schema.json",
        ),
        minimal_checks=("python scripts/run_lean_gate.py", "pytest tests/architecture -q"),
    ),
    ContextSpec(
        context_id="CTX-RESEARCH",
        summary="Backtest v2, minute replay, and HPO runtime/performance.",
        owned_paths=(
            "src/moex_carry/backtest_v2/",
            "src/moex_carry/hpo/",
            "src/moex_carry/signal_replay/",
            "src/moex_carry/analytics/alpha.py",
        ),
        guarded_paths=("contracts/", "src/moex_carry/storage/", "src/moex_carry/ui/", "ui-web/"),
        source_of_truth=(
            "AGENTS.md",
            "docs/architecture/modules/minute-replay-canon-v1.md",
            "docs/architecture/modules/compute-stack-policy.md",
        ),
        minimal_checks=("python scripts/run_lean_gate.py", "pytest tests/perf -q"),
    ),
    ContextSpec(
        context_id="CTX-API-UI",
        summary="API handlers, UI behavior, and operator-facing delivery surfaces.",
        owned_paths=("src/moex_carry/ui/", "ui-web/", "src/moex_carry/integrations/"),
        guarded_paths=(
            "src/moex_carry/strategy/",
            "src/moex_carry/backtest_v2/",
            "src/moex_carry/storage/",
        ),
        source_of_truth=(
            "AGENTS.md",
            "docs/architecture/modules/ui-web.md",
            "docs/contracts/api-v2.yaml",
        ),
        minimal_checks=(
            "python scripts/run_lean_gate.py",
            "npm --prefix ui-web run lint",
            "npm --prefix ui-web run build",
        ),
    ),
    ContextSpec(
        context_id="CTX-CONTRACTS",
        summary="Schema/version boundaries for storage and API contracts.",
        owned_paths=(
            "contracts/",
            "docs/contracts/api-v2.yaml",
            "src/moex_carry/storage/",
            "src/moex_carry/contracts/",
        ),
        guarded_paths=("src/moex_carry/strategy/", "src/moex_carry/backtest_v2/", "ui-web/"),
        source_of_truth=(
            "AGENTS.md",
            "docs/architecture/modules/contracts-configs.md",
            "docs/contracts/api-v2.yaml",
        ),
        minimal_checks=(
            "python scripts/run_lean_gate.py",
            "python scripts/validate_dependency_decisions.py",
        ),
        risk="high",
    ),
    ContextSpec(
        context_id="CTX-OPS",
        summary="Governance automation, observability, and operational tooling.",
        owned_paths=(
            "src/moex_carry/observability/",
            "scripts/",
            "docs/workflows/",
            "docs/runbooks/",
            "docs/agent-contexts/",
            "docs/session_handoff.md",
            "docs/readme.md",
            "memory/",
            "plans/",
            ".githooks/",
        ),
        guarded_paths=(
            "src/moex_carry/strategy/",
            "src/moex_carry/backtest_v2/",
            "contracts/",
            "ui-web/",
        ),
        source_of_truth=(
            "AGENTS.md",
            "docs/DEV_WORKFLOW.md",
            "docs/workflows/context-budget.md",
        ),
        minimal_checks=(
            "python scripts/run_lean_gate.py",
            "python scripts/validate_session_handoff.py",
        ),
    ),
)

CONTEXT_PRIORITY: tuple[str, ...] = tuple(spec.context_id for spec in CONTEXTS)


def _normalize_path(raw: str) -> str:
    return raw.replace("\\", "/").strip().lower()


def _prefix_match(path: str, owned: str) -> bool:
    normalized_owned = _normalize_path(owned).rstrip("/")
    return path == normalized_owned or path.startswith(f"{normalized_owned}/")


def _collect_changed_from_git(git_ref: str) -> list[str]:
    changed_cmd = ["git", "diff", "--name-only", git_ref]
    changed = subprocess.run(changed_cmd, check=False, capture_output=True, text=True)
    if changed.returncode != 0:
        return []

    untracked_cmd = ["git", "ls-files", "--others", "--exclude-standard"]
    untracked = subprocess.run(untracked_cmd, check=False, capture_output=True, text=True)
    untracked_lines: list[str] = []
    if untracked.returncode == 0:
        untracked_lines = [line.strip() for line in untracked.stdout.splitlines() if line.strip()]

    changed_lines = [line.strip() for line in changed.stdout.splitlines() if line.strip()]
    return _deduplicate(changed_lines + untracked_lines)


def _collect_changed_from_stdin() -> list[str]:
    return [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]


def _deduplicate(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        marker = _normalize_path(item)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def _get_context(context_id: str) -> ContextSpec:
    for spec in CONTEXTS:
        if spec.context_id == context_id:
            return spec
    raise KeyError(context_id)


def _select_primary(context_counts: dict[str, int]) -> str | None:
    if not context_counts:
        return None
    candidates = sorted(
        context_counts.items(),
        key=lambda item: (-item[1], CONTEXT_PRIORITY.index(item[0])),
    )
    return candidates[0][0]


def route_files(changed_files: list[str]) -> dict[str, object]:
    normalized = [(_normalize_path(path), path) for path in _deduplicate(changed_files)]
    if not normalized:
        return {
            "primary_context": None,
            "contexts": [],
            "unmapped_files": [],
            "recommendations": ["No files provided. Use --from-git, --stdin, or --changed-files."],
        }

    matched: dict[str, list[str]] = defaultdict(list)
    unmapped: list[str] = []

    for normalized_path, original_path in normalized:
        owners = [
            spec.context_id
            for spec in CONTEXTS
            if any(_prefix_match(normalized_path, owned) for owned in spec.owned_paths)
        ]
        if not owners:
            unmapped.append(original_path)
            continue
        for context_id in owners:
            matched[context_id].append(original_path)

    counts = {context_id: len(paths) for context_id, paths in matched.items()}
    primary = _select_primary(counts)

    context_entries: list[dict[str, object]] = []
    for context_id in sorted(matched, key=lambda cid: CONTEXT_PRIORITY.index(cid)):
        spec = _get_context(context_id)
        context_entries.append(
            {
                "id": context_id,
                "summary": spec.summary,
                "risk": spec.risk,
                "matched_files_count": len(matched[context_id]),
                "matched_files": sorted(matched[context_id]),
                "guarded_paths": list(spec.guarded_paths),
                "source_of_truth": list(spec.source_of_truth),
                "minimal_checks": list(spec.minimal_checks),
            }
        )

    recommendations: list[str] = []
    if len(context_entries) > 1:
        recommendations.append(
            "Patch touches multiple contexts. Split by ownership to keep review and agent context small."
        )
    if "CTX-CONTRACTS" in matched and len(context_entries) > 1:
        recommendations.append(
            "CTX-CONTRACTS is combined with other contexts. Use ordered patch series: contracts -> code -> docs."
        )
    if unmapped:
        recommendations.append(
            "Some files are unmapped. Classify manually before implementation."
        )
    if not recommendations:
        recommendations.append("Patch is scoped to one context.")

    return {
        "primary_context": primary,
        "contexts": context_entries,
        "unmapped_files": sorted(unmapped),
        "recommendations": recommendations,
    }


def _render_text(result: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append(f"primary_context: {result.get('primary_context')}")

    contexts = result.get("contexts", [])
    if isinstance(contexts, list):
        for item in contexts:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('id')} files={item.get('matched_files_count')} risk={item.get('risk')}"
            )
            matched_files = item.get("matched_files", [])
            if isinstance(matched_files, list):
                for path in matched_files:
                    lines.append(f"  * {path}")

    unmapped = result.get("unmapped_files", [])
    if isinstance(unmapped, list) and unmapped:
        lines.append("unmapped_files:")
        for path in unmapped:
            lines.append(f"- {path}")

    recommendations = result.get("recommendations", [])
    if isinstance(recommendations, list):
        lines.append("recommendations:")
        for note in recommendations:
            lines.append(f"- {note}")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Route changed files to AI ownership contexts."
    )
    parser.add_argument(
        "--from-git",
        action="store_true",
        help="Load changed files from `git diff --name-only <git-ref>`.",
    )
    parser.add_argument(
        "--git-ref",
        type=str,
        default="HEAD",
        help="Git ref used with --from-git (default: HEAD).",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Load newline-separated file paths from stdin.",
    )
    parser.add_argument(
        "--changed-files",
        nargs="*",
        default=[],
        help="Explicit changed file list.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    changed_files: list[str] = list(args.changed_files)
    if args.from_git:
        changed_files.extend(_collect_changed_from_git(args.git_ref))
    if args.stdin:
        changed_files.extend(_collect_changed_from_stdin())

    result = route_files(changed_files)

    if args.format == "text":
        print(_render_text(result))
        return 0

    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
