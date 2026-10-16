#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Lint docs markdown heading hierarchy. Checking does not rewrite files.

Every markdown file under docs/ is in scope. Two rules are enforced:

1. Exactly one H1 (``#``) per page. It is the page title.
2. No heading deeper than H3 (``###``). H4 (``####``) or more is a
   violation — use **bold text** or a list item instead.

ATX headings inside fenced code blocks (```` ``` ```` or ````~~~````)
are ignored, because code comments start with ``#`` and would otherwise
be counted as headings.

The default run only reports violations. --fix converts H4+ headings to
**bold text**; it does not touch H1 counts. Pre-commit does not pass --fix.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(frozen=True)
class Violation:
    path: Path
    lineno: int
    message: str


def repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def is_in_scope(path: Path) -> bool:
    resolved = path.resolve()
    if not resolved.is_relative_to(DOCS_ROOT):
        return False
    return resolved.suffix == ".md"


def iter_default_files() -> list[Path]:
    return sorted(p for p in DOCS_ROOT.rglob("*.md") if is_in_scope(p))


def resolve_targets(raw_paths: list[str]) -> list[Path]:
    if not raw_paths:
        return iter_default_files()
    return [Path(p) for p in raw_paths if is_in_scope(Path(p))]


def check_file(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    h1_lines: list[int] = []
    in_fence = False

    with path.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            stripped = raw.strip()
            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence:
                continue

            m = _HEADING_RE.match(raw)
            if not m:
                continue

            level = len(m.group(1))
            text = m.group(2).strip()

            if level == 1:
                h1_lines.append(lineno)
            elif level >= 4:
                violations.append(
                    Violation(
                        path,
                        lineno,
                        f"H{level} heading not allowed (max depth H3). "
                        f"Replace '{'#' * level} {text}' with **{text}** "
                        f"or a list item.",
                    )
                )

    if len(h1_lines) == 0:
        violations.insert(
            0, Violation(path, 1, "missing H1 (exactly one '# ' heading required).")
        )
    elif len(h1_lines) > 1:
        lines_str = ", ".join(str(n) for n in h1_lines)
        violations.insert(
            0,
            Violation(
                path,
                h1_lines[0],
                f"found {len(h1_lines)} H1 headings on lines {lines_str} "
                f"(exactly one required).",
            ),
        )

    return violations


def fix_file(path: Path) -> tuple[int, list[Violation]]:
    """Convert H4+ headings to **bold** text. Returns (fixed_count, remaining)."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    in_fence = False
    fixed = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) >= 4:
            text = m.group(2).strip()
            newline = "\n" if line.endswith("\n") else ""
            lines[i] = f"**{text}**{newline}"
            fixed += 1

    if fixed:
        path.write_text("".join(lines), encoding="utf-8")

    return fixed, check_file(path)


def format_violation(v: Violation) -> str:
    return f"{repo_relative(v.path)}:{v.lineno}: {v.message}"


def report_violations(violations: list[Violation]) -> int:
    if not violations:
        return 0
    for v in violations:
        print(format_violation(v), file=sys.stderr)
    print(
        f"\n{len(violations)} docs heading violation(s). "
        f"Run `python scripts/check_docs_headings.py --fix` "
        f"to auto-convert H4+ headings to bold text.",
        file=sys.stderr,
    )
    return 1


def run_check(paths: list[Path]) -> int:
    violations: list[Violation] = []
    for p in paths:
        violations.extend(check_file(p))
    return report_violations(violations)


def run_fix(paths: list[Path]) -> int:
    remaining: list[Violation] = []
    fixed_total = 0
    files_touched = 0
    for p in paths:
        fixed, leftover = fix_file(p)
        if fixed:
            files_touched += 1
            fixed_total += fixed
        remaining.extend(leftover)
    if fixed_total:
        print(f"converted {fixed_total} H4+ headings in {files_touched} file(s)")
    return report_violations(remaining)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", help="Markdown files (defaults to docs/)"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Convert H4+ headings to **bold** text in place",
    )
    args = parser.parse_args(argv)
    targets = resolve_targets(args.paths)
    if args.fix:
        return run_fix(targets)
    return run_check(targets)


if __name__ == "__main__":
    raise SystemExit(main())
