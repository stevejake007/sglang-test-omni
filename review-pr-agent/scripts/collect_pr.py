"""Build the frozen review input bundle for a PR.

Fetches PR metadata, changed files with patches, raw file contents at the
head commit, reviews, comments, and CI statuses from the GitHub API, writes
them under an artifacts directory, and computes one input hash over the
authorized inputs. The collector never executes scripts from the PR.
"""

import argparse
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from lib import (  # noqa: E402
    RULES_VERSION,
    api_get,
    canonical_json,
    input_hash,
    raw_get,
    resolve_token,
    write_json,
)

PAGE_SIZE = 100


def api_get_paged(path, token):
    """GET a paginated GitHub API list and return every page."""
    items = []
    page = 1
    while True:
        batch = api_get(path, token, {"per_page": PAGE_SIZE, "page": page})
        items.extend(batch)
        if len(batch) < PAGE_SIZE:
            return items
        page += 1
        time.sleep(0.2)


def _pick(dct, keys):
    out = {}
    for key in keys:
        if key in dct:
            out[key] = dct[key]
    return out


def collect(repo, pr_number, out_dir, token, fetch_content=True, rules_version=RULES_VERSION):
    """Collect a PR bundle and return the bundle dict and its input hash."""
    token = token or resolve_token()
    pr = api_get(f"/repos/{repo}/pulls/{pr_number}", token)
    if pr.get("mergeable") is None and "mergeable" in pr:
        pass
    base_sha = pr["base"]["sha"]
    head_sha = pr["head"]["sha"]
    pr_body = pr.get("body") or ""
    pr_title = pr.get("title") or ""

    files = api_get_paged(f"/repos/{repo}/pulls/{pr_number}/files", token)
    reviews = api_get_paged(f"/repos/{repo}/pulls/{pr_number}/reviews", token)
    comments = api_get_paged(f"/repos/{repo}/pulls/{pr_number}/comments", token)
    issue_comments = api_get_paged(f"/repos/{repo}/issues/{pr_number}/comments", token)
    check_runs = api_get(f"/repos/{repo}/commits/{head_sha}/check-runs", token).get("check_runs", [])

    file_meta = []
    for item in files:
        file_meta.append(
            {
                "filename": item.get("filename"),
                "status": item.get("status"),
                "additions": item.get("additions"),
                "deletions": item.get("deletions"),
                "changes": item.get("changes"),
                "patch": item.get("patch") or "",
            }
        )

    ci_status = []
    for run in check_runs:
        ci_status.append(
            {
                "name": run.get("name"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "commit": run.get("head_sha"),
            }
        )

    bundle = {
        "repo": repo,
        "pr": pr_number,
        "title": pr_title,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "body": pr_body,
        "files": file_meta,
        "reviews": [{"user": _pick(r, ["login"]), "state": r.get("state"), "body": r.get("body") or ""} for r in reviews],
        "comments": [{"user": _pick(c, ["login"]), "body": c.get("body") or ""} for c in comments],
        "issue_comments": [{"user": _pick(c, ["login"]), "body": c.get("body") or ""} for c in issue_comments],
        "ci": ci_status,
        "rules_version": rules_version,
        "model_config": {"model": None},
    }

    digest = {
        "repo": repo,
        "pr": pr_number,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "body": pr_body,
        "files": [
            {"filename": f["filename"], "status": f["status"], "patch": f["patch"]}
            for f in file_meta
        ],
        "comments": [c["body"] for c in comments] + [c["body"] for c in issue_comments],
        "ci": ci_status,
        "rules_version": rules_version,
    }
    digest_bytes = canonical_json(digest)
    bundle_hash = input_hash(digest)
    bundle["input_hash"] = bundle_hash

    run_id = f"{repo.replace('/', '-')}-pr{pr_number}-{uuid.uuid4().hex[:8]}"
    run_dir = Path(out_dir) / run_id
    files_dir = run_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    if fetch_content:
        for item in file_meta:
            if item["status"] == "removed":
                continue
            content = raw_get(repo, head_sha, item["filename"], token)
            if content is not None:
                (files_dir / item["filename"]).parent.mkdir(parents=True, exist_ok=True)
                (files_dir / item["filename"]).write_text(content, encoding="utf-8")

    write_json(run_dir / "bundle.json", bundle)
    (run_dir / "input_hash.txt").write_text(bundle_hash, encoding="utf-8")
    (run_dir / "digest.json").write_bytes(digest_bytes)
    return bundle, run_id, run_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", required=True, type=int, help="pull request number")
    parser.add_argument("--out", default="artifacts", help="artifacts root directory")
    parser.add_argument("--no-fetch-content", action="store_true", help="skip raw file contents")
    args = parser.parse_args()

    token = resolve_token()
    if not token:
        print("no GitHub token found (set GITHUB_TOKEN or populate the keychain)", file=sys.stderr)
        sys.exit(2)

    bundle, run_id, run_dir = collect(
        args.repo, args.pr, args.out, token, fetch_content=not args.no_fetch_content
    )
    print(f"run_id: {run_id}")
    print(f"input_hash: {bundle['input_hash']}")
    print(f"bundle: {run_dir / 'bundle.json'}")
    print(f"changed files: {len(bundle['files'])}")
    print(f"ci checks: {len(bundle['ci'])}")


if __name__ == "__main__":
    main()
