from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


PATTERNS = [
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "private-key-block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    (
        "openai-key-assignment",
        re.compile(r"(?i)\bOPENAI[_-]?API[_-]?KEY\b\s*[:=]\s*[\"']?sk-[A-Za-z0-9]{20,}"),
    ),
]

EXCLUDED_PREFIXES = (
    "docs/",
    "data/",
    ".cursor/",
)
EXCLUDED_SUFFIXES = (
    ".md",
    ".txt",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".lock",
    ".example",
)
EXCLUDED_FILES = {
    ".env.example",
    "ui-web/package-lock.json",
}


def _tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _should_scan(path: str) -> bool:
    if path in EXCLUDED_FILES:
        return False
    if path.startswith(EXCLUDED_PREFIXES):
        return False
    if path.endswith(EXCLUDED_SUFFIXES):
        return False
    return True


def run() -> int:
    findings: list[str] = []
    for rel in _tracked_files():
        if not _should_scan(rel):
            continue
        path = Path(rel)
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern_id, pattern in PATTERNS:
            match = pattern.search(text)
            if match:
                findings.append(f"{rel}:{pattern_id}:{match.group(0)[:60]}")

    if findings:
        print("secret scan failed:")
        for item in findings:
            print(f"- {item}")
        return 1

    print("secret scan: OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan tracked repository files for obvious secrets.")
    parser.parse_args()
    sys.exit(run())


if __name__ == "__main__":
    main()
