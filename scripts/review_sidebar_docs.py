"""Compare the Sphinx sidebar documentation in two repository snapshots."""

import argparse
import fnmatch
import re
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

PAGE_LINE_LIMIT = 500
SIDEBAR_PAGE_LIMIT = 100
SIDEBAR_ENTRY_LIMIT = 105
SIDEBAR_LINE_LIMIT = 18000
MAX_NEW_PAGES_PER_PR = 5
MAX_NEW_ENTRIES_PER_PR = 5
MAX_NEW_LINES_PER_PR = 600
DOCUMENT_SUFFIXES = (".md", ".rst")


@dataclass(frozen=True)
class NavigationEntry:
    source: Path
    line_number: int
    target: str
    is_glob: bool


def navigation_entries(source_path: Path, source: str) -> list[NavigationEntry]:
    """Read RST and MyST toctree entries without executing document code."""
    lines = source.splitlines()
    entries: list[NavigationEntry] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        rst = re.match(r"^(\s*)\.\. toctree::\s*$", line)
        myst = re.match(r"^\s*(`{3,}|:{3,})\{toctree\}\s*$", line)
        if re.match(r"^\s*(?:\.\. include::|(?:`{3,}|:{3,})\{include\})", line):
            raise ValueError(
                f"{source_path}:{index + 1}: include directives require manual review"
            )
        fence = (
            re.match(r"^\s*(`{3,}|~{3,})", line)
            if source_path.suffix == ".md"
            else None
        )
        if fence and not myst:
            index += 1
            while index < len(lines) and not re.fullmatch(
                r"\s*"
                + re.escape(fence.group(1)[0])
                + r"{"
                + str(len(fence.group(1)))
                + r",}\s*",
                lines[index],
            ):
                index += 1
            index += 1
            continue
        if not rst and not myst:
            index += 1
            continue
        is_glob = False
        options_block = False
        closed = bool(rst)
        index += 1
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if rst:
                if stripped and len(line) - len(line.lstrip()) <= len(rst.group(1)):
                    break
            elif myst and re.fullmatch(
                re.escape(myst.group(1)[0]) + r"{" + str(len(myst.group(1))) + r",}\s*",
                stripped,
            ):
                closed = True
                index += 1
                break
            if not stripped:
                index += 1
                continue
            if myst and stripped == "---":
                options_block = not options_block
            elif options_block:
                if re.fullmatch(r"glob:\s*(?:true|yes|on)?", stripped, re.IGNORECASE):
                    is_glob = True
            elif stripped.startswith(":"):
                if re.fullmatch(r":glob:\s*", stripped):
                    is_glob = True
            elif stripped.startswith("#"):
                pass
            else:
                entries.append(
                    NavigationEntry(source_path, index + 1, stripped, is_glob)
                )
            index += 1
        if options_block:
            raise ValueError(f"{source_path}: unclosed toctree options")
        if not closed:
            raise ValueError(f"{source_path}: unclosed toctree fence")
    return entries


def sidebar_snapshot(repository_root: Path) -> tuple[dict[str, int], list[str]]:
    """Resolve the navigation graph and count nonblank lines of each page."""
    docs_root = (repository_root / "docs").resolve()
    if (repository_root / "docs").is_symlink() or not docs_root.is_relative_to(
        repository_root.resolve()
    ):
        raise ValueError("docs root must be a directory inside the repository")
    index_path = docs_root / "index.rst"
    if not index_path.is_file():
        raise ValueError(f"missing sidebar root: {index_path}")
    document_paths = sorted(
        path
        for path in docs_root.rglob("*")
        if path.suffix in DOCUMENT_SUFFIXES and path.is_file() and not path.is_symlink()
    )
    documents = {
        path.relative_to(docs_root).with_suffix("").as_posix(): path
        for path in document_paths
    }
    if len(documents) != len(document_paths):
        raise ValueError("multiple source files have the same Sphinx document name")
    queue = deque([index_path])
    visited: dict[str, int] = {}
    edges: list[str] = []
    while queue:
        source_path = queue.popleft()
        if source_path.is_symlink() or not source_path.resolve().is_relative_to(
            docs_root
        ):
            raise ValueError(f"document outside docs root: {source_path}")
        relative_path = source_path.relative_to(docs_root).as_posix()
        if relative_path in visited:
            continue
        source = source_path.read_text(encoding="utf-8")
        visited[relative_path] = sum(bool(line.strip()) for line in source.splitlines())
        for entry in navigation_entries(source_path, source):
            target = entry.target
            titled = re.fullmatch(r".+?\s*<([^<>]+)>\s*", target)
            if titled:
                target = titled.group(1).strip()
            if target == "self" or urlsplit(target).scheme or target.startswith("//"):
                continue
            target = target.split("#", 1)[0]
            if not target:
                raise ValueError(
                    f"{relative_path}:{entry.line_number}: empty toctree target"
                )
            target_path = Path(target)
            if target_path.suffix in DOCUMENT_SUFFIXES:
                target_path = target_path.with_suffix("")
            if target.startswith("/"):
                candidate = docs_root / str(target_path).lstrip("/")
            else:
                candidate = source_path.parent / target_path
            candidate = candidate.resolve()
            if not candidate.is_relative_to(docs_root):
                raise ValueError(
                    f"{relative_path}:{entry.line_number}: target escapes docs root"
                )
            document_name = candidate.relative_to(docs_root).as_posix()
            if entry.is_glob and any(char in document_name for char in "*?["):
                matches = [
                    path
                    for name, path in documents.items()
                    if fnmatch.fnmatchcase(name, document_name) and path != source_path
                ]
            else:
                matches = (
                    [documents[document_name]] if document_name in documents else []
                )
            if not matches:
                raise ValueError(
                    f"{relative_path}:{entry.line_number}: unresolved toctree target {entry.target}"
                )
            for matched_path in matches:
                edges.append(
                    f"{relative_path}:{entry.line_number} -> {matched_path.relative_to(docs_root).as_posix()}"
                )
                queue.append(matched_path)
    return visited, edges


