#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reject mid-sentence line breaks in Markdown documentation.

Every Markdown file under docs/ is in scope, including files added later.
Checking does not rewrite files.

Rule: a hard line break may only appear after a sentence-ending punctuation
mark (。！？. ! ? …). A break in the middle of a sentence -- the previous line
does not end with one of those marks -- is a violation. Consecutive text
lines form one paragraph. Blank lines, ATX headings, setext underlines,
thematic breaks, table rows, list item starts, indented code blocks, HTML
blocks, and code fences end the current paragraph. Trailing Markdown
formatting (emphasis, strikethrough, inline code, closing quotes and
brackets) is ignored when deciding what a line ends with. Line breaks inside
fenced code blocks are ignored.

There is no noqa exemption. Run without arguments to check every doc file,
or pass explicit paths to check a subset.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parents[1] / "docs"

_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HEADING_RE = re.compile(r"^ {0,3}#{1,6}[ \t]+")
_SETEXT_RE = re.compile(r"^ {0,3}(?:=+|-{3,})[ \t]*$")
_TABLE_RE = re.compile(r"^ {0,3}\|[^\n]*\|[ \t]*$")
_LIST_RE = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]+|$)")
_INDENTED_CODE_RE = re.compile(r"^ {4,}\S")
_HTML_RE = re.compile(r"^ {0,3}<[A-Za-z!/?]")

# A line is allowed to break after one of these marks.
_SENTENCE_ENDERS = frozenset("。！？!?.…")

# Characters that may follow the final punctuation on a line: Markdown
# emphasis/strikethrough, inline code, and closing quotes and brackets.
_TRAILING_CHARS = frozenset(
    "*_~`\"'“”’『』「」）)】]》〉}>"
)


@dataclass(frozen=True, kw_only=True)
class Violation:
    path: Path
    line_number: int
    rule: str
    detail: str


def ends_with_sentence_ender(line: str) -> bool:
    """Whether a line ends with sentence-ending punctuation.

    Trailing Markdown formatting and closing quotes/brackets are stripped
    before the final character is inspected, so ``**Done.**`` and
    ``Done"`` both count as ending with a sentence end.
    """
    tail = line.rstrip()
    while tail and tail[-1] in _TRAILING_CHARS:
        tail = tail[:-1]
    if tail and tail[-1] in _SENTENCE_ENDERS:
        return True
    else:
        return False


def check_source(path: Path, source: str) -> list[Violation]:
    """Check line breaks in a single Markdown source without rewriting it."""
    violations: list[Violation] = []
    run: list[tuple[int, str]] = []

    def flush_run() -> None:
        for index in range(len(run) - 1):
            line_number, line = run[index]
            if ends_with_sentence_ender(line):
                pass
            else:
                violations.append(
                    Violation(
                        path=path,
                        line_number=line_number,
                        rule="mid-sentence-break",
                        detail=(
                            "line break in the middle of a sentence; every line "
                            "of a paragraph except the last must end with "
                            "sentence-ending punctuation (。！？. ! ? …)"
                        ),
                    )
                )
        run.clear()

    fence_marker = ""
    fence_start_line_number = 0
    for line_number, line in enumerate(source.splitlines(), start=1):
        fence = _FENCE_RE.match(line)
        if fence_marker:
            if (
                fence
                and fence.group(1)[0] == fence_marker[0]
                and len(fence.group(1)) >= len(fence_marker)
                and not fence.group(2).strip()
            ):
                fence_marker = ""
            else:
                pass
            continue
        if fence:
            flush_run()
            fence_marker = fence.group(1)
            fence_start_line_number = line_number
            continue
        if not line.strip():
            flush_run()
            continue
        if _HEADING_RE.match(line) or _SETEXT_RE.match(line) or _TABLE_RE.match(line):
            flush_run()
            continue
        if _HTML_RE.match(line):
            flush_run()
            continue
        if not run and _INDENTED_CODE_RE.match(line):
            flush_run()
            continue
        if _LIST_RE.match(line):
            # A list item is its own unit: the break before it belongs to a
            # list boundary, not to a sentence inside a paragraph.
            flush_run()
            run.append((line_number, line))
            continue
        run.append((line_number, line))
    flush_run()
    if fence_marker:
        violations.append(
            Violation(
                path=path,
                line_number=fence_start_line_number,
                rule="unclosed-fence",
                detail="unclosed code fence",
            )
        )
    else:
        pass
    return violations


def check_docs(docs_root: Path = DOCS_ROOT) -> list[Violation]:
    """Scan all Markdown documentation without rewriting files."""
    violations: list[Violation] = []
    for path in sorted(docs_root.rglob("*.md")):
        violations.extend(check_source(path, path.read_text(encoding="utf-8")))
    return violations


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    violations = check_docs()
    for violation in violations:
        print(
            f"{violation.path.relative_to(DOCS_ROOT.parent)}:"
            f"{violation.line_number}: {violation.rule}: {violation.detail}",
            file=sys.stderr,
        )
    return int(bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
else:
    pass
