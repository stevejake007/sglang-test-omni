"""Stdlib unittest suite for the review-pr agent. No network, no third-party deps."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import classify_file, input_hash, RULES_VERSION  # noqa: E402
from review import deterministic_findings  # noqa: E402
from validate_report import validate  # noqa: E402


def make_bundle(directory, body="", files=None, ci=None):
    """Write a bundle.json and optional files into directory."""
    files = files or []
    ci = ci or []
    bundle = {
        "repo": "stevejake007/sglang-test-omni",
        "pr": 1,
        "title": "test PR",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "body": body,
        "files": files,
        "reviews": [],
        "comments": [],
        "issue_comments": [],
        "ci": ci,
        "rules_version": RULES_VERSION,
        "input_hash": "unset",
    }
    bundle["input_hash"] = input_hash(
        {
            "repo": bundle["repo"],
            "body": body,
            "files": [{"filename": f["filename"], "patch": f.get("patch", "")} for f in files],
            "ci": ci,
            "rules_version": RULES_VERSION,
        }
    )
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    files_dir = directory / "files"
    for item in files:
        path = files_dir / item["filename"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.get("patch", ""), encoding="utf-8")
    return bundle


class HashTest(unittest.TestCase):
    def test_stable_and_sensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = make_bundle(tmp, body="same body")
            second = make_bundle(tmp, body="same body")
            self.assertEqual(first["input_hash"], second["input_hash"])
            changed = make_bundle(tmp, body="different body")
            self.assertNotEqual(first["input_hash"], changed["input_hash"])


class ClassifyTest(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(classify_file("sglang_omni/models/ming3_tts/model.py"), "model")
        self.assertEqual(classify_file("tests/unit_test/test_tts.py"), "test")
        self.assertEqual(classify_file("docs/cookbook/tts.md"), "docs")
        self.assertEqual(classify_file("benchmarks/bench_tts.py"), "benchmark")
        self.assertEqual(classify_file(".github/workflows/pr-test.yml"), "ci")


class RuleTest(unittest.TestCase):
    def test_missing_tests_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(
                tmp,
                files=[
                    {"filename": "sglang_omni/models/ming3_tts/model.py", "patch": "def forward(): pass"},
                ],
            )
            findings = deterministic_findings(bundle)
            self.assertTrue(any(f["rule"] == "RC-1" for f in findings))

    def test_no_missing_tests_rule_when_tests_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(
                tmp,
                files=[
                    {"filename": "sglang_omni/models/ming3_tts/model.py", "patch": "def forward(): pass"},
                    {"filename": "tests/unit_test/test_tts.py", "patch": "def test_tts(): pass"},
                ],
            )
            findings = deterministic_findings(bundle)
            self.assertFalse(any(f["rule"] == "RC-1" for f in findings))

    def test_perf_claim_without_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp, body="This makes decode 3x faster than before.")
            findings = deterministic_findings(bundle)
            self.assertTrue(any(f["rule"] == "RC-2" for f in findings))

    def test_perf_claim_with_numbers_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp, body="Latency drops from 12 ms to 6 ms, throughput 100 to 200 rps.")
            findings = deterministic_findings(bundle)
            self.assertFalse(any(f["rule"] == "RC-2" for f in findings))

    def test_ci_never_reports_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp, ci=[{"name": "docs build", "status": "completed", "conclusion": "skipped"}])
            findings = deterministic_findings(bundle)
            ci_findings = [f for f in findings if f["rule"] == "RC-3"]
            self.assertTrue(ci_findings)
            self.assertEqual(ci_findings[0]["severity"], "info")
            self.assertIn("never treated as passed", ci_findings[0]["evidence"]["quote"])

    def test_ci_failure_is_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp, ci=[{"name": "unit", "status": "completed", "conclusion": "failure"}])
            findings = deterministic_findings(bundle)
            ci_findings = [f for f in findings if f["rule"] == "RC-3"]
            self.assertEqual(ci_findings[0]["severity"], "blocker")


class ValidateTest(unittest.TestCase):
    def test_bad_quote_marked_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(
                tmp,
                files=[{"filename": "sglang_omni/models/ming3_tts/model.py", "patch": "def forward(): pass"}],
            )
            findings = [
                {
                    "id": "x1",
                    "rule": "RC-5",
                    "severity": "info",
                    "category": "test",
                    "location": {"file": "sglang_omni/models/ming3_tts/model.py", "lines": "1"},
                    "evidence": {"quote": "this quote does not exist anywhere", "source": "x", "quote_type": "file"},
                    "impact": "",
                    "fix": "",
                }
            ]
            validated = validate(bundle, Path(tmp) / "files", findings, {"rules_version": RULES_VERSION})
            self.assertEqual(validated[0]["status"], "uncertain")

    def test_verified_quote_stays_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(
                tmp,
                files=[{"filename": "sglang_omni/models/ming3_tts/model.py", "patch": "def forward(): pass"}],
            )
            findings = [
                {
                    "id": "x2",
                    "rule": "RC-5",
                    "severity": "info",
                    "category": "test",
                    "location": {"file": "sglang_omni/models/ming3_tts/model.py", "lines": "1"},
                    "evidence": {"quote": "def forward(): pass", "source": "x", "quote_type": "file"},
                    "impact": "",
                    "fix": "",
                }
            ]
            validated = validate(bundle, Path(tmp) / "files", findings, {"rules_version": RULES_VERSION})
            self.assertIn("verified", validated[0]["validation"])


if __name__ == "__main__":
    unittest.main()
