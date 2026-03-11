from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from handoff_resolver import read_task_note_lines

TOKEN_RE = re.compile(r"[0-9]+|[^\W\d_]+", re.UNICODE)
PY_FROM_IMPORT_RE = re.compile(
    r"^\s*from\s+(moex_carry(?:\.[A-Za-z0-9_]+)*)\s+import",
    re.MULTILINE,
)
PY_IMPORT_RE = re.compile(
    r"^\s*import\s+(moex_carry(?:\.[A-Za-z0-9_]+)*)",
    re.MULTILINE,
)
STOP_WORDS = {
    "agent",
    "agents",
    "and",
    "artifact",
    "artifacts",
    "block",
    "check",
    "checks",
    "code",
    "context",
    "contexts",
    "data",
    "docs",
    "file",
    "files",
    "for",
    "from",
    "goal",
    "guarded",
    "input",
    "inputs",
    "module",
    "modules",
    "output",
    "outputs",
    "owned",
    "path",
    "paths",
    "risk",
    "scope",
    "source",
    "sources",
    "src",
    "task",
    "tasks",
    "the",
    "truth",
    "use",
    "with",
}

COLD_CONTEXT_PREFIXES: tuple[str, ...] = (
    "plans/",
    "memory/",
    "artifacts/",
    "docs/releases/",
    "docs/releases.d/",
    ".cursor/skills/",
    "docs/tasks/archive/",
)


