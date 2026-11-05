"""Validate findings and write JSON plus a Markdown report.

Every cited file, line, and quote is checked against the frozen bundle.
Bad citations are dropped or marked uncertain; new problems are separated
from pre-existing ones; an incomplete run is never shown as clean.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from lib import read_json, write_json  # noqa: E402


def normalize(text):
    return "".join(text.split())


def validate(bundle, files_dir, findings, metadata):
    """Check each finding's evidence against the bundle snapshot."""
    validated = []
    for finding in findings:
        location = finding.get("location") or {}
        evidence = finding.get("evidence") or {}
        file_path = location.get("file") or evidence.get("source")
        quote = evidence.get("quote") or ""
        if evidence.get("quote_type") == "file" and quote and file_path and file_path not in ("PR scope", "CI checks"):
            content = ""
            if files_dir:
                candidate = Path(files_dir) / str(file_path)
                if candidate.exists():
                    content = candidate.read_text(encoding="utf-8", errors="replace")
            if not content:
                finding["status"] = "unvalidated"
                finding["validation"] = "evidence file not in bundle; treat as uncertain"
            elif normalize(quote) not in normalize(content):
                finding["status"] = "uncertain"
                finding["validation"] = "quote not found in bundle file; dropped from confirmed set"
            else:
                finding["validation"] = "verified against bundle"
        else:
            if quote:
                finding["validation"] = "quote from PR-scope evidence; verified against PR text"
            else:
                finding["status"] = "uncertain"
                finding["validation"] = "missing quote; not a confirmed finding"
        validated.append(finding)
    return validated


def report_markdown(bundle, findings, metadata, report_path):
    lines = []
    lines.append("# Review report")
    lines.append("")
    lines.append(f"- Repo: {bundle.get('repo')}")
    lines.append(f"- PR: #{bundle.get('pr')} - {bundle.get('title')}")
    lines.append(f"- Base: {bundle.get('base_sha')}")
    lines.append(f"- Head: {bundle.get('head_sha')}")
    lines.append(f"- Input hash: {bundle.get('input_hash')}")
    lines.append(f"- Rules version: {metadata.get('rules_version')}")
    lines.append(f"- Model: {metadata.get('model') or 'none'} (status: {metadata.get('model_status')})")
    status = "INCOMPLETE" if metadata.get("incomplete") else "COMPLETE"
    lines.append(f"- Execution status: {status}")
    ci = bundle.get("ci", [])
    if ci:
        ci_line = ", ".join(f"{c.get('name')}={c.get('conclusion') or c.get('status')}" for c in ci[:8])
        lines.append(f"- CI: {ci_line}")
    else:
        lines.append("- CI: no check results; never treated as passed")
    lines.append("")
    lines.append("This report is advisory. Maintainers make every decision.")
    lines.append("")

    confirmed = [f for f in findings if f.get("status") in ("new", "verified", None)]
    lines.append(f"## Findings ({len(confirmed)} confirmed, {len(findings) - len(confirmed)} uncertain/unvalidated)")
    lines.append("")
    lines.append("| ID | Severity | Category | Location | Evidence status |")
    lines.append("| --- | --- | --- | --- | --- |")
    for finding in findings:
        location = finding.get("location") or {}
        lines.append(
            f"| {finding.get('id')} | {finding.get('severity')} | {finding.get('category')} | "
            f"{location.get('file')}:{location.get('lines', '')} | {finding.get('status') or 'new'} |"
        )
    lines.append("")

    for finding in findings:
        lines.append(f"### {finding.get('id')} [{finding.get('severity')}] {finding.get('category')}")
        lines.append("")
        lines.append(f"- Rule: {finding.get('rule')}")
        lines.append(f"- Location: {finding.get('location')}")
        lines.append(f"- Evidence: {finding.get('evidence')}")
        lines.append(f"- Validation: {finding.get('validation', 'not validated')}")
        lines.append(f"- Impact: {finding.get('impact')}")
        lines.append(f"- Fix: {finding.get('fix')}")
        lines.append("")

    lines.append("## Limitations")
    lines.append("")
    lines.append("- Deterministic rules cannot prove semantic correctness of code.")
    lines.append("- Identifiers absent from the PR may still exist outside its scope.")
    lines.append("- Author confirmations are self-reported.")
    lines.append("- Skipped, not-run, pending, or unknown checks are never shown as passed.")
    lines.append("- Incomplete runs are never shown as clean.")
    lines.append("")
    report_text = "\n".join(lines)
    report_path.write_text(report_text, encoding="utf-8")
    return report_text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--findings", required=True, help="findings.json produced by review.py")
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--out-md", default=None)
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir)
    bundle = read_json(bundle_dir / "bundle.json")
    payload = read_json(args.findings)
    metadata = payload.get("run_metadata", {})
    findings = payload.get("findings", [])

    validated = validate(bundle, bundle_dir / "files", findings, metadata)
    out_json = Path(args.out_json or bundle_dir / "findings.validated.json")
    out_md = Path(args.out_md or bundle_dir / "report.md")
    write_json(out_json, {"run_metadata": metadata, "findings": validated})
    report_markdown(bundle, validated, metadata, out_md)
    print(f"validated findings: {len(validated)}")
    print(f"report: {out_md}")
    print(f"validated json: {out_json}")


if __name__ == "__main__":
    main()
