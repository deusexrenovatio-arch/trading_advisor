from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

SKILLS_ROOT = Path(".cursor/skills")
AGENTS_FILE = Path("AGENTS.md")

AGENTS_SKILL_PATTERN = re.compile(
    r"^- (?P<name>[a-z0-9-]+): .*?\(file:\s*(?P<path>[^)]+)\)\s*$"
)


def _resolve_skill_path(path_text: str, repo_root: Path) -> Path:
    raw = path_text.strip()
    direct = Path(raw)
    if direct.exists():
        return direct

    normalized = raw.replace("\\", "/")
    marker = ".cursor/skills/"
    idx = normalized.find(marker)
    if idx >= 0:
        rel = normalized[idx:]
        candidate = repo_root / rel
        if candidate.exists():
            return candidate

    return direct


def _load_yaml_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    try:
        _, body = text.split("---\n", 1)
        fm_raw, _ = body.split("\n---", 1)
    except ValueError:
        return {}
    data = yaml.safe_load(fm_raw) or {}
    return data if isinstance(data, dict) else {}


def _load_agents_skill_refs(path: Path, repo_root: Path) -> dict[str, Path]:
    refs: dict[str, Path] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = AGENTS_SKILL_PATTERN.match(line.strip())
        if not match:
            continue
        name = match.group("name").strip()
        skill_path = _resolve_skill_path(match.group("path"), repo_root)
        refs[name] = skill_path
    return refs


def _validate_skill_file(skill_dir: Path, errors: list[str]) -> None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        errors.append(f"missing SKILL.md: {skill_dir.as_posix()}")
        return

    frontmatter = _load_yaml_frontmatter(skill_md)
    name = str(frontmatter.get("name", "")).strip()
    description = str(frontmatter.get("description", "")).strip()

    if not name:
        errors.append(f"missing frontmatter name: {skill_md.as_posix()}")
    if not description:
        errors.append(f"missing frontmatter description: {skill_md.as_posix()}")

    if name and name != skill_dir.name:
        errors.append(
            f"frontmatter name mismatch: {skill_md.as_posix()} "
            f"(name={name}, dir={skill_dir.name})"
        )

    text = skill_md.read_text(encoding="utf-8")
    if "## Skill dependencies and lifecycle gates" not in text and skill_dir.name != "intraday-futures-trading-advisor":
        errors.append(f"missing lifecycle section: {skill_md.as_posix()}")

    if skill_dir.name == "intraday-futures-trading-advisor":
        # keep backward compatibility if section title is slightly different
        if "lifecycle gates" not in text.lower():
            errors.append(f"missing lifecycle gates guidance: {skill_md.as_posix()}")

    if "pre-push" not in text.lower():
        errors.append(f"missing pre-push guidance: {skill_md.as_posix()}")


def run(skills_root: Path, agents_file: Path) -> int:
    errors: list[str] = []

    if not skills_root.exists():
        print(f"skills root not found: {skills_root.as_posix()}")
        return 1
    if not agents_file.exists():
        print(f"agents file not found: {agents_file.as_posix()}")
        return 1

    skill_dirs = sorted([p for p in skills_root.iterdir() if p.is_dir()])
    skill_names = {p.name for p in skill_dirs}

    for skill_dir in skill_dirs:
        _validate_skill_file(skill_dir, errors)

    repo_root = agents_file.resolve().parent
    agents_refs = _load_agents_skill_refs(agents_file, repo_root)
    if not agents_refs:
        errors.append(f"no skills parsed from {agents_file.as_posix()}")
    else:
        for name, path in sorted(agents_refs.items()):
            if name not in skill_names:
                errors.append(f"AGENTS skill not found in .cursor/skills: {name}")
            if not path.exists():
                errors.append(f"AGENTS path does not exist: {path.as_posix()}")

        extra_skills = sorted(skill_names.difference(set(agents_refs.keys())))
        if extra_skills:
            errors.append(
                "skills present in .cursor/skills but missing in AGENTS.md: "
                + ", ".join(extra_skills)
            )

    if errors:
        print("skill validation failed:")
        for item in errors:
            print(f"- {item}")
        return 1

    print(f"skill validation: OK ({len(skill_dirs)} skills)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate local skill files and AGENTS mapping")
    parser.add_argument("--skills-root", default=str(SKILLS_ROOT))
    parser.add_argument("--agents-file", default=str(AGENTS_FILE))
    args = parser.parse_args()

    sys.exit(run(Path(args.skills_root), Path(args.agents_file)))


if __name__ == "__main__":
    main()
