# PR evidence history

A PR-driven model evidence knowledge base for the SGLang Omni repository family, adapted from the `model-pr-optimization-history` directory of BBuf/AI-Infra-Auto-Driven-SKILLS. These records are documentation, not installable skills: the directory acts as one queryable knowledge base for model-family PR evidence.

- `sglang_omni/`: SGLang Omni model histories and audits.
- `README.md`: this file.
- `scripts/query_history.py` (one level up): search helper for model slugs, doc paths, and keyword snippets.

## Card format

Each model-family doc (`history/sglang_omni/<slug>/README.en.md`, or a single file when the family is small) keeps, per family, an Implementation File Coverage table (file to git-traced PR numbers), a Timeline table (date, PR, state, title, main files), and per-PR diff cards (motivation, implementation files, evidence snippets, validation/risk notes, source tags).

## Honesty markers

Entries labeled EXAMPLE or "not a manual audit" are templates or discovery inventories, not audited conclusions. Read the full diff and the current callers before making review conclusions from them; API file counts and snippets do not establish complete diff coverage. Hand-written dated notes take precedence over generated rows. Open PRs are kept out of the merged-history cards until their diffs are manually reviewed.

## Populating from git

The upstream pattern (BBuf/AI-Infra-Auto-Driven-SKILLS, `tools/rebuild_model_pr_history_from_git.py`) rebuilds these docs from framework git traces: `git ls-files` plus per-model path filters select implementation files, `git log --name-only` on those files finds merged PR numbers that actually modified the model surface, and the GitHub PR and files APIs provide the final diff metadata and patch snippets. Merged PRs that already have an audited card keep that card verbatim; only new or still-open PRs are fetched again. Hand-written dated notes survive regeneration.

## Query

```bash
python3 scripts/query_history.py --list
python3 scripts/query_history.py qwen3-omni --paths-only
python3 scripts/query_history.py "tts streaming" --limit 5
```

Read the matching history before writing a review finding; save the short extracted evidence under `history/review-notes.md` with paths read, PR numbers, source files, and the decision each item influenced.
