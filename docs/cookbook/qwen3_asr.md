# Qwen3-ASR

Qwen3-ASR turns speech into text from an uploaded audio file or a live PCM stream. The official checkpoints are [Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) and [Qwen3-ASR-0.6B](https://huggingface.co/Qwen/Qwen3-ASR-0.6B).

File transcription uses the OpenAI-compatible `/v1/audio/transcriptions` endpoint. Requests to `/v1/audio/translations` return HTTP 400 with this model. See [ASR Model Usage](../basic_usage/asr.md) for the shared API reference.

## Prerequisites

Install SGLang-Omni for your platform. Run the examples from the repository root so that the YAML profiles and sample audio paths resolve.

| Hardware | Installation | Launch recipe |
|---|---|---|
| One CUDA GPU | [CUDA installation](../get_started/installation.md) | [CUDA quickstart](#cuda-quickstart) for 1.7B |
| One RTX 4090 (24 GB) or RTX 5090 (32 GB) | [CUDA installation](../get_started/installation.md) | [GPU-specific profiles](#rtx-4090-and-rtx-5090) for 1.7B |
| One Ascend 910 device | [Ascend NPU installation](../other_platforms/installation_npu.md) | [Ascend NPU profile](#ascend-npu-graph-execution) for 1.7B or 0.6B |
| Apple Silicon | [Apple Silicon installation](../other_platforms/installation_apple_silicon.md) | [Torch/MPS profile](#apple-silicon) with a 0.6B example |

## CUDA Quickstart

Download the pinned Qwen3-ASR-1.7B checkpoint with the Hugging Face CLI (`hf`), then start the server in the same shell.

```bash
MODEL_REVISION=7278e1e70fe206f11671096ffdd38061171dd6e5
MODEL_PATH="$(
  hf download Qwen/Qwen3-ASR-1.7B \
    --revision "${MODEL_REVISION}" \
    --quiet
)"
```

```bash
sgl-omni serve \
  --model-path "${MODEL_PATH}" \
  --model-name Qwen/Qwen3-ASR-1.7B \
  --host 127.0.0.1 \
  --port 8000
```

Once the server is ready, use [Transcribe Audio](#transcribe-audio) to verify the deployment from a second terminal.

## Choose a Transcription Method

| Goal | Interface | Audio input |
|---|---|---|
| Get the completed transcript of a file | [HTTP transcription](#transcribe-audio) | Upload a complete file. The server can split long recordings into chunks. |
| Read transcript text as it is decoded | [Server-Sent Events (SSE)](#stream-transcription) | Upload a complete file, then receive text deltas. |
| Send audio as it arrives | [Realtime WebSocket](#live-pcm-transcription) | Send mono 16 kHz PCM16 packets to a server started with `--enable-realtime`. |

## Transcribe Audio

Upload the sample WAV in a second terminal. If you launched a different checkpoint or set a custom `--model-name`, use the served model name in the `model` field.

```bash
curl -fsS http://localhost:8000/v1/audio/transcriptions \
  -F model=Qwen/Qwen3-ASR-1.7B \
  -F file=@tests/data/query_to_cars.wav \
  -F response_format=json
```

The JSON response includes the spoken question in `text`. Punctuation can vary.

```json
{"text": "How many cars are there in the picture?"}
```

For chunk-level start and end timestamps, use `response_format=verbose_json`. See [ASR Model Usage](../basic_usage/asr.md#use-curl) for the other response formats.

## Stream Transcription

Add `stream=true` to the same upload request. The `-N` option disables curl's output buffering.

```bash
curl -fsSN http://localhost:8000/v1/audio/transcriptions \
  -F model=Qwen/Qwen3-ASR-1.7B \
  -F file=@tests/data/query_to_cars.wav \
  -F response_format=json \
  -F stream=true
```

Expect zero or more `transcript.text.delta` events, a `transcript.text.done` event containing the complete text, and the `[DONE]` sentinel. Qwen3-ASR batches deltas for up to 50 ms by default and flushes buffered text at the end of decoding. See [ASR Model Usage](../basic_usage/asr.md#stream-transcription) for the full event format.

## Live PCM transcription

To accept live audio over WebSocket, add `--enable-realtime` to the CUDA quickstart command. Stop the previous server before starting this one on the same port.

```bash
sgl-omni serve \
  --model-path "${MODEL_PATH}" \
  --model-name Qwen/Qwen3-ASR-1.7B \
  --host 127.0.0.1 \
  --enable-realtime \
  --port 8000
```

Connect to `/v1/realtime?intent=transcription`, configure the session, and
append base64-encoded mono 16 kHz PCM16 packets. `input_audio_buffer.commit`
finalizes the active segment manually; server VAD also finalizes after the
configured silence interval. Send `transcription.done` after the final packet
to receive `transcription.completed`. `input_audio_buffer.clear` discards the
current segment and any partial hypothesis derived from it while keeping the
WebSocket session open for new audio.

```json
{
  "type": "session.update",
  "session": {
    "language": "English",
    "decode_interval_ms": 1000,
    "turn_detection": {
      "type": "server_vad",
      "threshold": 0.5,
      "prefix_padding_ms": 300,
      "silence_duration_ms": 500
    }
  }
}
```

`decode_interval_ms` is how much new audio arrives between partial decodes. It defaults to 2000 ms, must be at least 200 ms, and `null` restores the default. Like `language` and `turn_detection`, it can change only while no uncommitted audio is buffered; with server VAD that means before the first audio packet.

Each periodic decode is an ordinary stateless Qwen3-ASR request over all audio
in the active segment. After the first two refreshes, the server rolls five
tokens back from the prior hypothesis and uses the retained text as the next
prompt prefix. No decoder KV cache or worker affinity is retained. Segments are
also finalized at the configured `audio_chunking.max_audio_clip_s` boundary
(30 seconds by default).

Partial results are full replacements, not append-only deltas:

```json
{
  "type": "transcription.segment",
  "event_index": 7,
  "segment_id": 0,
  "audio_start_ms": 0,
  "audio_end_ms": 2000,
  "text": "hello wor",
  "is_final": false,
  "language": "English"
}
```

A later event for the same `segment_id` replaces this text. `audio_start_ms`
and `audio_end_ms` are the span of input audio the text was decoded from.
A partial can trail the audio already sent, since audio that arrives while it
decodes is left to the next partial. `audio_start_ms` stays fixed for the
segment, including segments opened by the 30 second boundary, which have no
`input_audio_buffer.speech_started` event. An event with
`is_final=true` is immutable. `transcription.completed` contains the joined
text from all final segments.

`language` is the language the segment was transcribed in, as Qwen3-ASR names it (for example `English`): the detected language, or the `language` hint when the session set one. `transcription.completed` carries the language of its last non-empty final segment. Both fields are `null` when the language is unknown.

Append events are not idempotent. After a transport failure, reconnect and
restart the transcription rather than retrying packets on the old session.
Reconnecting resets uncommitted audio, partial hypotheses, VAD state, and Qwen
rollback state.

This client uses `ffmpeg` on your `PATH` to convert the 48 kHz WAV fixture to raw 16 kHz PCM16 and uses the `websockets` package to send it in 100 ms packets. It disables server VAD and commits the replayed audio as one segment.

```python
import asyncio
import base64
import json
import subprocess

import websockets


async def receive_until(websocket, event_type):
    while True:
        event = json.loads(await asyncio.wait_for(websocket.recv(), timeout=60))
        if event["type"] == "error":
            raise RuntimeError(event["error"]["message"])
        if event["type"] == event_type:
            return event


async def main():
    pcm16 = subprocess.check_output(
        [
            "ffmpeg",
            "-loglevel", "error",
            "-i", "tests/data/query_to_cars.wav",
            "-ac", "1",
            "-ar", "16000",
            "-f", "s16le",
            "pipe:1",
        ]
    )
    async with websockets.connect(
        "ws://localhost:8000/v1/realtime?intent=transcription"
    ) as websocket:
        await receive_until(websocket, "session.created")
        await websocket.send(json.dumps({
            "type": "session.update",
            "session": {"language": "English", "turn_detection": None},
        }))
        await receive_until(websocket, "session.updated")

        # 100 ms at 16 kHz and two bytes per sample.
        for start in range(0, len(pcm16), 3200):
            await websocket.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm16[start:start + 3200]).decode(),
            }))

        await websocket.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await websocket.send(json.dumps({"type": "transcription.done"}))
        completed = await receive_until(websocket, "transcription.completed")
        print(completed["text"])


asyncio.run(main())
```

## Prompt and Vocabulary Biasing

The endpoint accepts the shared ASR request fields (`file`, `model`,
`language`, `response_format`, `temperature`, `stream`) described in
[ASR Model Usage](../basic_usage/asr.md#request-parameters). Three fields are
specific to this checkpoint:

- `prompt` — vocabulary biasing, described below.
- `repetition_penalty` defaults to `1.0` and accepts values in `(0, 2]`. Higher values can reduce loops on noisy or silent audio and can lower accuracy on clean audio. With DFlash, a value other than `1.0` requires [plain fallback](#per-request-plain-fallback).
- `max_new_tokens` — per-request generation cap; the default is the stage
  limit.

Biasing raises the model's preference for the supplied terms. It does not
force them: a term the audio does not contain will not be inserted, and an
irrelevant list biases the model toward words that were never spoken, which
hurts accuracy. A short, relevant list works best — in testing, accuracy
stopped improving past roughly 20 terms, while latency kept growing because
the text is prefilled with every request.

`verbose_json` uses the model adapter's verbose response schema and includes
duration-based usage (rounded-up audio seconds) when duration probing succeeds.

## Language Hints

When `language` is omitted, Qwen3-ASR detects the spoken language before
transcribing. Set an explicit hint when the language is known or automatic
detection is unreliable for short or ambiguous audio.

Qwen3-ASR accepts the following 30 explicit language codes and their canonical names:

| Codes | Canonical names |
|---|---|
| `ar`, `yue`, `zh`, `cs`, `da`, `nl`, `en`, `fil`, `fi`, `fr` | Arabic, Cantonese, Chinese, Czech, Danish, Dutch, English, Filipino, Finnish, French |
| `de`, `el`, `hi`, `hu`, `id`, `it`, `ja`, `ko`, `mk`, `ms` | German, Greek, Hindi, Hungarian, Indonesian, Italian, Japanese, Korean, Macedonian, Malay |
| `fa`, `pl`, `pt`, `ro`, `ru`, `es`, `sv`, `th`, `tr`, `vi` | Persian, Polish, Portuguese, Romanian, Russian, Spanish, Swedish, Thai, Turkish, Vietnamese |

For example, `language=es` and `language=Spanish` both force the prompt suffix
`language Spanish<asr_text>`. The legacy `cn` and regional `zh-*` spellings are
also accepted as Chinese. Unsupported language hints return HTTP 400 instead of
silently falling back to English.

The model also has ASR coverage for 22 Chinese dialects, but those dialect names
are not supported as forced `language` hints; use `Chinese`/`zh` for them.

## Long Audio

With the default CUDA settings, a non-streaming upload can contain up to 3,600 seconds of audio. SGLang-Omni splits recordings longer than 30 seconds into separate engine requests and joins the transcripts in order. The native limit for a single engine request is 1,200 seconds. See [Known Limitations](#known-limitations) for the Torch/MPS limits.

The shared `audio_chunking` flags, the aggregate guard, and the streaming
limit are described in [ASR Model Usage](../basic_usage/asr.md#long-audio);
the defaults and limits below are Qwen3-ASR's.

The scheduling policy is yours to tune, with dotted flags or the matching
YAML keys:

| Name | Default | Meaning |
|---|---|---|
| `--audio_chunking.max_audio_clip_s` | `30` | Longest clip we send to the engine in one request, and therefore the chunk length. It sits well below the model's native 1,200s on purpose: shorter chunks batch better, and the output-token budget scales with clip length on its own. Capped at the native clip limit. |
| `--audio_chunking.max_concurrent_chunks` | `8` | How many chunks of one request run in the engine at once. A per-request cap so one long upload can't crowd out everyone else's requests. |
| `--audio_chunking.max_total_audio_s` | `3600` | Upper limit on one upload; you get HTTP 400 above it. It bounds a single decoded waveform, not the total across uploads; that is the next knob's job. |
| `--audio_chunking.max_concurrent_long_audio_requests` | `max_running_requests // (2 × max_concurrent_chunks)`, at least 1; `4` with the stock defaults | How many long uploads the server admits at once. A long upload past the cap gets HTTP 503 instead of queueing; short uploads are never gated. The slot is taken before the upload is decoded and returned when its chunks are done. |

The last knob is the aggregate guard. Each admitted upload holds its decoded
waveform (float32 at 16 kHz, about 230 MB for an hour) and drives up to
`max_concurrent_chunks` engine requests, so:

- decoded waveforms held at once are at most
  `max_concurrent_long_audio_requests × max_total_audio_s × 16000 × 4` bytes
  (decoding itself has transient peaks above that);
- engine slots long audio can take together are at most
  `max_concurrent_long_audio_requests × max_concurrent_chunks`.

The default keeps that product at half of `--asr.engine.max_running_requests`
so short requests always have slots left. Setting the knob explicitly to a
value whose product reaches `max_running_requests` logs a warning at startup:
it is not an error, since extra chunks only queue in the engine, but short
requests then wait behind long audio whenever it is saturated. Raising
`max_running_requests` instead also resizes CUDA graph capture, so treat it
as the GPU capacity knob and this one as the long-audio share of it.

The model properties are ClassVars on `Qwen3ASRPipelineConfig`; no
configuration path reaches them:

| Name | Value | Meaning |
|---|---|---|
| `allow_audio_chunking` | `true` | Qwen3-ASR transcribes an isolated chunk correctly, so chunking is on. |
| `max_native_clip_s` | `1200` | Longest clip the model takes as one request (its native limit). Streaming cannot chunk, so this is the streaming cutoff; the Torch MPS compatibility path resolves it to its qualified 60-second cap. |
| `min_tail_s` | `0.5` | Shortest final chunk worth transcribing; if the tail would be shorter, we move the previous cut earlier to absorb it. This matches the model's own minimum input length. |

Note: Raising `audio_chunking.max_audio_clip_s` also resizes the encoder CUDA-graph bucket
ladder, which is derived from the chunk length: a longer chunk means more and
larger captured graphs, and their static buffers stay resident for the life of
the server (roughly 6.6 KB per token of ladder ceiling; at 1,200s the ceiling
is 124,800 tokens). Budget for that when you raise the flag on small GPUs.

Behavior notes:

- **`verbose_json` returns one segment per chunk** with the chunk's real
  start/end timestamps -- chunk-level granularity, not word-level (Qwen3-ASR
  does not emit word timestamps).
- A few unusual audio formats may not expose a readable duration; we fall
  back to the non-chunked path for those uploads.
- SSE streams run as one engine request. On CUDA, use `stream=false` for recordings over 1,200 seconds. On Torch/MPS, split recordings over 60 seconds into separate files before uploading.

## Server Configuration

### CUDA tuning

Qwen3-ASR runs a single ASR stage on one GPU. Its default `auto` dtype follows
the checkpoint configuration (BF16 for Qwen3-ASR-1.7B); pass
`--asr.factory.dtype float16` to force FP16.
Without a draft, async decode is enabled by default for all decode batch sizes, allowing the
shared one-step-lookahead path to overlap host-side result processing with the
next GPU decode forward even for a single request. Use
`--asr.factory.enable_async_decode false` to disable it, or tune the crossover
with `--asr.factory.async_decode_min_batch_size`.
The request builders also use the shared LM prefill-admission gate: prefill
starts when 16 built requests are ready or after the oldest ready request waits
40 ms. Once request-build work drains, a ready prefill is released immediately
if decode is idle; while decode is active, it continues coalescing until the
same request target or deadline. By default with a DFlash draft, a ready
prefill is released as soon as request-build work drains, whether or not decode
is active; set `--asr.factory.prefill_coalesce_after_builds_during_decode true`
to keep coalescing during decode.

To compare with synchronous decode, append `--asr.factory.enable_async_decode false` to the [CUDA quickstart](#cuda-quickstart) command.

### RTX 4090 and RTX 5090

For a single 24 GB RTX 4090 (SM89), use the checked-in consumer profile:

```bash
sgl-omni serve \
  --config examples/configs/qwen3_asr_rtx4090.yaml \
  --model-name Qwen/Qwen3-ASR-1.7B \
  --port 8000
```

This qualified profile keeps the model in BF16, limits the stage to 16 running
requests, and sets `mem_fraction_static` to `0.65`. Its bounds are specific to
the validated RTX 4090 layout; use the default configuration or a separately
qualified profile on other GPU architectures.

For a single 32 GB RTX 5090, use:

```bash
sgl-omni serve \
  --config examples/configs/qwen3_asr_rtx5090.yaml \
  --model-name Qwen/Qwen3-ASR-1.7B \
  --port 8000
```

This profile uses BF16, allows up to 16 running requests, and sets
`mem_fraction_static=0.65`. See the
[RTX 5090 benchmark report](https://github.com/sgl-project/sglang-omni/issues/1212)
for results measured on an earlier release.

### Ascend NPU graph execution

See [Qwen3-ASR graph execution on Ascend NPU](../other_platforms/installation_npu.md#qwen3-asr-graph-execution) for queue settings and runtime restrictions.

After following the [Ascend NPU installation guide](../other_platforms/installation_npu.md), start the server with the shared example.

```bash
sgl-omni serve \
  --config examples/configs/qwen3_asr_ascend910.yaml \
  --model-name Qwen/Qwen3-ASR-1.7B \
  --port 8000
```

The example defaults to Qwen3-ASR-1.7B. To use 0.6B, add `--model-path Qwen/Qwen3-ASR-0.6B` and set `--model-name` to the same model ID. For a local checkpoint, use its path as `--model-path` and the model identifier in your transcription requests as `--model-name`.

This example uses eager LM decode and prefill to avoid truncated outputs observed in [targeted transcription checks on Ascend910_9362](https://github.com/sgl-project/sglang-omni/pull/3199#discussion_r4510634009), while retaining the default encoder graphs.

<a id="apple-silicon-torch-mps"></a>

### Apple Silicon

Qwen3-ASR runs on Apple Silicon through a Torch/MPS compatibility path. Install
with the [Apple Silicon installer](../other_platforms/installation_apple_silicon.md)
and follow its environment-activation and `DYLD_LIBRARY_PATH` steps; TorchCodec
needs Homebrew's keg-only FFmpeg libraries on the path before the server starts.

Pass an official PyTorch checkpoint such as `Qwen/Qwen3-ASR-0.6B`. The path uses
one device (`tp_size=1`), greedy decoding, and the eager `torch_native`/`sdpa`
profile:

```bash
export DYLD_LIBRARY_PATH="$(brew --prefix ffmpeg@7)/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"

sgl-omni serve \
  --model-path Qwen/Qwen3-ASR-0.6B \
  --model-name Qwen/Qwen3-ASR-0.6B \
  --asr.engine.max_running_requests 1 \
  --port 8000
```

Radix caching, chunked prefill, and CUDA graphs are not used by this path. Use the [HTTP](#transcribe-audio) and [SSE](#stream-transcription) examples with `model=Qwen/Qwen3-ASR-0.6B`. SSE sends text deltas as tokens are decoded.
The Apple path applies `repetition_penalty` but does not provide other sampling
penalties or token logprobs yet.

The initial Torch MPS profile is bounded to a 2,048-token KV budget, uses
`audio_chunking.max_audio_clip_s` for non-streaming chunks (30 seconds by
default), and caps native/whole-upload requests at 60 seconds. Values above
that qualified limit are rejected.

## DFlash speculative decoding

Enable experimental DFlash decoding for Qwen3-ASR-1.7B on one CUDA GPU with the pinned draft model:

```bash
sgl-omni serve \
  --config examples/configs/qwen3_asr_1_7b_dflash.yaml \
  --asr.engine.max_running_requests 8 \
  --port 8000
```

DFlash serves any `temperature`. Above 0, verification accepts each drafted token with the target model's probability for it and otherwise samples from the target's remaining probabilities. ASR transcripts are confident, so sampling barely lowers acceptance: on one H100 with SeedTTS English and Chinese clips at 16 concurrent requests, each verification step committed 5.66 tokens at `temperature` 0, 5.66 at 0.7 and 5.62 at 1.0. On the same server at the default cap of 64 running requests, the speedup at 0.7 and 1.0 stayed close to its greedy speedup at every load tested, from 1 to 64 concurrent requests. DFlash retains CUDA graphs.

With DFlash alone, a `repetition_penalty` other than `1.0` returns HTTP 400. To use the penalty, disable the draft with `--asr.engine.disable_speculative_decoding true` or enable [per-request plain fallback](#per-request-plain-fallback).

The draft overlaps scheduling with host work by default; add `--asr.factory.enable_async_decode false` to schedule synchronously. On one H100 with greedy decoding and the prefix cache off, overlap ran at 1.12–1.26x synchronous scheduling on 60-second recordings, 1.01–1.15x on SeedTTS English clips and 0.99–1.15x on SeedTTS Chinese clips, from 1 to 64 concurrent requests, with the same WER and CER. On short clips it also removed the draft's loss under load: at 64 concurrent requests the synchronous draft ran at 0.94x the server without a draft on English clips and 0.91x on Chinese, and the overlapped draft at 1.08x and 1.04x. Overlap runs one extra verify round per request, so the logged acceptance length drops (5.9 to 4.6 tokens on English clips), and streamed first text arrives about 2 ms later for one short clip at a time. With `--asr.factory.async_decode_min_batch_size` set above 1, a decode batch smaller than it, or a prefill after which fewer requests than it are decoding, has its result processed before the next batch is chosen; other batches overlap. At 4 on the same H100 with SeedTTS clips, first streamed text for one clip at a time matched the server without a draft, and throughput stayed within 5% of overlap except at 2 requests, where it was about 7% lower.

The command above caps the server at 8 running requests. A load sweep at the default cap with the prefix cache off ([#3454](https://github.com/sgl-project/sglang-omni/pull/3454)), on one H200 over SeedTTS English clips, found that the synchronous draft gives no speedup at 32 concurrent requests and is about 10% slower at 64. To serve such a load, turn the draft off; `disable_speculative_decoding` drops every `speculative_*` key from the stage:

```bash
sgl-omni serve \
  --config examples/configs/qwen3_asr_1_7b_dflash.yaml \
  --asr.engine.disable_speculative_decoding true \
  --port 8000
```

Send the form field `return_spec_tokens_details=true` to get `sglext.spec_tokens_details` (`spec_accept_length`, `spec_accept_rate`, the draft counts and the per-verify histogram) on `json` and `verbose_json` responses and on the streamed `transcript.text.done` event. Audio long enough to be transcribed in chunks returns none. `spec_accept_rate` and `spec_num_proposed_drafts` are left out when no drafts were proposed or the draft width is adaptive.

Realtime transcription sessions (`--enable-realtime`) use the draft too. On one H100 at the default memory fraction and cap of 64 running requests, SeedTTS English and Chinese clips and 60-second LongLibriHeavy recordings streamed at wall-clock pace, 1 to 16 sessions at a time, with server VAD or manual commit. No session hit an error or a protocol violation, WER stayed within 0.03 percentage points of the server without the draft, and the median time to a segment's first partial was 11 to 28% lower with the synchronous draft, least at a 1000 ms decode interval, and to its final transcript 17 to 27% lower. Overlap, now the default, gave the same transcripts and median latencies as the synchronous draft on SeedTTS English sessions with server VAD, 1 and 16 at a time, with no errors or protocol violations.

The draft's weights and KV cache come out of the stage's memory fraction. On an 80 GB H100 at `--mem-fraction-static 0.08`, as in the streaming cascade profiles, the KV cache holds 11,501 tokens with the draft and 20,705 without. At that fraction, 640 SeedTTS Chinese sessions, 16 at a time, ran with no errors.

### Per-request plain fallback

Set `asr.factory.enable_plain_fallback` to route requests that DFlash cannot serve through ordinary decoding. For example, `repetition_penalty=1.2` uses ordinary decoding, and supported sampling temperatures can still use DFlash. Requests that fit the target context but leave too little room for draft KV also use ordinary decoding.

```bash
sgl-omni serve \
  --config examples/configs/qwen3_asr_1_7b_plain_fallback.yaml \
  --port 8000
```

This option requires synchronous DFlash on one CUDA GPU, with prefill CUDA graphs, mixed chunks, and DP attention disabled. Decode CUDA graphs and radix caching can stay enabled. Both paths share the target model and KV pool, and each path caches its prefixes separately.

When both paths have work, the scheduler gives speculative batches one to two turns per plain turn, according to their live request counts. This reduces the cost of sparse fallback traffic on speculative requests, but increases latency for plain requests. The two-turn cap prevents plain requests from starving; it does not bound wall-clock waiting time because forward durations vary. Fallback requires synchronous decoding, while Qwen3-ASR DFlash on its own overlaps draft execution by default, so even 0% fallback can cost throughput relative to the default DFlash server. Benchmark both request cohorts before enabling this option.

### Ascend NPU

NPU DFlash supports only greedy decoding (`temperature=0`). Requests with a nonzero temperature are rejected because NPU verification uses argmax. For one Ascend device, use the BF16 eager example below. It uses the same pinned draft as the CUDA example and explicitly sets `enable_async_decode: false` to retain the validated greedy, synchronous NPU configuration. Follow the [NPU installation guide](../other_platforms/installation_npu.md) for runtime setup and [graph queue requirements](../other_platforms/installation_npu.md#qwen3-asr-graph-execution).

```bash
sgl-omni serve --config examples/configs/qwen3_asr_1_7b_dflash_npu.yaml --port 8000
```

To enable draft and target verification decode graphs, select `examples/configs/qwen3_asr_1_7b_dflash_npu_graph.yaml` instead. Its request buckets are one and two; prefill and encoder remain eager, and Torch Compile stays disabled. Keep `SGLANG_DFLASH_EAGER_DRAFT_SAMPLER` unset or `0` to capture the reduced-vocabulary draft head. These buckets describe the validated example, not a platform concurrency limit or an optimal performance setting.

Both NPU examples explicitly select `ascend` for target and draft attention. Direct factory callers must supply the same engine overrides and `enable_encoder_cuda_graph=False`. Keep effective `context_length`, including the audio/text prefix and verification reserve, within the pinned causal draft's 32768-token attention window; a larger output budget or context override can exceed it. For offline serving, pass local snapshots with `--model-path` and `--asr.engine.speculative_draft_model_path`. Overlap, realtime, TP>1, quantization and longer contexts remain outside this validation.

## Benchmarking

Start the server from the [CUDA quickstart](#cuda-quickstart) to load the pinned Qwen3-ASR checkpoint. In a second terminal, set `SERVER_GPU_PID` to the GPU process PID reported by `nvidia-smi` and run the SeedTTS English sweep with the pinned dataset revision.

```bash
python -m benchmarks.eval.benchmark_asr_seedtts \
  --port 8000 \
  --gpu-process-pid "${SERVER_GPU_PID}" \
  --dataset-revision 27f4c1adee83b5b29b7c4b375f6b976324bda308 \
  --model-revision 7278e1e70fe206f11671096ffdd38061171dd6e5 \
  --concurrencies 1,2,4,8,16,32,64 \
  --repeats 3 --warmup
```

Compare word error rate (WER), throughput, and latency at the same concurrency and with the same checkpoint and dataset revisions. See [ASR Model Usage](../basic_usage/asr.md#benchmarking) and the [ASR benchmark runbook](../developer_reference/asr_bench.md) for result fields, GPU sampling, and reproducibility flags.

The ASR CI gate runs the selected ASR CI model preset on this same benchmark
entry point (`tests/test_model/test_asr_ci_seedtts.py`). Qwen3-ASR remains
the transcriber for the TTS and talker WER stages.

For the current-main concurrency baseline, the fixed-baseline comparison, and
the per-stage bottleneck decomposition (issue #1324), see
[Qwen3-ASR concurrency profile](../developer_reference/qwen3_asr_concurrency_profile.md).
The benchmark's `--profile-events`, `--sample-util`, `--save-raw-dir`, and
`--fingerprint` flags capture the telemetry that report uses.

## Concurrency tuning

The request-build, admission, and CUDA-graph policy defaults come from a
measured sweep (issue #1324 Q-PR5): `request_build_max_workers` {2, 4, 8} ×
`request_build_max_pending` {16, 32, 64} × `max_running_requests` {16, 32, 64}
with matching CUDA-graph coverage, each configuration a full SeedTTS EN
concurrency sweep (1–64, three repeats plus warmup) on one 141 GB GPU with the
pre-LM encoder enabled and its embedding cache disabled (unique-input regime).
Requests/s by client concurrency:

| config (workers/pending/running) | c=8 | c=16 | c=32 | c=64 | shed at c=64 |
|---|---:|---:|---:|---:|---:|
| 2 / 16 / 32 | 39.1 | 47.5 | 52.3 | 51.0 | 704/3264 |
| 4 / 16 / 32 | 47.6 | 60.3 | 70.4 | 55.4 | 301/3264 |
| 8 / 16 / 32 | 48.5 | 75.6 | 89.7 | 64.6 | 173/3264 |
| 8 / 16 / 16 | 57.6 | 75.4 | 42.2 | 46.7 | 250/3264 |
| 8 / 32 / 32 | 57.7 | 76.5 | 87.1 | 65.1 | 0 |
| 8 / 64 / 32 | 55.2 | 76.6 | 87.9 | 64.7 | 0 |
| **8 / 32 / 64 (default)** | 57.4 | 77.0 | 90.2 | 96.8 | 0 |
| 8 / 64 / 64 | 57.0 | 74.3 | 88.8 | 100.3 | 0 |

Reading, and the resulting defaults:

- **Build workers scale monotonically to 8** at every concurrency ≥ 8 and cost
  nothing at concurrency 1 (0.099–0.101 s mean everywhere), so 8 is the
  default. Those workers do CPU request construction (decode audio,
  optional mel FFT) and submit encoder work asynchronously. When no extra
  builds are queued, the request builder waits for encode and returns a
  ready request like the sync path; when pending+backlog exceeds the
  worker pool, it returns a deferred admission so workers can pull the
  backlog. A cache hit still skips mel extraction entirely.
- **Pending 16 → 32 removes all concurrency-64 shedding** and lifts
  concurrency-8 throughput ~19 %; 64 adds nothing further. 32 is the default.
- **`max_running_requests` 16 collapses concurrency 32** (queue-bound) with no
  light-load latency benefit, so there is no latency-first case for lowering
  it. The default is 64 because it unlocks the concurrency-64 regime (+~50 %
  requests/s, zero shedding), at the price of larger CUDA-graph and KV memory.
  On memory-constrained GPUs, use the memory-conservative override:

```bash
sgl-omni serve --model-path Qwen/Qwen3-ASR-1.7B \
  --asr.engine.max_running_requests 32
```

- Corpus WER stayed 0.0122 for every configuration at every level.

## Known Limitations

The limits shared with the other ASR models are listed in
[ASR Model Usage](../basic_usage/asr.md#known-limitations). Qwen3-ASR adds:

- The Torch MPS path caps both native and whole-upload requests at 60 seconds,
  rejects longer audio, and provides no token logprobs or sampling controls
  beyond `repetition_penalty`.
- CUDA SSE requests are limited to 1,200 seconds. Use `stream=false` to enable [chunking](#long-audio) for longer CUDA uploads.
- DFlash returns HTTP 400 for `repetition_penalty` values other than `1.0` unless [plain fallback](#per-request-plain-fallback) is enabled.
