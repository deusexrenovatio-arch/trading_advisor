#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import re
import sys


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "change"


def _build_content(title: str) -> str:
    return (
        f"# {title}\n\n"
        "## Highlights\n"
        "- \n\n"
        "## API/Data changes\n"
        "- \n\n"
        "## Config\n"
        "- \n\n"
        "## Docs/Tests\n"
        "- \n\n"
        "## Migration notes\n"
        "- \n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a release note fragment in docs/releases.d/."
    )
    parser.add_argument("--slug", required=True, help="Short slug or title")
    parser.add_argument("--title", default=None, help="Title for the note")
    parser.add_argument(
        "--dir", default="docs/releases.d", help="Output directory (default: docs/releases.d)"
    )
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Date in YYYY-MM-DD (default: today)",
    )
    args = parser.parse_args()

    slug = _slugify(args.slug)
    filename = f"{args.date}-{slug}.md"
    out_dir = Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    if out_path.exists():
        print(f"Refusing to overwrite existing file: {out_path}", file=sys.stderr)
        return 2

    title = args.title or args.slug
    out_path.write_text(_build_content(title), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
