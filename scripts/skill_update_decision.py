from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


GOVERNANCE_TRIGGER_FILES = {
    "agents.md",
    "docs/dev_workflow.md",
    "docs/checklists/first-time-right-gate.md",
    "docs/runbooks/governance-remediation.md",
    "scripts/run_loop_gate.py",
}
SKILL_FILE_RE = re.compile(r"^\.cursor/skills/([^/\\\\]+)(/|\\\\)SKILL\\.md$", re.IGNORECASE)
STOP_WORDS = {
    "add",
    "against",
    "and",
    "api",
    "as",
    "at",
    "auto",
    "before",
    "build",
    "by",
    "change",
    "changes",
    "check",
    "context",
    "decision",
    "for",
    "from",
    "governance",
    "how",
    "in",
    "into",
    "into",
    "is",
    "it",
    "its",
    "just",
    "local",
    "may",
    "must",
    "need",
    "of",
    "on",
    "or",
    "out",
    "project",
    "related",
    "request",
    "run",
    "should",
    "skill",
    "skills",
    "to",
    "update",
    "updated",
    "updates",
    "без",
    "для",
    "если",
    "это",
    "как",
    "когда",
    "надо",
    "нужно",
    "по",
    "при",
    "про",
    "так",
    "через",
    "using",
    "when",
    "with",
    "would",
}

TOKEN_RE = re.compile(r"[0-9]+|[^\W\d_]+", re.UNICODE)
COVERAGE_STRONG = 0.45
COVERAGE_MODERATE = 0.25
COVERAGE_GAP_AMBIGUOUS = 0.08


@dataclass
class Candidate:
    name: str
    score: float
    reasons: list[str]


@dataclass
class Decision:
    action: str
    confidence: str
    score: float
    targets: list[Candidate]
    gates: list[dict[str, str]]
    rationale: list[str]
    next_steps: list[str]


def _normalize(s: str) -> str:
    return s.replace("\\", "/").lower()


def _tokenize(text: str) -> set[str]:
    return {
        t.lower()
        for t in TOKEN_RE.findall(text.lower())
        if t.lower() not in STOP_WORDS and len(t) > 2
    }


def _load_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8-sig").lstrip("\ufeff")
    if not text.startswith("---"):
        return {}
    try:
        _, body = text.split("---", 1)
        fm_raw, _ = body.split("\n---", 1)
    except ValueError:
        return {}
    data = yaml.safe_load(fm_raw) or {}
    return data if isinstance(data, dict) else {}


def _load_skills(skills_root: Path) -> dict[str, set[str]]:
    skills: dict[str, set[str]] = {}
    if not skills_root.exists():
        return skills

    for skill_dir in sorted([p for p in skills_root.iterdir() if p.is_dir()]):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        fm = _load_frontmatter(skill_file)
        name = str(fm.get("name", skill_dir.name))
        description = str(fm.get("description", ""))
        tokens = _tokenize(name.replace("-", " ") + " " + description)
        tokens.update(_tokenize(skill_dir.name))
        # add skill-name alias forms
        for alias in skill_dir.name.split("-"):
            tokens.add(alias)
        tokens.add(skill_dir.name.replace("-", " "))
        skills[name] = tokens
    return skills


def _collect_changed_from_git() -> list[Path]:
    cmd = ["git", "diff", "--name-only", "HEAD"]
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        return []
    return [
        Path(line.strip())
        for line in completed.stdout.splitlines()
        if line.strip()
    ]


def _collect_intent_tokens(
    changed_paths: Iterable[Path], request: str | None
) -> set[str]:
    tokens: set[str] = set()
    for path in changed_paths:
        tokens.update(_tokenize(path.as_posix().replace("\\", " ")))
    if request:
        tokens.update(_tokenize(request))
    return tokens


def _normalize_global_roots() -> list[Path]:
    roots = []
    for candidate in (os.environ.get("CODEX_HOME"), os.environ.get("USERPROFILE")):
        if not candidate:
            continue
        base = Path(candidate).expanduser()
        if base.name.lower() == "skills":
            roots.append(base)
        elif base.name.lower() == ".codex":
            roots.append(base / "skills")
        else:
            roots.append(base / ".codex" / "skills")
    return roots


