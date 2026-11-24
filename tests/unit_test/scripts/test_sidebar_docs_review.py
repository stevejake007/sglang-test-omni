"""Regression tests for sidebar navigation and growth budgets."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.review_sidebar_docs import review, sidebar_snapshot

GENERAL_USAGE = ".. toctree::\n   :caption: General Usage\n"
DEVELOPER_REFERENCE = ".. toctree::\n   :caption: Developer Reference\n"


def root_navigation(
    general_usage: str = "\n   self\n", developer_reference: str = "\n   self\n"
) -> str:
    return (
        GENERAL_USAGE + general_usage + "\n" + DEVELOPER_REFERENCE + developer_reference
    )


def write_document(repository_root: Path, relative_path: str, content: str) -> None:
    document_path = repository_root / "docs" / relative_path
    document_path.parent.mkdir(parents=True, exist_ok=True)
    document_path.write_text(content, encoding="utf-8")


def seed_repository(repository_root: Path) -> None:
    write_document(
        repository_root,
        "index.rst",
        root_navigation(general_usage="   :hidden:\n\n   company\n"),
    )
    write_document(
        repository_root,
        "company.md",
        "# Company\n\n```{toctree}\n---\nmaxdepth: 1\n---\n\nmodel\n```\n",
    )
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
        self.assertIn(
            "`docs/model.md`: 2 → 2 nonblank lines (+0); content changed", report
        )

    def test_total_budget_applies_even_when_each_page_is_small(self) -> None:
        navigation = root_navigation(
            general_usage="\n" + "".join(f"   page_{index}\n" for index in range(40))
        )
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
            write_document(
                root,
                "index.rst",
                root_navigation(developer_reference="   :glob:\n\n   guides/*\n"),
            )
            write_document(root, "guides/old.md", "# Old\n")
        write_document(self.head_root, "guides/new.md", "# New\n")
        write_document(
            self.head_root, "guides/other/ignored.md", "outside the glob\n" * 700
        )
        report, failed = review(self.base_root, self.head_root)
        self.assertFalse(failed)
        self.assertIn("`docs/guides/new.md`", report)
        self.assertNotIn("ignored.md", report)

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
        write_document(
            self.head_root,
            "model.md",
            "# Model\n\n~~~rst\n.. toctree::\n\n   missing\n~~~\n",
        )
        self.assertEqual(
            set(sidebar_snapshot(self.head_root)[0]), {"company.md", "model.md"}
        )

    def test_duplicate_entries_count_toward_sidebar_budget(self) -> None:
        write_document(
            self.head_root,
            "index.rst",
            root_navigation(general_usage="\n" + "   company\n" * 7),
        )
        report, failed = review(self.base_root, self.head_root)
        self.assertTrue(failed)
        self.assertIn("Net new toctree entries: 6 exceeds 5", report)

    def test_include_is_incomplete_instead_of_silently_ignored(self) -> None:
        write_document(
            self.head_root, "model.md", "# Model\n\n```{include} ../outside.md\n```\n"
        )
        with self.assertRaisesRegex(ValueError, "include directives"):
            sidebar_snapshot(self.head_root)

    def test_unrelated_section_additions_and_removals_leave_report_unchanged(
        self,
    ) -> None:
        clean_report = review(self.base_root, self.base_root)
        for root, caption in (
            (self.base_root, "Get Started"),
            (self.head_root, "Cookbook"),
        ):
            write_document(
                root,
                "index.rst",
                root_navigation(general_usage="\n   company\n")
                + f"\n.. toctree::\n   :caption: {caption}\n\n   outside\n   missing\n",
            )
        write_document(self.base_root, "outside.md", "# Removed page\n")
        write_document(self.head_root, "outside.rst", "out of scope\n" * 700)
        write_document(self.head_root, "outside.md", "```{toctree}\n")
        self.assertEqual(review(self.base_root, self.head_root), clean_report)
        self.assertFalse(clean_report[1])

    def test_mixed_pr_reviews_nested_pages_reachable_from_either_section(self) -> None:
        navigation = (
            GENERAL_USAGE
            + "\n   company\n\n"
            + DEVELOPER_REFERENCE
            + "\n   developer_reference/index\n\n.. toctree::\n   :caption: Cookbook\n\n   cookbook/only\n   cookbook/shared\n"
        )
        for root in (self.base_root, self.head_root):
            write_document(root, "index.rst", navigation)
            write_document(
                root,
                "developer_reference/index.rst",
                ".. toctree::\n   :caption: Examples\n\n   /cookbook/shared\n   /model\n",
            )
            write_document(root, "cookbook/shared.md", "# Shared page\n")
            write_document(root, "cookbook/only.md", "# Cookbook only\n")
        write_document(self.head_root, "cookbook/only.md", "ignored\n" * 700)
        write_document(self.head_root, "cookbook/shared.md", "shared\n" * 501)
        report, failed = review(self.base_root, self.head_root)
        self.assertTrue(failed)
        self.assertIn("docs/cookbook/shared.md", report)
        self.assertNotIn("cookbook/only", report)
        pages, entries = sidebar_snapshot(self.head_root)
        self.assertEqual(len(pages), 4)
        self.assertEqual(len(entries), 5)

    def test_page_moves_into_and_out_of_scope_without_file_edits(self) -> None:
        write_document(
            self.base_root,
            "index.rst",
            root_navigation() + "\n.. toctree::\n   :caption: Cookbook\n\n   company\n",
        )
        report, failed = review(self.base_root, self.head_root)
        self.assertFalse(failed)
        self.assertIn("Added pages: `docs/company.md`, `docs/model.md`", report)
        report, failed = review(self.head_root, self.base_root)
        self.assertFalse(failed)
        self.assertIn("Removed pages: `docs/company.md`, `docs/model.md`", report)

    def test_ambiguous_in_scope_target_is_incomplete(self) -> None:
        write_document(self.head_root, "model.rst", "Ambiguous model\n")
        with self.assertRaisesRegex(ValueError, "same Sphinx document name: model"):
            sidebar_snapshot(self.head_root)

    def test_root_scope_changes_exit_incomplete(self) -> None:
        """A lost or unclassified section used to bypass the growth check."""
        index_path = self.head_root / "docs/index.rst"
        original = index_path.read_text(encoding="utf-8")
        write_document(self.head_root, "advanced.md", "line\n" * 2000)
        for navigation, diagnostic in (
            (
                original.replace("General Usage", "Basic Usage"),
                "missing reviewed section(s): General Usage",
            ),
            (
                original.partition(DEVELOPER_REFERENCE)[0],
                "missing reviewed section(s): Developer Reference",
            ),
            (
                original + "\n.. toctree::\n   :caption: Advanced\n\n   advanced\n",
                "unclassified root toctree(s): Advanced",
            ),
            (
                original + "\n.. toctree::\n\n   advanced\n",
                "unclassified root toctree(s): (uncaptioned)",
            ),
        ):
            with self.subTest(diagnostic=diagnostic):
                index_path.write_text(navigation, encoding="utf-8")
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "scripts.review_sidebar_docs",
                        "--base",
                        str(self.base_root),
                        "--head",
                        str(self.head_root),
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(diagnostic, result.stderr)


if __name__ == "__main__":
    unittest.main()
