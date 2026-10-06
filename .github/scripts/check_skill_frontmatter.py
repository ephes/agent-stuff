#!/usr/bin/env python3
"""Check that every skill's SKILL.md starts with usable frontmatter.

Each `<agent>/skills/<name>/SKILL.md` must open with a `---` block that parses
as a YAML mapping holding a string `name` equal to the directory name and a
non-empty string `description`. An agent loads skills by that frontmatter, so
a typo here silently drops or misnames a skill. Needs PyYAML; run from
anywhere.
"""
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]


def frontmatter(path):
    """Return (fields, error) for the leading `---` block of `path`."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return None, "no `---` frontmatter block at the top"
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return None, "frontmatter block is not closed with `---`"
    try:
        fields = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        return None, f"frontmatter is not valid YAML: {exc}"
    if not isinstance(fields, dict):
        return None, "frontmatter is not a YAML mapping"
    return fields, None


def main():
    problems = []
    skills = sorted(ROOT.glob("*/skills/*/SKILL.md"))
    for path in skills:
        rel = path.relative_to(ROOT)
        fields, error = frontmatter(path)
        if error:
            problems.append(f"{rel}: {error}")
            continue
        name = fields.get("name")
        if name != path.parent.name:
            problems.append(f"{rel}: name {name!r} does not match directory {path.parent.name!r}")
        description = fields.get("description")
        if not isinstance(description, str) or not description.strip():
            problems.append(f"{rel}: missing or empty description")
    if not skills:
        problems.append("no */skills/*/SKILL.md files found")
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"checked {len(skills)} skills, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
