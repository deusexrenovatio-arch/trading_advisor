from __future__ import annotations

import argparse
import sys
from pathlib import Path


REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"
REQUIRED_SNIPPETS: dict[Path, tuple[str, ...]] = {
    Path(".githooks/pre-push"): (
        "MOEX_CARRY_EMERGENCY_MAIN_PUSH",
        "MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON",
        "direct push to main is disabled (PR-only policy)",
        "use a feature branch + PR flow",
    ),
    Path("AGENTS.md"): (
        "PR-only flow for `main`",
        "MOEX_CARRY_EMERGENCY_MAIN_PUSH",
        "MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON",
    ),
    Path("docs/DEV_WORKFLOW.md"): (
        "Direct push to `main` is blocked (PR-only).",
        "MOEX_CARRY_EMERGENCY_MAIN_PUSH",
        "MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON",
    ),
    Path("README.md"): (
        "PR-only policy for `main`",
        "MOEX_CARRY_EMERGENCY_MAIN_PUSH",
        "MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON",
    ),
}
FORBIDDEN_SNIPPETS: dict[Path, tuple[str, ...]] = {
    Path(".githooks/pre-push"): (
        "MOEX_CARRY_BLOCK_MAIN_PUSH=0",
    ),
    Path("AGENTS.md"): ("MOEX_CARRY_ALLOW_MAIN_PUSH=1",),
    Path("docs/DEV_WORKFLOW.md"): ("MOEX_CARRY_ALLOW_MAIN_PUSH=1",),
    Path("README.md"): ("MOEX_CARRY_ALLOW_MAIN_PUSH=1",),
}


def run(root: Path) -> int:
    errors: list[str] = []
    for rel_path, snippets in REQUIRED_SNIPPETS.items():
        path = root / rel_path
        if not path.exists():
            errors.append(f"missing file: {rel_path.as_posix()}")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for snippet in snippets:
            if snippet not in text:
                errors.append(
                    f"{rel_path.as_posix()}: missing required snippet '{snippet}'"
                )

    for rel_path, snippets in FORBIDDEN_SNIPPETS.items():
        path = root / rel_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for snippet in snippets:
            if snippet in text:
                errors.append(
                    f"{rel_path.as_posix()}: contains forbidden snippet '{snippet}'"
                )

    if errors:
        print("PR-only policy validation failed:")
        for item in errors:
            print(f"- {item}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    print("PR-only policy validation: OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate PR-only policy enforcement.")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    sys.exit(run(Path(args.repo_root)))


if __name__ == "__main__":
    main()