def _classify_changed(
    changed_paths: Iterable[Path],
) -> tuple[set[str], bool, bool]:
    direct_skill_targets: set[str] = set()
    governance_touched = False
    global_skill_touched = False
    global_roots = [_normalize(str(p)) for p in _normalize_global_roots()]

    for path in changed_paths:
        normalized = _normalize(path.as_posix())
        if normalized.startswith(".cursor/skills/") and normalized.endswith("skill.md"):
            marker = ".cursor/skills/"
            if marker in normalized:
                suffix = normalized.split(marker, 1)[1]
                target = suffix.split("/", 1)[0]
                if target:
                    direct_skill_targets.add(target)
                    continue
        m = SKILL_FILE_RE.match(normalized)
        if m:
            direct_skill_targets.add(m.group(1))
            continue

        normalized_name = Path(normalized).name.lower()
        if normalized in GOVERNANCE_TRIGGER_FILES or normalized_name in GOVERNANCE_TRIGGER_FILES:
            governance_touched = True

        for root in global_roots:
            if root and normalized.startswith(root):
                global_skill_touched = True
                break

    return direct_skill_targets, governance_touched, global_skill_touched


def _score_candidates(
    intent_tokens: set[str], skill_index: dict[str, set[str]]
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for name, tokens in skill_index.items():
        if not intent_tokens:
            score = 0.0
            reason = ["No intent tokens provided."]
            candidates.append(Candidate(name=name, score=score, reasons=reason))
            continue
        overlap = intent_tokens & tokens
        if not overlap:
            score = 0.0
            reason = ["No token overlap between request and skill metadata."]
        else:
            score = (2 * len(overlap) / (len(intent_tokens) + len(tokens)))
            reason = [f"Overlapping tokens: {', '.join(sorted(overlap))}"]
        candidates.append(Candidate(name=name, score=round(score, 3), reasons=reason))
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates


def _decision_from_candidates(
    direct_skills: set[str],
    governance_touched: bool,
    global_touched: bool,
    known_skills: set[str],
    intent_tokens: set[str],
    candidates: list[Candidate],
) -> Decision:
    gates: list[dict[str, str]] = []
    rationale: list[str] = []
    next_steps: list[str] = []

    if governance_touched:
        gates.append(
            {
                "gate": "evidence_source_docs",
                "status": "pass",
                "reason": "Change touches repository governance source documents.",
            }
        )
    else:
        gates.append(
            {
                "gate": "evidence_source_docs",
                "status": "warn",
                "reason": "No direct governance-source file change detected.",
            }
        )

    known_direct_skills = sorted([skill for skill in direct_skills if skill in known_skills])
    unknown_direct_skills = sorted(direct_skills - set(known_direct_skills))

    if known_direct_skills:
        gates.append(
            {
                "gate": "existing_skill_target",
                "status": "pass",
                "reason": "Direct local skill file change detected.",
            }
        )
        if unknown_direct_skills:
            gates.append(
                {
                    "gate": "unknown_skill_target",
                    "status": "warn",
                    "reason": (
                        "Some direct targets are not in local catalog: "
                        + ", ".join(unknown_direct_skills)
                    ),
                }
            )
            rationale.append(
                "Update known skills and route unknown targets through onboarding."
            )
            next_steps.append(
                "Run `skill-creator` and `skill-installer` for unknown targets, then update `AGENTS.md`."
            )
        action = "UPDATE_EXISTING"
        confidence = "high"
        targets = [
            Candidate(
                name=skill,
                score=1.0,
                reasons=["Direct .cursor/skills/<skill>/SKILL.md edit."],
            )
            for skill in known_direct_skills
        ]
        rationale.append("Workflow change is scoped to one or more existing skills.")
        next_steps.extend(
            [
                "Mirror/refresh global content if applicable.",
                "Run `python scripts/validate_skills.py`.",
            ]
        )
        return Decision(action, confidence, 1.0, targets, gates, rationale, next_steps)

    if unknown_direct_skills:
        action = "ADD_NEW"
        confidence = "medium"
        gates.append(
            {
                "gate": "existing_skill_target",
                "status": "warn",
                "reason": (
                    "Direct local skill path change does not map to existing catalog: "
                    + ", ".join(unknown_direct_skills)
                ),
            }
        )
        rationale.append(
            "Direct local skill edits do not match local catalog; add a new skill through onboarding."
        )
        targets = [
            Candidate(
                name=unknown_direct_skills[0],
                score=0.0,
                reasons=["Unknown target path changed."],
            )
        ]
        next_steps.extend(
            [
                "Run `skill-creator` then `skill-installer` for the new skill.",
                "Keep baseline governance section in new `SKILL.md` and add path in `AGENTS.md`.",
                "Run `python scripts/validate_skills.py`.",
            ]
        )
        return Decision(action, confidence, 0.0, targets, gates, rationale, next_steps)

    if governance_touched:
        gates.append(
            {
                "gate": "governance_scope",
                "status": "pass",
                "reason": "Change touches governance source docs; apply baseline update path.",
            }
        )
        action = "UPDATE_EXISTING"
        confidence = "high"
        rationale.append(
            "Governance docs changed, so all local skills should pass through the baseline sync flow."
        )
        targets = [
            Candidate(
                name="all_local_skills",
                score=1.0,
                reasons=[
                    "Repo-level governance baseline update requested in update workflow."
                ],
            )
        ]
        next_steps.extend(
            [
                "Refresh all local skill governance sections per this workflow.",
                "Re-run `python scripts/validate_skills.py` and `python scripts/run_loop_gate.py --from-git --git-ref HEAD`.",
            ]
        )
        return Decision(action, confidence, 1.0, targets, gates, rationale, next_steps)

    if global_touched:
        gates.append(
            {
                "gate": "global_mirror",
                "status": "pass",
                "reason": "Global catalog path changed; mirror workflow applies.",
            }
        )
        action = "UPDATE_EXISTING"
        confidence = "high"
        rationale.append(
            "Global-catalog change should be mirrored locally and synchronized."
        )
        top = candidates[0] if candidates else None
        target_name = top.name if top else "global-skill"
        targets = [
            Candidate(
                name=target_name,
                score=top.score if top else 1.0,
                reasons=["Triggered by global catalog drift."],
            )
        ]
        next_steps.extend(
            [
                "Mirror or refresh the matching skill into `.cursor/skills`.",
                "Sync governance baseline section in mirrored skills.",
            ]
        )
        return Decision(action, confidence, targets[0].score, targets, gates, rationale, next_steps)

    if not candidates:
        gates.append(
            {
                "gate": "candidate_scoring",
                "status": "fail",
                "reason": "No candidate skills available for matching.",
            }
        )
        return Decision(
            action="NO_CHANGE",
            confidence="low",
            score=0.0,
            targets=[],
            gates=gates,
            rationale=["No skill catalog available."],
            next_steps=["Check `.cursor/skills` exists and re-run command."],
        )

    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    gap = (top.score - second.score) if second else top.score

    if top.score >= COVERAGE_STRONG and gap >= COVERAGE_GAP_AMBIGUOUS * 2:
        gates.append(
            {
                "gate": "coverage_strength",
                "status": "pass",
                "reason": f"Strong overlap with '{top.name}' (score {top.score:.2f}).",
            }
        )
        gates.append(
            {
                "gate": "ambiguity",
                "status": "pass",
                "reason": "Clear winner in token overlap scoring.",
            }
        )
        rationale.append(
            "Best match signal is strong and unambiguous; update existing skill."
        )
        next_steps.extend(
            [
                f"Patch `{top.name}` instead of creating a new skill.",
                "Run `docs/workflows/skill-governance-sync.md` update step if governance text changed.",
            ]
        )
        return Decision(
            action="UPDATE_EXISTING",
            confidence="high",
            score=top.score,
            targets=[top],
            gates=gates,
            rationale=rationale,
            next_steps=next_steps,
        )

    if top.score >= COVERAGE_MODERATE and gap >= COVERAGE_GAP_AMBIGUOUS and intent_tokens:
        gates.append(
            {
                "gate": "coverage_strength",
                "status": "warn",
                "reason": f"Moderate overlap with '{top.name}' (score {top.score:.2f}).",
            }
        )
        gates.append(
            {
                "gate": "ambiguity",
                "status": "pass" if gap >= 0.08 else "warn",
                "reason": f"Top/2 gap is {gap:.2f}.",
            }
        )
        rationale.append(
            "Some match exists, but signal strength is moderate; proceed with careful scope check."
        )
        next_steps.extend(
            [
                f"Prefer `{top.name}` if scope is within current workflow.",
                "If intent extends to a new domain boundary, switch to ADD_NEW.",
            ]
        )
        return Decision(
            action="UPDATE_EXISTING",
            confidence="medium",
            score=top.score,
            targets=[top],
            gates=gates,
            rationale=rationale,
            next_steps=next_steps,
        )

    if top.score < COVERAGE_MODERATE:
        gates.append(
            {
                "gate": "coverage_strength",
                "status": "fail",
                "reason": f"Low overlap with known skills (best '{top.name}' score {top.score:.2f}).",
            }
        )
        gates.append(
            {
                "gate": "ambiguity",
                "status": "warn",
                "reason": "No single domain skill has clear lexical support.",
            }
        )
        rationale.append(
            "No existing skill has clear coverage for this intent; adding a new skill is likely better."
        )
        next_steps.extend(
            [
                "Create a new skill (use `python .cursor/skills/skill-installer/SKILL.md` workflow when needed).",
                "Keep baseline governance section and add to `AGENTS.md` skill list.",
                "Re-run `python scripts/validate_skills.py`.",
            ]
        )
        return Decision(
            action="ADD_NEW",
            confidence="medium",
            score=top.score,
            targets=[top],
            gates=gates,
            rationale=rationale,
            next_steps=next_steps,
        )

    gates.append(
        {
            "gate": "coverage_strength",
            "status": "warn",
            "reason": "Match is too ambiguous under current heuristics.",
        }
    )
    rationale.append("Keep this as a manual review case before choosing action.")
    next_steps.extend(
        [
            "Re-run with explicit `--request` text or domain boundaries.",
            "Provide a concrete user scenario before deciding new vs existing.",
        ]
    )
    return Decision(
        action="NO_CHANGE",
        confidence="low",
        score=top.score,
        targets=[top],
        gates=gates,
        rationale=rationale,
        next_steps=next_steps,
    )


def _render_text(decision: Decision) -> None:
    print(f"action: {decision.action}")
    print(f"confidence: {decision.confidence} (score={decision.score:.2f})")
    print("gates:")
    for gate in decision.gates:
        print(
            f"- {gate['gate']}: {gate['status']} -> {gate['reason']}"
        )

    if decision.targets:
        print("targets:")
        for target in decision.targets[:3]:
            reason = ", ".join(target.reasons)
            print(f"- {target.name}: {target.score:.2f} ({reason})")

    print("rationale:")
    for item in decision.rationale:
        print(f"- {item}")

    if decision.next_steps:
        print("next steps:")
        for step in decision.next_steps:
            print(f"- {step}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Machine-guided decision helper: existing skill update vs new skill creation."
        )
    )
    parser.add_argument(
        "--changed-files",
        nargs="*",
        default=None,
        help="Optional explicit paths that triggered the request.",
    )
    parser.add_argument(
        "--from-git",
        action="store_true",
        help="Collect changed paths from `git diff --name-only HEAD`.",
    )
    parser.add_argument(
        "--request",
        default=None,
        help="Free-text request/intent that caused this workstream.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    parser.add_argument(
        "--skills-root",
        default=".cursor/skills",
        help="Root of local skills catalog.",
    )
    args = parser.parse_args()

    changed_paths = [Path(path) for path in args.changed_files] if args.changed_files else []
    if args.from_git:
        changed_paths = _collect_changed_from_git()

    if not changed_paths and not args.request:
        print(
            "No changed files provided and no --request text."
            " Use --changed-files or --request."
        )
        return 1

    direct_skills, governance_touched, global_skill_touched = _classify_changed(
        changed_paths
    )
    intent_tokens = _collect_intent_tokens(changed_paths, args.request)
    skill_index = _load_skills(Path(args.skills_root))
    candidates = _score_candidates(intent_tokens, skill_index)
    decision = _decision_from_candidates(
        direct_skills=direct_skills,
        governance_touched=governance_touched,
        global_touched=global_skill_touched,
        known_skills=set(skill_index),
        intent_tokens=intent_tokens,
        candidates=candidates,
    )

    if args.json:
        payload = {
            "action": decision.action,
            "confidence": decision.confidence,
            "score": decision.score,
            "targets": [
                {"name": c.name, "score": c.score, "reasons": c.reasons}
                for c in decision.targets
            ],
            "gates": decision.gates,
            "rationale": decision.rationale,
            "next_steps": decision.next_steps,
            "meta": {
                "changed_files": [path.as_posix() for path in changed_paths],
                "intent_tokens": sorted(intent_tokens),
                "skill_count": len(skill_index),
                "top_candidate": candidates[0].name if candidates else None,
                "thresholds": {
                    "coverage_strong": COVERAGE_STRONG,
                    "coverage_moderate": COVERAGE_MODERATE,
                    "ambiguity_gap": COVERAGE_GAP_AMBIGUOUS,
                },
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _render_text(decision)

    return 0


if __name__ == "__main__":
    sys.exit(main())

