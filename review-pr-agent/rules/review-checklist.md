# Review checklist

Version: 1.0.0. This file is the versioned rule set (R0) that `review.py` applies. Changing a rule changes `RULES_VERSION` in `lib.py`; the input hash includes the rules version, so cached reports are invalidated when the rules change. A PR cannot change the rules used to review it.

Rules point back to CONTRIBUTING and the repo doc standards and do not create a second set of contributor requirements. Every rule states what it checks, what evidence it needs, and which change types it applies to. The agent separates a supported defect, a request for evidence, and an optional preference.

## Rules

| ID | Applies to | What it checks | Evidence needed | Response |
| --- | --- | --- | --- | --- |
| RC-1 | model / runtime / config changes | The PR changes implementation files but ships no test file in the same PR | List of changed files, rule reference | warning, missing-evidence |
| RC-2 | any PR body or diff | Performance claim (faster, speedup, throughput, latency, x%, ms, rps) without comparable before/after numbers with units | The claim text, the missing numbers | warning, missing-evidence |
| RC-3 | any PR with CI results | CI honesty: failed or cancelled runs reported as failures; skipped, not-run, pending, unknown, or missing runs never reported as passed | CI status list with per-check status and commit | blocker for failures, info otherwise |
| RC-4 | every PR | Contributor checklist completeness: Summary, Validation, Untested areas present in the PR body | The PR body | info, maintainer follow-up, not rejection |
| RC-5 | docs changes | Backticked identifiers in docs (parameters, symbols, file paths) that do not appear in any changed code or config file in the PR | The identifier and the searched changed files | info, unverified-reference, not "wrong" |
| RC-6 | docs changes | Doc type mapping and per-type checks (cookbook, API reference, developer reference, benchmark) | Doc path and the matched type | info per type |

## Per-doc-type checks (RC-6)

| Doc type | Main checks | Example problem |
| --- | --- | --- |
| Cookbook | Deploy steps, model-specific notes, what was validated | Claims a GPU is supported but there is no validation record for it |
| API reference | Parameters, defaults, inputs and outputs, error behavior | Says the endpoint returns WAV; the code returns PCM |
| Developer reference | Architecture, module roles, call flow | Describes a scheduling flow the code no longer follows |
| Benchmark | Comparable setup, metrics, reproduction, quality results | Before and after runs use different concurrency, yet the speedup is credited to the code |

Doc type is picked mainly by file path (`docs/cookbook/`, `docs/developer_reference/`, `docs/benchmarks/`); page content is the fallback. A page can match more than one type, for example a cookbook with a benchmark table. A page that matches no type gets only the general rules (RC-1 to RC-5).

## Contributor checklist (R1, mirrored in CONTRIBUTING)

Authors fill this in on their PR: what changed and why, confirmation they reviewed the final diff, checks run and their real results, and untested areas. Performance claims need before/after numbers with units, a command to reproduce, and the setup (hardware, software, model, dataset, config, load, repeats). Missing items become a maintainer follow-up, not an automatic rejection. Author confirmations are self-reported; the agent cannot verify them independently.