@dataclass(frozen=True)
class ContextSpec:
    context_id: str
    summary: str
    owned_paths: tuple[str, ...]
    guarded_paths: tuple[str, ...]
    source_of_truth: tuple[str, ...]
    minimal_checks: tuple[str, ...]
    intent_keywords: tuple[str, ...]
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
            "docs/agent/entrypoint.md",
            "docs/architecture/modules/backend-core.md",
            "docs/architecture/modules/compute-stack-policy.md",
        ),
        minimal_checks=(
            "python scripts/run_loop_gate.py --from-git --git-ref HEAD",
            "python scripts/check_data_integrity.py --data-dir data --max-day-gap 2",
        ),
        intent_keywords=(
            "ingest",
            "ingestion",
            "marketdata",
            "moex",
            "cbr",
            "history",
            "candle",
            "candles",
            "minute",
            "provider",
            "snapshot",
        ),
    ),
    ContextSpec(
        context_id="CTX-STRATEGY",
        summary="Signals, gates, portfolio intent, and decision semantics.",
        owned_paths=(
            "src/moex_carry/strategy/",
            "src/moex_carry/signal_engine/",
            "src/moex_carry/selection/",
            "src/moex_carry/portfolio/",
            "src/moex_carry/pretrade/",
            "src/moex_carry/domain/",
        ),
        guarded_paths=("contracts/", "docs/contracts/", "src/moex_carry/storage/", "ui-web/"),
        source_of_truth=(
            "docs/agent/entrypoint.md",
            "docs/architecture/modules/strategy-signal-interface.md",
            "contracts/decision-log.schema.json",
        ),
        minimal_checks=("python scripts/run_loop_gate.py --from-git --git-ref HEAD", "pytest tests/architecture -q"),
        intent_keywords=(
            "signal",
            "signals",
            "strategy",
            "risk",
            "portfolio",
            "allocation",
            "selection",
            "ranking",
            "decision",
            "pretrade",
            "gate",
        ),
    ),
    ContextSpec(
        context_id="CTX-RESEARCH",
        summary="Backtest, replay, analytics, and HPO runtime/performance.",
        owned_paths=(
            "src/moex_carry/analytics/",
            "src/moex_carry/backtest/",
            "src/moex_carry/backtest_v2/",
            "src/moex_carry/broker/",
            "src/moex_carry/costs/",
            "src/moex_carry/execution/",
            "src/moex_carry/forward/",
            "src/moex_carry/hpo/",
            "src/moex_carry/perf.py",
            "src/moex_carry/signal_replay/",
            "src/moex_carry/snapshot/",
        ),
        guarded_paths=("contracts/", "src/moex_carry/storage/", "src/moex_carry/ui/", "ui-web/"),
        source_of_truth=(
            "docs/agent/entrypoint.md",
            "docs/architecture/modules/minute-replay-canon-v1.md",
            "docs/architecture/modules/compute-stack-policy.md",
        ),
        minimal_checks=("python scripts/run_loop_gate.py --from-git --git-ref HEAD", "pytest tests/perf -q"),
        intent_keywords=(
            "analytics",
            "alpha",
            "backtest",
            "costs",
            "execution",
            "forward",
            "hpo",
            "replay",
            "research",
            "snapshot",
            "walk",
        ),
    ),
    ContextSpec(
        context_id="CTX-NEWS",
        summary="News intelligence, shock pipeline, and event-driven alerting.",
        owned_paths=(
            "src/moex_carry/news/",
            "src/moex_carry/news_causal.py",
            "src/moex_carry/news_causal_rules.py",
            "src/moex_carry/news_commodity_graph.py",
            "src/moex_carry/news_commodity_graph_knowledge.py",
            "src/moex_carry/news_live_bridge.py",
            "src/moex_carry/news_live_causal_ops.py",
            "src/moex_carry/news_live_clients.py",
            "src/moex_carry/news_live_feed.py",
            "src/moex_carry/news_live_runtime.py",
            "src/moex_carry/news_live_runtime_ops.py",
            "src/moex_carry/news_live_schema.py",
            "src/moex_carry/news_live_scoring.py",
            "src/moex_carry/news_mode_compare.py",
            "src/moex_carry/news_root_maintenance.py",
            "src/moex_carry/news_runtime_state.py",
            "src/moex_carry/news_shock_backfill.py",
            "src/moex_carry/news_shock_enrichment.py",
            "src/moex_carry/news_shock_live_input.py",
            "src/moex_carry/news_shock_live_input_helpers.py",
            "src/moex_carry/news_shock_schema.py",
            "src/moex_carry/news_shock_automation.py",
            "src/moex_carry/news_shock_pipeline.py",
            "src/moex_carry/news_shock_readiness.py",
            "src/moex_carry/news_shock_store.py",
            "src/moex_carry/news_shock_symbol_map.py",
            "src/moex_carry/news_silver_store.py",
            "src/moex_carry/news_storage.py",
            "src/moex_carry/news_topic.py",
            "src/moex_carry/shock_alert_delivery.py",
            "src/moex_carry/shock_episodes.py",
        ),
        guarded_paths=("src/moex_carry/storage/", "ui-web/", "contracts/"),
        source_of_truth=(
            "docs/agent/entrypoint.md",
            "docs/architecture/layers-v2.md",
            "docs/contracts/api-v2.yaml",
        ),
        minimal_checks=("python scripts/run_loop_gate.py --from-git --git-ref HEAD", "pytest tests/test_news_live_runtime.py -q"),
        intent_keywords=(
            "news",
            "shock",
            "headline",
            "alert",
            "alerts",
            "commodity",
            "sentiment",
            "severity",
            "event",
            "events",
            "story",
        ),
    ),
    ContextSpec(
        context_id="CTX-ORCHESTRATION",
        summary="Entrypoints, runtime wiring, configuration, and cross-context orchestration.",
        owned_paths=(
            "src/moex_carry/__main__.py",
            "src/moex_carry/cli.py",
            "src/moex_carry/cli_news_handlers.py",
            "src/moex_carry/cli_news_parsers.py",
            "src/moex_carry/cli_news_runtime_handlers.py",
            "src/moex_carry/config.py",
            "src/moex_carry/config_news.py",
            "src/moex_carry/config_resolver.py",
            "src/moex_carry/pipeline.py",
            "src/moex_carry/pipeline_helpers.py",
            "src/moex_carry/parameter_specs.py",
            "src/moex_carry/server/",
            "src/moex_carry/unified_runtime.py",
        ),
        guarded_paths=("src/moex_carry/storage/", "contracts/", "ui-web/"),
        source_of_truth=(
            "docs/agent/entrypoint.md",
            "docs/architecture/trading-advisor.md",
            "docs/architecture/layers-v2.md",
        ),
        minimal_checks=("python scripts/run_loop_gate.py --from-git --git-ref HEAD", "python scripts/validate_architecture_policy.py"),
        intent_keywords=(
            "cli",
            "config",
            "entrypoint",
            "orchestration",
            "pipeline",
            "runtime",
            "settings",
            "unified",
            "wiring",
        ),
    ),
    ContextSpec(
        context_id="CTX-API-UI",
        summary="API handlers, UI behavior, operator actions, and delivery surfaces.",
        owned_paths=(
            "src/moex_carry/integrations/",
            "src/moex_carry/signal_execution_contract.py",
            "src/moex_carry/signals_ack.py",
            "src/moex_carry/signals_delivery.py",
            "src/moex_carry/ui/",
            "ui-web/",
        ),
        guarded_paths=(
            "src/moex_carry/strategy/",
            "src/moex_carry/backtest_v2/",
            "src/moex_carry/storage/",
        ),
        source_of_truth=(
            "docs/agent/entrypoint.md",
            "docs/architecture/modules/ui-web.md",
            "docs/contracts/api-v2.yaml",
        ),
        minimal_checks=(
            "python scripts/run_loop_gate.py --from-git --git-ref HEAD",
            "npm --prefix ui-web run lint",
            "npm --prefix ui-web run build",
        ),
        intent_keywords=(
            "action",
            "actions",
            "api",
            "dashboard",
            "delivery",
            "flask",
            "react",
            "route",
            "telegram",
            "ui",
            "view",
        ),
    ),
    ContextSpec(
        context_id="CTX-CONTRACTS",
        summary="Schema/version boundaries for storage, decision projection, and API contracts.",
        owned_paths=(
            "contracts/",
            "docs/contracts/api-v2.yaml",
            "src/moex_carry/contracts/",
            "src/moex_carry/decision_log.py",
            "src/moex_carry/storage/",
        ),
        guarded_paths=("src/moex_carry/strategy/", "src/moex_carry/backtest_v2/", "ui-web/"),
        source_of_truth=(
            "docs/agent/entrypoint.md",
            "docs/architecture/modules/contracts-configs.md",
            "docs/contracts/api-v2.yaml",
        ),
        minimal_checks=(
            "python scripts/run_loop_gate.py --from-git --git-ref HEAD",
            "python scripts/validate_dependency_decisions.py",
        ),
        intent_keywords=(
            "api",
            "contract",
            "contracts",
            "database",
            "decision",
            "projection",
            "repository",
            "schema",
            "sqlite",
            "storage",
        ),
        risk="high",
    ),
    ContextSpec(
        context_id="CTX-OPS",
        summary="Governance automation, observability, logging, and operational tooling.",
        owned_paths=(
            ".githooks/",
            "docs/agent-contexts/",
            "docs/dev_workflow.md",
            "docs/readme.md",
            "docs/runbooks/",
            "docs/session_handoff.md",
            "docs/workflows/",
            "memory/",
            "plans/",
            "scripts/",
            "src/moex_carry/governance/",
            "src/moex_carry/logging.py",
            "src/moex_carry/observability/",
            "tests/architecture/",
            "tests/test_context_router.py",
        ),
        guarded_paths=(
            "src/moex_carry/strategy/",
            "src/moex_carry/backtest_v2/",
            "contracts/",
            "ui-web/",
        ),
        source_of_truth=(
            "docs/agent/entrypoint.md",
            "docs/DEV_WORKFLOW.md",
            "docs/workflows/context-budget.md",
        ),
        minimal_checks=(
            "python scripts/run_loop_gate.py --from-git --git-ref HEAD",
            "python scripts/validate_session_handoff.py",
        ),
        intent_keywords=(
            "ci",
            "gate",
            "governance",
            "handoff",
            "hook",
            "logging",
            "memory",
            "observability",
            "plan",
            "validator",
            "worktree",
        ),
    ),
)

