# SPDX-License-Identifier: Apache-2.0
"""Exercise the documentation line-break checker with synthetic Markdown."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_doc_linebreak import check_docs, check_source

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/check_doc_linebreak.py"


@pytest.mark.parametrize(
    "source",
    [
        "Sentence one.\nSentence two.\n\nNext paragraph.\n",
        "第一句。\n第二句！\n\n第三段？\n",
        "One sentence with a period. Next with a question mark? Yes!\n",
        "A paragraph ending with an ellipsis…\nThen another line.\n",
    ],
)
def test_check_source_allows_breaks_after_sentence_enders(source: str) -> None:
    assert check_source(Path("guide.md"), source) == []


@pytest.mark.parametrize(
    "source, expected_lines",
    [
        ("Sentence one\ncontinues without punctuation.\n", [1]),
        ("Sentence one. Second sentence\nspans two lines and ends here.\n", [1]),
        ("Use **bold text**\nthat continues on the next line.\n", [1]),
        ("Use `inline code`\nand more text afterwards.\n", [1]),
        ("第一句没有标点\n第二句。\n", [1]),
    ],
)
def test_check_source_reports_mid_sentence_breaks(
    source: str, expected_lines: list[int]
) -> None:
    violations = check_source(Path("guide.md"), source)

    assert [violation.line_number for violation in violations] == expected_lines
    assert all(violation.rule == "mid-sentence-break" for violation in violations)


def test_check_source_ignores_trailing_markdown_formatting() -> None:
    source = (
        "This is **bold with a period.**\n"
        "Then `code with a period.`\n"
        "And *emphasis!*\n"
        "Followed by ~~strikethrough?~~\n"
    )

    violations = check_source(Path("guide.md"), source)

    assert violations == []


def test_check_source_ignores_fenced_code() -> None:
    source = (
        "# Guide\n\n"
        "```python\n"
        "def f():\n"
        "    return 1  # no punctuation anywhere\n"
        "```\n"
        "~~~text\n"
        "arbitrary\n"
        "breaks\n"
        "~~~\n"
        "Outside the fence. Sentence one\n"
        "continues after the fence.\n"
    )

    violations = check_source(Path("guide.md"), source)

    assert [violation.line_number for violation in violations] == [11]


def test_check_source_reports_unclosed_fence_at_opening_line() -> None:
    source = "# Guide\n\n```python\nno closing fence\n"

    violations = check_source(Path("guide.md"), source)

    assert len(violations) == 1
    assert (violations[0].line_number, violations[0].rule) == (3, "unclosed-fence")


@pytest.mark.parametrize(
    "source",
    [
        "# Heading\nBody sentence.\n",
        "# Heading\n\nBody sentence.\n",
        "| Column | Value |\n| --- | --- |\n| One | Two |\n",
        "---\nBody sentence.\n",
        "- Item one.\n- Item two.\n",
        "1. Item one.\n2. Item two.\n",
        "    indented code\n    with no punctuation\n",
        "<!-- html comment\nwithout punctuation -->\n",
    ],
)
def test_check_source_ignores_structural_lines(source: str) -> None:
    assert check_source(Path("guide.md"), source) == []


def test_check_source_flags_breaks_inside_list_item_continuation() -> None:
    source = "- Item one continues\n  onto a wrapped line.\n- Item two.\n"

    violations = check_source(Path("guide.md"), source)

    assert len(violations) == 1
    assert violations[0].line_number == 1


def test_check_docs_scans_all_markdown_files_recursively(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    nested_root = docs_root / "nested" / "deeper"
    nested_root.mkdir(parents=True)
    (docs_root / "clean.md").write_text("# Clean\n", encoding="utf-8")
    nested_path = nested_root / "guide.md"
    nested_path.write_text("# Guide\n\nBroken sentence\ncontinues.\n", encoding="utf-8")
    (docs_root / "ignored.txt").write_text("Broken\n", encoding="utf-8")

    violations = check_docs(docs_root)

    assert len(violations) == 1
    assert violations[0].path == nested_path
    assert violations[0].line_number == 3
    assert violations[0].rule == "mid-sentence-break"


def copy_script_fixture(tmp_path: Path, document_text: str) -> tuple[Path, Path]:
    """Create an isolated scripts/docs tree for CLI checks."""
    repository_root = tmp_path / "fixture"
    script_path = repository_root / "scripts" / "check_doc_linebreak.py"
    document_path = repository_root / "docs" / "guide.md"
    script_path.parent.mkdir(parents=True)
    document_path.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, script_path)
    document_path.write_text(document_text, encoding="utf-8")
    return repository_root, document_path


@pytest.mark.parametrize(
    "document_text, expected_exit_code",
    [("# Clean\n", 0), ("# Bad\n\nBroken sentence\ncontinues.\n", 1)],
)
def test_cli_scans_the_copied_script_fixture(
    tmp_path: Path, document_text: str, expected_exit_code: int
) -> None:
    repository_root, document_path = copy_script_fixture(tmp_path, document_text)
    script_path = repository_root / "scripts" / "check_doc_linebreak.py"

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=repository_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == expected_exit_code
    if expected_exit_code == 0:
        assert result.stderr == ""
    else:
        assert result.stderr.startswith(
            f"docs/{document_path.name}:3: mid-sentence-break: "
        )
        assert "。！？. ! ? …" in result.stderr


def test_cli_rejects_arguments_with_exit_status_two(tmp_path: Path) -> None:
    repository_root, _ = copy_script_fixture(tmp_path, "# Clean\n")
    script_path = repository_root / "scripts" / "check_doc_linebreak.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--unexpected"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert "unrecognized arguments" in result.stderr
