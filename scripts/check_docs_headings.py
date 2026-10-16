#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Lint docs markdown heading hierarchy.

Rules enforced on every ``.md`` file under ``docs/``:

1. Exactly one H1 (``#``) per file — it summarizes the page topic.
2. No heading deeper than H3 (``###``). ``####`` or more is an error;
   use **bold text** or a list item instead.

Headings inside fenced code blocks (```` ``` ````) are ignored.

Exit status is non-zero when any violation is found. The script does not
rewrite files.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"

# ATX heading: one to six '#' followed by whitespace and text.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def check_file(path: Path) -> list[str]:
    """Return a list of violation messages for *path*."""
    violations: list[str] = []
    try:
        rel = path.relative_to(REPO_ROOT)
    except ValueError:
        rel = path

    h1_lines: list[int] = []
    in_fence = False

    with path.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            stripped = raw.strip()
            # Toggle fenced code block on lines that open/close a fence.
            if stripped.startswith("```") or stripped.startswith("~~~"):
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
                    f"{rel}:{lineno}: H{level} heading is not allowed "
                    f"(max depth H3). Replace '{'#' * level} {text}' with "
                    f"**{text}** or a list item."
                )

    if len(h1_lines) == 0:
        violations.insert(0, f"{rel}: missing H1 (exactly one '# ' heading required).")
    elif len(h1_lines) > 1:
        lines_str = ", ".join(str(n) for n in h1_lines)
        violations.insert(
            0,
            f"{rel}: found {len(h1_lines)} H1 headings on lines {lines_str} "
            f"(exactly one required).",
        )

    return violations


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        targets = [Path(a) for a in argv[1:]]
    else:
        targets = sorted(DOCS_ROOT.rglob("*.md"))

    all_violations: list[str] = []
    for path in targets:
        if not path.exists():
            continue
        all_violations.extend(check_file(path))

    if all_violations:
        for v in all_violations:
            print(v, file=sys.stderr)
        print(f"\n{len(all_violations)} docs heading violation(s).", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
