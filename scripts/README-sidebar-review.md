# Sidebar documentation review

The PR check reviews the top-level toctrees captioned `General Usage` and `Developer Reference` in `docs/index.rst`. On both the PR base and head it follows their explicit and glob entries through nested RST and MyST toctrees, including pages in other directories. Shared pages count once toward the combined content budget. Each navigation entry counts toward the entry budget. The root index only supplies navigation, so edits to its landing-page text and to unrelated sections such as Cookbook leave the counts unchanged. If a reviewed section is renamed intentionally, update the caption in the checker and reviewer instructions.

At commit `82a939a` the two sections together contain 31 reachable pages, 31 navigation entries, and 7,137 nonblank source lines. The limits from #60 apply to their combined totals. Lines include markup and code. Maintainers can adjust the constants in `scripts/review_sidebar_docs.py`.

| Budget | Limit |
| --- | ---: |
| Reachable pages | 100 |
| Toctree entries, including repeated links | 105 |
| Nonblank source lines across reachable pages | 18,000 |
| Nonblank source lines per reachable page | 500 |
| New reachable pages per PR | 5 |
| Net new toctree entries per PR | 5 |
| Net new nonblank sidebar source lines per PR | 600 |

If the base already exceeds an overall or per-page limit, the effective limit is its base value, so a PR may reduce it but cannot make it larger. This allows existing large pages to be maintained while encouraging contributors to consolidate content. New pages count even if their files existed but were not reachable from the base navigation. Moving content off the sidebar can reduce the count; reviewers must examine removals and avoid losing important content. Line counting is not a semantic duplicate detector, and a passing check does not mean a review or docs build passed.

The check exits 0 for a pass, 1 for budget violations, and 2 for an incomplete review, such as an unresolved local toctree target, unsupported include directive, or unreadable page. It ignores external and self links. It does not build Sphinx, expand includes, discover generated navigation, evaluate headings as sidebar entries, or validate documentation accuracy. If the documentation adopts those features, extend the checker before relying on its counts. The existing docs build remains necessary.

Run against two checked-out repository snapshots:

```bash
python3 scripts/review_sidebar_docs.py --base /path/to/base --head /path/to/head --report sidebar-review.md
python3 -m unittest discover -s tests/unit_test/scripts -p 'test_sidebar_docs_review.py' -v
```

The workflow runs on each PR with a read-only token and no model key. It executes the checker from the base commit and reads the PR checkout as data, so a PR cannot change the checker or budgets used in its own normal run. The workflow file itself is part of the PR and is not a tamper-proof enforcement boundary: use a separately controlled required workflow or ruleset and branch protection if adversarial bypass must be prevented. The first PR introducing this check reports that the base has no checker; after merging, subsequent PRs run the base version. Configure the resulting check as required separately if it must block merges.

For qualitative review, select the Sidebar Documentation Reviewer custom agent and ask it to use the `sidebar-doc-review` skill. The automated workflow does not invoke an LLM, read an API key, post a comment, or perform semantic review. An optional model-assisted workflow would need a separately designed trusted execution and secret policy.