CONTEXT_PRIORITY: tuple[str, ...] = tuple(spec.context_id for spec in CONTEXTS)
DEFAULT_SESSION_HANDOFF_PATH = "docs/session_handoff.md"


def _normalize_path(raw: str) -> str:
    return raw.replace("\\", "/").strip().lower()


def _tokenize(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_RE.findall(text.lower())
        if token.lower() not in STOP_WORDS and len(token) > 2
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _load_session_handoff_text(path_value: str | None) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    if not path.exists():
        return ""
    _resolved_path, lines, _is_pointer = read_task_note_lines(path)
    return "\n".join(lines)


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


def _context_token_pool(spec: ContextSpec) -> set[str]:
    fields = [
        spec.context_id.replace("CTX-", " "),
        spec.summary,
        *spec.intent_keywords,
    ]
    return _tokenize(" ".join(fields))


def _target_bonus(spec: ContextSpec, target_modules: list[str]) -> int:
    bonus = 0
    normalized_owned = [_normalize_path(path) for path in spec.owned_paths]
    for target in target_modules:
        normalized_target = _normalize_path(target)
        if not normalized_target:
            continue
        target_name = Path(normalized_target).stem
        for owned in normalized_owned:
            owned_name = Path(owned).stem
            if normalized_target == owned:
                bonus += 4
            elif target_name and target_name == owned_name:
                bonus += 3
            elif target_name and target_name in owned:
                bonus += 2
    return bonus


def _score_intent_contexts(
    *,
    request_text: str,
    session_handoff_text: str,
    target_modules: list[str],
) -> tuple[dict[str, int], list[str]]:
    intent_sources: list[str] = []
    intent_parts: list[str] = []

    if request_text.strip():
        intent_parts.append(request_text)
        intent_sources.append("request")
    if session_handoff_text.strip():
        intent_parts.append(session_handoff_text)
        intent_sources.append("session_handoff")
    if target_modules:
        intent_parts.extend(target_modules)
        intent_sources.append("target_module")

    intent_tokens = _tokenize(" ".join(intent_parts))
    if not intent_tokens and not target_modules:
        return {}, intent_sources

    scores: dict[str, int] = {}
    for spec in CONTEXTS:
        overlap = len(intent_tokens & _context_token_pool(spec))
        bonus = _target_bonus(spec, target_modules)
        score = overlap + bonus
        if score > 0:
            scores[spec.context_id] = score
    return scores, intent_sources


def _owned_path_to_module_prefix(owned_path: str) -> str | None:
    normalized = _normalize_path(owned_path)
    if not normalized.startswith("src/moex_carry/"):
        return None
    suffix = normalized[len("src/") :]
    if suffix.endswith("/"):
        return suffix[:-1].replace("/", ".")
    if suffix.endswith(".py"):
        return suffix[:-3].replace("/", ".")
    return None


def _contexts_for_module(module_name: str) -> set[str]:
    normalized_module = module_name.strip()
    if not normalized_module:
        return set()

    matched: set[str] = set()
    for spec in CONTEXTS:
        for owned_path in spec.owned_paths:
            module_prefix = _owned_path_to_module_prefix(owned_path)
            if not module_prefix:
                continue
            if (
                normalized_module == module_prefix
                or normalized_module.startswith(f"{module_prefix}.")
                or module_prefix.startswith(f"{normalized_module}.")
            ):
                matched.add(spec.context_id)
    return matched


def _extract_imported_modules(source_text: str) -> set[str]:
    modules = {match.group(1) for match in PY_FROM_IMPORT_RE.finditer(source_text)}
    modules.update(match.group(1) for match in PY_IMPORT_RE.finditer(source_text))
    return {module for module in modules if module}


def _dependency_contexts_for_file(
    file_path: str,
    *,
    owned_contexts: set[str],
) -> list[str]:
    normalized_path = _normalize_path(file_path)
    if not normalized_path.startswith("src/moex_carry/") or not normalized_path.endswith(".py"):
        return []

    source_text = _read_text(Path(file_path))
    if not source_text:
        return []

    related_contexts: set[str] = set()
    for module_name in _extract_imported_modules(source_text):
        related_contexts.update(_contexts_for_module(module_name))

    return sorted(
        related_contexts - owned_contexts,
        key=lambda context_id: CONTEXT_PRIORITY.index(context_id),
    )


def route_files(
    changed_files: list[str],
    *,
    request_text: str = "",
    target_modules: list[str] | None = None,
    session_handoff_text: str = "",
) -> dict[str, object]:
    target_modules = target_modules or []
    normalized = [(_normalize_path(path), path) for path in _deduplicate(changed_files)]

    matched: dict[str, list[str]] = defaultdict(list)
    context_dependency_hints: dict[str, set[str]] = defaultdict(set)
    cold_context_files: list[str] = []
    unmapped: list[str] = []
    unmapped_dependency_hints: dict[str, list[str]] = {}

    for normalized_path, original_path in normalized:
        if any(_prefix_match(normalized_path, prefix) for prefix in COLD_CONTEXT_PREFIXES):
            cold_context_files.append(original_path)
            continue
        owners = [
            spec.context_id
            for spec in CONTEXTS
            if any(_prefix_match(normalized_path, owned) for owned in spec.owned_paths)
        ]
        dependency_contexts = _dependency_contexts_for_file(
            original_path,
            owned_contexts=set(owners),
        )

        if not owners:
            unmapped.append(original_path)
            if dependency_contexts:
                unmapped_dependency_hints[original_path] = dependency_contexts
            continue

        for context_id in owners:
            matched[context_id].append(original_path)
            context_dependency_hints[context_id].update(dependency_contexts)

    intent_scores, intent_sources = _score_intent_contexts(
        request_text=request_text,
        session_handoff_text=session_handoff_text,
        target_modules=target_modules,
    )
    counts = {context_id: len(paths) for context_id, paths in matched.items()}
    primary = _select_primary(counts) or _select_primary(intent_scores)

    if not normalized and not intent_scores:
        return {
            "primary_context": None,
            "contexts": [],
            "intent_sources": intent_sources,
            "cold_context_files": [],
            "unmapped_dependency_hints": {},
            "unmapped_files": [],
            "recommendations": ["No files provided. Use --from-git, --stdin, or --changed-files."],
        }

    visible_contexts: list[str]
    if matched:
        visible_contexts = sorted(matched, key=lambda cid: CONTEXT_PRIORITY.index(cid))
    else:
        max_score = max(intent_scores.values()) if intent_scores else 0
        visible_contexts = [
            context_id
            for context_id, score in sorted(
                intent_scores.items(),
                key=lambda item: (-item[1], CONTEXT_PRIORITY.index(item[0])),
            )
            if score >= max(max_score - 1, 1)
        ]

    context_entries: list[dict[str, object]] = []
    for context_id in visible_contexts:
        spec = _get_context(context_id)
        matched_files = sorted(matched.get(context_id, []))
        context_entries.append(
            {
                "id": context_id,
                "summary": spec.summary,
                "risk": spec.risk,
                "matched_files_count": len(matched_files),
                "matched_files": matched_files,
                "guarded_paths": list(spec.guarded_paths),
                "source_of_truth": list(spec.source_of_truth),
                "minimal_checks": list(spec.minimal_checks),
                "intent_score": int(intent_scores.get(context_id, 0)),
                "dependency_contexts": sorted(
                    context_dependency_hints.get(context_id, set()),
                    key=lambda cid: CONTEXT_PRIORITY.index(cid),
                ),
            }
        )

    recommendations: list[str] = []
    if not normalized and intent_scores:
        recommendations.append("No diff yet. Using request/session intent fallback.")
    if len(context_entries) > 1:
        if matched:
            recommendations.append(
                "Patch touches multiple contexts. Split by ownership to keep review and agent context small."
            )
        else:
            recommendations.append(
                "Intent spans multiple contexts. Set an explicit target module before implementation."
            )
    if "CTX-CONTRACTS" in matched and len(context_entries) > 1:
        recommendations.append(
            "CTX-CONTRACTS is combined with other contexts. Use ordered patch series: contracts -> code -> docs."
        )

    for entry in context_entries:
        dependency_contexts = entry.get("dependency_contexts", [])
        if isinstance(dependency_contexts, list) and len(dependency_contexts) > 1:
            recommendations.append(
                f"{entry['id']} imports span multiple neighboring contexts. Treat as cross-cutting and keep adapters thin."
            )

    if unmapped:
        recommendations.append("Some files are unmapped. Classify manually before implementation.")
    if cold_context_files:
        recommendations.append(
            "Cold-context files are present. Keep them out of hot retrieval unless the task explicitly needs them."
        )

    if not recommendations:
        recommendations.append("Patch is scoped to one context.")

    return {
        "primary_context": primary,
        "contexts": context_entries,
        "intent_sources": intent_sources,
        "cold_context_files": sorted(cold_context_files),
        "unmapped_dependency_hints": unmapped_dependency_hints,
        "unmapped_files": sorted(unmapped),
        "recommendations": recommendations,
    }


def _render_text(result: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append(f"primary_context: {result.get('primary_context')}")

    intent_sources = result.get("intent_sources", [])
    if isinstance(intent_sources, list) and intent_sources:
        lines.append(f"intent_sources: {', '.join(intent_sources)}")

    contexts = result.get("contexts", [])
    if isinstance(contexts, list):
        for item in contexts:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('id')} files={item.get('matched_files_count')} risk={item.get('risk')}"
            )
            intent_score = item.get("intent_score")
            if isinstance(intent_score, int) and intent_score > 0:
                lines.append(f"  * intent_score={intent_score}")
            matched_files = item.get("matched_files", [])
            if isinstance(matched_files, list):
                for path in matched_files:
                    lines.append(f"  * {path}")
            dependency_contexts = item.get("dependency_contexts", [])
            if isinstance(dependency_contexts, list) and dependency_contexts:
                lines.append(f"  * dependency_contexts={', '.join(dependency_contexts)}")

    unmapped = result.get("unmapped_files", [])
    if isinstance(unmapped, list) and unmapped:
        lines.append("unmapped_files:")
        for path in unmapped:
            lines.append(f"- {path}")

    cold_files = result.get("cold_context_files", [])
    if isinstance(cold_files, list) and cold_files:
        lines.append("cold_context_files:")
        for path in cold_files:
            lines.append(f"- {path}")

    unmapped_dependency_hints = result.get("unmapped_dependency_hints", {})
    if isinstance(unmapped_dependency_hints, dict) and unmapped_dependency_hints:
        lines.append("unmapped_dependency_hints:")
        for path, contexts_hint in sorted(unmapped_dependency_hints.items()):
            if not contexts_hint:
                continue
            lines.append(f"- {path}: {', '.join(contexts_hint)}")

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
        "--request",
        type=str,
        default="",
        help="Optional user request text used as intent fallback.",
    )
    parser.add_argument(
        "--target-module",
        action="append",
        default=[],
        help="Optional target module/path hint. Repeat for multiple targets.",
    )
    parser.add_argument(
        "--session-handoff-path",
        type=str,
        default=DEFAULT_SESSION_HANDOFF_PATH,
        help=f"Optional session handoff path for intent fallback (default: {DEFAULT_SESSION_HANDOFF_PATH}).",
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

    result = route_files(
        changed_files,
        request_text=args.request,
        target_modules=list(args.target_module),
        session_handoff_text=_load_session_handoff_text(args.session_handoff_path),
    )

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