def review(base_root: Path, head_root: Path) -> tuple[str, bool]:
    """Report navigation growth and enforce the documented size budgets."""
    base_pages, base_edges = sidebar_snapshot(base_root)
    head_pages, head_edges = sidebar_snapshot(head_root)
    added_pages = sorted(head_pages.keys() - base_pages.keys())
    removed_pages = sorted(base_pages.keys() - head_pages.keys())
    base_total = sum(base_pages.values())
    head_total = sum(head_pages.values())
    violations: list[str] = []
    page_changes = []
    for path in sorted(head_pages):
        previous_lines = base_pages.get(path, 0)
        current_lines = head_pages[path]
        content_changed = (
            path not in base_pages
            or (base_root / "docs" / path).read_bytes()
            != (head_root / "docs" / path).read_bytes()
        )
        if current_lines != previous_lines or content_changed:
            page_changes.append(
                f"- `docs/{path}`: {previous_lines} → {current_lines} nonblank lines ({current_lines - previous_lines:+}); content changed"
            )
        if current_lines > max(PAGE_LINE_LIMIT, previous_lines):
            violations.append(
                f"`docs/{path}`: {current_lines} lines exceeds limit {max(PAGE_LINE_LIMIT, previous_lines)} (base {previous_lines})"
            )
    if len(head_pages) > max(SIDEBAR_PAGE_LIMIT, len(base_pages)):
        violations.append(
            f"Sidebar pages: {len(head_pages)} exceeds {max(SIDEBAR_PAGE_LIMIT, len(base_pages))}"
        )
    if len(head_edges) > max(SIDEBAR_ENTRY_LIMIT, len(base_edges)):
        violations.append(
            f"Toctree entries: {len(head_edges)} exceeds {max(SIDEBAR_ENTRY_LIMIT, len(base_edges))}"
        )
    if head_total > max(SIDEBAR_LINE_LIMIT, base_total):
        violations.append(
            f"Sidebar content: {head_total} lines exceeds {max(SIDEBAR_LINE_LIMIT, base_total)}"
        )
    if len(added_pages) > MAX_NEW_PAGES_PER_PR:
        violations.append(
            f"Newly reachable pages: {len(added_pages)} exceeds {MAX_NEW_PAGES_PER_PR} per PR"
        )
    if len(head_edges) - len(base_edges) > MAX_NEW_ENTRIES_PER_PR:
        violations.append(
            f"Net new toctree entries: {len(head_edges) - len(base_edges)} exceeds {MAX_NEW_ENTRIES_PER_PR} per PR"
        )
    if head_total - base_total > MAX_NEW_LINES_PER_PR:
        violations.append(
            f"Net sidebar content growth: {head_total - base_total} lines exceeds {MAX_NEW_LINES_PER_PR} per PR"
        )
    report = [
        "# Sidebar documentation review",
        "",
        f"- Reachable pages: {len(base_pages)} → {len(head_pages)} ({len(head_pages) - len(base_pages):+})",
        f"- Toctree entries: {len(base_edges)} → {len(head_edges)} ({len(head_edges) - len(base_edges):+})",
        f"- Nonblank source lines: {base_total} → {head_total} ({head_total - base_total:+})",
        f"- Added pages: {', '.join(f'`docs/{path}`' for path in added_pages) or 'none'}",
        f"- Removed pages: {', '.join(f'`docs/{path}`' for path in removed_pages) or 'none'}",
        "",
        "## Budget findings",
        "",
    ]
    (
        report.extend(f"- {violation}" for violation in violations)
        if violations
        else report.append("No budget violations.")
    )
    report.extend(["", "## Changed reachable pages", ""])
    report.extend(page_changes or ["No size changes."])
    report.extend(
        [
            "",
            "Counts use nonblank source lines, including code and markup, not rendered text. Review whether added material belongs in an existing page and whether removals retain useful content. This check does not assess semantic duplication or accuracy.",
        ]
    )
    return "\n".join(report) + "\n", bool(violations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base", required=True, type=Path, help="trusted base repository snapshot"
    )
    parser.add_argument(
        "--head", required=True, type=Path, help="pull request repository snapshot"
    )
    parser.add_argument("--report", type=Path, help="write a Markdown report")
    arguments = parser.parse_args()
    try:
        report, has_violations = review(arguments.base, arguments.head)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"Sidebar review incomplete: {error}", file=sys.stderr)
        return 2
    print(report)
    if arguments.report:
        arguments.report.write_text(report, encoding="utf-8")
    return 1 if has_violations else 0


if __name__ == "__main__":
    sys.exit(main())
