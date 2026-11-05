"""Search the PR evidence history knowledge base.

Adapted from scripts/query.py in BBuf/AI-Infra-Auto-Driven-SKILLS
(model-pr-optimization-history). Scans every markdown file under history/,
scores docs by query term hits and slug matches, and prints the exact docs
to read.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from lib import REVIEW_AGENT_ROOT  # noqa: E402

HISTORY_ROOT = REVIEW_AGENT_ROOT / "history"


def _tokenize(value):
    tokens = re.split(r"[^a-z0-9]+", value.lower())
    return list(dict.fromkeys(token for token in tokens if token))


def _docs():
    if not HISTORY_ROOT.exists():
        return []
    return sorted(HISTORY_ROOT.rglob("*.md"))


def _score(path, terms):
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    score = 0
    for term in terms:
        if term in path.stem.lower():
            score += 1000
        score += text.count(term) * 2
    return score


def _matching_lines(path, terms, limit=6):
    matches = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        lowered = line.lower()
        if any(term in lowered for term in terms):
            compact = re.sub(r"\s+", " ", line).strip()
            if compact:
                matches.append(f"{path.relative_to(REVIEW_AGENT_ROOT)}:{line_no}: {compact[:200]}")
        if len(matches) >= limit:
            break
    return matches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="*", help="search terms or a model slug")
    parser.add_argument("--list", action="store_true", help="list all history docs")
    parser.add_argument("--paths-only", action="store_true", help="print doc paths only")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    all_docs = _docs()
    if args.list:
        for doc in all_docs:
            print(doc.relative_to(REVIEW_AGENT_ROOT))
        return 0
    if not all_docs:
        print("history directory is empty; run the collector and save PR notes first", file=sys.stderr)
        return 1

    terms = _tokenize(" ".join(args.query))
    if not terms:
        for doc in all_docs[: args.limit]:
            print(doc.relative_to(REVIEW_AGENT_ROOT))
        return 0

    scored = sorted(((doc, _score(doc, terms)) for doc in all_docs), key=lambda pair: -pair[1])
    for doc, score in scored[: args.limit]:
        if args.paths_only:
            print(doc.relative_to(REVIEW_AGENT_ROOT))
            continue
        print(f"## {doc.relative_to(REVIEW_AGENT_ROOT)} score={score}")
        for line in _matching_lines(doc, terms):
            print(f"- {line}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
