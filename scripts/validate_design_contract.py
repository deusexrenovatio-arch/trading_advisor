from __future__ import annotations

import argparse
import sys
from pathlib import Path


REQUIRED_HEADERS = [
    "# UI UX Standards",
    "## Purpose",
    "## Tests and acceptance",
]
REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"


def run(path: Path) -> int:
    if not path.exists():
        print(f"design contract failed: missing file {path.as_posix()}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    lines = [line for line in text.splitlines() if line.strip()]
    errors: list[str] = []
    if len(lines) < 20:
        errors.append("design standards document is too short (<20 non-empty lines)")
    for header in REQUIRED_HEADERS:
        if header not in text:
            errors.append(f"missing section header: {header}")

    if errors:
        print("design contract failed:")
        for item in errors:
            print(f"- {item}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    print("design contract: OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate UI design contract documentation.")
    parser.add_argument("--path", default="docs/ui-ux-standards.md")
    args = parser.parse_args()
    sys.exit(run(Path(args.path)))


if __name__ == "__main__":
    main()
