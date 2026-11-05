"""One-command review pipeline: collect, review, validate, cache, report.

Runs are recorded in a SQLite ledger. Identical input hashes reuse the
completed report; changed evidence never reuses an old result. Budget
limits are enforced per run and per day before any paid model call.
"""

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from lib import read_json, write_json  # noqa: E402

DEFAULT_DAY_BUDGET = int(os.environ.get("REVIEW_BUDGET_DAY", "5"))


def ledger_connect(artifacts_root):
    db_path = Path(artifacts_root) / "ledger.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS runs ("
        "run_id TEXT PRIMARY KEY, input_hash TEXT, status TEXT, "
        "report_path TEXT, model_calls INTEGER, created_at TEXT)"
    )
    return connection


def today(connection):
    prefix = time.strftime("%Y-%m-%d")
    row = connection.execute(
        "SELECT COALESCE(SUM(model_calls), 0) FROM runs WHERE created_at LIKE ?", (prefix + "%",)
    ).fetchone()
    return int(row[0] or 0)


def find_cached(connection, input_hash):
    row = connection.execute(
        "SELECT report_path FROM runs WHERE input_hash = ? AND status = 'complete' "
        "ORDER BY created_at DESC LIMIT 1",
        (input_hash,),
    ).fetchone()
    return row[0] if row else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="owner/repo")
    parser.add_argument("--pr", type=int, help="pull request number")
    parser.add_argument("--bundle-dir", help="use an existing bundle instead of collecting")
    parser.add_argument("--out", default="artifacts", help="artifacts root directory")
    parser.add_argument("--model", help="optional model name for semantic review")
    parser.add_argument("--budget-per-run", type=int, default=1, help="max model calls per run")
    parser.add_argument("--no-reuse", action="store_true", help="disable cache reuse")
    parser.add_argument("--no-llm", action="store_true", help="force deterministic rules only")
    args = parser.parse_args()

    artifacts_root = Path(args.out)
    connection = ledger_connect(artifacts_root)

    if args.bundle_dir:
        bundle_dir = Path(args.bundle_dir)
        bundle = read_json(bundle_dir / "bundle.json")
        run_id = bundle_dir.name
    else:
        if not (args.repo and args.pr):
            parser.error("provide --repo/--pr or --bundle-dir")
        from collect_pr import collect
        from lib import resolve_token

        token = resolve_token()
        if not token:
            print("no GitHub token found", file=sys.stderr)
            sys.exit(2)
        bundle, run_id, bundle_dir = collect(args.repo, args.pr, artifacts_root, token)
        print(f"collected run {run_id} hash {bundle['input_hash']}")

    input_hash = bundle["input_hash"]

    if not args.no_reuse:
        cached = find_cached(connection, input_hash)
        if cached:
            print(f"reusing cached report: {cached}")
            print(f"input hash: {input_hash}")
            return

    use_model = bool(args.model) and not args.no_llm
    if use_model and args.budget_per_run > 0 and today(connection) + 1 > DEFAULT_DAY_BUDGET:
        print(f"daily budget exceeded ({DEFAULT_DAY_BUDGET}), model step skipped")
        use_model = False

    from review import review
    from validate_report import report_markdown, validate

    findings, metadata = review(bundle, bundle_dir / "files", args.model if use_model else None)
    validated = validate(bundle, bundle_dir / "files", findings, metadata)
    report_path = bundle_dir / "report.md"
    report_markdown(bundle, validated, metadata, report_path)
    write_json(bundle_dir / "findings.validated.json", {"run_metadata": metadata, "findings": validated})

    model_calls = 1 if (use_model and metadata.get("model_status") == "ok") else 0
    connection.execute(
        "INSERT OR REPLACE INTO runs (run_id, input_hash, status, report_path, model_calls, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, input_hash, "complete", str(report_path), model_calls, time.strftime("%Y-%m-%d %H:%M:%S")),
    )
    connection.commit()

    by_severity = {}
    for finding in validated:
        by_severity[finding.get("severity")] = by_severity.get(finding.get("severity"), 0) + 1
    print(f"findings by severity: {by_severity or 'none'}")
    print(f"report: {report_path}")
    print(f"input hash: {input_hash}")
    if metadata.get("incomplete"):
        print("execution status: INCOMPLETE")


if __name__ == "__main__":
    main()
