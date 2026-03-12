from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    imported: str
    reason: str


def _iter_python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _is_ui_path(path: Path, ui_root: Path) -> bool:
    try:
        path.relative_to(ui_root)
        return True
    except ValueError:
        return False


def _collect_imports(path: Path) -> list[tuple[int, str]]:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(path))
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((int(node.lineno), str(alias.name)))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append((int(node.lineno), str(node.module)))
    return imports


def run(
    *,
    src_root: Path,
    forbidden_prefix: str,
    allowed_paths: set[Path],
) -> int:
    ui_root = src_root / "ui"
    violations: list[Violation] = []

    for path in _iter_python_files(src_root):
        if _is_ui_path(path, ui_root):
            continue
        if path in allowed_paths:
            continue
        for line, imported in _collect_imports(path):
            if imported == forbidden_prefix or imported.startswith(f"{forbidden_prefix}."):
                violations.append(
                    Violation(
                        path=path,
                        line=line,
                        imported=imported,
                        reason="core->ui import is forbidden outside UI layer and entrypoint allowlist",
                    )
                )

    if violations:
        print("import boundary violations:")
        for violation in violations:
            print(
                f"- {violation.path.as_posix()}:{violation.line}: "
                f"import '{violation.imported}' ({violation.reason})"
            )
        return 1

    print("import boundary check: OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Python import boundaries (no core->ui dependencies)."
    )
    parser.add_argument("--src-root", default="src/moex_carry")
    parser.add_argument("--forbidden-prefix", default="moex_carry.ui")
    parser.add_argument(
        "--allow",
        action="append",
        default=[
            "src/moex_carry/cli.py",
            "src/moex_carry/server/__init__.py",
            "src/moex_carry/server/app.py",
        ],
        help="Path allowed to import UI modules (repeatable).",
    )
    args = parser.parse_args()

    src_root = Path(args.src_root)
    allowed_paths = {Path(path) for path in args.allow}
    return run(
        src_root=src_root,
        forbidden_prefix=str(args.forbidden_prefix),
        allowed_paths=allowed_paths,
    )


if __name__ == "__main__":
    raise SystemExit(main())
