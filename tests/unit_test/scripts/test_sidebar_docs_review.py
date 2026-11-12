"""Regression tests for sidebar navigation and growth budgets."""

import tempfile
import unittest
from pathlib import Path

from scripts.review_sidebar_docs import review, sidebar_snapshot


def write_document(repository_root: Path, relative_path: str, content: str) -> None:
    document_path = repository_root / "docs" / relative_path
    document_path.parent.mkdir(parents=True, exist_ok=True)
    document_path.write_text(content, encoding="utf-8")


def seed_repository(repository_root: Path) -> None:
    write_document(repository_root, "index.rst", ".. toctree::\n   :hidden:\n\n   company\n")
    write_document(repository_root, "company.md", "# Company\n\n```{toctree}\n---\nmaxdepth: 1\n---\n\nmodel\n```\n")
    write_document(repository_root, "model.md", "# Model\n\nGetting started.\n")


class SidebarReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base_root = Path(self.directory.name) / "base"
        self.head_root = Path(self.directory.name) / "head"
        seed_repository(self.base_root)
        seed_repository(self.head_root)

    def test_nested_myst_page_growth_is_reported(self) -> None:
        write_document(self.head_root, "model.md", "# Model\n" + "extra\n" * 500)
        report, failed = review(self.base_root, self.head_root)
        self.assertTrue(failed)
        self.assertIn("docs/model.md", report)
        self.assertIn("exceeds limit 500", report)

    def test_existing_oversized_page_cannot_grow_but_can_shrink(self) -> None:
        write_document(self.base_root, "model.md", "line\n" * 510)
        write_document(self.head_root, "model.md", "line\n" * 511)
        self.assertTrue(review(self.base_root, self.head_root)[1])
        write_document(self.head_root, "model.md", "line\n" * 509)
        self.assertFalse(review(self.base_root, self.head_root)[1])

    def test_same_size_content_changes_are_reported(self) -> None:
        write_document(self.head_root, "model.md", "# Model\n\nChanged guidance.\n")
        report, failed = review(self.base_root, self.head_root)
        self.assertFalse(failed)
        self.assertIn("`docs/model.md`: 2 → 2 nonblank lines (+0); content changed", report)

    def test_total_budget_applies_even_when_each_page_is_small(self) -> None:
        navigation = ".. toctree::\n\n" + "".join(f"   page_{index}\n" for index in range(40))
        for root in (self.base_root, self.head_root):
            write_document(root, "index.rst", navigation)
            for index in range(40):
                write_document(root, f"page_{index}.md", "line\n" * 450)
        write_document(self.head_root, "page_0.md", "line\n" * 451)
        report, failed = review(self.base_root, self.head_root)
        self.assertTrue(failed)
        self.assertIn("Sidebar content:", report)

    def test_glob_discovers_new_page_without_changed_navigation(self) -> None:
        for root in (self.base_root, self.head_root):
            write_document(root, "index.rst", ".. toctree::\n   :glob:\n\n   guides/*\n")
            write_document(root, "guides/old.md", "# Old\n")
        write_document(self.head_root, "guides/new.md", "# New\n")
        report, failed = review(self.base_root, self.head_root)
        self.assertFalse(failed)
        self.assertIn("`docs/guides/new.md`", report)

    def test_six_new_nested_pages_exceed_per_pr_budget(self) -> None:
        content = "# Company\n\n```{toctree}\n:hidden:\n\nmodel\n"
        for index in range(6):
            content += f"new_{index}\n"
            write_document(self.head_root, f"new_{index}.md", "# New\n")
        write_document(self.head_root, "company.md", content + "```\n")
        report, failed = review(self.base_root, self.head_root)
        self.assertTrue(failed)
        self.assertIn("Newly reachable pages: 6 exceeds 5", report)

    def test_broken_target_and_unclosed_toctree_are_incomplete(self) -> None:
        write_document(self.head_root, "company.md", "```{toctree}\n\nmissing\n```\n")
        with self.assertRaisesRegex(ValueError, "unresolved"):
            sidebar_snapshot(self.head_root)
        write_document(self.head_root, "company.md", "```{toctree}\n\nmodel\n")
        with self.assertRaisesRegex(ValueError, "unclosed"):
            sidebar_snapshot(self.head_root)

    def test_fenced_examples_are_not_navigation(self) -> None:
        write_document(self.head_root, "model.md", "# Model\n\n~~~rst\n.. toctree::\n\n   missing\n~~~\n")
        self.assertEqual(len(sidebar_snapshot(self.head_root)[0]), 3)

    def test_duplicate_entries_count_toward_sidebar_budget(self) -> None:
        write_document(self.head_root, "index.rst", ".. toctree::\n\n" + "   company\n" * 7)
        report, failed = review(self.base_root, self.head_root)
        self.assertTrue(failed)
        self.assertIn("Net new toctree entries: 6 exceeds 5", report)

    def test_include_is_incomplete_instead_of_silently_ignored(self) -> None:
        write_document(self.head_root, "model.md", "# Model\n\n```{include} ../outside.md\n```\n")
        with self.assertRaisesRegex(ValueError, "include directives"):
            sidebar_snapshot(self.head_root)


if __name__ == "__main__":
    unittest.main()
