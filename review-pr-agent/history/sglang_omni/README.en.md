# SGLang Omni Model PR Evidence

Refresh: seed. Source head: this repository main. Status: template with seed rows; entries are not a manual audit until reviewed.

## Implementation File Coverage

Seed rows below list real model surfaces in this repository, with no audited PR mapping yet. They become evidence rows once `git log --name-only` tracing (see history/README.md) and a diff audit attach PR numbers.

| File | Git-traced PRs |
| --- | --- |
| `sglang_omni/models/arkasr/*` | not audited yet |
| `sglang_omni/models/audar_tts/*` | not audited yet |
| `sglang_omni/models/fishaudio_s2_pro/*` | not audited yet |
| `sglang_omni/models/ming3_asr/*` | not audited yet |
| `sglang_omni/models/ming3_audio/*` | not audited yet |
| `sglang_omni/models/ming3_tts/*` | not audited yet |
| `sglang_omni/models/ming_omni/*` | not audited yet |
| `sglang_omni/models/moss_tts/*` | not audited yet |
| `sglang_omni/models/nemotron_diarization/*` | not audited yet |
| `sglang_omni/preprocessing/*` | not audited yet |
| `sglang_omni/pipeline/*` | not audited yet |

## Timeline

| Date | PR | State | Title | Main files |
| --- | --- | --- | --- | --- |
| - | - | - | (empty until audited) | - |

## Example card (illustrative, not a real PR)

### PR #00000 - EXAMPLE: support streaming for a TTS model

- Link: https://github.com/example/repo/pull/0
- Status/date: illustrative / unknown
- Source: example template, not a manual audit. Read the real diff before drawing conclusions.

Motivation: title: "EXAMPLE"; model line: TTS; category: model support; main diff: `sglang_omni/models/ming3_tts/*`.

Implementation file coverage: `sglang_omni/models/ming3_tts/model.py` (modified +40/-5), `sglang_omni/preprocessing/streaming.py` (modified +12/-2).

Validation risk: runtime path change; risk points are weight loading, chunked audio preprocessing, and sampler output; needs at least one real checkpoint smoke and a streaming end-to-end run.

This card is a template for the format: motivation, implementation files, evidence snippets, validation risk, and source tags per PR. Replace it with audited data before relying on it.
