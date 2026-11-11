# Omni Model Usage

Omni models take multimodal input and answer with text, speech, or an image
through one OpenAI-compatible endpoint. This guide covers the request and
response contract those pipelines share. Launch commands, pipeline stages,
per-stage tuning, quantization, and per-model limits stay in each model's
cookbook.

Models that native SGLang serves through its own chat API, such as the Cosmos3
Reasoner, use the chat path documented in [Native Chat Stage](native_chat_stage.md)
instead of the multi-stage contract here.

## Supported Omni Models

| Model | Input | Output | Notes |
|---|---|---|---|
| [Qwen3-Omni](../cookbook/qwen3_omni.md) | text, image, audio, video | text, text + speech | Text-only mode, or the eight-stage speech pipeline; realtime sessions with server-side turn detection |
| [Ming-Omni](../cookbook/ming_omni.md) | text, image, audio, video | text, text + speech | 44.1 kHz talker; streaming speech arrives in SSE chunks |
| [Ming-3.0-audio-flash](../cookbook/ming3_audio.md) | audio, text | text, text + speech | Also serves transcription and speech synthesis on their own routes |
| [MiniCPM-o](../cookbook/minicpm_o.md) | text, image, audio, video | text, speech | Native full-duplex sessions on `/v1/realtime` |
| [PersonaPlex](../cookbook/personaplex.md) | caller audio | text, speech | Offline pipeline plus a full-duplex session variant |
| [LLaDA2.0-Uni](../cookbook/llada2_uni.md) | text, image | text, images | Image endpoints imply image output; no `modalities` field is needed for them |

## Launch a Server

Every pipeline starts from its checkpoint:

```bash
sgl-omni serve --model-path <checkpoint> --model-name <served-name> --port 8000
```

Speech output needs the stages that synthesize it, so a text-only launch answers
text requests only. Which stages a model runs, their placement, their memory
budgets, and the example configs that pin all of it belong to the cookbook.

## Send a Request

`POST /v1/chat/completions` takes OpenAI-style messages with a `model`
identifier and a `messages` list. A message's `content` is either a string or
a list of typed parts:

```json
{
  "role": "user",
  "content": [
    {"type": "image_url", "image_url": {"url": "https://example.com/scene.png"}},
    {"type": "text", "text": "What is in this picture?"}
  ]
}
```

The part types are `text`, `image_url`, `video_url`, `audio_url` and
`input_audio`; an `input_audio` part carries base64 `wav` or `mp3`. A `url` is
an HTTP(S) URL, a data URL, or a local path the server can read. Media can
alternatively arrive in the top-level `images`, `audios` and `videos` lists, a
sglang-omni extension. A pipeline may read only one of the two carriers and
refuse the other with 400, so the cookbook says which form its pipeline reads.

A picture with a question, answered in text:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<served-name>",
    "messages": [{"role": "user", "content": "How many cars are there in the picture?"}],
    "images": ["tests/data/cars.jpg"],
    "modalities": ["text"],
    "max_tokens": 64
  }'
```

```python
import requests

resp = requests.post(
    "http://localhost:8000/v1/chat/completions",
    json={
        "model": "<served-name>",
        "messages": [{"role": "user", "content": "How many cars are there in the picture?"}],
        "images": ["tests/data/cars.jpg"],
        "modalities": ["text"],
        "max_tokens": 64,
    },
)
resp.raise_for_status()
print(resp.json()["choices"][0]["message"]["content"])
```

Speech and video use the same fields, and a request can mix them with a still
image:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<served-name>",
    "messages": [{"role": "user", "content": "What is said in the audio, and what happens in the video?"}],
    "audios": ["https://example.com/sample.wav"],
    "videos": ["https://example.com/clip.mp4"],
    "video_max_frames": 16,
    "modalities": ["text"],
    "max_tokens": 128
  }'
```

The reply is a chat completion: `choices[0].message.content` holds the text.
Sampling fields a request leaves out come from the checkpoint's generation
config, not from a fixed default, so two models can answer the same request
with different temperature.

## Speech Output

`modalities` selects what the reply contains. The default is `["text"]`;
`["text", "audio"]` also synthesizes the reply as speech:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<served-name>",
    "messages": [{"role": "user", "content": "Say one friendly sentence."}],
    "modalities": ["text", "audio"],
    "audio": {"format": "wav"},
    "max_tokens": 64
  }'
