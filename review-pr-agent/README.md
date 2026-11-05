# Review PR Agent

An evidence-based, advisory-only PR review agent for the SGLang Omni repository family. It adapts two sources: the PR-driven model optimization history knowledge base pattern from BBuf/AI-Infra-Auto-Driven-SKILLS (`model-pr-optimization-history`), and the review principles of sgl-project/sglang-omni issue #3502 (Evidence-Based Documentation Review Agent).

## Why

Docs and code can pass lint and build and still be wrong: they can mention parameters that do not exist, list hardware nobody tested, claim speedups without numbers, or duplicate shared content. Catching this means comparing a PR against the code, the configs, and the CI results. Maintainer time and model budget are limited, so this agent is a local, manually run tool that reports problems, each backed by evidence.

## Principles

1. Advisory only. The agent never approves, merges, or closes a PR. Maintainers decide. It judges the change and its evidence, not whether the author is new or used AI.
2. Every finding needs evidence: file, line, and quote. If evidence is missing, report it as missing, not as wrong.
3. Lint checks rules; the agent checks meaning. Formatting stays in lint; the agent checks whether docs match code, whether claims have evidence, and whether shared content is duplicated.
4. Rules come from the repository. The contributor checklist lives in `rules/review-checklist.md` and in CONTRIBUTING; the agent checks a PR against those rules and does not define its own.
5. Cost is bounded. Fixed budgets per run and per day. Pushes and comments never trigger new paid reviews.
6. A PR cannot change the rules used to review it. The rules version is part of the input hash.

## Layout

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Agent contract: when to use, workflow, evidence and safety rules |
| `rules/review-checklist.md` | Versioned review rules (R0 checklist) |
| `history/` | PR evidence knowledge base in the BBuf model-pr-optimization-history format |
| `scripts/lib.py` | Shared helpers: GitHub API, token resolution, input hashing, file classification |
| `scripts/collect_pr.py` | Builds the frozen review input bundle from a PR, computes the input hash |
| `scripts/review.py` | Applies deterministic rules and an optional read-only model, emits findings |
| `scripts/validate_report.py` | Validates every citation, drops bad ones, writes JSON and Markdown reports |
| `scripts/run_review.py` | One-command pipeline: collect, review, validate, cache, report |
| `scripts/query_history.py` | Search prior PR evidence before writing findings |
| `tests/` | Stdlib unittest suite, no network |

## Quick start

```bash
# token: export GITHUB_TOKEN, or the macOS keychain entry is used automatically
python3 scripts/run_review.py --repo stevejake007/sglang-test-omni --pr 43
# report: artifacts/<run_id>/report.md ; rerunning the same input reuses the cached report

# consult prior PR evidence before writing findings
python3 scripts/query_history.py qwen3-omni --paths-only

# offline run on an existing bundle (tests use this)
python3 scripts/run_review.py --bundle-dir artifacts/<run_id>
```

Optional semantic review: pass `--model <name>` and export `OPENAI_API_KEY`. The model gets read-only access to the frozen bundle only; a model failure marks the report incomplete instead of "no findings".

## Relationship to the references

- From BBuf/AI-Infra-Auto-Driven-SKILLS: the history knowledge base layout (`history/`), the per-PR evidence card format, the "not a manual audit" honesty marker, the query helper, and the idea of rebuilding evidence from `git log --name-only` plus the GitHub API.
- From sglang-omni issue #3502: the six operating principles, the R0 review checklist, the frozen input bundle with an input hash (R2), the collector that never executes PR scripts and reports CI status explicitly (R3), the single read-only reviewer with prompt-injection resistance (R4), citation validation that never shows an incomplete run as clean (R5), and the SQLite cache with budget ledger (R6).

## Status

MVP. Phases 3 (multiple models plus a judge) and 4 (GitHub pilot with private storage and triggers) from issue #3502 are deliberately out of scope; H1/H2 (separate evidence hashes, concurrent budget reservation) are extension points noted in `SKILL.md`.