```

The speech comes back base64-encoded inside the same message:

```json
{
  "choices": [
    {
      "message": {
        "content": "Hello! It is nice to meet you.",
        "audio": {"data": "<base64 WAV>", "format": "wav"}
      }
    }
  ]
}
```

```python
import base64

choice = resp.json()["choices"][0]["message"]
with open("reply.wav", "wb") as f:
    f.write(base64.b64decode(choice["audio"]["data"]))
```

The WAV carries the pipeline's own speech rate — 24 kHz on Qwen3-Omni and
PersonaPlex, 44.1 kHz on Ming-Omni — and Ming-Omni currently stamps a 24 kHz
header on 44.1 kHz samples, so read the rate from the model's cookbook rather
than the header.

The `audio` object carries the reply format and, on pipelines that support
voices, the voice selection. Both are model-specific: the cookbook lists the
voices a checkpoint ships and the formats it can emit. A pipeline without
speech stages cannot return audio; asking for it fails instead of silently
dropping the field.

## Streaming

With `stream: true`, the reply arrives as Server-Sent Events in OpenAI chunk
shape: text in `choices[0].delta.content`, speech in `choices[0].delta.audio`
as base64 WAV chunks, then a chunk with an empty delta and `finish_reason`
before `data: [DONE]`:

```text
data: {"choices":[{"delta":{"content":"Hello"}}]}
data: {"choices":[{"delta":{"audio":{"data":"<base64 WAV chunk>"}}}]}
data: {"choices":[{"delta":{},"finish_reason":"stop"}]}
data: [DONE]
```

Whether speech arrives as many chunks or as one aggregate chunk depends on the
pipeline that serves the request: a streaming speech pipeline emits codec-sized
chunks, while a non-streaming one still answers a `stream: true` request with
SSE but sends the finished audio in a single chunk. Each cookbook says which
pipeline it starts. Errors detected after the stream has started keep the HTTP
status at 200 and arrive as an error event, so clients must read the events
instead of the status code alone.

## Realtime Sessions

`/v1/realtime` holds a live full-duplex session instead of one request and one
reply. Qwen3-Omni, MiniCPM-o and PersonaPlex serve it, each with its own
session graph and turn handling. The wire protocol, the session-level
negotiation, and the per-model graphs are documented in
[Full Duplex Interactive Model](../developer_reference/full_duplex_guide.md);
each model's cookbook covers the parts that are specific to it.

## Request Parameters

The endpoint accepts one schema for every pipeline, so a field can be present
even where a checkpoint ignores it:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `model` | string | served model | Model identifier |
| `messages` | list | required | Chat messages; `content` is a string or typed parts |
| `modalities` | list | `["text"]` | `["text"]` or `["text", "audio"]` |
| `images` / `audios` / `videos` | list | none | Media as local paths, URLs or data URLs, applied to the final user message |
| `video_fps`, `video_max_frames`, `video_min_pixels`, `video_max_pixels`, `video_total_pixels` | number | none | Frame and pixel budgets for video preprocessing |
| `use_audio_in_video` | bool | none | Read the audio track of a video file instead of a separate upload |
| `max_tokens` / `max_completion_tokens` | int | none | Generation cap; the second is an OpenAI-compatible alias |
| `temperature`, `top_p`, `top_k`, `min_p`, `repetition_penalty`, `stop`, `seed` | — | checkpoint config | Text sampling |
| `stream` | bool | `false` | Emit SSE chunks |
| `audio` | dict | none | Reply audio options such as `{"format": "wav"}` |
| `stage_sampling` | dict | none | Per-stage sampling overrides keyed by stage name |
| `stage_params` | dict | none | Per-stage request fields keyed by stage name |

Two families of fields are not shared. The `talker_*` sampling overrides and
`return_spec_tokens_details` belong to Qwen3-Omni's speech stages; the
`stage_params` keys, the voice options, and the frame budgets a pipeline
actually honors are documented per model. Where a pipeline maps a field onto
something else — Ming-Omni forwards `max_tokens` as `max_new_tokens`, and
PersonaPlex ignores a token cap because its frame count follows the input
length — the cookbook states the mapping.

A message that carries only media has no text to quote, so a request without
text still needs a `messages` entry; whether its `content` may be empty is per
pipeline, and Qwen3-Omni documents the empty-string form it accepts.

## Errors

The endpoint answers 400 for an unsupported parameter, an unreadable media
reference or a part type the pipeline does not accept, 503 when the request
queue is full, and 500 for other server failures. A request rejected before
inference never starts a stage; one that fails after streaming has started
reports the failure in an event, as described in Streaming.
